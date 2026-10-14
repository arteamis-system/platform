#!/usr/bin/env bash
# Restore only into a newly created disposable container. Never accept a target URL.
set -euo pipefail

if [[ $# -ne 2 || ( "$1" != --dump && "$1" != --s3-uri ) ]]; then
  echo "Usage: $0 --dump /private/path.dump | --s3-uri s3://bucket/key.dump" >&2
  exit 2
fi

restore_tmp=$(mktemp -d)
chmod 700 "$restore_tmp"
restore_container="arteamis-restore-$(python3 -c 'import uuid; print(uuid.uuid4().hex[:12])')"
cleanup() {
  docker rm -f "$restore_container" >/dev/null 2>&1 || true
  rm -rf "$restore_tmp"
}
trap cleanup EXIT

umask 077
if [[ "$1" == --s3-uri ]]; then
  [[ "$2" == s3://* ]] || { echo "Expected an S3 URI" >&2; exit 2; }
  aws s3 cp "$2" "$restore_tmp/backup.dump" --only-show-errors
else
  cp "$2" "$restore_tmp/backup.dump"
fi
test -s "$restore_tmp/backup.dump"
python3 -c 'import secrets; print("POSTGRES_PASSWORD=" + secrets.token_hex(24))' > "$restore_tmp/postgres.env"
docker run -d --name "$restore_container" --env-file "$restore_tmp/postgres.env" \
  pgvector/pgvector:pg16 >/dev/null

ready=false
for ((attempt=0; attempt<60; attempt++)); do
  if docker exec "$restore_container" pg_isready -U postgres >/dev/null 2>&1; then
    ready=true
    break
  fi
  sleep 1
done
[[ "$ready" == true ]] || { echo "Disposable database did not start" >&2; exit 1; }

docker exec "$restore_container" psql -X -U postgres -v ON_ERROR_STOP=1 -c \
  'CREATE ROLE arteamis NOLOGIN NOSUPERUSER NOBYPASSRLS; CREATE ROLE arteamis_app NOLOGIN NOSUPERUSER NOBYPASSRLS; CREATE ROLE arteamis_rls_helper NOLOGIN NOSUPERUSER BYPASSRLS;' >/dev/null
docker exec "$restore_container" createdb -U postgres restored
docker exec "$restore_container" psql -X -U postgres -d restored -v ON_ERROR_STOP=1 -c \
  'CREATE EXTENSION vector; CREATE EXTENSION pgcrypto; CREATE EXTENSION pg_trgm;' >/dev/null
docker cp "$restore_tmp/backup.dump" "$restore_container:/tmp/backup.dump"
if gzip -t "$restore_tmp/backup.dump" 2>/dev/null; then
  # September releases wrote gzip-compressed SQL. Keep support for those real
  # offsite objects as well as the new custom-format dumps.
  gzip -dc "$restore_tmp/backup.dump" | awk '$0 != "CREATE SCHEMA public;"' | \
    docker exec -i "$restore_container" psql -X -U postgres -d restored \
      -v ON_ERROR_STOP=1 >/dev/null
else
  docker exec "$restore_container" pg_restore --list /tmp/backup.dump > "$restore_tmp/full.toc"
  # Infrastructure has already created these. Do not replay the old cluster's
  # extension ownership or public-schema metadata in the disposable target.
  awk '!/ EXTENSION / && !/ SCHEMA - public /' "$restore_tmp/full.toc" > "$restore_tmp/restore.toc"
  docker cp "$restore_tmp/restore.toc" "$restore_container:/tmp/restore.toc"
  docker exec "$restore_container" pg_restore -U postgres -d restored --exit-on-error \
    --no-owner --no-privileges --use-list=/tmp/restore.toc /tmp/backup.dump
fi

docker exec "$restore_container" psql -X -U postgres -d restored -Atc \
  "SELECT format('SELECT %L, count(*) FROM %I.%I;', tablename, schemaname, tablename) FROM pg_tables WHERE schemaname='public' ORDER BY tablename" > "$restore_tmp/counts.sql"
docker exec -i "$restore_container" psql -X -U postgres -d restored -At -v ON_ERROR_STOP=1 \
  < "$restore_tmp/counts.sql" > "$restore_tmp/counts.txt"
tables=$(wc -l < "$restore_tmp/counts.txt" | tr -d ' ')
rows=$(awk -F '|' '{n += $2} END {print n+0}' "$restore_tmp/counts.txt")
revision=$(docker exec "$restore_container" psql -X -U postgres -d restored -Atc 'SELECT version_num FROM alembic_version')
echo "Restore verified in disposable container: tables=$tables rows=$rows revision=$revision"
echo "The disposable database is removed on exit. A local dump drill does not verify offsite transport."
