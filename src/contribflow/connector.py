"""Connector specs: how one provider's file maps to canonical fields (D11)."""

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel

from contribflow.models import INPUT_FIELDS

CONNECTORS_DIR = Path(__file__).parent / "connectors"


class Connector(BaseModel):
    id: str
    format: Literal["csv", "fixed_width"]
    date_format: str
    amount_style: Literal["plain", "currency", "implied_cents"]

    # csv only: canonical field -> column header in the file
    columns: dict[str, str] = {}

    # fixed_width only: canonical field -> [start, end) character positions,
    # used exactly like a Python slice: line[start:end]
    fields: dict[str, tuple[int, int]] = {}
    header_record_type: str | None = None
    detail_record_type: str | None = None
    trailer_record_type: str | None = None
    trailer_fields: dict[str, tuple[int, int]] = {}


def load_connector(connector_id: str) -> Connector:
    path = CONNECTORS_DIR / f"{connector_id}.yaml"
    connector = Connector.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))

    mapping = connector.columns if connector.format == "csv" else connector.fields
    if set(mapping) != set(INPUT_FIELDS):
        raise ValueError(
            f"connector {connector_id} must map exactly these fields: {sorted(INPUT_FIELDS)}"
        )
    return connector
