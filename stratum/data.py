"""Read a data table for the evidence checks (DECISIONS.md D-048).

A CSV file with a header row, UTF-8. Every cell is kept as text with surrounding
whitespace stripped; nothing is converted, filled in, or dropped here. Undeclared
extra columns are kept and simply never used.
"""
import csv
import io
import re
from dataclasses import dataclass
from fractions import Fraction
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Union

MISSING_TOKENS = ("", "NA")       # D-043 reading 5
_DECIMAL = re.compile(r"^[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?$")


@dataclass(frozen=True)
class Table:
    columns: Tuple[str, ...]
    rows: Tuple[Dict[str, str], ...]
    source: str = ""


def read_table(source: Union[Path, str], *, text: Optional[str] = None) -> Table:
    """Read a CSV from a path, or from `text` (source is then only a label)."""
    if text is None:
        text = Path(source).read_text(encoding="utf-8-sig")
    reader = csv.reader(io.StringIO(text), strict=True)
    try:
        header = [h.strip() for h in next(reader)]
    except StopIteration:
        return Table((), (), str(source))
    if not header or any(not h for h in header) or len(set(header)) != len(header):
        raise ValueError("CSV headers must be nonempty and unique after trimming whitespace")
    rows: List[Dict[str, str]] = []
    for raw in reader:
        if not raw or all(not c.strip() for c in raw):
            continue                                  # a blank line is not a row
        if len(raw) != len(header):
            raise ValueError("CSV row at line %d has %d fields; header has %d. "
                             "Use an empty field or NA for a missing response."
                             % (reader.line_num, len(raw), len(header)))
        cells = [c.strip() for c in raw]
        rows.append(dict(zip(header, cells)))
    return Table(tuple(header), tuple(rows), str(source))


def is_missing(cell: str) -> bool:
    return cell in MISSING_TOKENS


def parse_response(cell: str) -> Optional[Fraction]:
    """The exact value of a finite decimal number, or None if it is not one."""
    if not _DECIMAL.match(cell):
        return None
    return Fraction(cell)
