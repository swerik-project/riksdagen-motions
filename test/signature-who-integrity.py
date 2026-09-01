#!/usr/bin/env python3
"""
Semantic integrity tests for motion signature person references.

Corpus guarantee:

* every ``@who`` value on a signature item inside a TEI ``signatureBlock`` is
  either ``unknown`` or a known SWERIK person id;
* a signature block does not repeat the same mapped signer;
* explicit location suffixes on mapped signature items are supported by the
  mapped person's entries in ``riksdagen-persons/data/location_specifier.csv``.

This matters because motion signatures are a curated person-mapping layer. A
false person reference is worse than an unknown signer, and duplicate mapped
signers usually indicate that one ambiguous signature should be reviewed.

Input data:

* motion TEI XML files in year directories under ``data/``;
* person ids from ``../riksdagen-persons/data/person.csv`` by default;
* location specifiers from
  ``../riksdagen-persons/data/location_specifier.csv`` by default.

Set ``PERSONS_ROOT`` to point at another riksdagen-persons checkout. Full
documentation lives in ``test/docs/signature-who-integrity.md`` and the test
style follows umbrella decision 0021 on SWERIK data integrity tests.

Location normalization is comparison-only: the test writes diagnostics, but it
does not write normalized values or any other changes back to the corpus XML.
"""

from __future__ import annotations

import os
import re
import unicodedata
import unittest
from collections.abc import Iterable
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import polars as pl
from lxml import etree
from pyriksdagen.utils import corpus_iterator, infer_metadata
from trainerlog import get_logger


LOGGER = get_logger(name="signature-who-integrity")

TEI_NS = "http://www.tei-c.org/ns/1.0"
XML_NS = "http://www.w3.org/XML/1998/namespace"
TEI_ITEM = f"{{{TEI_NS}}}item"
TEI_SIGNATURE_BLOCK = f"{{{TEI_NS}}}signatureBlock"
XML_ID = f"{{{XML_NS}}}id"

UNKNOWN_WHO = "unknown"
INVALID_WHO_REFERENCE = "invalid_signature_who_reference"
UNSUPPORTED_SIGNATURE_LOCATION = "unsupported_signature_location"
DUPLICATE_MAPPED_SIGNER = "duplicate_mapped_signer"
UNKNOWN_SIGNATURE_LOCATION = "unknown_signature_location"

RESULTS_PATH = Path("test/results/signature-who-integrity.tsv")
CHUNK_SIZE = 500
DEFAULT_WORKERS = min(8, os.cpu_count() or 1)

# Current-data baselines keep these release-blocking regression guards active
# while known signature issues are curated in separate follow-up issues.
ACCEPTED_SIGNATURE_WHO_FAILURES = 5
ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS = 739
ACCEPTED_DUPLICATE_MAPPED_SIGNERS = 353

LOCATION_SUFFIX_RE = re.compile(
    r"\b(?:i|från|fran)\s+([A-ZÅÄÖ][^\d,;:()|]*)\s*$",
    flags=re.IGNORECASE,
)
LOCATION_PREFIX_RE = re.compile(r"^(?:i|från|fran)\s+", flags=re.IGNORECASE)

DIAGNOSTIC_SCHEMA = {
    "file": pl.Utf8,
    "sitting": pl.Utf8,
    "year": pl.Int64,
    "secondary_year": pl.Int64,
    "chamber": pl.Utf8,
    "protocol": pl.Utf8,
    "error_type": pl.Utf8,
    "issue": pl.Utf8,
    "signature_block_id": pl.Utf8,
    "xml_id": pl.Utf8,
    "who": pl.Utf8,
    "signature_text": pl.Utf8,
    "location": pl.Utf8,
    "observed": pl.Utf8,
    "expected": pl.Utf8,
}
SORT_COLUMNS = [
    "file",
    "error_type",
    "signature_block_id",
    "xml_id",
    "who",
    "location",
    "observed",
]

