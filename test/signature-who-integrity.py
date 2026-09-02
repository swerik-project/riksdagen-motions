#!/usr/bin/env python3
"""Checks motion signature person references against ``riksdagen-persons``.

Guarantees:

* every signature-item ``@who`` is either ``unknown`` or one known person id;
* a ``signatureBlock`` does not repeat the same mapped signer;
* mapped signature locations, such as ``i Mora`` or ``från Nerike``, exist in
  the mapped person's ``location_specifier.csv`` rows.

The test scans all motion XML under ``data/`` with ``pyriksdagen`` and parsed
TEI. Reference data is read from ``PERSONS_ROOT`` or ``../riksdagen-persons``.
Large row-level diagnostics are written to
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

# Current-data baselines. These count diagnostic rows, not files or blocks.
ERROR_BASELINES = {
    INVALID_WHO_REFERENCE: 5,
    DUPLICATE_MAPPED_SIGNER: 353,
    UNSUPPORTED_SIGNATURE_LOCATION: 739,
}

RESULTS_PATH = Path("test/results/signature-who-integrity.tsv")
XML_ID = f"{XML_NS}id"
TEI_ITEM = f"{TEI_NS}item"
TEI_SIGNATURE_BLOCK = f"{TEI_NS}signatureBlock"
# Applied only to text extracted from parsed XML, not to tags or attributes.
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

def location_key(value: str) -> str:
    """Fold case and whitespace for comparison while preserving Swedish letters."""
    return " ".join(value.strip().strip(".").split()).casefold()


def load_person_reference(persons_root: Path) -> tuple[set[str], dict[str, set[str]]]:
    """Load person ids and location specifiers from ``riksdagen-persons``."""
    person_ids = set(
        pl.read_csv(
            persons_root / "data" / "person.csv",
            schema_overrides={"person_id": pl.Utf8},
            null_values=[""],
            infer_schema_length=10000,
        )
        .select(pl.col("person_id").drop_nulls())
        .get_column("person_id")
        .to_list()
    )

    locations = pl.read_csv(
        persons_root / "data" / "location_specifier.csv",
        schema_overrides={"person_id": pl.Utf8, "location": pl.Utf8},
        null_values=[""],
        infer_schema_length=10000,
    )
    locations_by_person: dict[str, set[str]] = {}
    for person_id, location in (
        locations.filter(
            pl.col("person_id").is_not_null() & pl.col("location").is_not_null()
        )
        .select("person_id", "location")
        .iter_rows()
    ):
        locations_by_person.setdefault(person_id, set()).add(location_key(location))

    return person_ids, locations_by_person


def element_text(element) -> str | None:
    text = " ".join(" ".join(element.itertext()).split())
    return text or None


def signature_location(text: str | None) -> str | None:
    match = LOCATION_SUFFIX_RE.search(text or "")
    if match is None:
        return None

    location = " ".join(match.group(1).strip().strip(".").split())
    if not location or len(location.split()) > 4:
        return None
    return location


def error_row(
    *,
    path: str,
    block_id: str | None,
    item_id: str | None,
    who: str | None,
    text: str | None,
    error_type: str,
    issue: str,
    observed: str | None,
    expected: str | None,
    location: str | None = None,
) -> dict[str, str | None]:
    return {
        "file": path,
        "error_type": error_type,
        "issue": issue,
        "signature_block_id": block_id,
        "xml_id": item_id,
        "who": who,
        "signature_text": text,
        "location": location,
        "observed": observed,
        "expected": expected,
    }


def collect_signature_errors() -> tuple[pl.DataFrame, int]:
    """Collect one diagnostic row for each bounded signature integrity error."""
    persons_root = Path(os.environ.get("PERSONS_ROOT", "../riksdagen-persons"))
    person_ids, locations_by_person = load_person_reference(persons_root)
    rows: list[dict[str, str | None]] = []
    signature_items = 0

    paths = sorted(corpus_iterator("motions", corpus_root="data"))
    LOGGER.info("Checking %s motion XML files", len(paths))

    for path in paths:
        root = parse_tei(path, get_ns=False)
        for block in root.iter(TEI_SIGNATURE_BLOCK):
            block_id = block.get(XML_ID)
            seen_signers: dict[str, str | None] = {}

            for item in block.iter(TEI_ITEM):
                if item.get("type") != "signature":
                    continue

                signature_items += 1
                path_text = str(path)
                item_id = item.get(XML_ID)
                who = item.get("who")
                text = element_text(item)

                if not who:
                    rows.append(
                        error_row(
                            path=path_text,
                            block_id=block_id,
                            item_id=item_id,
                            who=who,
                            text=text,
                            error_type=INVALID_WHO_REFERENCE,
                            issue="signature item has no @who value",
                            observed=who,
                            expected=f"{UNKNOWN_WHO} or known person_id",
                        )
                    )
                    continue

                if who == UNKNOWN_WHO:
                    continue

                if who not in person_ids:
                    rows.append(
                        error_row(
                            path=path_text,
                            block_id=block_id,
                            item_id=item_id,
                            who=who,
                            text=text,
                            error_type=INVALID_WHO_REFERENCE,
                            issue="signature @who value is not in person.csv",
                            observed=who,
                            expected=f"{UNKNOWN_WHO} or known person_id",
                        )
                    )
                    continue

                if who in seen_signers:
                    rows.append(
                        error_row(
                            path=path_text,
                            block_id=block_id,
                            item_id=item_id,
                            who=who,
                            text=text,
                            error_type=DUPLICATE_MAPPED_SIGNER,
                            issue="signature block repeats the same mapped signer",
                            observed=who,
                            expected=seen_signers[who],
                        )
                    )
                else:
                    seen_signers[who] = item_id

                location = signature_location(text)
                registered_locations = locations_by_person.get(who, set())
                if location and location_key(location) not in registered_locations:
                    rows.append(
                        error_row(
                            path=path_text,
                            block_id=block_id,
                            item_id=item_id,
                            who=who,
                            text=text,
                            error_type=UNSUPPORTED_SIGNATURE_LOCATION,
                            issue="mapped signature location is not listed for person",
                            location=location,
                            observed=location,
                            expected=" | ".join(sorted(registered_locations)) or None,
                        )
                    )

    df = pl.DataFrame(rows, schema=DIAGNOSTIC_SCHEMA, strict=False).sort(
        ["file", "error_type", "signature_block_id", "xml_id", "who"]
    )
    RESULTS_PATH.parent.mkdir(parents=True, exist_ok=True)
    df.write_csv(RESULTS_PATH, separator="\t")
    LOGGER.info(
        "Checked %s signature items; wrote %s diagnostics", signature_items, df.height
    )
    return df, signature_items


class SignatureWhoIntegrityTests(unittest.TestCase):
    """Release-blocking checks for motion signature person references."""

    def test_signature_errors_do_not_exceed_current_baselines(self):
        """Signature integrity error rows should not exceed current baselines."""
        df, signature_items = collect_signature_errors()
        self.assertGreater(signature_items, 0, "No signature items were checked")

        counts = {
            row["error_type"]: row["count"]
            for row in df.group_by("error_type").len(name="count").iter_rows(named=True)
        }
        for error_type, accepted_errors in ERROR_BASELINES.items():
            with self.subTest(error_type=error_type):
                failures = counts.get(error_type, 0)
                self.assertLessEqual(
                    failures,
                    accepted_errors,
                    (
                        f"{failures} {error_type} row(s), exceeding current-data "
                        f"baseline {accepted_errors}; see {RESULTS_PATH}"
                    ),
                )


if __name__ == "__main__":
    unittest.main()
