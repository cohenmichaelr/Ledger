# CLAUDE.md

Guidance for Claude when working in this repository.

## Project
Ledger is a trading and portfolio analytics backend, my portfolio project for returning to
hands-on development. v1 target: a deployed, tested API by Nov 1, 2026.

**Source of truth for scope and status is the Ledger v1 Release Board**
(https://claude.ai/artifact/6UhSYLPTdhnARH1pvTSrAQ). I paste the story I'm working on
(e.g. LED-202) into each session. Do not plan from the README roadmap.

## Stack
Python 3.12 · FastAPI · SQLAlchemy 2.0 · Pydantic v2 · pytest · uv · ruff.
SQLite locally; hosted Neon Postgres in production via `LEDGER_DATABASE_URL` (LED-201).
Deployed on Render free tier (`render.yaml`); every push to `main` redeploys.

I'm coming from C#/.NET. When you introduce a Python idiom I may not know, add a short
comment or explain it in your reply. Keep the existing ASP.NET / EF Core analogies style.

## Commands (Windows / PowerShell)
```powershell
uv sync                                   # install deps (incl. dev) into .venv
uv run uvicorn ledger.main:app --reload   # run API; docs at http://127.0.0.1:8000/docs
uv run pytest                             # all tests
uv run pytest tests/test_trades.py -v     # one file
uv run ruff check .                       # lint (--fix to auto-fix)
uv run ruff format .                      # format
```
Ruff: line length 100, rules `E, F, I, UP, B`. pytest runs with `pythonpath = ["src"]`.

## Layout
- `src/ledger/main.py` app factory `create_app()` · `config.py` settings (`LEDGER_*` env / `.env`)
- `db.py` engine, `Base`, per-request session via `SessionDep`
- `models.py` ORM tables (`Portfolio`, `Trade`) · `schemas.py` Pydantic request/response models
- `positions.py` FIFO position math (`compute_positions`) · `csv_import.py` CSV parsing and row errors
- `portfolios.py` default-portfolio helper · `api/` one router per resource
- `tests/` pytest; the `client` fixture in `conftest.py` gives each test an in-memory database
- `samples/trades.csv` sample upload

Adding an endpoint: model → schemas → router in `api/<resource>.py` using `SessionDep` →
register in `create_app()` → tests in `tests/test_<resource>.py` using `client`.

## Conventions
- Money and quantities are `Decimal` end to end, `Numeric(18, 6)` in the DB. Never float.
- SQLAlchemy 2.0 style: `select()`, `Mapped[]`, `mapped_column()`. No legacy `query()` API.
- ORM models and API schemas stay separate; routes return ORM objects and let
  `response_model` serialize (read schemas use `from_attributes=True`).
- Symbols are stored uppercase and matched uppercase.
- Tables are created at startup with `create_all`; no migrations in v1.
- Tests never call external APIs. Fake the market-data adapter.

## How we work
1. Plan first. For any story, propose a short plan and wait for my OK before writing code.
2. One story per session. Stay inside its acceptance criteria.
3. Small steps: change, run tests, then continue. Never stack changes on failing tests.
4. When tests pass, suggest a commit message. Small commits with clear messages.
5. If a fix fails twice, stop and tell me. We revert to the last commit and try a smaller ask.
6. Don't add dependencies without asking.
7. If something I ask is outside v1 scope, say so instead of building it.

## v1 scope
In: CSV trade import, trades and portfolios, positions, realized P&L (FIFO), end-of-day prices
with caching, unrealized P&L, exposure, concentration, max drawdown, deployment.
Out (v2): front end, auth, Docker, Alembic, intraday or streaming prices, WebSocket,
VaR/volatility, options, shorts, multi-currency.

## Definition of done for a story
All acceptance criteria met · tests pass · ruff clean · README updated if behavior changed · committed.
