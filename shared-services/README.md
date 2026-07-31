# shared-services — the edge + database for a project VM

The two things a project VM needs *once*, shared by every component on it:

- **Traefik** — reverse proxy on 80/443 with **automatic HTTPS** (Let's Encrypt via
  Cloudflare DNS-01). Routes to components by hostname from a per-component file in
  `dynamic/` — add a component, drop a route file, no proxy config to hand-edit.
  (File provider, not the Docker-socket provider — see the note at the bottom.)
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

## Attach a component (a route file, not the app repo)

Drop one file at `/opt/<project>/edge/dynamic/<component>.yml`. Traefik hot-reloads
it and reaches the container by name over `${PROJECT}_net`. Example for the backend:

```yaml
# /opt/tasmil/edge/dynamic/backend.yml
http:
  routers:
    backend:
      rule: "Host(`api.tasmil.finance`)"
      entryPoints: [websecure]
      service: backend
      tls: { certResolver: le }
  services:
    backend:
      loadBalancer:
        servers:
          - url: "http://tasmil-backend:3000"   # container_name : port
```

mcp and ai are identical with their own `Host(...)`, container name and port. The
component's `docker-compose.prod.yml` just needs `container_name` + `networks: [tasmil_net]`
and **no** published `ports:` — Traefik fronts it. `onboard-project.sh` generates
these route files from the manifest.

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

## Why the file provider, not the Docker-socket provider (resolved on AWS 2026-07-31)

The obvious design is Traefik's Docker provider (discover containers by label). On
these VMs it fails — reproduced on **both** Ubuntu's `docker.io` (Docker 29.1.3,
minAPI 1.44) **and** upstream Docker CE (29.7.0, minAPI 1.40), with Traefik **v3.3
and v3.5**:

```
ERR ... "client version 1.24 is too old. Minimum supported API version is 1.44" providerName=docker
```

Traefik's socket client negotiates from API 1.24 and the daemon rejects it, so it
never sees the containers. Postgres and the app path are unaffected.

**The fix is the file provider** (used above): routes live in `dynamic/*.yml`, so
Traefik never touches the Docker socket. Verified end-to-end on AWS — a real Let's
Encrypt certificate issued via DNS-01 and HTTPS routing to a backend container both
worked. Slightly less "magic" than labels (a route file per component instead of
labels), but reliable and generated automatically by `onboard-project.sh`.

## Why Traefik over nginx+certbot

The hand-rolled arteamis kit wired nginx sites + certbot renewals per host. Traefik
replaces both: it issues and renews TLS itself and hot-reloads a new route file with
zero restarts — the whole point of a platform that onboards project #100 as cheaply
as #10.
