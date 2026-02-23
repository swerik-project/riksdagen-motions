#!/usr/bin/env python3
"""
Check that at least 90% of scraped motion dates are within +-1 year
of the year encoded in the filename.
"""

from glob import glob
import os
import re
import sys
import json
import unittest
import csv
from tqdm import tqdm

from trainerlog import get_logger
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import version_number_is_valid


log_level = os.environ.get("LOGLEVEL", "INFO").upper()
logger = get_logger(name="motion-date-year-check", level=log_level)

VERSION = "v99.99.99"

argv = sys.argv[:]
sys.argv = argv[:2]
if len(argv) > 2:
    if argv[2] != "docs":
        VERSION = argv[2]
_ = version_number_is_valid(VERSION)


class TestMotionDateVsFilenameYear(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.version = VERSION

        cls.motions = sorted(glob("data/*/*.xml"))
        cls.motions = [
            p for p in cls.motions
            if p.startswith("data/1") or p.startswith("data/2")
        ]

        os.makedirs("test/results", exist_ok=True)

        cls.mismatch_log_path = "test/results/motion-date-year-mismatches.tsv"
        cls.mismatch_log = open(cls.mismatch_log_path, "w", encoding="utf-8")
        cls.mismatch_log.write("motion\tfilename_year\tscraped_year\tdiff\n")

        cls.total_checked = 0
        cls.within_range = 0
        cls.no_date_count = 0
        cls.outliers = []
        cls.per_year_stats = {}
        cls.no_dates = []

        logger.info(f"Loaded {len(cls.motions)} motions")
        logger.info(f"Writing mismatches to {cls.mismatch_log_path}")

    @staticmethod
    def _extract_filename_year(motion_path: str):
        fname = os.path.basename(motion_path)

        m = re.match(r"mot-(\d{4,8})-", fname)
        if not m:
            return None

        code = m.group(1)

        if len(code) == 4:
            return int(code)

        if len(code) == 6:
            return int(code[:4])

        if len(code) == 8:
            return int(code[:4])

        return None

    @staticmethod
    def _extract_scraped_year(root, ns, motion_path):
        """
        Extract the year from a motion TEI file.

        1. Prefer the <p type="date"> in the motion body
        2. Fallback to any <correspAction>/<date> with 'when' attribute
        3. Return None if no year found
        """

        try:
            body_dates = root.findall(f".//{ns['tei_ns']}p[@type='date']")
            if not body_dates:
                raise ValueError
        except Exception:
            body_dates = root.findall(".//p[@type='date']")

        for d in body_dates:
            if d.text:
                m = re.search(r"(1[0-9]{3}|20[0-9]{2})", d.text)
                if m:
                    year = int(m.group(1))
                    logger.debug(f"Using body date for {motion_path}: {year}")
                    return year

        try:
            actions = root.findall(f".//{ns['tei_ns']}correspAction")
        except Exception:
            actions = root.findall(".//correspAction")

        for action in actions:
            for date_el in action.findall(f"{ns['tei_ns']}date") + action.findall("date"):
                if date_el is not None and date_el.get("when"):
                    try:
                        year = int(date_el.get("when")[:4])
                        logger.debug(f"Using fallback metadata date for {motion_path}: {year}")
                        return year
                    except Exception:
                        continue

        logger.warning(f"No scraped year found: {motion_path}")
        return None

    def test_date_within_filename_year_range(self):
        for motion in tqdm(self.motions):
            filename_year = self._extract_filename_year(motion)

            if filename_year is None:
                logger.warning(f"Could not parse filename year: {motion}")
                continue

            root, ns = parse_tei(motion)

            scraped_year = self._extract_scraped_year(root, ns, motion)

            if scraped_year is None:
                self.__class__.no_date_count += 1
                self.__class__.total_checked += 1
                self.__class__.no_dates.append(motion)
                continue

            self.__class__.total_checked += 1

            diff = abs(scraped_year - filename_year)
            ok = diff <= 1

            py = motion.split("/")[1]
            if py not in self.per_year_stats:
                self.per_year_stats[py] = {"checked": 0, "ok": 0}

            self.per_year_stats[py]["checked"] += 1

            if ok:
                self.__class__.within_range += 1
                self.per_year_stats[py]["ok"] += 1
            else:
                record = {
                    "motion": motion,
                    "filename_year": filename_year,
                    "scraped_year": scraped_year,
                    "diff": diff,
                }

                self.__class__.outliers.append(record)

                msg = f"{motion}\t{filename_year}\t{scraped_year}\t{diff}"

                logger.warning(
                    f"Year mismatch >1: {motion} "
                    f"(filename={filename_year}, scraped={scraped_year})"
                )

                self.__class__.mismatch_log.write(msg + "\n")

        if self.total_checked == 0:
            self.fail("No motions were checked.")

        ratio = self.within_range / self.total_checked

        logger.info(
            f"Within ±1 year: {self.within_range}/{self.total_checked} "
            f"({ratio:.2%})"
        )

        self.assertGreaterEqual(
            ratio,
            0.90,
            f"Only {ratio:.2%} of motions within ±1 year of filename year"
        )

    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "mismatch_log"):
            cls.mismatch_log.close()

        summary = {
            "version": cls.version,
            "total_checked": cls.total_checked,
            "within_range": cls.within_range,
            "no_date_count": cls.no_date_count,
            "ratio": (
                cls.within_range / cls.total_checked
                if cls.total_checked > 0 else 0
            ),
            "outliers": len(cls.outliers),
        }

        with open("test/results/motion-date-year-check-summary.json", "w") as f:
            json.dump(summary, f, indent=4)

        with open("test/results/motion-date-year-outliers.json", "w") as f:
            json.dump(cls.outliers, f, indent=2)
        
        if cls.no_dates:
            with open("test/results/motion-has-no-date.csv", "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["motion_file"])
                for motion in sorted(cls.no_dates):
                    writer.writerow([motion])

        logger.info("Saved test summary")
        logger.info("Results written to test/results/")


if __name__ == "__main__":
    unittest.main()