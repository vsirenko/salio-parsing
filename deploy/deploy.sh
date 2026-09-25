#!/usr/bin/env bash
# One deploy, on the server, from the checkout it lives in: the commit GitHub pushed, built,
# migrated, started, and checked. Run by the deploy workflow over SSH, or by hand.
#
#   deploy/deploy.sh [commit]
#
# It stops at the first thing that fails. A migration that fails leaves the old api running,
# because `migrate` must complete before `api` is started again.
set -euo pipefail

cd "$(dirname "$0")/.."
# ENV_FILE points elsewhere only to try the stack beside another one; on a server it is .env.
ENV_FILE="${ENV_FILE:-.env}"
COMPOSE=(docker compose -f docker-compose.prod.yml --env-file "$ENV_FILE")
COMMIT="${1:-origin/main}"

if [ ! -f "$ENV_FILE" ]; then
  echo "no .env here: copy .env.example, fill it in for production (see deploy/README.md)" >&2
  exit 1
fi

echo "==> fetching ${COMMIT}"
git fetch --quiet origin
# The server's checkout is a copy of what was pushed and nothing else; a change made on the
# server by hand would be lost here, which is the point.
git reset --quiet --hard "${COMMIT}"
echo "    at $(git log --oneline -1)"

echo "==> building"
"${COMPOSE[@]}" build --quiet

echo "==> migrating and starting"
"${COMPOSE[@]}" up -d --remove-orphans

echo "==> waiting for the api"
PORT="$(grep -E '^API_PORT=' "$ENV_FILE" | cut -d= -f2 || true)"
PORT="${PORT:-8080}"
for _ in $(seq 1 30); do
  if curl -fsS "http://127.0.0.1:${PORT}/health/ready" >/dev/null 2>&1; then
    echo "    ready on 127.0.0.1:${PORT}"
    "${COMPOSE[@]}" ps --format 'table {{.Service}}\t{{.Status}}'
    docker image prune -f >/dev/null
    exit 0
  fi
  sleep 2
done

echo "the api did not become ready; its last lines:" >&2
"${COMPOSE[@]}" logs --tail 50 api >&2
exit 1
