"""HTTP error helpers shared by the routers."""

from dataclasses import asdict

from fastapi import HTTPException, Request, status
from fastapi.responses import JSONResponse

from ledger.csv_import import RowError
from ledger.market_data import MarketDataError


def unprocessable(errors: list[RowError]) -> HTTPException:
    """422 whose detail lists each bad row: [{"row": 3, "reason": "..."}]."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=[asdict(e) for e in errors]
    )


def market_data_unavailable(request: Request, exc: MarketDataError) -> JSONResponse:
    """Exception handler: a price we need can't be had (API down and nothing cached) -> 503.

    Registered in create_app(), like an exception filter in ASP.NET.
    """
    return JSONResponse(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE, content={"detail": str(exc)}
    )
