"""LED-201: trades and portfolios are persisted and survive an app restart."""

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ledger.config import Settings
from ledger.db import make_engine
from ledger.models import Portfolio

from .conftest import client_for

TRADE = {
    "symbol": "AAPL",
    "side": "BUY",
    "quantity": "10",
    "price": "187.50",
    "executed_at": "2026-09-24T14:30:00Z",
}


def test_trades_survive_app_restart(tmp_path):
    url = f"sqlite:///{tmp_path / 'ledger.db'}"  # a real file, like production

    engine = make_engine(url)
    with client_for(engine) as client:
        created = client.post("/trades", json=TRADE).json()
    engine.dispose()  # close every connection: the "process" is gone

    engine = make_engine(url)  # a brand-new app starting against the same file
    with client_for(engine) as client:
        trades = client.get("/trades").json()
    engine.dispose()

    assert trades == [created]


def test_trades_go_into_one_default_portfolio(client):
    first = client.post("/trades", json=TRADE).json()
    client.post(
        "/trades/import",
        files={"file": ("t.csv", "date,symbol,side,quantity,price\n2026-09-25,MSFT,BUY,1,400\n")},
    )
    ids = {t["portfolio_id"] for t in client.get("/trades").json()}
    assert ids == {first["portfolio_id"]}


def test_default_portfolio_is_created_once(tmp_path):
    engine = make_engine(f"sqlite:///{tmp_path / 'ledger.db'}")
    with client_for(engine) as client:
        client.post("/trades", json=TRADE)
        client.post("/trades", json=TRADE)
    with Session(engine) as session:
        names = session.scalars(select(Portfolio.name)).all()
        assert names == ["Default"]
        assert session.scalar(select(func.count()).select_from(Portfolio)) == 1
    engine.dispose()


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (
            "postgresql://u:p@host/db?sslmode=require",
            "postgresql+psycopg://u:p@host/db?sslmode=require",
        ),
        ("postgres://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
        ("sqlite:///./ledger.db", "sqlite:///./ledger.db"),
    ],
)
def test_database_url_uses_psycopg_driver(given, expected):
    assert Settings(database_url=given).database_url == expected
