#!/usr/bin/env python3
"""Release-blocking checks for motion signature person-reference guarantees."""

import os
import re
import unittest
from pathlib import Path

import polars as pl
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import TEI_NS, XML_NS, corpus_iterator
from trainerlog import get_logger
from tqdm import tqdm


LOGGER = get_logger(name="signature-who-integrity-v3")

PERSONS_ROOT = Path(os.environ.get("PERSONS_ROOT", "../riksdagen-persons"))
XML_ID = f"{XML_NS}id"
TEI_ITEM = f"{TEI_NS}item"
TEI_SIGNATURE_BLOCK = f"{TEI_NS}signatureBlock"

MAX_INVALID_SIGNATURE_WHO_REFERENCES = 5
MAX_DUPLICATE_MAPPED_SIGNER_BLOCKS = 348
MAX_UNSUPPORTED_SIGNATURE_LOCATIONS = 745

# Applied only to text extracted from parsed XML, not to XML tags or attributes.
LOCATION_SUFFIX_RE = re.compile(
    r"\b(?:i|från|fran)\s+([A-ZÅÄÖa-zåäö][^,;:()|0-9]*?)\.?\s*$",
    flags=re.IGNORECASE,
)


def location_key(location):
    """Normalize location spelling for comparison while preserving Swedish letters."""
    return " ".join(location.strip().strip(".").split()).lower()


def signature_location(text):
    """Extract a trailing ``i``/``från`` location from signature text."""
    match = LOCATION_SUFFIX_RE.search(text)
    if match is None:
        return None

    location = " ".join(match.group(1).strip().strip(".").split())
    if not location or len(location.split()) > 4:
        return None

    return location


