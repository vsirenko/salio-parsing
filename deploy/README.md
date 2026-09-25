# Deploying

One server, the four services of `docker-compose.prod.yml` — `db`, `migrate`, `api`,
`scheduler` — and a push to `main` that deploys itself once CI passes.

| file | what it is |
|---|---|
| `docker-compose.prod.yml` | the server's stack: the database's password from `.env`, no database port on the host, the api on the loopback for a reverse proxy, rotating logs |
| `deploy/deploy.sh` | one deploy, run on the server: fetch the commit, build, migrate, start, wait for `/health/ready` |
| `deploy/dump-local.sh` | the laptop's database and snapshots, packed for the server |
| `deploy/restore.sh` | on the server, once: that pack restored in place of what is there |
| `.github/workflows/ci.yml` | ruff, `alembic check` and the suite on every push; the deploy job on a push to `main` |

## Why the data moves with the code

Categories, attributes and their aliases, the brand and model registries, colours, every
catalogue entry and the price history were entered through the API and live in the
database — none of it is in a migration. A server started on an empty database would
serve an empty catalogue. So the first deploy restores the laptop's database, and the
snapshots with it: without them a reparse reads nothing, and a parser fix means crawling
every shop again.

## The server, once

1. Docker with the compose plugin, git, curl. A user that may run docker and owns the
   checkout — `deploy` below.
2. The checkout, where `DEPLOY_PATH` will point:

   ```
   git clone https://github.com/vsirenko/salio-parsing.git /srv/salio-parsing
   ```

3. The settings: a `.env` made from `.env.example`, stored whole as the `PROD_ENV` secret
   of the `production` environment on GitHub. Every deploy writes the server's `.env` from
   it (mode 600), so a secret is changed in one place — GitHub → Settings → Environments →
   production — and takes effect on the next deploy. Edit the server's copy by hand and
   the next deploy overwrites it. What differs from a laptop's:

   | setting | value |
   |---|---|
   | `ENVIRONMENT` | `production` — startup then refuses the dev secret and the demo seed |
   | `SECRET_KEY` | `python -c "import secrets; print(secrets.token_urlsafe(48))"` |
   | `SEED_USERS` | `false` |
   | `POSTGRES_PASSWORD` | a long random one; nothing outside the compose network reaches the database |
   | `WORKER_PASSWORD` | a long random one — `ensure-worker` sets the account to it |
   | `API_PORT` | the loopback port the reverse proxy forwards to; `8090` on this server, where `8080` is another project's |
   | `API_BASE_URL` | `http://api:8000` (the workers reach the api inside the network) |
   | `DOCS_ENABLED` | `false`, unless the panel's developers want `/docs` there |
   | `CORS_ORIGINS` | the panel's and the storefront's origins, explicitly |
   | `TRUST_PROXY_HEADERS` | `true` behind the reverse proxy, which rewrites `X-Forwarded-For` |
   | `DEBUG` | `false` |
   | `TYPESAFE_API_KEY` | the judge's key, or empty to leave judging off |

4. A reverse proxy in front of `127.0.0.1:${API_PORT}` with TLS. With Caddy, the whole of it:

   ```
   api.example.com {
       reverse_proxy 127.0.0.1:8090
   }
   ```

## The first deploy: the laptop's data

On the laptop, with the dev stack running:

```
deploy/dump-local.sh                  # var/transfer/app-<stamp>.dump, snapshots-<stamp>.tar.gz
scp var/transfer/*-<stamp>* deploy@server:/srv/salio-parsing/var/
```

On the server:

```
cd /srv/salio-parsing
deploy/deploy.sh                      # builds and starts on an empty database
deploy/restore.sh var/app-<stamp>.dump var/snapshots-<stamp>.tar.gz
```

`restore.sh` asks before it replaces anything, stops the api and the scheduler, restores
the database and the snapshots, runs the migrations the laptop had not, switches off the
demo accounts and resets the collector's password to `WORKER_PASSWORD`, then starts
everything again. Checked on 25.09.2026: a dump restored into a scratch database came back
with the same 2097 families, 5837 entries, 18778 listings, 936 model names and migration.

## Accounts

Production seeds nothing, and a copied database brings the laptop's accounts along. So:

```
docker compose -f docker-compose.prod.yml exec api python -m app.features.users.cli retire-demo
docker compose -f docker-compose.prod.yml exec api python -m app.features.users.cli ensure-worker
docker compose -f docker-compose.prod.yml exec api python -m app.features.users.cli create --email you@example.com --role admin
```

`create` reads the password from the terminal, never from an argument. `retire-demo`
switches off `admin@example.com` and `customer@example.com`, whose passwords are in the
repository. `scripts@example.com`, the account the laptop's maintenance scripts used, comes
along too: switch it off in the panel unless scripts will run against the server.

## Deploys after that

A push to `main` runs the checks, and if they pass the `deploy` job connects to the server,
writes its `.env` from `PROD_ENV` and runs `deploy/deploy.sh <commit>`. Its secrets, all in
the `production` environment:

| secret | what |
|---|---|
| `DEPLOY_HOST` | the server's address |
| `DEPLOY_USER` | the user that owns the checkout, `deploy` |
| `DEPLOY_PATH` | the checkout, `/srv/salio-parsing` |
| `DEPLOY_SSH_KEY` | a private key made for this and nothing else; its public half in that user's `~/.ssh/authorized_keys` |
| `DEPLOY_KNOWN_HOSTS` | `ssh-keyscan <host>` from a machine you trust, so the job refuses a server that is not yours |
| `PROD_ENV` | the whole `.env`, see "The server, once" |

A secret is best set without its value passing through a terminal's scrollback: piped,
`ssh <server> 'cat /srv/salio-parsing/.env' | gh secret set PROD_ENV --env production`, and
likewise for a new key made on the server and removed there once stored.

Until they are set the `deploy` job fails and the checks still run.

**A migration is not undone by deploying an older commit.** `deploy/deploy.sh <older sha>`
brings the old code back onto the new schema; every migration here adds, so that usually
works, but check the ones in between before relying on it. The database is what to back up
before a deploy that changes it: `docker compose -f docker-compose.prod.yml exec db pg_dump
-U app -d app --format=custom > backup.dump`.

## Replacing the old stack

The server runs another backend and frontend now. Before switching the proxy over:

1. The new stack up beside the old on its own `API_PORT`, the data restored, a sign-in and a
   page of families checked against it.
2. The proxy pointed at the new port; the old one stopped, not removed.
3. The old containers and volumes removed only once the new one has run a day's collection.
