"""File level controls that need normalized records (D24)."""

import re

from contribflow.connector import Connector
from contribflow.models import CanonicalContribution
from contribflow.parsing.normalize import parse_amount


def check_trailer(
    trailer: dict[str, str], records: list[CanonicalContribution], connector: Connector
) -> list[str]:
    count_text = trailer["record_count"].strip()
    total_text = trailer["deferral_total"].strip()
    if not re.fullmatch(r"[0-9]+", count_text):
        return ["TRAILER_MALFORMED"]
    try:
        trailer_total = parse_amount(total_text, connector.amount_style)
    except ValueError:
        return ["TRAILER_MALFORMED"]

    errors = []
    if int(count_text) != len(records):
        errors.append("TRAILER_COUNT_MISMATCH")

    # If any deferral is unreadable the total cannot be verified, so it counts as a mismatch.
    deferrals = [r.pretax_deferral for r in records] + [r.roth_deferral for r in records]
    if any(d is None for d in deferrals) or sum(deferrals) != trailer_total:
        errors.append("TRAILER_TOTAL_MISMATCH")
    return errors