SUMMARY_KEYS = [
    "files",
    "signature_blocks",
    "signature_items",
    "who_values",
    "location_suffixes",
    "mapped_location_suffixes",
]

_SIGNATURE_INTEGRITY_RESULT: tuple[pl.DataFrame, dict[str, int]] | None = None


def normalize_text(value: str | None) -> str | None:
    """Normalize extracted text for comparison without changing source data."""
    if value is None:
        return None

    folded = unicodedata.normalize("NFKD", value.casefold())
    without_accents = ''.join(
        char for char in folded if not unicodedata.combining(char)
    )
    normalized = re.sub(r"[^a-z0-9]+", " ", without_accents).strip()
    return normalized if normalized else None


def motion_paths() -> list[Path]:
    """Return all year-directory motion XML paths in stable order."""
    paths = [Path(path) for path in corpus_iterator("motions", corpus_root="data")]
    return sorted(path for path in paths if path.parent.name.isdigit())


def load_person_ids(persons_root: Path) -> set[str]:
    """Load known SWERIK person ids from the person catalog."""
    person_path = persons_root / "data" / "person.csv"
    people = pl.read_csv(
        person_path,
        schema_overrides={"person_id": pl.Utf8},
        null_values=[""],
        infer_schema_length=10000,
    )
    return set(
        people.select(pl.col("person_id").cast(pl.Utf8).drop_nulls())
        .get_column("person_id")
        .to_list()
    )


def load_locations_by_person(persons_root: Path) -> dict[str, set[str]]:
    """Load normalized location specifiers keyed by SWERIK person id."""
    location_path = persons_root / "data" / "location_specifier.csv"
    locations = pl.read_csv(
        location_path,
        schema_overrides={"person_id": pl.Utf8, "location": pl.Utf8},
        null_values=[""],
        infer_schema_length=10000,
    )
    locations = (
        locations.filter(
            pl.col("person_id").is_not_null() & pl.col("location").is_not_null()
        )
        .with_columns(
            pl.col("location")
            .map_elements(normalize_text, return_dtype=pl.Utf8)
            .alias("normalized_location")
        )
        .filter(pl.col("normalized_location").is_not_null())
        .select("person_id", "normalized_location")
    )

    locations_by_person: dict[str, set[str]] = {}
    for person_id, location in locations.iter_rows():
        locations_by_person.setdefault(person_id, set()).add(location)
    return locations_by_person


def iter_signature_blocks(path: Path) -> Iterable[etree._Element]:
    """Yield TEI signature blocks from a motion without holding the full tree."""
    context = etree.iterparse(
        str(path),
        events=("end",),
        tag=TEI_SIGNATURE_BLOCK,
        recover=True,
    )
    for _, block in context:
        yield block
        parent = block.getparent()
        block.clear()
        if parent is not None:
            while block.getprevious() is not None:
                del parent[0]


def collapsed_element_text(element: etree._Element) -> str | None:
    """Return normalized whitespace text extracted from a parsed XML element."""
    text = " ".join(" ".join(element.itertext()).split())
    return text if text else None


def signature_location_suffix(text: str | None) -> tuple[str, str] | None:
    """Extract a location suffix from signature text, if one is present."""
    if text is None:
        return None

    collapsed = " ".join(text.split())
    match = LOCATION_SUFFIX_RE.search(collapsed)
    if match is None:
        return None

    raw_location = match.group(0)
    normalized_location = normalize_text(LOCATION_PREFIX_RE.sub("", raw_location))
    if normalized_location is None:
        return None

    token_count = len(normalized_location.split())
    if not 1 <= token_count <= 4:
        return None

    return raw_location, normalized_location


def expected_locations(
    locations_by_person: dict[str, set[str]], person_id: str
) -> str | None:
    """Return a readable expected-location value for diagnostics."""
    locations = sorted(locations_by_person.get(person_id, set()))
    return " | ".join(locations) if locations else None


