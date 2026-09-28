"""Parse a trades CSV (date, symbol, side, quantity, price) into validated TradeCreate rows."""

import csv
import io
from dataclasses import dataclass
from datetime import timezone

from pydantic import ValidationError

from ledger.schemas import TradeCreate

COLUMNS = ("date", "symbol", "side", "quantity", "price")


@dataclass
class RowError:
    row: int | None  # line number in the file; the header is row 1, like a spreadsheet
    reason: str


class CsvImportError(ValueError):
    def __init__(self, errors: list[RowError]):
        self.errors = errors
        super().__init__(f"{len(errors)} invalid row(s)")


def parse_trades_csv(data: bytes) -> list[tuple[int, TradeCreate]]:
    """Return (row number, trade) pairs, or raise CsvImportError listing every bad row."""
    try:
        text = data.decode("utf-8-sig")  # -sig strips the byte-order mark Excel adds
    except UnicodeDecodeError:
        raise CsvImportError([RowError(1, "file is not UTF-8 text")]) from None

    reader = csv.DictReader(io.StringIO(text))
    header = [name.strip().lower() for name in reader.fieldnames or []]
    if sorted(header) != sorted(COLUMNS):
        raise CsvImportError([RowError(1, f"header must be: {','.join(COLUMNS)}")])
    reader.fieldnames = header  # use the cleaned-up names as dict keys

    trades: list[tuple[int, TradeCreate]] = []
    errors: list[RowError] = []
    for record in reader:
        row = reader.line_num  # physical line just read (blank lines are skipped but counted)
        # DictReader puts extra values under the key None and fills missing ones with None
        if None in record or None in record.values():
            errors.append(RowError(row, f"expected {len(COLUMNS)} columns"))
            continue
        try:
            trade = TradeCreate(
                symbol=record["symbol"].strip(),
                side=record["side"].strip().upper(),
                quantity=record["quantity"].strip(),
                price=record["price"].strip(),
                executed_at=record["date"].strip(),
            )
        except ValidationError as exc:
            reasons = []
            for err in exc.errors():
                field = "date" if err["loc"][0] == "executed_at" else err["loc"][0]
                reasons.append(f"{field}: {err['msg']}")
            errors.append(RowError(row, "; ".join(reasons)))
            continue
        if trade.executed_at.tzinfo is None:  # a bare date like 2026-09-24 -> midnight UTC
            trade.executed_at = trade.executed_at.replace(tzinfo=timezone.utc)
        trade.symbol = trade.symbol.upper()
        trades.append((row, trade))

    if errors:
        raise CsvImportError(errors)
    if not trades:
        raise CsvImportError([RowError(1, "file has no trade rows")])
    return trades
