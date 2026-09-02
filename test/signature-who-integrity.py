#!/usr/bin/env python3
"""
Integrity tests for motion signature person references.

Corpus guarantee:

* every signature-item ``@who`` value is either ``unknown`` or one known
  ``riksdagen-persons`` person id;
* a ``signatureBlock`` does not repeat the same mapped signer;
* mapped signature locations, such as ``i Mora`` or ``från Nerike``, are listed
  for the mapped person in ``riksdagen-persons/data/location_specifier.csv``.

The test scans all motion XML files under ``data/`` and reads reference data
from ``../riksdagen-persons`` by default. Set ``PERSONS_ROOT`` to use another
checkout. Large current-data failure sets are written to
``test/results/signature-who-integrity.tsv`` for follow-up curation.

"""

from __future__ import annotations

import os
import re
import unittest
from pathlib import Path

import polars as pl
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import TEI_NS, XML_NS, corpus_iterator
from trainerlog import get_logger


LOGGER = get_logger(name="signature-who-integrity")

UNKNOWN_WHO = "unknown"
INVALID_WHO_REFERENCE = "invalid_signature_who_reference"
DUPLICATE_MAPPED_SIGNER = "duplicate_mapped_signer"
UNSUPPORTED_SIGNATURE_LOCATION = "unsupported_signature_location"

RESULTS_PATH = Path("test/results/signature-who-integrity.tsv")

# Current-data baselines. These count diagnostic rows, not files or blocks.
ACCEPTED_SIGNATURE_WHO_FAILURES = 5
ACCEPTED_DUPLICATE_MAPPED_SIGNERS = 353
ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS = 739

XML_ID = f"{XML_NS}id"
LOCATION_SUFFIX_RE = re.compile(
    r"\b(?:i|från|fran)\s+([A-ZÅÄÖa-zåäö][^,;:()|0-9]*?)\.?\s*$",
    flags=re.IGNORECASE,
)

