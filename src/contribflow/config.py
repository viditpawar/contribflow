"""Load configuration files: plan limits and the employee census."""

import csv
import io
from decimal import Decimal
from pathlib import Path

import yaml
from pydantic import BaseModel

from contribflow.models import CensusEmployee


class PlanYearLimits(BaseModel):
    deferral_limit: Decimal
    catch_up_limit: Decimal
    catch_up_age: int
    enhanced_catch_up_limit: Decimal
    enhanced_catch_up_min_age: int
    enhanced_catch_up_max_age: int


class Limits(BaseModel):
    plan_years: dict[int, PlanYearLimits]
    election_tolerance: Decimal


def load_limits(path: Path) -> Limits:
    return Limits.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))


def load_census_text(text: str) -> dict[str, CensusEmployee]:
    census = {}
    for row in csv.DictReader(io.StringIO(text, newline="")):
        employee = CensusEmployee.model_validate(row)
        if employee.employee_id in census:
            raise ValueError(f"duplicate employee_id in census: {employee.employee_id}")
        census[employee.employee_id] = employee
    return census


def load_census(path: Path) -> dict[str, CensusEmployee]:
    return load_census_text(path.read_text(encoding="utf-8-sig"))
