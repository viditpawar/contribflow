from contribflow.connector import Connector
from contribflow.parsing.csv_parser import parse_csv
from contribflow.parsing.fixed_width_parser import parse_fixed_width
from contribflow.parsing.parsed_file import ParsedFile


def parse_file(text: str, connector: Connector) -> ParsedFile:
    if connector.format == "csv":
        return parse_csv(text, connector)
    return parse_fixed_width(text, connector)