def empty_summary() -> dict[str, int]:
    """Return a zero-filled scan summary."""
    return dict.fromkeys(SUMMARY_KEYS, 0)


def combine_summary(target: dict[str, int], source: dict[str, int]) -> None:
    """Add one scan summary into another."""
    for key in SUMMARY_KEYS:
        target[key] += source[key]


def metadata_context(path: Path) -> dict[str, str | int | None]:
    """Return stable review metadata inferred from a motion file path."""
    metadata = infer_metadata(str(path))
    return {
        "file": str(path),
        "sitting": metadata.get("sitting"),
        "year": metadata.get("year"),
        "secondary_year": metadata.get("secondary_year"),
        "chamber": metadata.get("chamber"),
        "protocol": metadata.get("protocol"),
    }


def diagnostic_row(**values: str | int | None) -> dict[str, str | int | None]:
    """Normalize diagnostic rows to the stable nullable schema."""
    return {column: values.get(column) for column in DIAGNOSTIC_SCHEMA}


def signature_who_values(item: etree._Element) -> list[str]:
    """Return parsed ``@who`` tokens from a signature item."""
    who = item.get("who")
    return who.split() if who is not None else []


def scan_motion(
    path: Path,
    person_ids: set[str],
    locations_by_person: dict[str, set[str]],
) -> tuple[dict[str, int], list[dict[str, str | int | None]]]:
    """Collect signature diagnostics for one motion file."""
    summary = empty_summary()
    summary["files"] = 1
    rows: list[dict[str, str | int | None]] = []
    context = metadata_context(path)

    for block in iter_signature_blocks(path):
        summary["signature_blocks"] += 1
        block_id = block.get(XML_ID)
        seen_mapped_signers: dict[str, str | None] = {}

        for item in block.iter(TEI_ITEM):
            if item.get("type") != "signature":
                continue

            summary["signature_items"] += 1
            xml_id = item.get(XML_ID)
            signature_text = collapsed_element_text(item)
            who_values = signature_who_values(item)
            summary["who_values"] += len(who_values)

            if not who_values:
                rows.append(
                    diagnostic_row(
                        **context,
                        error_type=INVALID_WHO_REFERENCE,
                        issue="signature item has no @who value",
                        signature_block_id=block_id,
                        xml_id=xml_id,
                        signature_text=signature_text,
                        observed=None,
                        expected=f"{UNKNOWN_WHO} or known person_id",
                    )
                )

            mapped_who_values = [
                who for who in who_values if who != UNKNOWN_WHO and who in person_ids
            ]

            for who in who_values:
                if who == UNKNOWN_WHO or who in person_ids:
                    continue

                rows.append(
                    diagnostic_row(
                        **context,
                        error_type=INVALID_WHO_REFERENCE,
                        issue="signature @who value is not in person.csv",
                        signature_block_id=block_id,
                        xml_id=xml_id,
                        who=who,
                        signature_text=signature_text,
                        observed=who,
                        expected=f"{UNKNOWN_WHO} or known person_id",
                    )
                )

            for who in mapped_who_values:
                if who in seen_mapped_signers:
                    rows.append(
                        diagnostic_row(
                            **context,
                            error_type=DUPLICATE_MAPPED_SIGNER,
                            issue="signature block repeats the same mapped signer",
                            signature_block_id=block_id,
                            xml_id=xml_id,
                            who=who,
                            signature_text=signature_text,
                            observed=who,
                            expected=seen_mapped_signers[who],
                        )
                    )
                else:
                    seen_mapped_signers[who] = xml_id

            suffix = signature_location_suffix(signature_text)
            if suffix is None:
                continue

            raw_location, normalized_location = suffix
            summary["location_suffixes"] += 1

            if not mapped_who_values and UNKNOWN_WHO in who_values:
                rows.append(
                    diagnostic_row(
                        **context,
                        error_type=UNKNOWN_SIGNATURE_LOCATION,
                        issue="signature has a location suffix but no mapped signer",
                        signature_block_id=block_id,
                        xml_id=xml_id,
                        signature_text=signature_text,
                        location=raw_location,
                        observed=normalized_location,
                        expected="mapped signer before location validation",
                    )
                )
                continue

            for who in mapped_who_values:
                summary["mapped_location_suffixes"] += 1
                if normalized_location in locations_by_person.get(who, set()):
                    continue

                rows.append(
                    diagnostic_row(
                        **context,
                        error_type=UNSUPPORTED_SIGNATURE_LOCATION,
                        issue="mapped signature location is not listed for person",
                        signature_block_id=block_id,
                        xml_id=xml_id,
                        who=who,
                        signature_text=signature_text,
                        location=raw_location,
                        observed=normalized_location,
                        expected=expected_locations(locations_by_person, who),
                    )
                )

    return summary, rows


