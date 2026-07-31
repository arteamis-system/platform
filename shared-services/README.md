# shared-services — the edge + database for a project VM

The two things a project VM needs *once*, shared by every component on it:

- **Traefik** — reverse proxy on 80/443 with **automatic HTTPS** (Let's Encrypt via
  Cloudflare DNS-01). Routes to components by hostname using their Docker labels —
  add a component, add a label, no proxy config to edit.
- **Postgres 16** — one database, persistent on the host at `/opt/<project>/data/postgres`,
  reachable by other containers as `postgres:5432` (never published to the internet).

This is the piece that turns "N containers on a box" into "a project with TLS and a DB".

## How it fits

```
                         :443 (TLS auto)
   Internet ──► Traefik ──┬──► backend   (Host: api.tasmil.finance)
                          ├──► mcp       (Host: mcp.tasmil.finance)
                          └──► ai        (Host: ai.tasmil.finance)
                    postgres:5432 ◄──────┘  (internal only)
   all on the ${PROJECT}_net network created by cloud-init
```

Deploy the edge once per VM (to `/opt/<project>/edge`); the app components
(`deploy-vm.yml`) join the same network and are picked up automatically.

## Deploy the edge

Secrets come from Infisical / the secrets manager, never the repo:

```bash
PROJECT=tasmil DOMAIN=tasmil.finance ACME_EMAIL=ops@tasmil.finance \
CF_DNS_API_TOKEN=<cloudflare token for the zone> \
POSTGRES_USER=app POSTGRES_PASSWORD=<strong> POSTGRES_DB=tasmil \
docker compose -p tasmil-edge up -d
```

`CF_DNS_API_TOKEN` must manage the project's zone — for tasmil that is the
`cf_api_token_tasmil` token (zone **tasmil.finance**). Traefik uses it only for the
DNS-01 challenge, so certs issue even before any traffic reaches the box.

## Attach a component (the only change per app repo)

In the component's `docker-compose.prod.yml`, add Traefik labels and drop the raw
`ports:` (Traefik now fronts it). Example for the backend:

```yaml
services:
  backend:
    image: ${IMAGE}
    env_file: [.env]
    networks: [tasmil_net]
    labels:
      - traefik.enable=true
      - traefik.http.routers.backend.rule=Host(`api.tasmil.finance`)
      - traefik.http.routers.backend.entrypoints=websecure
      - traefik.http.routers.backend.tls.certresolver=le
      - traefik.http.services.backend.loadbalancer.server.port=3000
networks:
  tasmil_net:
    external: true
```

mcp and ai are identical with their own `Host(...)` and port. No `ports:` mapping,
no certbot, no nginx site file.

## Connect a component to Postgres

The app reads `DATABASE_URL` from its `.env` (materialised from Infisical by
`deploy-vm.yml`). Point it at the shared Postgres over the network:

```
DATABASE_URL=postgres://app:<password>@postgres:5432/tasmil
```

Store that value in Infisical under the project+environment; nothing DB-related
lives in the repo.

## DNS

Point the component hostnames at the VM's IP — one A record each, which the
`cloudflare-dns` module already generates for `vm_components`:

```
api.tasmil.finance  A  <vm ip>
mcp.tasmil.finance  A  <vm ip>
ai.tasmil.finance   A  <vm ip>
```

Once these resolve, Traefik's DNS-01 challenge (using the same Cloudflare token)
issues the certificates automatically.

## Why Traefik over nginx+certbot

The hand-rolled arteamis kit wired nginx sites + certbot renewals per host. Traefik
replaces both: it discovers containers by label, issues and renews TLS itself, and
needs zero config when a new component joins — which is the whole point of a
platform that onboards project #100 as cheaply as #10.
