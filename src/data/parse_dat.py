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
