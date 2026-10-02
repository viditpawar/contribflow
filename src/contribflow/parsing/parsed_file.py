"""What a parser returns: raw text values, before any type conversion."""

from dataclasses import dataclass, field


@dataclass
class RawRow:
    line_number: int
    # canonical field -> text exactly as it appeared in the file
    values: dict[str, str]


@dataclass
class ParsedFile:
    rows: list[RawRow] = field(default_factory=list)
    # file level reason codes (D24, D27); any entry rejects the whole file
    file_errors: list[str] = field(default_factory=list)
    # fixed width only: trailer field -> text
    trailer: dict[str, str] | None = None