def chunked(paths: list[Path], size: int) -> Iterable[list[Path]]:
    """Yield fixed-size chunks of paths for bounded threaded scanning."""
    for start in range(0, len(paths), size):
        yield paths[start : start + size]


def scan_motion_chunk(
    paths: list[Path],
    person_ids: set[str],
    locations_by_person: dict[str, set[str]],
) -> tuple[dict[str, int], list[dict[str, str | int | None]]]:
    """Collect diagnostics for a bounded list of motion files."""
    summary = empty_summary()
    rows: list[dict[str, str | int | None]] = []
    for path in paths:
        path_summary, path_rows = scan_motion(path, person_ids, locations_by_person)
        combine_summary(summary, path_summary)
        rows.extend(path_rows)
    return summary, rows


def worker_count() -> int:
    """Return the configured full-corpus scan worker count."""
    configured = os.environ.get("SIGNATURE_INTEGRITY_WORKERS")
    if configured is None:
        return DEFAULT_WORKERS

    try:
        workers = int(configured)
    except ValueError:
        LOGGER.warning(
            "Ignoring invalid SIGNATURE_INTEGRITY_WORKERS=%s", configured
        )
        return DEFAULT_WORKERS

    if workers < 1:
        LOGGER.warning(
            "Ignoring invalid SIGNATURE_INTEGRITY_WORKERS=%s", configured
        )
        return DEFAULT_WORKERS

    return workers


def collect_signature_integrity_rows() -> tuple[
    list[dict[str, str | int | None]], dict[str, int]
]:
    """Scan the motion corpus and return diagnostics plus corpus summary."""
    persons_root = Path(os.environ.get("PERSONS_ROOT", "../riksdagen-persons"))
    person_ids = load_person_ids(persons_root)
    locations_by_person = load_locations_by_person(persons_root)
    paths = motion_paths()
    workers = worker_count()

    LOGGER.info("Loaded %s person ids from %s", len(person_ids), persons_root)
    LOGGER.info(
        "Loaded location specifiers for %s people from %s",
        len(locations_by_person),
        persons_root,
    )
    LOGGER.info(
        "Checking %s motion XML files with %s worker(s)", len(paths), workers
    )

    summary = empty_summary()
    rows: list[dict[str, str | int | None]] = []
    path_chunks = list(chunked(paths, CHUNK_SIZE))

    if workers == 1:
        partial_results = (
            scan_motion_chunk(chunk, person_ids, locations_by_person)
            for chunk in path_chunks
        )
        for partial_summary, partial_rows in partial_results:
            combine_summary(summary, partial_summary)
            rows.extend(partial_rows)
    else:
        with ThreadPoolExecutor(max_workers=workers) as executor:
            partial_results = executor.map(
                lambda chunk: scan_motion_chunk(
                    chunk, person_ids, locations_by_person
                ),
                path_chunks,
            )
            for partial_summary, partial_rows in partial_results:
                combine_summary(summary, partial_summary)
                rows.extend(partial_rows)

    return rows, summary


