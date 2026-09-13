# Project map

## Files

```
ops-dashboard/
├── run.py                  Start here. Entry point + CLI flags.
├── server.py               Serves the page and the JSON endpoints.
├── config.json             YOUR CREDENTIALS. Gitignored. You create this.
├── config.example.json     Template to copy.
├── README.md               Setup guide.
├── PROJECT_MAP.md          This file.
│
├── lib/
│   ├── config.py           Loads config.json, applies defaults, validates.
│   ├── fetch.py            Shared HTTP: TLS, proxies, timeouts, error text.
│   ├── aggregator.py       Polls all three sources on a timer, holds results.
│   └── demo.py             Sample data for `--demo`. No network.
│
├── sources/                One file per hook. Each exposes fetch(cfg).
│   ├── zabbix.py           JSON-RPC. Alerts.
│   ├── planner.py          Dataverse OData. This week's tasks.
│   └── deskpro.py          REST. Tickets.
│
└── static/                 What the browser loads.
    ├── index.html          Page shell — three empty columns.
    ├── style.css           All styling. Design tokens at the top.
    └── app.js              Fetches /api/data, renders the columns.
```

## How data moves

```
  Zabbix ─┐
 Planner ─┼─→ sources/*.py ─→ aggregator ─→ /api/data ─→ app.js ─→ page
 DeskPro ─┘     (normalise)     (cache)       (JSON)      (render)
```

1. `aggregator.py` runs a background thread that calls each `sources/*.fetch()`
   every `refresh_seconds`, **each in its own thread** so one slow source cannot
   stall the others.
2. Each adapter returns `{"items": [...], "meta": {...}}` in a normalised shape.
   A failure raises `SourceError` and is caught — one dead source shows an error
   in its own column while the other two keep working.
3. The browser polls `/api/data`, which is only ever a read from that cache.

**Credentials stay in Python.** The browser never sees a token and never talks
to Zabbix, Dataverse or DeskPro. Ten open tabs still produce one poll per
interval, not ten.

## Endpoints

| Route | Purpose |
|---|---|
| `GET /` | The dashboard page |
| `GET /api/data` | Cached results for all three sources |
| `GET /api/refresh` | Force a poll of everything, then return it |
| `GET /api/refresh/<source>` | Force a poll of one source |

## Where to change things

| You want to | Go to |
|---|---|
| Add a field to the alert rows | `sources/zabbix.py` (`_attach_hosts`), then `renderZabbix` in `static/app.js` |
| Change colours, spacing, fonts | Design tokens at the top of `static/style.css` |
| Change which tasks count as "this week" | `week_bounds()` and the `$filter` in `sources/planner.py` |
| Change ticket sorting | The `items.sort(...)` at the end of `sources/deskpro.py` |
| Add a fourth source | New `sources/yours.py` with a `fetch(cfg)`, add it to `ADAPTERS` in `lib/aggregator.py`, add defaults in `lib/config.py`, add a column in `index.html` + a render function in `app.js` |

## Notes that will save you time

Each of these cost real research; they are not obvious from the APIs.

**Zabbix** — every scalar in a response is a JSON *string*: `severity` is `"3"`,
`acknowledged` is `"1"`. `"0"` is truthy in Python, so `if p["acknowledged"]`
marks everything acknowledged. Authentication also moved: the `auth` body field
up to 6.2, an `Authorization: Bearer` header from 6.4, and the field is
**removed** in 7.2. `zabbix.py` probes `apiinfo.version` once at startup (which
must be called with no credentials at all) and picks. It also falls back to the
old field on 6.4/7.0, because Apache commonly strips the auth header and makes a
valid token look invalid.

**Planner Premium** — not on Microsoft Graph at all; the Graph Planner endpoints
serve Planner *Basic* only and reject app-only tokens even when the Application
permission has been granted. Premium is Dataverse. `msdyn_progress` is a
**0–1 fraction** there, not Graph's 0–100 integer. Paging must follow
`@odata.nextLink` verbatim — the `$skiptoken` is opaque and re-adding query
options to it breaks it.

**DeskPro** — the auth scheme is the bare word `key`, and the credential is both
halves of `id:code`. There is no `open` status; open means
`awaiting_agent` + `awaiting_user`. Related objects come back as bare integer
ids with the real objects in a separate `linked` block — and those keys are JSON
object keys, so they are **strings** while the ids on the ticket are
**integers**. `str()` the id or every agent name comes back blank. Dates use a
basic-format offset (`+0000`, no colon) that `datetime.fromisoformat()` rejects
before Python 3.11.
