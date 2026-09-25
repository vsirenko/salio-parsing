#!/usr/bin/env bash
# The laptop's database and snapshots, packed for the server: everything the catalogue is —
# categories, attributes, the registries, entries, price history — lives in the database and
# nowhere in the migrations, so a server started empty would have none of it.
#
#   deploy/dump-local.sh [out-dir]      # from the repository, with the dev stack running
set -euo pipefail

cd "$(dirname "$0")/.."
OUT="${1:-var/transfer}"
mkdir -p "$OUT"
STAMP="$(date -u +%Y%m%d-%H%M%S)"

echo "==> database"
docker compose exec -T db pg_dump -U app -d app --format=custom --no-owner --no-privileges \
  > "$OUT/app-$STAMP.dump"

echo "==> snapshots"
docker compose run --rm --no-deps -T --entrypoint sh scheduler \
  -c 'tar -C /snapshots -czf - .' > "$OUT/snapshots-$STAMP.tar.gz"

ls -lh "$OUT"/*"$STAMP"*
echo "copy both to the server, then run deploy/restore.sh there (see deploy/README.md)"
