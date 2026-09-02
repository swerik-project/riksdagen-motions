#!/usr/bin/env python3
"""
Tests for motion signature person references.
"""

import re
import unittest
import tqdm

import polars as pl
from lxml import etree
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import corpus_iterator, infer_metadata
from trainerlog import get_logger
from pyriksdagen.utils import XML_NS, TEI_NS

LOGGER = get_logger(name="signature-who-integrity")

# Current values; not to be exceeded
ACCEPTED_SIGNATURE_WHO_FAILURES = 5
ACCEPTED_DUPLICATE_MAPPED_SIGNERS = 353


def load_person_ids(persons_root):
    person_path = persons_root / "data" / "person.csv"
    persons = pl.read_csv(
        person_path,
        infer_schema_length=10000
    )
    return persons


def load_locations_by_person(persons_root):
    location_path = persons_root / "data" / "location_specifier.csv"
    locations = pl.read_csv(
        location_path,
        infer_schema_length=10000
    )
    return locations
    


class SignatureWhoIntegrityTests(unittest.TestCase):

    def test_missing_whos(self):
        """The number of missing ``@who`` attributes should not exceed the current number"""

        failures = 0
        for path in tqdm.tqdm(list(corpus_iterator("motions", corpus_root="data"))):
            root, ns = parse_tei(path)
            for signatureBlock in root.findall(f".//{TEI_NS}signatureBlock"):
                for item in signatureBlock.findall(f".//{TEI_NS}item"):
                    if item.get("type") == "signature" and item.get("who") is None:
                        LOGGER.error(f"No who attribute in {path}, signature: {item.text}")
                        failures += 1

        self.assertLessEqual(
            failures,
            ACCEPTED_SIGNATURE_WHO_FAILURES,
            (
                f"{failures} invalid signature @who reference(s), exceeding "
                f"current-data baseline {ACCEPTED_SIGNATURE_WHO_FAILURES}; "
            ),
        )

    def test_location_specifiers(self):
        """Check that the location specifiers in the signatures exist in the database."""
        # TODO
        pass

    def test_duplicates(self):
        """Test that there are not too many duplicated signers in each signature block."""
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
