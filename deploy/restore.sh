#!/usr/bin/env bash
# On the server: the database and snapshots dump-local.sh packed, replacing what is there.
# Run once, before the first real use — it empties the server's database.
#
#   deploy/restore.sh app-<stamp>.dump snapshots-<stamp>.tar.gz
set -euo pipefail

cd "$(dirname "$0")/.."
DUMP="${1:?the .dump file}"
SNAPSHOTS="${2:?the snapshots .tar.gz}"
# ENV_FILE points elsewhere only to try the stack beside another one; on a server it is .env.
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")
USER_="$(grep -E '^POSTGRES_USER=' "$ENV_FILE" | cut -d= -f2 || true)"; USER_="${USER_:-app}"
DB_="$(grep -E '^POSTGRES_DB=' "$ENV_FILE" | cut -d= -f2 || true)"; DB_="${DB_:-app}"

read -r -p "This replaces the database '$DB_' and all snapshots on this server. Type yes: " ok
[ "$ok" = "yes" ] || { echo "stopped"; exit 1; }

echo "==> stopping what writes"
"${COMPOSE[@]}" stop api scheduler || true
"${COMPOSE[@]}" up -d db

echo "==> database"
"${COMPOSE[@]}" exec -T db dropdb -U "$USER_" --if-exists "$DB_"
"${COMPOSE[@]}" exec -T db createdb -U "$USER_" "$DB_"
"${COMPOSE[@]}" exec -T db pg_restore -U "$USER_" -d "$DB_" --no-owner --no-privileges < "$DUMP"

echo "==> snapshots"
"${COMPOSE[@]}" run --rm --no-deps -T --entrypoint sh scheduler \
  -c 'find /snapshots -mindepth 1 -delete && tar -C /snapshots -xzf -' < "$SNAPSHOTS"

echo "==> migrations, accounts, start"
"${COMPOSE[@]}" run --rm migrate
"${COMPOSE[@]}" run --rm --no-deps api python -m app.features.users.cli retire-demo
"${COMPOSE[@]}" run --rm --no-deps api python -m app.features.users.cli ensure-worker
"${COMPOSE[@]}" up -d
echo "done; now make your own admin: see deploy/README.md, 'Accounts'"
