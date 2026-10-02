"""Read fixed width payroll text into raw rows keyed by canonical field."""

from contribflow.connector import Connector
from contribflow.parsing.parsed_file import ParsedFile, RawRow


def slice_fields(line: str, positions: dict[str, tuple[int, int]]) -> dict[str, str]:
    return {field: line[start:end] for field, (start, end) in positions.items()}


def parse_fixed_width(text: str, connector: Connector) -> ParsedFile:
    parsed = ParsedFile()
    trailers = []

    for line_number, line in enumerate(text.splitlines(), start=1):
        if not line.strip():
            continue
        record_type = line[0]
        if record_type == connector.header_record_type:
            continue
        if record_type == connector.detail_record_type:
            values = slice_fields(line, connector.fields)
            parsed.rows.append(RawRow(line_number=line_number, values=values))
        elif record_type == connector.trailer_record_type:
            trailers.append(slice_fields(line, connector.trailer_fields))
        elif "UNKNOWN_RECORD_TYPE" not in parsed.file_errors:
            parsed.file_errors.append("UNKNOWN_RECORD_TYPE")

    if len(trailers) == 1:
        parsed.trailer = trailers[0]
    elif not trailers:
        parsed.file_errors.append("TRAILER_MISSING")
    else:
        parsed.file_errors.append("TRAILER_MALFORMED")
    return parsed
