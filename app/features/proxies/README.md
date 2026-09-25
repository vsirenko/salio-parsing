# proxies

Named ways out to the shops that do not let the server's own address in. Made once here and
chosen by any channel through its `proxy_id`.

## Endpoints

| | |
|---|---|
| `GET · POST /api/admin/proxies` | list and add proxies — addresses shown masked |
| `GET · PATCH · DELETE /api/admin/proxies/{proxy_id}` | read, change or remove one; a proxy a channel uses is not removed |
| `POST /api/admin/proxies/{proxy_id}/check` | every address asked for the probe page once: answered or not, how fast, and the address the far side saw |

A channel takes one with `proxy_id` on `POST /api/admin/shops/{id}/sources` or
`PATCH /api/admin/sources/{id}`; `null` takes it away.

## How it works

**A proxy is chosen by a channel, not by a shop.** One shop's channels reach different hosts
— rdveikals' phones and laptops are two channels — and only some of them are blocked. A
proxy is made once and chosen by as many channels as need it, so its password changes in one
place.

**Several addresses, taken in turn.** A proxy holds up to fifty `urls`, `http://`,
`https://`, `socks5://` or `socks5h://`, each with its credentials. The worker makes one
client per address and sends each request through the next one still up; an address that
fails to connect, or answers `407` for its own credentials, is out for the rest of the run,
and the request is tried again through another. When every address is out the request
fails, and the run with it — a run through a broken proxy should look broken, not empty.

**The addresses are a secret, and only the worker sees them whole.** Every schema a caller
reads masks the credentials, `http://***@host:port`; the audit trail records the masked
form; the collector's log names an address the same way. The job a worker is handed
(`GET /api/worker/runs/{id}`) carries them whole, because the worker is what connects.
Sending `urls` replaces the whole list: a masked address cannot be sent back.

**Switched off, its channels go direct.** `is_enabled = false` leaves every `proxy_id` in
place and gives the next job no proxy, which is the way to find out whether a shop still
needs one.

## Decisions worth knowing before changing it

- A proxy a channel uses cannot be deleted (409 `proxy_in_use`, naming the channels): taking
  it away would send them out direct without anybody asking for that.
- `POST …/check` asks `PROXY_CHECK_URL` — by default a page that answers with the address it
  saw — so the check says which address the shop would see, not only that a connection
  opened. It reaches the internet from the api, not from a worker.
- SOCKS needs `socksio`, which is in the requirements; `socks5h` resolves the shop's name on
  the proxy's side, where the provider's DNS is what the shop expects to see.
