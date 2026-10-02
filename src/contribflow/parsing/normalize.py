"""Convert raw text values into a typed canonical record (D12, D27)."""

import re
from datetime import date, datetime
from decimal import Decimal

from contribflow.connector import Connector
from contribflow.models import AMOUNT_FIELDS, DATE_FIELDS, INPUT_FIELDS, CanonicalContribution
from contribflow.parsing.parsed_file import RawRow

CENTS = Decimal("0.01")

# Strict on purpose: Decimal() alone would accept "NaN", "1e5" and negative values.
AMOUNT_PATTERNS = {
    "plain": re.compile(r"[0-9]+\.[0-9]{2}"),  # 1234.56
    "currency": re.compile(r"\$[0-9]{1,3}(,[0-9]{3})*\.[0-9]{2}"),  # $1,234.56
    "implied_cents": re.compile(r"[0-9]+"),  # 0000123456
}


def parse_amount(text: str, style: str) -> Decimal:
    if not AMOUNT_PATTERNS[style].fullmatch(text):
        raise ValueError(f"not a {style} amount: {text!r}")
    if style == "implied_cents":
        return (Decimal(text) / 100).quantize(CENTS)
    return Decimal(text.replace("$", "").replace(",", ""))


def parse_date(text: str, date_format: str) -> date:
    return datetime.strptime(text, date_format).date()


def normalize(raw: RawRow, connector: Connector) -> CanonicalContribution:
    values = {}
    field_errors = {}

    for field in INPUT_FIELDS:
        text = raw.values.get(field, "").strip()
        if not text:
            field_errors[field] = "MISSING_FIELD"
            continue
        try:
            if field in DATE_FIELDS:
                values[field] = parse_date(text, connector.date_format)
            elif field in AMOUNT_FIELDS:
                values[field] = parse_amount(text, connector.amount_style)
            else:
                values[field] = text
        except ValueError:
            field_errors[field] = "MALFORMED_FIELD"

    return CanonicalContribution(
        connector_id=connector.id,
        source_row=raw.line_number,
        field_errors=field_errors,
        **values,
    )
