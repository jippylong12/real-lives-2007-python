"""
Parser for Real Lives 2007 .dat files.

The original data files are Borland Delphi serialized records (BDE/Paradox-like
format). Each .dat file is laid out as:

  - 0x000..0x200: file header (magic 0x77 0x08 ..., timestamp, metadata)
  - 0x200 onwards: 768-byte (0x300) records

The first N records are *schema records* — each one declares one field of the
underlying table. A schema record has this layout:

  off 0x00: uint16  field_id        (1, 2, 3, ...)
  off 0x02: uint8   name_len        (Pascal length byte)
  off 0x03: bytes   field_name      (ASCII)
  off 0xa4: uint16  type_code       (1=string, 4/5=int16, 6=uint32, 7=double)
  off 0xa9: uint16  slot_size       (bytes occupied by the value, sans tag)
  off 0xac: uint32  record_offset   (byte offset of the 0x01 tag inside the
                                      *concatenated* per-country data buffer)
  off 0x1e6..    : qualified name "tablename.FieldName" as a Pascal string

After the schema records come *data records*. Each country occupies three
consecutive 0x300 records, treated as one 0x900 buffer. Inside that buffer
each field's value is preceded by a 0x01 tag at the offset given by the
schema's record_offset. The decoder is implemented in
:func:`decode_country_record`.

That recovered schema + decoded values + string pool is enough to (a) anchor
the SQLite tables to the original game's columns, (b) seed string-typed
fields like job titles and country names, and (c) optionally cross-check the
curated real-world stats in :mod:`src.data.seed` against the binary's
2007-era values.
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
    type_code: int = 0
    slot_size: int = 0
    record_offset: int = 0  # offset of the 0x01 tag inside the per-row buffer

    @property
    def python_type(self) -> str:
        """A short label describing how to decode this field's value."""
        return _TYPE_NAMES.get(self.type_code, "unknown")


# Schema type codes recovered from world.dat / jobs.dat / etc. by examining
# how each field's slot_size lines up with the bytes the data records actually
# carry at its declared offset.
_TYPE_NAMES: dict[int, str] = {
    1: "string",
    4: "int16",   # used for boolean-ish flags (AtWar, etc.)
    5: "int16",
    6: "uint32",
    7: "double",
}


@dataclass
class DatFile:
    """Parsed contents of a .dat file."""

    path: Path
    total_records: int
    schema: list[DatField] = field(default_factory=list)
    string_pool: list[str] = field(default_factory=list)
    # Per-record short strings (>= 3 chars, tagged with record index).
    record_strings: dict[int, list[str]] = field(default_factory=dict)
    # Long printable runs (>= 30 chars), tagged with the record index they
    # came from. Used to recover encyclopedia-style descriptive text.
    long_strings: list[tuple[int, str]] = field(default_factory=list)


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


