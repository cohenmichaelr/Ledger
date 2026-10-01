# Ledger

A trading & portfolio analytics backend: record trades, compute positions and P&L,
ingest market data, and expose risk metrics over a REST (and later streaming) API.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest · uv · ruff

**Live demo:** <https://ledger-wegu.onrender.com/docs>. Nothing to install: open **POST
/trades/import**, click **Try it out**, and upload
[samples/trades.csv](https://github.com/cohenmichaelr/Ledger/blob/main/samples/trades.csv)
(download it with the "Download raw file" button). It runs on a free tier, so the first request
after 15 idle minutes takes about a minute ([details](#deployment)). The demo is shared, so you
may see trades other visitors imported.

> **Status:** The trades API, portfolios, CSV trade import with FIFO positions, realized P&L
> and a live deployment are done and tested. End-of-day prices, unrealized P&L and risk
> metrics are next. See the [Roadmap](#roadmap).

## Quick start (Windows / PowerShell)

```powershell
# one-time: install uv  (https://docs.astral.sh/uv/)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

git clone https://github.com/cohenmichaelr/Ledger.git
cd Ledger
uv python install 3.12
uv sync                                   # creates .venv and installs deps (incl. dev)
uv run uvicorn ledger.main:app --reload   # API at http://127.0.0.1:8000
```

Open <http://127.0.0.1:8000/docs> for interactive Swagger UI. On startup the app creates
its tables in a local SQLite file, `ledger.db`, which git ignores.

On macOS/Linux, install uv with `curl -LsSf https://astral.sh/uv/install.sh | sh`. The
other commands are the same.

## API

| Method | Path | Description | Success | Errors |
|---|---|---|---|---|
| `GET` | `/health` | Liveness check | `200 {"status": "ok"}` | |
| `POST` | `/portfolios` | Create a portfolio (`{"name": "Retirement"}`) | `201` + portfolio | `409` name taken, `422` invalid name |
| `GET` | `/portfolios` | List portfolios | `200` + list | |
| `POST` | `/portfolios/{id}/trades` | Add one trade (JSON) or a CSV (multipart `file`) | `201` + trade, or list of trades for a CSV | `404`, `415`, `422` |
| `GET` | `/portfolios/{id}/trades` | List the portfolio's trades, newest first | `200` + list | `404` unknown portfolio |
| `POST` | `/trades` | Record an executed trade | `201` + trade | `422` invalid body |
| `GET` | `/trades` | List trades ordered by `executed_at`; optional `?symbol=` filter | `200` + list | |
| `GET` | `/trades/{id}` | Get one trade | `200` + trade | `404` not found |
| `POST` | `/trades/import` | Import a CSV of trades; returns open positions | `200` + positions | `422` bad rows |

**Trade fields**

| Field | Type | Rules |
|---|---|---|
| `symbol` | string | 1–16 chars; stored uppercased (`aapl` → `AAPL`) |
| `side` | `"BUY"` \| `"SELL"` | |
| `quantity` | decimal | `> 0` |
| `price` | decimal | `> 0` |
| `executed_at` | ISO-8601 datetime | e.g. `2026-09-24T14:30:00Z` |
| `id` | int | response only |
| `portfolio_id` | int | response only |

Quantities and prices are `Decimal` end to end (`NUMERIC(18,6)` in the DB), never `float`.
Send them as JSON strings (`"187.50"`) to avoid rounding errors.

**Example**

```powershell
# PowerShell
$body = @{ symbol="aapl"; side="BUY"; quantity="10"; price="187.50"; executed_at="2026-09-24T14:30:00Z" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/trades -ContentType application/json -Body $body
Invoke-RestMethod "http://127.0.0.1:8000/trades?symbol=AAPL"
```

```bash
# bash / curl
curl -X POST http://127.0.0.1:8000/trades -H "Content-Type: application/json" \
  -d '{"symbol":"aapl","side":"BUY","quantity":"10","price":"187.50","executed_at":"2026-09-24T14:30:00Z"}'
curl "http://127.0.0.1:8000/trades?symbol=AAPL"
```

### Portfolios

A portfolio has a unique `name` (1–64 characters, surrounding spaces trimmed). The `/trades`
endpoints predate portfolios and put every trade into a portfolio named **Default**, created on
first use.

`POST /portfolios/{id}/trades` picks the format from the request's `Content-Type`:

- `application/json`: one trade (see **Trade fields**). Responds `201` with the trade.
- `multipart/form-data` with a CSV in the `file` field (format below). Responds `201` with the
  list of created trades, in file order.
- Anything else: `415`.

Both are all or nothing, and a sell larger than the quantity held **in that portfolio** is
rejected with `422` (`row` is `null` for a JSON trade). An unknown portfolio id is `404`, checked
before the body is read.

```bash
curl -X POST http://127.0.0.1:8000/portfolios -H "Content-Type: application/json" -d '{"name":"Retirement"}'
curl -X POST http://127.0.0.1:8000/portfolios/1/trades -H "Content-Type: application/json" \
  -d '{"symbol":"aapl","side":"BUY","quantity":"10","price":"187.50","executed_at":"2026-09-24T14:30:00Z"}'
curl -F "file=@samples/trades.csv" http://127.0.0.1:8000/portfolios/1/trades
curl http://127.0.0.1:8000/portfolios/1/trades
curl http://127.0.0.1:8000/portfolios/1/pnl
```

### Realized P&L

`GET /portfolios/{id}/pnl` returns the realized P&L of each symbol that has had at least one sell
(including fully closed positions), sorted by symbol, and the total:

```json
{"portfolio_id": 1,
 "symbols": [{"symbol": "AAPL", "realized_pnl": "250.000000"},
             {"symbol": "MSFT", "realized_pnl": "-100.000000"}],
 "total": "150.000000"}
```

Each sell is matched against the oldest open lots first, and every lot slice it consumes realizes
`quantity x (sell price - lot price)`. Trades are replayed in `executed_at` order, not upload
order. Figures are rounded to 6 places per symbol and the total is the sum of those figures.
Fees are not modelled in v1. A sell larger than the position never reaches this endpoint: it is
rejected with `422` when the trade is added. Unknown portfolio: `404`.

**Why FIFO?** Lot matching decides which purchase a sale closes, which changes the realized
P&L (buy 10 @ 100, buy 10 @ 110, sell 15 @ 120 realizes 250 under FIFO but 200 under LIFO).
FIFO is used because:

- It is the IRS default for shares when specific lots aren't identified, so the numbers match
  what a US broker reports.
- It is deterministic and easy to check by hand, which makes it testable (see LED-204).
- Positions already use it, so `avg_cost` on open positions and realized P&L come from one
  lot-matching routine (`positions._match_fifo`) and always agree.

Average cost and specific-lot identification are out of scope for v1.

### CSV import

`POST /trades/import` (Default portfolio) and `POST /portfolios/{id}/trades` take a multipart
file field named `file`. The header must be
`date,symbol,side,quantity,price`. `date` is an ISO date (`2026-09-24`), an ISO datetime, or a
US-style `M/D/YYYY` date (`9/24/2026`, as US-locale Excel saves it); dates without a time are read
as midnight UTC. `D/M/YYYY` is **not** supported and would be misread. Files saved from Excel work,
including its UTF-8 byte-order mark and old-Mac `\r` line endings. See
[samples/trades.csv](samples/trades.csv).

- **All or nothing:** if any row is invalid, nothing is stored and the response is `422` listing
  every bad row, for example `{"detail": [{"row": 3, "reason": "quantity: Input should be greater than 0"}]}`.
  `row` is the line number in the file (the header is row 1).
- **`/trades/import` response:** open positions in the Default portfolio (all its trades, not just
  this file), sorted by symbol:
  `[{"symbol": "AAPL", "quantity": "15", "avg_cost": "186.666667"}]`.
- **Average cost is FIFO:** sells consume the oldest lots first, and `avg_cost` is the cost of the
  remaining lots divided by the quantity held (rounded to 6 places). Fully closed positions are omitted.
- A sell larger than the position held is rejected (`422`). Shorts are not supported.

```powershell
# PowerShell 7+ (Windows PowerShell 5.1 lacks -Form; use curl.exe below)
Invoke-RestMethod -Method Post -Uri http://127.0.0.1:8000/trades/import -Form @{ file = Get-Item samples/trades.csv }
```

```bash
curl -F "file=@samples/trades.csv" http://127.0.0.1:8000/trades/import
```

## Configuration

Settings are read from environment variables with the `LEDGER_` prefix, or from a `.env`
file in the working directory. Copy `.env.example` to `.env` to get started.

| Variable | Default | Notes |
|---|---|---|
| `LEDGER_DATABASE_URL` | `sqlite:///./ledger.db` | SQLite locally; a `postgresql://…` URL (e.g. from Neon) in production |
| `LEDGER_DEBUG` | `false` | |

## Development

```powershell
uv run pytest                          # all tests
uv run pytest tests/test_trades.py -v  # one file, verbose
uv run ruff check .                    # lint (add --fix to auto-fix)
uv run ruff format .                   # format
```

Each test gets its own in-memory SQLite database. The `client` fixture in
[tests/conftest.py](tests/conftest.py) overrides the `get_session` dependency, so tests
never touch `ledger.db`.

### Adding an endpoint

1. Add or extend the ORM model in `models.py` and the request/response schemas in `schemas.py`.
2. Add a router in `api/<resource>.py`. Inject a DB session with `session: SessionDep`.
3. Register the router in `create_app()` in `main.py`.
4. Add tests in `tests/test_<resource>.py` that use the `client` fixture.

## Deployment

The app runs on [Render](https://render.com)'s free tier, configured by
[render.yaml](render.yaml) (a Render "Blueprint"). Every push to `main` redeploys it.

- **Build:** `uv sync --frozen --no-dev`. Render detects `uv.lock` and uses the Python version in
  `.python-version` (3.12).
- **Start:** `uvicorn` on the `$PORT` Render provides. `/health` is the health check, and `/`
  redirects to `/docs`.
- **Cold starts:** a free service sleeps after 15 minutes without traffic, so the first request
  after that takes about a minute.
- **Database:** [Neon](https://neon.com) free-tier Postgres, so data survives deploys, restarts
  and sleeps. Render's own disk is temporary, which is why the app doesn't use SQLite there.
  Neon suspends after 5 idle minutes and wakes on the next query in about a second.

First-time setup:
1. In Neon, create a project and copy its connection string (`postgresql://…`).
2. In Render choose **New → Blueprint**, connect this GitHub repo, and apply. When asked, or later
   under the service's **Environment** tab, set `LEDGER_DATABASE_URL` to the Neon connection
   string.

Tables are created on startup (`create_all`). There are no migrations yet, so a change to an
existing table means resetting the database.

## Layout

```
src/ledger/
  main.py      app factory + startup           (Program.cs)
  config.py    settings from env / .env        (appsettings + IOptions)
  db.py        engine, session, Base           (DbContext)
  models.py    ORM tables                      (EF entities)
  schemas.py   request/response models         (DTOs)
  api/         routers, one file per resource  (Controllers)
    health.py
    trades.py
  csv_import.py  CSV parsing + per-row validation
  positions.py   FIFO position and realized P&L math (pure functions)
samples/       sample trades CSV
tests/         pytest; conftest.py = fixtures
```

The ASP.NET equivalents in parentheses are there for readers coming from C#.

## Roadmap

About 5 weeks to v1, at 20+ hours a week.

| Week | Goal | Done when |
|---|---|---|
| 1 | Trades CRUD | `tests/test_trades.py` passes, pushed to GitHub with CI |
| 2 | Positions & realized/unrealized P&L (FIFO) + Alembic migrations + Postgres via Docker | `/positions` and `/pnl` endpoints tested |
| 3 | Market data ingestion (scheduled price pulls, e.g. Alpha Vantage / Polygon), async httpx | prices stored; P&L marks to market |
| 4 | Risk metrics (exposure, volatility, VaR, drawdown) + WebSocket price/P&L stream | `/risk` endpoint + live stream demo |
| 5 | Auth, Dockerfile, deploy (Render/Fly), README with architecture diagram | public URL + write-up on cohenmr.com |

### Week 1 checklist

- [x] Run the quick start; open `/docs` and try `/health`
- [x] Create `github.com/cohenmichaelr/Ledger` and push
- [x] Implement `POST /trades`, `GET /trades`, `GET /trades/{id}`
- [x] Un-skip `tests/test_trades.py`; all tests pass
- [ ] GitHub Actions workflow that runs `ruff check` + `pytest` on push
- [ ] Stretch: `DELETE /trades/{id}` with a test you write yourself
