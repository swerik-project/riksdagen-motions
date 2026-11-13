"""Regression checks for the signature estimator using temporary motion fixtures."""

from importlib import import_module
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lxml import etree
import polars as pl


estimator = import_module("quality.qe_signature-matching")


class TestSignatureMatching(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        repository = patch.object(estimator, "REPO", self.root)
        repository.start()
        self.addCleanup(repository.stop)

    def motion(self, number, body_ids, metadata_ids):
        """Write a source fixture whose body and header can disagree."""
        path = Path("data/1901") / f"mot-1901--ak--{number:05}.xml"
        destination = self.root / path
        destination.parent.mkdir(parents=True, exist_ok=True)
        persons = "".join(f"<person><idno>{pid}</idno></person>" for pid in metadata_ids)
        signatures = "".join(f'<item type="signature" who="{pid}"/>' for pid in body_ids)
        destination.write_text(
            '<TEI xmlns="http://www.tei-c.org/ns/1.0">'
            f"<teiHeader><profileDesc><particDesc><listPerson>{persons}</listPerson>"
            "</particDesc></profileDesc></teiHeader>"
            f"<text><body><list>{signatures}</list></body></text></TEI>",
            encoding="utf-8",
        )
        return path.as_posix()

    def test_body_scores_count_wrong_extra_and_unmapped_signees(self):
        """Body scores count each person once and distinguish errors from unknowns."""
        first = self.motion(1, ["i-A", "i-A", "i-C", "unknown"], ["i-D"])
        second = self.motion(2, ["unknown"], ["i-D"])
        third = self.motion(3, ["i-E"], ["i-E"])
        sample = pl.DataFrame({
            "motion": [first, second, third],
            estimator.SIGNEE_COLUMN: ["i-A; i-B", "i-D", "i-E"],
        })

        comparison = estimator.comparison_rows(sample, "body")
        self.assertEqual(comparison["true_positives"].to_list(), [1, 0, 1])
        self.assertEqual(comparison["false_positives"].to_list(), [1, 0, 0])
        self.assertEqual(comparison["false_negatives"].to_list(), [1, 1, 0])
        self.assertEqual(comparison["unknown_signature_count"].to_list(), [1, 1, 0])
        self.assertEqual(comparison["xml_predicted_ids"].to_list(), [["i-A", "i-C"], [], ["i-E"]])
        self.assertEqual(comparison["parliament_year"].to_list(), ["1901", "1901", "1901"])

        summary = estimator.metrics(comparison, "body")
        self.assertAlmostEqual(summary["precision"], 2 / 3)
        self.assertAlmostEqual(summary["recall"], 1 / 2)
        self.assertAlmostEqual(summary["f1"], 4 / 7)
        self.assertAlmostEqual(summary["macro_f1"], 1 / 2)
        self.assertAlmostEqual(summary["exact_match"], 1 / 3)
        decade = estimator.decade_estimates(comparison, "v1.0.0").row(0, named=True)
        self.assertEqual((decade["decade"], decade["motions"]), (1900, 3))
        self.assertAlmostEqual(decade["f1"], 4 / 7)

    def test_prediction_source_selects_body_header_or_union(self):
        """Choosing another source changes the prediction set explicitly."""
        path = self.motion(1, ["i-A"], ["i-B"])
        sample = pl.DataFrame({"motion": [path], estimator.SIGNEE_COLUMN: ["i-A; i-B"]})
        for source, expected in (("body", ["i-A"]), ("metadata", ["i-B"]), ("union", ["i-A", "i-B"])):
            comparison = estimator.comparison_rows(sample, source)
            self.assertEqual(comparison["xml_predicted_ids"].to_list(), [expected])

    def test_unreadable_xml_stops_estimation(self):
        """An unreadable motion cannot become an empty prediction."""
        malformed = self.root / "malformed.xml"
        malformed.write_text("<TEI>", encoding="utf-8")
        with self.assertRaises(etree.XMLSyntaxError):
            estimator.xml_signees(malformed)
        with self.assertRaises(OSError):
            estimator.xml_signees(self.root / "missing.xml")

    def test_missing_gold_annotation_stays_null_in_diagnostics(self):
        """Diagnostic output preserves the missing source annotation."""
        sample = pl.DataFrame(
            {"motion": ["data/1901/mot-1901--ak--00001.xml"], estimator.SIGNEE_COLUMN: [None]},
            schema_overrides={estimator.SIGNEE_COLUMN: pl.String},
        )
        problem = estimator.gold_problems(sample, {"i-A"}).row(0, named=True)
        self.assertEqual(problem["problem"], "blank-signee-cell")
        self.assertIsNone(problem["signee_entry"])
        self.assertIsNone(problem["raw_signee_cell"])

    def test_primary_person_names_stay_null(self):
        """Primary-name selection keeps null names and ignores alternate names."""
        pl.DataFrame({"person_id": ["i-A"]}).write_csv(self.root / "person.csv")
        pl.DataFrame({
            "person_id": ["i-A", "i-A"],
            "name": [None, "Alternate"],
            "primary_name": [True, False],
        }).write_csv(self.root / "name.csv")
        persons, names = estimator.person_tables(self.root)
        self.assertEqual(persons, {"i-A"})
        self.assertEqual(names, {"i-A": None})

    def test_refreshing_working_estimates_keeps_released_results(self):
        """Working estimates are replaceable; existing release results are retained."""
        path = self.root / "difference.csv"
        pl.DataFrame({
            "version": ["v1.0.0", "v99.99.99"], "decade": [1900, 1900], "f1": [0.5, 0.6],
        }).write_csv(path)
        updated = pl.DataFrame({"version": ["v99.99.99"], "decade": [1900], "f1": [0.7]})
        result = estimator.update_difference(updated, self.root, "v99.99.99")
        self.assertEqual(result["f1"].to_list(), [0.5, 0.7])

        released = pl.DataFrame({"version": ["v1.0.0"], "decade": [1900], "f1": [0.9]})
        result = estimator.update_difference(released, self.root, "v1.0.0")
        self.assertEqual(result["f1"].to_list(), [0.5, 0.7])
        self.assertEqual(pl.read_csv(path)["f1"].to_list(), [0.5, 0.7])


if __name__ == "__main__":
    unittest.main()
