#!/usr/bin/env python3
"""
Tests for motion signature person references.
"""

import re, os
import unittest
import tqdm
from pathlib import Path

import polars as pl
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import corpus_iterator, infer_metadata
from trainerlog import get_logger
from pyriksdagen.utils import XML_NS, TEI_NS

LOGGER = get_logger(name="signature-who-integrity")

# Current values; not to be exceeded
ACCEPTED_SIGNATURE_WHO_FAILURES = 5
ACCEPTED_DUPLICATE_MAPPED_SIGNERS = 353
ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS = 739

PERSONS_ROOT = Path(os.environ.get("PERSONS_ROOT", "../riksdagen-persons"))

class SignatureWhoIntegrityTests(unittest.TestCase):

    def test_missing_whos(self):
        """The number of missing ``@who`` attributes should not exceed the current number"""
        persons = pl.read_csv(PERSONS_ROOT / "data" / "person.csv")
        person_ids = set(persons.get_column("person_id"))

        failures = 0
        for path in tqdm.tqdm(sorted(corpus_iterator("motions", corpus_root="data"))):
            root, ns = parse_tei(path)
            for signatureBlock in root.findall(f".//{TEI_NS}signatureBlock"):
                for item in signatureBlock.findall(f".//{TEI_NS}item"):
                    if item.get("type") == "signature":
                        person_id = item.get("who")
                        if person_id is None:
                            LOGGER.error(f"No who attribute in {path}, signature: {item.text}")
                            failures += 1
                        elif person_id != "unknown" and person_id not in person_ids:
                            LOGGER.error(f"who attribute {person_id} in {path} is not in the persons database")
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
        """Check that the location specifiers in the signatures match the database."""
        
        locations = pl.read_csv(
            PERSONS_ROOT / "data" / "location_specifier.csv",
            infer_schema_length=10000
        )
        location_dict, all_locations = {}, set()
        for person_id, location in locations.iter_rows():
            location_dict[person_id] = location_dict.get(person_id, set()).union({location})
            all_locations.add(location)

        location_expression = re.compile(r"(i|från|fran) ([A-ZÅÄÖ][a-zåöä]{2,15})")
        failures = 0
        for path in tqdm.tqdm(list(corpus_iterator("motions", corpus_root="data"))):
            root, ns = parse_tei(path)
            for signatureBlock in root.findall(f".//{TEI_NS}signatureBlock"):
                for item in signatureBlock.findall(f".//{TEI_NS}item"):
                    person_id = item.get("who", "unknown")
                    if item.get("type") == "signature" and person_id != "unknown":
                        m = location_expression.search(" ".join(item.text.split()))
                        if m is not None:
                            iort = m.group(2)
                            if iort in all_locations and iort not in location_dict[person_id]:
                                failures += 1
                                msg = f"In {path}, person: {person_id} has inconsistent i-ort: {iort}"
                                msg += f" (not included in {location_dict[person_id]})"
                                LOGGER.error(msg)
                            
        self.assertLessEqual(
            failures,
            ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS,
            (
                f"{failures} inconsistent location specifier(s), exceeding "
                f"current-data baseline {ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS}; "
            ),
        )


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