def _extract_long_strings(record: bytes, min_len: int = 30, max_len: int = 1500) -> list[str]:
    """Pull *long* printable ASCII runs out of a record's value blob.

    Encyclopedia-style fields (Location, Climate, Terrain, EnvironmentalIssues,
    EncyclopediaHistoryName, ...) are 50–250 char descriptive sentences. The
    short-string extractor caps runs at 80 chars and would truncate them, so
    we run a separate pass with a much higher cap.
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
                # Type / size / offset live at fixed positions in the schema
                # record (recovered by reverse-engineering Algeria + Afghanistan).
                type_code = struct.unpack_from("<H", rec, 0xa4)[0]
                slot_size = struct.unpack_from("<H", rec, 0xa9)[0]
                record_offset = struct.unpack_from("<I", rec, 0xac)[0]
                parsed.schema.append(
                    DatField(
                        field_id=field_id,
                        name=name,
                        qualified_name=qualified,
                        raw_offset=off,
                        type_code=type_code,
                        slot_size=slot_size,
                        record_offset=record_offset,
                    )
                )
                continue
            # First record that doesn't fit the schema pattern → switch modes.
            in_schema = False

        # Data records: harvest printable strings.
        rec_short = _extract_strings(rec)
        if rec_short:
            parsed.record_strings[idx] = rec_short
            for s in rec_short:
                parsed.string_pool.append(s)
        for s in _extract_long_strings(rec):
            parsed.long_strings.append((idx, s))

    return parsed


_CITY_STOP_TOKENS = {
    # Religions, languages, ethnic / cultural identifiers, geographic descriptors
    # — anything that looks like a Capitalized place but isn't.
    "Muslim", "Catholic", "Protestant", "Christian", "Hindu", "Buddhist", "Jewish",
    "Orthodox", "Sunni", "Shia", "Shi'a", "Coptic", "Animist", "Roman", "Sikh",
    "Jain", "Anglican", "Baptist", "Lutheran", "Methodist", "Adventist",
    "Other", "None", "Indigenous", "Mixed", "Black", "White", "African", "European",
    "Asian", "Arab", "Persian", "Slav", "Turkic", "Latin", "Mestizo", "Creole",
    "Spanish", "English", "French", "German", "Italian", "Portuguese", "Russian",
    "Chinese", "Japanese", "Korean", "Vietnamese", "Hindi", "Urdu", "Arabic",
    "Turkish", "Bengali", "Pashto", "Dari", "Tajik", "Uzbek", "Hausa", "Yoruba",
    "Igbo", "Swahili", "Berber", "Tagalog", "Filipino", "Malay", "Thai", "Khmer",
    "Lao", "Burmese", "Mongolian", "Tibetan", "Uighur", "Maori", "Polynesian",
    "Melanesian", "Micronesian", "Aboriginal", "Inuit", "Quechua", "Aymara",
    "Sub-Saharan", "Mediterranean", "Atlantic", "Pacific", "Caribbean", "Sahara",
    "Sahel", "Northern", "Southern", "Eastern", "Western", "Central",
    "Africa", "Asia", "Europe", "Oceania", "America",
    "Major", "Minor", "East", "West", "North", "South",
    "Region", "Province", "District", "Department", "State", "Republic",
    "Bantu", "Zulu", "Xhosa", "Ibo", "Akan", "Fula", "Wolof", "Mandingo",
    "Tutsi", "Hutu", "Maasai", "Kikuyu", "Luo", "Tonga", "Luba", "Mongo",
    "Tswana", "Bemba", "Shona", "Ndebele", "Bakongo", "Bemba",
    "Beja", "Dinka", "Nubian", "Kgalagadi", "Basarwa", "Batswana", "Motswana",
    "Serbo-Croatian", "Serbo-Croation",
    # Demonyms / nationalities
    "Albanian", "American", "Argentine", "Australian", "Austrian", "Belgian",
    "Brazilian", "Britain", "British", "Briton", "Burmese", "Canadian", "Chilean",
    "Colombian", "Cuban", "Danish", "Dutch", "Egyptian", "Emirian", "Filipino",
    "Finnish", "Greek", "Haitian", "Hungarian", "Icelandic", "Indian", "Indonesian",
    "Iranian", "Iraqi", "Irish", "Israeli", "Jamaican", "Jordanian", "Kenyan",
    "Kuwaiti", "Lebanese", "Libyan", "Malaysian", "Maltese", "Mexican", "Moroccan",
    "Nepalese", "Nigerian", "Norwegian", "Omani", "Pakistani", "Palestinian",
    "Panamanian", "Paraguayan", "Peruvian", "Polish", "Qatari", "Romanian",
    "Rwandan", "Saudi", "Scottish", "Senegalese", "Singaporean", "Slovak",
    "Slovenian", "Somali", "Sudanese", "Swedish", "Swiss", "Syrian", "Taiwanese",
    "Tanzanian", "Tunisian", "Turkmen", "Ugandan", "Ukrainian", "Uruguayan",
    "Venezuelan", "Vietnamese", "Welsh", "Yemeni", "Zambian", "Zimbabwean",
    "Hispanic", "Caucasian", "Anglo",
}


def _looks_like_city(s: str) -> bool:
    """Heuristic: a recovered string looks like a real city / place name."""
    if not s or len(s) < 3 or len(s) > 30:
        return False
    if not s[0].isupper():
        return False
    if not all(c.isalpha() or c in " -'.()" for c in s):
        return False
    words = s.split()
    if len(words) > 4:
        return False
    # Reject strings whose last word is lowercase — these are usually
    # currency phrases like "Congo francs" rather than place names. Real
    # multi-word place names use Title Case (or hyphenated lowercase
    # interior segments, e.g., Mazar-i-Sharif, which have a single word).
    if len(words) > 1 and words[-1][0].islower():
        return False
    for w in words:
        if w in _CITY_STOP_TOKENS:
            return False
    return True


# CIA Factbook → seed.py country name aliases. Most country blocks anchor on
# their seed.py name verbatim, but a handful use older / longer / abbreviated
# variants in the original .dat file (some are truncated by the parser's
# 80-char string cap).
_COUNTRY_NAME_ALIASES = {
    "Burma": "Myanmar",
    "Korea, North": "North Korea",
    "Korea, South": "South Korea",
    "Cote d'Ivoire": "Ivory Coast",
    "Cote dIvoire": "Ivory Coast",
    "Bahamas, The": "Bahamas",
    "Gambia, The": "Gambia",
    "Congo, Republic of": "Republic of the Congo",
    "Congo, Democratic Republic of": "DR Congo",
    "the Congo Democratic Republic": "DR Congo",
    "Russian Federation": "Russia",
    "East Timor": "Timor-Leste",
    "Yugoslav": "Serbia and Montenegro",
    "Uzbekist": "Uzbekistan",
    "the United States": "United States",
    "the United Kingdom": "United Kingdom",
    "the United Arab Emirates": "United Arab Emirates",
    "the Ukraine": "Ukraine",
    "GreatBri": "United Kingdom",
    "UntdAE": "United Arab Emirates",
}


def extract_cities_per_country(
    string_pool: list[str],
    seed_country_names: list[str],
) -> dict[str, list[str]]:
    """Walk the recovered ``world.dat`` string pool and emit per-country city
    lists.

    The pool is roughly alphabetical (Afghanistan, Albania, Algeria, ...) and
    each country's block ends with a run of 5–9 city names just before the
    currency strings. We anchor blocks on the *first* occurrence of each known
    country name (or alias), then within each block pick the longest run of
    consecutive city-shaped strings.

    Empty list for any country whose block can't be located or doesn't yield
    a recognizable city run — callers should fall back to the capital.
    """
    name_set = set(seed_country_names)
    anchors: list[tuple[int, str]] = []
    seen_anchor: set[str] = set()
    for i, s in enumerate(string_pool):
        canon = _COUNTRY_NAME_ALIASES.get(s, s)
        if canon in name_set and canon not in seen_anchor:
            anchors.append((i, canon))
            seen_anchor.add(canon)

    out: dict[str, list[str]] = {n: [] for n in seed_country_names}
    for j, (pos, name) in enumerate(anchors):
        end = anchors[j + 1][0] if j + 1 < len(anchors) else len(string_pool)
        block = string_pool[pos:end]
        # Find consecutive runs of city-like strings; pick the longest run
        # with at least two entries (skipping the country name itself).
        runs: list[list[str]] = []
        i = 0
        while i < len(block):
            if _looks_like_city(block[i]) and block[i] != name:
                j2 = i
                while j2 < len(block) and _looks_like_city(block[j2]):
                    j2 += 1
                runs.append(block[i:j2])
                i = j2
            else:
                i += 1
        if not runs:
            continue
        runs.sort(key=len, reverse=True)
        best = runs[0]
        if len(best) < 2:
            continue
        seen_local: set[str] = set()
        cities = []
        for s in best:
            if s == name or s in seen_local:
                continue
            seen_local.add(s)
            cities.append(s)
        out[name] = cities
    return out


def extract_descriptions_per_country(
    parsed: "DatFile",
    seed_country_names: list[str],
    *,
    record_window: int = 4,
) -> dict[str, str]:
    """Compose a short encyclopedia paragraph for each country from the
    parsed ``world.dat`` file.

    Each country's data lives in roughly ``record_window`` consecutive 0x300
    records. The first record contains the country name as a short string;
    the next several contain the Location / Climate / Terrain /
    EnvironmentalIssues / etc. fields as long printable runs. We anchor on
    the first record where a country name appears, then collect the long
    descriptive runs from that record and the next few.
    """
    name_set = set(seed_country_names)

    # Build a sorted list of (record_idx, country_name) from per-record short
    # strings. Skip duplicates so each country anchors on its FIRST record.
    anchors: list[tuple[int, str]] = []
    seen: set[str] = set()
    for rec_idx in sorted(parsed.record_strings.keys()):
        for s in parsed.record_strings[rec_idx]:
            canon = _COUNTRY_NAME_ALIASES.get(s, s)
            if canon in name_set and canon not in seen:
                anchors.append((rec_idx, canon))
                seen.add(canon)

    # Group long_strings by record index for fast lookup.
    long_by_rec: dict[int, list[str]] = {}
    for ri, s in parsed.long_strings:
        long_by_rec.setdefault(ri, []).append(s)

    out: dict[str, str] = {n: "" for n in seed_country_names}
    for j, (rec_idx, name) in enumerate(anchors):
        next_rec = (
            anchors[j + 1][0] if j + 1 < len(anchors) else rec_idx + record_window + 1
        )
        end_rec = min(next_rec, rec_idx + record_window + 1)
        seen_local: set[str] = set()
        pieces: list[str] = []
        for ri in range(rec_idx, end_rec):
            for s in long_by_rec.get(ri, []):
                # Drop the country name itself and per-country tags.
                if s == name or _COUNTRY_NAME_ALIASES.get(s, s) == name:
                    continue
                # Skip filesystem-style path identifiers like "asia/afghanistan".
                if "/" in s and len(s) < 60:
                    continue
                if not any(c.isalpha() for c in s):
                    continue
                s_clean = s.strip()
                if not s_clean or len(s_clean) < 30:
                    continue
                # Reject strings dominated by non-letters (control glyphs, etc.).
                letters = sum(1 for c in s_clean if c.isalpha())
                if letters / len(s_clean) < 0.6:
                    continue
                if s_clean in seen_local:
                    continue
                seen_local.add(s_clean)
                pieces.append(s_clean)
        if pieces:
            out[name] = " ".join(pieces[:4])
    return out


# ---------------------------------------------------------------------------
# Data record decoder (binary -> typed values)
# ---------------------------------------------------------------------------

# Empirically determined fixed row size for world.dat: 2384 bytes per country.
# (193 countries × 2384 bytes = 460112 bytes = data section length.)
WORLD_ROW_SIZE = 2384


def _row_size_for(parsed: "DatFile") -> int | None:
    """Compute the per-row stride for a parsed .dat file by dividing the data
    section size by a hand-chosen number of rows. Returns None if the file
    doesn't follow the world.dat row layout."""
    blob = parsed.path.read_bytes()
    data_section = len(blob) - HEADER_SIZE - len(parsed.schema) * RECORD_SIZE
    # world.dat: 193 rows × 2384 bytes
    if data_section == 193 * WORLD_ROW_SIZE:
        return WORLD_ROW_SIZE
    return None


