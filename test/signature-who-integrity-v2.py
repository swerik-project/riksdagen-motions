#!/usr/bin/env python3
"""
Semantic integrity tests for motion signature person references.

"""

import re
import unittest
from pathlib import Path
import tqdm

import polars as pl
from lxml import etree
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import corpus_iterator, infer_metadata
from trainerlog import get_logger
from pyriksdagen.utils import XML_NS, TEI_NS

LOGGER = get_logger(name="signature-who-integrity")

# Current-data baselines keep these release-blocking regression guards active
# while known signature issues are curated in separate follow-up issues.
ACCEPTED_SIGNATURE_WHO_FAILURES = 5
ACCEPTED_DUPLICATE_MAPPED_SIGNERS = 353


def load_person_ids(persons_root: Path):
    """Load known SWERIK person ids from the person catalog."""
    person_path = persons_root / "data" / "person.csv"
    persons = pl.read_csv(
        person_path,
        infer_schema_length=10000
    )
    return persons


def load_locations_by_person(persons_root: Path):
    """Load normalized location specifiers keyed by SWERIK person id."""
    location_path = persons_root / "data" / "location_specifier.csv"
    locations = pl.read_csv(
        location_path,
        infer_schema_length=10000
    )
    return locations
    


class SignatureWhoIntegrityTests(unittest.TestCase):
    """Release-blocking checks for motion signature person references."""

    def test_missing_whos(self):
        """Signature ``@who`` reference failures should not regress."""

        failures = 0
        for path in tqdm.tqdm(list(corpus_iterator("motions", corpus_root="data"))):
            root, ns = parse_tei(path)
            for body in root.findall(f".//{TEI_NS}body"):
                for signatureBlock in body.findall(f".//{TEI_NS}signatureBlock"):
                    for item in signatureBlock.findall(f".//{TEI_NS}item"):
                        if item.get("type") == "signature" and item.get("who") is None:
                            LOGGER.error(f"No who attribute in {path}, signature: {item.text}")
                            failures += 1
            #for 
        self.assertLessEqual(
            failures,
            ACCEPTED_SIGNATURE_WHO_FAILURES,
            (
                f"{failures} invalid signature @who reference(s), exceeding "
                f"current-data baseline {ACCEPTED_SIGNATURE_WHO_FAILURES}; "
            ),
        )

    def test_location_specifiers(self):
        """Mapped signature location suffixes should not regress."""
        # TODO
        pass

    def test_duplicates(self):
        """Duplicate mapped signers should not regress."""
        failures = 0
        for path in tqdm.tqdm(list(corpus_iterator("motions", corpus_root="data"))):
            root, ns = parse_tei(path)
            for signatureBlock in root.findall(f".//{TEI_NS}signatureBlock"):
                whos = []
                for item in signatureBlock.findall(f".//{TEI_NS}item"):
                    if item.get("type") == "signature" and item.get("who", "unknown") != "unknown":
                        whos.append(item.get("who"))

                if len(whos) != len(set(whos)):
                    LOGGER.error(f"Duplicated who attribute in {path}, signature: {whos}")
                    failures += 1

        self.assertLessEqual(
            failures,
            ACCEPTED_DUPLICATE_MAPPED_SIGNERS,
            (
                f"{failures} duplicate mapped signer(s), exceeding current-data "
                f"baseline {ACCEPTED_DUPLICATE_MAPPED_SIGNERS}"
            ),
        )


if __name__ == "__main__":
    unittest.main()
