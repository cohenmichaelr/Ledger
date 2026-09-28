# Ledger

A trading & portfolio analytics backend: record trades, compute positions and P&L,
ingest market data, and expose risk metrics over a REST (and later streaming) API.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest · uv · ruff

> **Status:** Week 1 of 5. The trades API (create / list / get) works and is tested.
> Positions, P&L, market data and risk are next. See the [Roadmap](#roadmap).

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

### CSV import

`POST /trades/import` takes a multipart file field named `file`. The header must be
`date,symbol,side,quantity,price`. `date` is an ISO date (`2026-09-24`, read as midnight UTC) or
datetime. See [samples/trades.csv](samples/trades.csv).

- **All or nothing:** if any row is invalid, nothing is stored and the response is `422` listing
  every bad row, for example `{"detail": [{"row": 3, "reason": "quantity: Input should be greater than 0"}]}`.
  `row` is the line number in the file (the header is row 1).
- **Response:** open positions across **all** stored trades, not just this file, sorted by symbol:
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
| `LEDGER_DATABASE_URL` | `sqlite:///./ledger.db` | Any SQLAlchemy URL (Postgres arrives in Week 2) |
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
  positions.py   FIFO position math (pure functions)
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