def country_buffer(parsed: "DatFile", country_index: int) -> bytes:
    """Return the raw byte buffer for one row in a parsed file. Returns an
    empty bytes object if the file doesn't follow a fixed-row layout or if
    the index is out of range.
    """
    row = _row_size_for(parsed)
    if row is None:
        return b""
    blob = parsed.path.read_bytes()
    data_start = HEADER_SIZE + len(parsed.schema) * RECORD_SIZE
    off = data_start + country_index * row
    return blob[off:off + row]


def decode_value(buf: bytes, field: DatField) -> object:
    """Pull a single field's value out of a per-country data buffer.

    Returns the decoded Python value (str / int / float) or None if the field
    can't be decoded for some reason (offset past end, unknown type code).
    """
    off = field.record_offset
    if off >= len(buf):
        return None
    if buf[off] != 0x01:
        # No tag — value not stored. Common for sparsely-populated fields.
        return None
    val_off = off + 1
    if field.type_code == 1:  # string
        slot = buf[val_off:val_off + field.slot_size]
        s = slot.split(b"\x00", 1)[0]
        # Original game stored Latin-1; emit unicode with the accents intact.
        return s.decode("latin-1", errors="replace")
    if field.type_code in (4, 5):  # int16
        return struct.unpack_from("<H", buf, val_off)[0]
    if field.type_code == 6:  # uint32
        return struct.unpack_from("<I", buf, val_off)[0]
    if field.type_code == 7:  # double
        return struct.unpack_from("<d", buf, val_off)[0]
    return None


def decode_country_record(parsed: "DatFile", country_index: int) -> dict[str, object]:
    """Decode every schema field for one country into a name -> value dict."""
    buf = country_buffer(parsed, country_index)
    out: dict[str, object] = {}
    for f in parsed.schema:
        out[f.name] = decode_value(buf, f)
    return out


def decode_all_countries(parsed: "DatFile") -> list[dict[str, object]]:
    """Decode every country's full row into a name → value dict. The list is
    in the same alphabetical order as the original game's UI ('Afghanistan'
    first, 'Zimbabwe' last). Returns an empty list if the file doesn't have
    a recognizable fixed-row layout."""
    row = _row_size_for(parsed)
    if row is None:
        return []
    blob = parsed.path.read_bytes()
    data_section_len = len(blob) - HEADER_SIZE - len(parsed.schema) * RECORD_SIZE
    n_countries = data_section_len // row
    return [decode_country_record(parsed, i) for i in range(n_countries)]


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
