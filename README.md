# Ledger

A trading & portfolio analytics backend: record trades, compute positions and P&L,
ingest market data, and expose risk metrics over a REST (and later streaming) API.

**Stack:** Python 3.12 · FastAPI · SQLAlchemy 2.0 · Pydantic · pytest · uv · ruff

## Quick start (Windows / PowerShell)

```powershell
# one-time: install uv  (https://docs.astral.sh/uv/)
powershell -ExecutionPolicy ByPass -c "irm https://astral.sh/uv/install.ps1 | iex"

cd $HOME\Projects\ledger
uv python install 3.12
uv sync                                   # creates .venv and installs deps
uv run pytest                             # run tests
uv run uvicorn ledger.main:app --reload   # http://127.0.0.1:8000/docs
uv run ruff check . ; uv run ruff format .
```

## Layout

```
src/ledger/
  main.py      app factory + startup           (Program.cs)
  config.py    settings from env / .env        (appsettings + IOptions)
  db.py        engine, session, Base           (DbContext)
  models.py    ORM tables                      (EF entities)
  schemas.py   request/response models         (DTOs)
  api/         routers, one file per resource  (Controllers)
tests/         pytest; conftest.py = fixtures
```

## Roadmap (v1 in ~5 weeks, 20+ hrs/week)

| Week | Goal | Done when |
|---|---|---|
| 1 | Trades CRUD | `tests/test_trades.py` passes, pushed to GitHub with CI |
| 2 | Positions & realized/unrealized P&L (FIFO) + Alembic migrations + Postgres via Docker | `/positions` and `/pnl` endpoints tested |
| 3 | Market data ingestion (scheduled price pulls, e.g. Alpha Vantage / Polygon), async httpx | prices stored; P&L marks to market |
| 4 | Risk metrics (exposure, volatility, VaR, drawdown) + WebSocket price/P&L stream | `/risk` endpoint + live stream demo |
| 5 | Auth, Dockerfile, deploy (Render/Fly), README with architecture diagram | public URL + write-up on cohenmr.com |

## Week 1 tasks

1. Run the quick start; open `/docs` and try `/health`.
2. `git init`, create `github.com/cohenmichaelr/ledger`, push.
3. Implement the three endpoints in `src/ledger/api/trades.py` (TODO hints inside).
4. Delete the `pytestmark = ...skip` line in `tests/test_trades.py`; make all tests pass.
5. Add a GitHub Actions workflow that runs `ruff check` + `pytest` on push.
6. Stretch: add `DELETE /trades/{id}` with a test you write yourself.