DIAGNOSTIC_SCHEMA = {
    "file": pl.Utf8,
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
SORT_COLUMNS = ["file", "error_type", "signature_block_id", "xml_id", "who"]

_SIGNATURE_SCAN: tuple[pl.DataFrame, int] | None = None


def location_key(value: str) -> str:
    """Return a comparison key that preserves Swedish letters."""
    return " ".join(value.strip().strip(".").split()).casefold()


def load_person_ids(persons_root: Path) -> set[str]:
    """Load known SWERIK person ids from the person catalog."""
    people = pl.read_csv(
        persons_root / "data" / "person.csv",
        schema_overrides={"person_id": pl.Utf8},
        null_values=[""],
        infer_schema_length=10000,
    )
    return set(
        people.select(pl.col("person_id").drop_nulls())
        .get_column("person_id")
        .to_list()
    )


def load_locations_by_person(persons_root: Path) -> dict[str, set[str]]:
    locations = pl.read_csv(
        persons_root / "data" / "location_specifier.csv",
        schema_overrides={"person_id": pl.Utf8, "location": pl.Utf8},
        null_values=[""],
        infer_schema_length=10000,
    )
    rows = (
        locations.filter(
            pl.col("person_id").is_not_null() & pl.col("location").is_not_null()
        )
        .select("person_id", "location")
        .iter_rows()
    )

    by_person: dict[str, set[str]] = {}
    for person_id, location in rows:
        by_person.setdefault(person_id, set()).add(location_key(location))
    return by_person


def signature_text(item) -> str | None:
    text = " ".join(" ".join(item.itertext()).split())
    return text or None


def signature_location(text: str | None) -> str | None:
    if text is None:
        return None

    match = LOCATION_SUFFIX_RE.search(text)
    if match is None:
        return None

    location = " ".join(match.group(1).strip().strip(".").split())
    if not location or len(location.split()) > 4:
        return None
    return location


def add_error(
    rows: list[dict[str, str | None]],
    *,
    path: str,
    block_id: str | None,
    item,
    error_type: str,
    issue: str,
    observed: str | None,
    expected: str | None,
    location: str | None = None,
) -> None:
    rows.append(
        {
            "file": path,
            "error_type": error_type,
            "issue": issue,
            "signature_block_id": block_id,
            "xml_id": item.get(XML_ID),
            "who": item.get("who"),
            "signature_text": signature_text(item),
            "location": location,
            "observed": observed,
            "expected": expected,
        }
    )


def collect_signature_errors() -> tuple[pl.DataFrame, int]:
    persons_root = Path(os.environ.get("PERSONS_ROOT", "../riksdagen-persons"))
    person_ids = load_person_ids(persons_root)
    locations_by_person = load_locations_by_person(persons_root)
    paths = sorted(corpus_iterator("motions", corpus_root="data"))

    LOGGER.info("Checking %s motion XML files", len(paths))

    signature_items = 0
    rows: list[dict[str, str | None]] = []

    for path in paths:
        root, _ = parse_tei(path)
        for block in root.findall(f".//{TEI_NS}signatureBlock"):
            block_id = block.get(XML_ID)
            seen_signers: dict[str, str | None] = {}

            for item in block.findall(f".//{TEI_NS}item"):
                if item.get("type") != "signature":
                    continue

                signature_items += 1
                path_text = str(path)
                who = item.get("who")

                if who is None or who == "":
                    add_error(
                        rows,
                        path=path_text,
                        block_id=block_id,
                        item=item,
                        error_type=INVALID_WHO_REFERENCE,
                        issue="signature item has no @who value",
                        observed=who,
                        expected=f"{UNKNOWN_WHO} or known person_id",
                    )
                    continue

                if who == UNKNOWN_WHO:
                    continue

                if who not in person_ids:
                    add_error(
                        rows,
                        path=path_text,
                        block_id=block_id,
                        item=item,
                        error_type=INVALID_WHO_REFERENCE,
                        issue="signature @who value is not in person.csv",
                        observed=who,
                        expected=f"{UNKNOWN_WHO} or known person_id",
                    )
                    continue

                if who in seen_signers:
                    add_error(
                        rows,
                        path=path_text,
                        block_id=block_id,
                        item=item,
                        error_type=DUPLICATE_MAPPED_SIGNER,
                        issue="signature block repeats the same mapped signer",
                        observed=who,
                        expected=seen_signers[who],
                    )
                else:
                    seen_signers[who] = item.get(XML_ID)

                location = signature_location(signature_text(item))
                if (
                    location is not None
                    and location_key(location) not in locations_by_person.get(who, set())
                ):
                    add_error(
                        rows,
                        path=path_text,
                        block_id=block_id,
                        item=item,
                        error_type=UNSUPPORTED_SIGNATURE_LOCATION,
                        issue="mapped signature location is not listed for person",
                        location=location,
                        observed=location,
                        expected=" | ".join(sorted(locations_by_person.get(who, set())))
                        or None,
                    )

    df = pl.DataFrame(rows, schema=DIAGNOSTIC_SCHEMA, strict=False).sort(SORT_COLUMNS)
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(RESULTS_PATH, separator="\t")
    LOGGER.info(
        "Checked %s signature items; wrote %s diagnostics", signature_items, df.height
    )
    return df, signature_items


def signature_scan() -> tuple[pl.DataFrame, int]:
    global _SIGNATURE_SCAN
    if _SIGNATURE_SCAN is None:
        _SIGNATURE_SCAN = collect_signature_errors()
    return _SIGNATURE_SCAN


def error_count(error_type: str) -> int:
    df, _ = signature_scan()
    return df.filter(pl.col("error_type") == error_type).height


class SignatureWhoIntegrityTests(unittest.TestCase):
    """Release-blocking checks for motion signature person references."""

    def test_signature_items_are_checked(self):
        """The corpus scan should find the signature annotation layer."""
        _, signature_items = signature_scan()
        self.assertGreater(signature_items, 0, "No signature items were checked")

    def test_signature_who_references_do_not_exceed_current_baseline(self):
        """Invalid signature ``@who`` rows should not exceed the current baseline."""
        failures = error_count(INVALID_WHO_REFERENCE)
        self.assertLessEqual(
            failures,
            ACCEPTED_SIGNATURE_WHO_FAILURES,
            (
                f"{failures} invalid signature @who row(s), exceeding current-data "
                f"baseline {ACCEPTED_SIGNATURE_WHO_FAILURES}; see {RESULTS_PATH}"
            ),
        )

    def test_duplicate_mapped_signers_do_not_exceed_current_baseline(self):
        """Duplicate mapped signer rows should not exceed the current baseline."""
        failures = error_count(DUPLICATE_MAPPED_SIGNER)
        self.assertLessEqual(
            failures,
            ACCEPTED_DUPLICATE_MAPPED_SIGNERS,
            (
                f"{failures} duplicate mapped signer row(s), exceeding current-data "
                f"baseline {ACCEPTED_DUPLICATE_MAPPED_SIGNERS}; see {RESULTS_PATH}"
            ),
        )

    def test_signature_locations_do_not_exceed_current_baseline(self):
        """Unsupported mapped location rows should not exceed the current baseline."""
        failures = error_count(UNSUPPORTED_SIGNATURE_LOCATION)
        self.assertLessEqual(
            failures,
            ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS,
            (
                f"{failures} unsupported mapped location row(s), exceeding "
                f"current-data baseline {ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS}; "
                f"see {RESULTS_PATH}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
