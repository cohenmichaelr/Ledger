"""HTTP error helpers shared by the routers."""

from dataclasses import asdict

from fastapi import HTTPException, status

from ledger.csv_import import RowError


def unprocessable(errors: list[RowError]) -> HTTPException:
    """422 whose detail lists each bad row: [{"row": 3, "reason": "..."}]."""
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=[asdict(e) for e in errors]
    )
