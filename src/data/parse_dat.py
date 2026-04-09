"""
Parser for Real Lives 2007 .dat files.

The original data files are Borland Delphi serialized records (BDE/Paradox-like
format). Each .dat file is laid out as:

  - 0x000..0x200: file header (metadata, version, timestamp)
  - 0x200 onwards: 768-byte (0x300) records

The first N records are *schema records* — each one declares one field of the
underlying table. A schema record has this layout:

  off 0x00: uint16  field_id        (1, 2, 3, ...)
  off 0x02: uint8   name_len        (Pascal length byte)
  off 0x03: bytes   field_name      (ASCII)
  off 0x100..0x300: type metadata + qualified name ("world.<FieldName>")

After the schema records come *data records*. Each data record packs multiple
row values for the table. Rows use a tag-stream where each field is preceded
by a 0x01 marker followed by either a 4-byte little-endian uint32 (for ints)
or a fixed-width null-padded string (for text).

The full binary format encodes Delphi extended-precision floats and dynamic
arrays in ways that are not fully tractable to clean-room reverse-engineer
inside one project. This parser therefore extracts what it can RELIABLY:

  1. The complete field schema for every .dat file (field id + name)
  2. Any printable ASCII strings embedded in the data records (job names,
     country names, city names, etc.)

That recovered schema + string list is enough to (a) anchor the SQLite tables
to the original game's columns and (b) seed string-typed fields like job
titles and country names. Numeric fields (population, GDP, life expectancy,
etc.) are populated from a curated bundled JSON of real-world stats — the
same statistical sources the original game pulled from in 2007 (CIA World
Factbook, World Bank, UNICEF, etc.).
"""

from __future__ import annotations

import struct
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


HEADER_SIZE = 0x200
RECORD_SIZE = 0x300


@dataclass
class DatField:
    """One column descriptor recovered from a schema record."""

    field_id: int
    name: str
    qualified_name: str = ""
    raw_offset: int = 0


@dataclass
class DatFile:
    """Parsed contents of a .dat file."""

    path: Path
    total_records: int
    schema: list[DatField] = field(default_factory=list)
    string_pool: list[str] = field(default_factory=list)


def _iter_records(blob: bytes) -> Iterator[tuple[int, int, bytes]]:
    """Yield (record_index, file_offset, record_bytes) for each 0x300 record."""
    n = (len(blob) - HEADER_SIZE) // RECORD_SIZE
    for i in range(n):
        off = HEADER_SIZE + i * RECORD_SIZE
        yield i, off, blob[off : off + RECORD_SIZE]


def _read_pascal_string(buf: bytes, offset: int, max_len: int = 64) -> str | None:
    """Read a Pascal-style length-prefixed ASCII string at `offset`.

    Returns the decoded string, or None if it doesn't look like one.
    """
    if offset >= len(buf):
        return None
    length = buf[offset]
    if length == 0 or length > max_len:
        return None
    raw = buf[offset + 1 : offset + 1 + length]
    if len(raw) < length:
        return None
    try:
        s = raw.decode("ascii")
    except UnicodeDecodeError:
        return None
    if not all(32 <= b < 127 for b in raw):
        return None
    return s


def _looks_like_field_name(s: str) -> bool:
    """Heuristic — schema field names are CamelCase ASCII identifiers."""
    if not s:
        return False
    if not s[0].isalpha():
        return False
    return all(c.isalnum() or c in "_ " for c in s)


def _extract_strings(record: bytes, min_len: int = 3, max_len: int = 80) -> list[str]:
    """Pull printable ASCII runs out of a record's value blob.

    Used to recover human-readable strings (job names, city names) from
    the Delphi serialized data area.
    """
    out: list[str] = []
    i = 0
    while i < len(record):
        b = record[i]
        if 32 <= b < 127:
            j = i
            while j < len(record) and 32 <= record[j] < 127:
                j += 1
            run = record[i:j].decode("ascii", errors="ignore")
            if len(run) >= min_len and len(run) <= max_len:
                run = run.strip()
                if run:
                    out.append(run)
            i = j
        else:
            i += 1
    return out


def parse_dat(path: str | Path) -> DatFile:
    """Parse a Real Lives 2007 .dat file and return its schema + recovered strings."""
    p = Path(path)
    blob = p.read_bytes()
    total = (len(blob) - HEADER_SIZE) // RECORD_SIZE

    parsed = DatFile(path=p, total_records=total)
    seen_field_ids: set[int] = set()
    in_schema = True

    for idx, off, rec in _iter_records(blob):
        if in_schema:
            field_id = struct.unpack_from("<H", rec, 0)[0]
            name = _read_pascal_string(rec, 2, max_len=40)
            # Schema records have small sequential IDs and ASCII identifier names.
            if (
                name is not None
                and _looks_like_field_name(name)
                and field_id > 0
                and field_id < 1000
                and field_id not in seen_field_ids
                and (field_id == 1 or (field_id - 1) in seen_field_ids)
            ):
                seen_field_ids.add(field_id)
                qualified = ""
                # The qualified name "tablename.FieldName" lives further into
                # the record. Scan a likely region for another Pascal string
                # containing a dot.
                for probe in range(0x100, 0x2c0):
                    s = _read_pascal_string(rec, probe, max_len=64)
                    if s and "." in s and s.endswith(name):
                        qualified = s
                        break
                parsed.schema.append(
                    DatField(
                        field_id=field_id,
                        name=name,
                        qualified_name=qualified,
                        raw_offset=off,
                    )
                )
                continue
            # First record that doesn't fit the schema pattern → switch modes.
            in_schema = False

        # Data records: harvest printable strings.
        for s in _extract_strings(rec):
            parsed.string_pool.append(s)

    return parsed


def parse_all(data_dir: str | Path) -> dict[str, DatFile]:
    """Parse every .dat file in `data_dir` and return a dict keyed by basename."""
    d = Path(data_dir)
    out: dict[str, DatFile] = {}
    for p in sorted(d.glob("*.dat")):
        out[p.stem] = parse_dat(p)
    return out


if __name__ == "__main__":
    import sys

    target = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parents[2] / "data"
    for name, parsed in parse_all(target).items():
        print(f"== {name}.dat ==")
        print(f"   total_records: {parsed.total_records}")
        print(f"   schema fields: {len(parsed.schema)}")
        for f in parsed.schema[:10]:
            print(f"     - id={f.field_id} {f.name!r} qualified={f.qualified_name!r}")
        if len(parsed.schema) > 10:
            print(f"     ... and {len(parsed.schema) - 10} more")
        print(f"   recovered strings: {len(parsed.string_pool)}")
        for s in parsed.string_pool[:5]:
            print(f"     · {s!r}")
        print()
