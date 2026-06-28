#!/usr/bin/env python3
"""
API contract tests for the public riksdagen-motions folder structure.

These tests guard the corpus interface described in the motions corpus paper.
They intentionally do not validate TEI content, CSV metadata, or CSVW files;
those checks belong to separate tests.
"""
from pathlib import Path
import re
import unittest


DATA_DIR = Path("data")
PARLIAMENT_YEAR = re.compile(r"^\d{4}(\d{2}|\d{4})?$")
SPECIAL_DATA_DIRS = {"fort", "reg"}
TOP_LEVEL_XML = {"mot-ak.xml", "mot-ek.xml", "mot-fk.xml"}


class APIContractTest(unittest.TestCase):

    def test_public_directories_exist(self):
        """
        The repository exposes the data, docs, quality, and test folders from the paper.
        """
        for dirname in ["data", "docs", "quality", "quality/data", "quality/docs", "quality/estimates", "test", "test/data", "test/docs", "test/results"]:
            with self.subTest(dirname=dirname):
                self.assertTrue(Path(dirname).is_dir(), f"{dirname}/ is part of the public repository structure")

    def test_motions_are_grouped_by_parliament_year(self):
        """
        Motion XML files are exposed in data/<parliament_year>/ folders.
        """
        parliament_year_dirs = sorted(
            path for path in DATA_DIR.iterdir()
            if path.is_dir() and path.name not in SPECIAL_DATA_DIRS
        )
        self.assertGreater(len(parliament_year_dirs), 0, "data/ should contain parliament-year directories")

        for path in parliament_year_dirs:
            with self.subTest(path=path):
                self.assertRegex(path.name, PARLIAMENT_YEAR, f"{path} should be named as a parliament year")
                self.assertGreater(len(list(path.glob("*.xml"))), 0, f"{path} should contain motion XML files")

    def test_bicameral_index_directories_exist(self):
        """
        Bicameral motion indexes are exposed through data/reg/ and data/fort/.
        """
        for dirname in SPECIAL_DATA_DIRS:
            with self.subTest(dirname=dirname):
                self.assertTrue((DATA_DIR / dirname).is_dir(), f"data/{dirname}/ should exist")

    def test_top_level_data_files_are_chamber_indexes(self):
        """
        The only public top-level XML files in data/ are chamber index files.
        """
        top_level_xml = {path.name for path in DATA_DIR.glob("*.xml")}
        self.assertLessEqual(top_level_xml, TOP_LEVEL_XML)
        self.assertTrue(top_level_xml, "data/ should expose at least one chamber index XML file")

        visible_non_xml_files = [
            path.name for path in DATA_DIR.iterdir()
            if path.is_file() and not path.name.startswith(".") and path.suffix != ".xml"
        ]
        self.assertEqual([], visible_non_xml_files, "data/ should not expose non-XML files at top level")


if __name__ == "__main__":
    unittest.main()