class SignatureWhoIntegrityTests(unittest.TestCase):
    """Checks for motion signature mappings against ``riksdagen-persons``."""

    def test_signature_who_values_are_unknown_or_known_person_ids(self):
        """Guarantee: every signature item has a valid ``@who`` value.

        Why this matters: mapped motion signatures should point to one known
        person in ``riksdagen-persons``, while unmapped signatures should be
        explicitly marked as ``unknown``.

        Data: reads ``../riksdagen-persons/data/person.csv`` with Polars and
        scans all motion XML under ``data/`` with ``pyriksdagen``.
        """
        persons = pl.read_csv(
            PERSONS_ROOT / "data" / "person.csv",
            schema_overrides={"person_id": pl.Utf8},
            infer_schema_length=10000,
        )
        person_ids = set(persons.get_column("person_id").to_list())

        failures = 0
        signature_items = 0
        paths = sorted(corpus_iterator("motions", corpus_root="data"))
        LOGGER.info("Checking valid @who values in %s motion XML files", len(paths))

        for path in tqdm(paths, desc="signature @who"):
            root = parse_tei(path, get_ns=False)
            for block in root.iter(TEI_SIGNATURE_BLOCK):
                block_id = block.get(XML_ID)
                for item in block.iter(TEI_ITEM):
                    if item.get("type") != "signature":
                        continue

                    signature_items += 1
                    who = item.get("who")
                    if who is None or who == "":
                        failures += 1
                        LOGGER.error(
                            "file=%s | signature_block_id=%s | xml_id=%s | "
                            "who=%s | issue=signature item has no @who value",
                            path,
                            block_id,
                            item.get(XML_ID),
                            who,
                        )
                    elif who != "unknown" and who not in person_ids:
                        failures += 1
                        LOGGER.error(
                            "file=%s | signature_block_id=%s | xml_id=%s | "
                            "who=%s | issue=@who value is not in person.csv",
                            path,
                            block_id,
                            item.get(XML_ID),
                            who,
                        )

        LOGGER.info("Checked %s signature items", signature_items)
        self.assertGreater(signature_items, 0, "No signature items were checked")
        self.assertLessEqual(
            failures,
            MAX_INVALID_SIGNATURE_WHO_REFERENCES,
            (
                f"{failures} invalid signature @who reference(s), exceeding "
                f"baseline {MAX_INVALID_SIGNATURE_WHO_REFERENCES}; diagnostics "
                "logged with trainerlog"
            ),
        )

    def test_signature_blocks_do_not_repeat_known_mapped_signers(self):
        """Guarantee: a signature block does not repeat the same known signer.

        Why this matters: repeated mapped signers in one ``signatureBlock`` are
        usually stale or duplicated signature annotations.

        Data: reads ``../riksdagen-persons/data/person.csv`` with Polars so
        invalid ``@who`` values are left to the separate reference test, then
        scans all motion XML under ``data/`` with ``pyriksdagen``.
        """
        persons = pl.read_csv(
            PERSONS_ROOT / "data" / "person.csv",
            schema_overrides={"person_id": pl.Utf8},
            infer_schema_length=10000,
        )
        person_ids = set(persons.get_column("person_id").to_list())

        failures = 0
        signature_blocks = 0
        paths = sorted(corpus_iterator("motions", corpus_root="data"))
        LOGGER.info(
            "Checking duplicate mapped signers in %s motion XML files", len(paths)
        )

        for path in tqdm(paths, desc="duplicate signers"):
            root = parse_tei(path, get_ns=False)
            for block in root.iter(TEI_SIGNATURE_BLOCK):
                block_id = block.get(XML_ID)
                seen_whos = set()
                duplicate_whos = set()
                has_known_signer = False

                for item in block.iter(TEI_ITEM):
                    if item.get("type") != "signature":
                        continue

                    who = item.get("who")
                    if who not in (None, "", "unknown") and who in person_ids:
                        has_known_signer = True
                        if who in seen_whos:
                            duplicate_whos.add(who)
                        else:
                            seen_whos.add(who)

                if not has_known_signer:
                    continue

                signature_blocks += 1
                if duplicate_whos:
                    failures += 1
                    LOGGER.error(
                        "file=%s | signature_block_id=%s | duplicate_who=%s | "
                        "issue=signature block repeats known mapped signer(s)",
                        path,
                        block_id,
                        "|".join(sorted(duplicate_whos)),
                    )

        LOGGER.info(
            "Checked %s signature blocks with known signers", signature_blocks
        )
        self.assertGreater(signature_blocks, 0, "No signature blocks were checked")
        self.assertLessEqual(
            failures,
            MAX_DUPLICATE_MAPPED_SIGNER_BLOCKS,
            (
                f"{failures} signature block(s) with duplicate known mapped "
                f"signers, exceeding baseline {MAX_DUPLICATE_MAPPED_SIGNER_BLOCKS}; "
                "diagnostics logged with trainerlog"
            ),
        )

    def test_mapped_signature_locations_match_person_location_specifiers(self):
        """Guarantee: mapped signature locations belong to the mapped person.

        Why this matters: signature text often disambiguates politicians by
        location, e.g. ``i Mora`` or ``från Nerike``. When such a location is
        present on a mapped signature, it should exist in that person's
        ``location_specifier.csv`` rows.

        Data: reads ``../riksdagen-persons/data/person.csv`` and
        ``../riksdagen-persons/data/location_specifier.csv`` with Polars, then
        scans all motion XML under ``data/`` with ``pyriksdagen``.
        """
        persons = pl.read_csv(
            PERSONS_ROOT / "data" / "person.csv",
            schema_overrides={"person_id": pl.Utf8},
            infer_schema_length=10000,
        )
        person_ids = set(persons.get_column("person_id").to_list())

        locations = pl.read_csv(
            PERSONS_ROOT / "data" / "location_specifier.csv",
            infer_schema_length=10000,
        )
        locations_by_person = {}
        location_rows = locations.select("person_id", "location").iter_rows()
        for person_id, location in location_rows:
            locations_by_person.setdefault(person_id, set()).add(
                location_key(location)
            )

        failures = 0
        checked_locations = 0
        paths = sorted(corpus_iterator("motions", corpus_root="data"))
        LOGGER.info("Checking signature locations in %s motion XML files", len(paths))

        for path in tqdm(paths, desc="signature locations"):
            root = parse_tei(path, get_ns=False)
            for block in root.iter(TEI_SIGNATURE_BLOCK):
                block_id = block.get(XML_ID)
                for item in block.iter(TEI_ITEM):
                    if item.get("type") != "signature":
                        continue

                    who = item.get("who")
                    if who in (None, "", "unknown") or who not in person_ids:
                        continue

                    text = " ".join(" ".join(item.itertext()).split())
                    location = signature_location(text)
                    if location is None:
                        continue

                    checked_locations += 1
                    registered_locations = locations_by_person.get(who, set())
                    if location_key(location) not in registered_locations:
                        failures += 1
                        LOGGER.error(
                            "file=%s | signature_block_id=%s | xml_id=%s | "
                            "who=%s | location=%s | issue=signature location "
                            "is not listed for mapped person",
                            path,
                            block_id,
                            item.get(XML_ID),
                            who,
                            location,
                        )

        LOGGER.info("Checked %s mapped signature locations", checked_locations)
        self.assertGreater(
            checked_locations, 0, "No signature locations were checked"
        )
        self.assertLessEqual(
            failures,
            MAX_UNSUPPORTED_SIGNATURE_LOCATIONS,
            (
                f"{failures} unsupported signature location(s), exceeding "
                f"baseline {MAX_UNSUPPORTED_SIGNATURE_LOCATIONS}; diagnostics "
                "logged with trainerlog"
            ),
        )


if __name__ == "__main__":
    unittest.main()