def diagnostics_by_error_type(df: pl.DataFrame, error_type: str) -> int:
    """Count diagnostics of one semantic error type."""
    return df.filter(pl.col("error_type") == error_type).height


def signature_integrity_result() -> tuple[pl.DataFrame, dict[str, int]]:
    """Return cached full-corpus diagnostics and write the review TSV."""
    global _SIGNATURE_INTEGRITY_RESULT

    if _SIGNATURE_INTEGRITY_RESULT is None:
        rows, summary = collect_signature_integrity_rows()
        df = pl.DataFrame(rows, schema=DIAGNOSTIC_SCHEMA, strict=False)
        df = df.sort(SORT_COLUMNS)

        RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
        df.write_csv(RESULTS_PATH, separator="\t")

        LOGGER.info(
            "Scanned %(files)s files, %(signature_blocks)s signature blocks, "
            "%(signature_items)s signature items, and %(who_values)s @who values",
            summary,
        )
        LOGGER.info("Wrote %s diagnostic row(s) to %s", df.height, RESULTS_PATH)
        if df.height:
            counts = (
                df.group_by("error_type")
                .len(name="count")
                .sort("error_type")
                .iter_rows(named=True)
            )
            for row in counts:
                LOGGER.info("%s: %s", row["error_type"], row["count"])

        _SIGNATURE_INTEGRITY_RESULT = (df, summary)

    return _SIGNATURE_INTEGRITY_RESULT


class SignatureWhoIntegrityTests(unittest.TestCase):
    """Release-blocking checks for motion signature person references."""

    def test_signature_scan_finds_expected_corpus_content(self):
        """The full-corpus scan should see the signature annotation layer."""
        _, summary = signature_integrity_result()

        self.assertGreater(summary["files"], 0, "No motion files were scanned")
        self.assertGreater(
            summary["signature_blocks"], 0, "No TEI signatureBlock elements found"
        )
        self.assertGreater(
            summary["signature_items"], 0, "No signature items found in corpus"
        )
        self.assertGreater(
            summary["who_values"], 0, "No signature @who values found in corpus"
        )

    def test_signature_who_references_do_not_exceed_current_baseline(self):
        """Signature ``@who`` reference failures should not regress."""
        df, _ = signature_integrity_result()
        failures = diagnostics_by_error_type(df, INVALID_WHO_REFERENCE)

        self.assertLessEqual(
            failures,
            ACCEPTED_SIGNATURE_WHO_FAILURES,
            (
                f"{failures} invalid signature @who reference(s), exceeding "
                f"current-data baseline {ACCEPTED_SIGNATURE_WHO_FAILURES}; "
                f"see {RESULTS_PATH}"
            ),
        )

    def test_signature_locations_do_not_exceed_current_baseline(self):
        """Mapped signature location suffixes should not regress."""
        df, summary = signature_integrity_result()
        failures = diagnostics_by_error_type(df, UNSUPPORTED_SIGNATURE_LOCATION)

        self.assertGreater(
            summary["location_suffixes"],
            0,
            "No signature location suffixes were found; check location extraction",
        )
        self.assertLessEqual(
            failures,
            ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS,
            (
                f"{failures} unsupported mapped signature location(s), exceeding "
                f"current-data baseline {ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS}; "
                f"see {RESULTS_PATH}"
            ),
        )

    def test_signature_blocks_do_not_exceed_duplicate_baseline(self):
        """Duplicate mapped signers should not regress."""
        df, _ = signature_integrity_result()
        failures = diagnostics_by_error_type(df, DUPLICATE_MAPPED_SIGNER)

        self.assertLessEqual(
            failures,
            ACCEPTED_DUPLICATE_MAPPED_SIGNERS,
            (
                f"{failures} duplicate mapped signer(s), exceeding current-data "
                f"baseline {ACCEPTED_DUPLICATE_MAPPED_SIGNERS}; see {RESULTS_PATH}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
