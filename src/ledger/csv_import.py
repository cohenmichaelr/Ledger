"""Parse a trades CSV (date, symbol, side, quantity, price) into validated TradeCreate rows."""

import csv
import io
import re
from dataclasses import dataclass
from datetime import datetime, timezone

from pydantic import ValidationError

from ledger.schemas import TradeCreate

COLUMNS = ("date", "symbol", "side", "quantity", "price")
DATE_FORMATS = "YYYY-MM-DD, an ISO datetime, or M/D/YYYY"
US_DATE = re.compile(r"\d{1,2}/\d{1,2}/\d{4}")  # 9/1/2026, as US-locale Excel exports dates


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

    # newline="" hands line endings to the csv module, which understands \n, \r\n and bare \r
    # (old Mac/Excel exports). Without it, a \r-only file reads as one broken line.
    reader = csv.DictReader(io.StringIO(text, newline=""))
    try:
        trades, errors = _read_rows(reader)
    except csv.Error as exc:  # e.g. an unterminated quote
        raise CsvImportError([RowError(reader.line_num or 1, f"unreadable CSV: {exc}")]) from None

    if errors:
        raise CsvImportError(errors)
    if not trades:
        raise CsvImportError([RowError(1, "file has no trade rows")])
    return trades


def _read_rows(reader: csv.DictReader) -> tuple[list[tuple[int, TradeCreate]], list[RowError]]:
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
        date = record["date"].strip()
        if US_DATE.fullmatch(date):
            try:
                # strptime = parse with an explicit format (like DateTime.ParseExact)
                date = datetime.strptime(date, "%m/%d/%Y").date().isoformat()
            except ValueError:
                errors.append(RowError(row, f"date: {date!r} is not a valid M/D/YYYY date"))
                continue
        try:
            trade = TradeCreate(
                symbol=record["symbol"].strip(),
                side=record["side"].strip().upper(),
                quantity=record["quantity"].strip(),
                price=record["price"].strip(),
                executed_at=date,
            )
        except ValidationError as exc:
            reasons = []
            for err in exc.errors():
                if err["loc"][0] == "executed_at":
                    # pydantic's message ("input is too short") doesn't say what we accept
                    reasons.append(f"date: {date!r} is not a date; use {DATE_FORMATS}")
                else:
                    reasons.append(f"{err['loc'][0]}: {err['msg']}")
            errors.append(RowError(row, "; ".join(reasons)))
            continue
        if trade.executed_at.tzinfo is None:  # a bare date like 2026-09-24 -> midnight UTC
            trade.executed_at = trade.executed_at.replace(tzinfo=timezone.utc)
        trade.symbol = trade.symbol.upper()
        trades.append((row, trade))
    return trades, errors
