"""A throwaway canvas over the pipeline endpoints, written as one HTML file.

    .venv/bin/python -m tools.canvas            # a snapshot, var/preview/canvas.html
    .venv/bin/python -m tools.canvas --serve    # live, on http://localhost:8781

Temporary, to be deleted once the admin panel draws the same thing. It calls the running
API — `/api/admin/scheduler`, `/api/admin/pipeline` for everything, each category and each
channel, and `/api/admin/offers/{id}/trace` for every listing that did not place plus a few
that did from each channel — and writes `var/preview/canvas.html` with the answers inside
it, so the page needs no token and no server of its own. Running it again is the refresh.

`--serve` is the same page, live: a local server hands it out and passes `/api/admin/*` on
to the API with a token it mints itself, so the browser needs neither a token nor CORS. The
page polls the scheduler, the pipeline and the latest runs, and every channel has buttons to
queue a `full`, `quick` or `reparse` run — which the scheduler takes on its next tick.
"""

import argparse
import asyncio
import json
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from sqlalchemy import select, text

from app.core.security import Audience, create_access_token
from app.db.models import User
from app.db.session import engine, session_factory

API = "http://localhost:8080/api/admin"
OUT = Path(__file__).resolve().parent.parent / "var" / "preview" / "canvas.html"
# The page itself, which reads the data written into it. A file of its own so it can be
# edited as HTML, and deleted with this module.
PAGE = Path(__file__).with_name("canvas.html")
PLACED_PER_SOURCE = 4

SAMPLES = """
with latest as (
    select distinct on (r.offer_id) r.offer_id, r.source_id
    from raw_offers r left join runs ru on ru.id = r.run_id
    where ru.kind is null or ru.kind <> 'quick'
    order by r.offer_id, r.fetched_at desc, r.id desc
)
select l.offer_id, l.source_id,
       exists (select 1 from offer_matches m
               where m.offer_id = l.offer_id and m.superseded_at is null) as placed,
       exists (select 1 from match_queue q where q.offer_id = l.offer_id) as queued
from latest l join offers o on o.id = l.offer_id
order by l.source_id, l.offer_id
"""


async def mint() -> str:
    try:
        async with session_factory() as session:
            admin = await session.scalar(select(User).where(User.role == "admin").limit(1))
            return create_access_token(admin.id, admin.token_epoch, Audience.ADMIN)
    finally:
        # Every call runs in an event loop of its own, and a pooled connection belongs to
        # the loop that opened it: the second page load failed with "attached to a
        # different loop" until the pool was let go each time.
        await engine.dispose()


async def token_and_samples() -> tuple[str, list[int]]:
    try:
        async with session_factory() as session:
            admin = await session.scalar(select(User).where(User.role == "admin").limit(1))
            token = create_access_token(admin.id, admin.token_epoch, Audience.ADMIN)
            rows = (await session.execute(text(SAMPLES))).mappings().all()
    finally:
        await engine.dispose()
    placed_seen: dict[int, int] = defaultdict(int)
    chosen: list[int] = []
    for row in rows:
        if row["queued"] and not row["placed"]:
            chosen.append(row["offer_id"])
        elif row["placed"] and placed_seen[row["source_id"]] < PLACED_PER_SOURCE:
            placed_seen[row["source_id"]] += 1
            chosen.append(row["offer_id"])
    return token, chosen


def get(path: str, token: str, **params: str) -> dict:
    query = f"?{urllib.parse.urlencode(params)}" if params else ""
    request = urllib.request.Request(
        f"{API}{path}{query}", headers={"Authorization": f"Bearer {token}"}
    )
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.loads(response.read())


def collect() -> dict:
    token, offer_ids = asyncio.run(token_and_samples())
    scheduler = get("/scheduler", token)
    everything = get("/pipeline", token)
    categories = sorted({s["category"] for s in everything["sources"] if s["category"]})
    by_category = {c: get("/pipeline", token, category=c) for c in categories}
    by_source = {
        s["source"]: get("/pipeline", token, source=s["source"]) for s in everything["sources"]
    }
    traces = {}
    for offer_id in offer_ids:
        trace = get(f"/offers/{offer_id}/trace", token)
        # The shop's full attribute table is the heaviest thing on the page and the trace
        # already shows what each rule made of it; the first thirty names are kept.
        payload = (trace.get("observation") or {}).get("payload") or {}
        for key in ("attributes", "specs", "parameters"):
            if isinstance(payload.get(key), dict) and len(payload[key]) > 30:
                payload[key] = dict(list(payload[key].items())[:30])
        traces[offer_id] = trace
    return {
        "generated_at": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"),
        "scheduler": scheduler,
        "pipeline": {"all": everything, **by_category},
        "by_source": by_source,
        "traces": traces,
    }


def render(data: dict) -> str:
    blob = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")
    return PAGE.read_text(encoding="utf-8").replace("__DATA__", blob)


def main() -> None:
    data = collect()
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(render(data), encoding="utf-8")
    print(OUT)
    print(f"{len(data['traces'])} listings traced, {len(data['by_source'])} channels")


def serve(port: int) -> None:
    """The page, live: `/` is the page, `/api/admin/*` is the API with a token added."""
    state = {"token": asyncio.run(mint())}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args) -> None:  # the terminal is for the operator
            return

        def _proxy(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = self.rfile.read(length) if length else None
            for attempt in (1, 2):
                request = urllib.request.Request(
                    f"http://localhost:8080{self.path}",
                    data=body,
                    method=method,
                    headers={
                        "Authorization": f"Bearer {state['token']}",
                        "Content-Type": "application/json",
                    },
                )
                try:
                    with urllib.request.urlopen(request, timeout=120) as response:
                        status, payload = response.status, response.read()
                except urllib.error.HTTPError as error:
                    status, payload = error.code, error.read()
                if status == 401 and attempt == 1:
                    state["token"] = asyncio.run(mint())  # expired: mint and ask again
                    continue
                break
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:
            if self.path.startswith("/api/admin/"):
                return self._proxy("GET")
            page = render({**collect(), "live": True}).encode()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(page)

        def do_POST(self) -> None:
            if self.path.startswith("/api/admin/"):
                return self._proxy("POST")
            self.send_error(404)

    print(f"live canvas on http://localhost:{port}  (ctrl-c to stop)")
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--serve", action="store_true", help="serve it live instead")
    parser.add_argument("--port", type=int, default=8781)
    arguments = parser.parse_args()
    if arguments.serve:
        serve(arguments.port)
    else:
        main()
