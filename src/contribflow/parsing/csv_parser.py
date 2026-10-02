"""Read CSV payroll text into raw rows keyed by canonical field."""

import csv
import io

from contribflow.connector import Connector
from contribflow.parsing.parsed_file import ParsedFile, RawRow


def parse_csv(text: str, connector: Connector) -> ParsedFile:
    # newline="" lets the csv module handle both \n and \r\n line endings.
    reader = csv.DictReader(io.StringIO(text, newline=""))
    header = reader.fieldnames or []
    if any(column not in header for column in connector.columns.values()):
        return ParsedFile(file_errors=["COLUMN_MISSING"])

    parsed = ParsedFile()
    for row in reader:
        # A short row leaves trailing columns as None.
        values = {field: row[column] or "" for field, column in connector.columns.items()}
        parsed.rows.append(RawRow(line_number=reader.line_num, values=values))
    return parsed
