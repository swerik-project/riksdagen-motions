#!/usr/bin/env python3
"""
Check that at least 90% of motion dates are within ±1 year of the
filename year, and track per-year/chamber/committee stats for
accuracy and Spearman correlation between motion number and date.
"""

from collections import defaultdict
from datetime import datetime
from glob import glob
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import infer_metadata
from scipy.stats import spearmanr
from trainerlog import get_logger
from tqdm import tqdm

import csv
import locale
import os
import re
import unittest

logger = get_logger(name="motion-date-year-check")

try:
    locale.setlocale(locale.LC_TIME, 'sv_SE.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_TIME, 'Swedish_Sweden')
    except locale.Error:
        logger.warning("WARNING: Swedish locale not available. Month names may not parse correctly.")


class TestMotionDateVsFilenameYear(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.motions = sorted(glob("data/*/*.xml"))
        cls.motions = [
            p for p in cls.motions
            if p.startswith("data/1") or p.startswith("data/2")
        ]

        os.makedirs("test/results/result-dates", exist_ok=True)

        cls.mismatch_log_path = "test/results/result-dates/motion-date-year-outliers.tsv"
        cls.mismatch_log = open(cls.mismatch_log_path, "w", encoding="utf-8")
        cls.mismatch_log.write("motion\tfilename_year\tscraped_year\tdiff\n")

        cls.total_checked = 0
        cls.within_range = 0
        cls.no_date_count = 0
        cls.outliers = []
        cls.per_year_stats = {}
        cls.no_dates = []
        cls.low_corr = []
        cls.unparsable_dates = []
        cls.per_group_stats = {}

        logger.info(f"Loaded {len(cls.motions)} motions")
        logger.info(f"Writing mismatches to {cls.mismatch_log_path}")


    def _get_parliament_year_and_chamber(self, scraped_year, motion_path, metadata):
        parliament_year = metadata.get("year") or scraped_year

        chamber_map = {"Andra kammaren": "ak", "Första kammaren": "fk"}
        chamber = chamber_map.get(metadata.get("chamber"))

        fname = os.path.basename(motion_path)
        parts = fname.split("-")
        committee = parts[2] if len(parts) > 2 else "unknown"

        return parliament_year, chamber, committee


    def _find_motion_dates(self, root, ns, motion_filename):
        """
        Returns a list of parsed date objects for a motion.
        Prefer <p type="date"> first, then <correspAction>/<date>.
        """
        dates = []

        try:
            body_dates = root.findall(f".//{ns['tei_ns']}p[@type='date']")
        except Exception:
            body_dates = root.findall(".//p[@type='date']")

        for d in body_dates:
            if d.text:
                full_text = d.text.strip()
                for m in re.findall(r"(\d{1,2} \w+ (?:1[0-9]{3}|20[0-9]{2}))", full_text):
                    try:
                        date_obj = datetime.strptime(m, "%d %B %Y")
                        dates.append(date_obj)
                    except ValueError:
                        self.__class__.unparsable_dates.append((motion_filename, full_text))

        try:
            actions = root.findall(f".//{ns['tei_ns']}correspAction") or root.findall(".//correspAction")
        except Exception:
            actions = root.findall(".//correspAction")

        for act in actions:
            for d in act.findall(f"{ns['tei_ns']}date") + act.findall("date"):
                when = d.get("when")
                if when:
                    try:
                        date_obj = datetime.strptime(when[:10], "%Y-%m-%d")
                        dates.append(date_obj)
                    except ValueError:
                        self.__class__.unparsable_dates.append((motion_filename, when))

        return dates


    def test_date_within_filename_year_range(self):
        """Verify that the parsed motion dates are within ±1 year of the year indicated
        in the filename, and track per year/chamber/committee stats for CSV output.
        A motion passes if at least one date is within the ±1-year range.
        """

        for motion in tqdm(self.motions, desc="Checking motion dates"):
            metadata = infer_metadata(motion)
            filename_year = metadata.get("year")

            if filename_year is None:
                logger.debug(f"Could not parse filename year: {motion}")
                continue

            root, ns = parse_tei(motion)
            dates = self._find_motion_dates(root, ns, motion)

            if not dates:
                self.__class__.no_dates.append(motion)
                self.__class__.no_date_count += 1
                self.__class__.total_checked += 1
                continue


            ok = any(abs(d.year - filename_year) <= 1 for d in dates)
            self.__class__.total_checked += 1

            if ok:
                self.__class__.within_range += 1

            scraped_year = dates[0].year
            parliament_year, chamber, committee = self._get_parliament_year_and_chamber(scraped_year, motion, metadata)
            group_key = (parliament_year, chamber or "unknown", committee or "unknown")

            if group_key not in self.__class__.per_group_stats:
                self.__class__.per_group_stats[group_key] = {"checked": 0, "within_range": 0}

            self.__class__.per_group_stats[group_key]["checked"] += 1
            if ok:
                self.__class__.per_group_stats[group_key]["within_range"] += 1

            if not ok:
                diff = min(abs(d.year - filename_year) for d in dates)
                record = {
                    "motion": motion,
                    "filename_year": filename_year,
                    "scraped_year": scraped_year,
                    "diff": diff,
                }
                self.__class__.outliers.append(record)
                msg = f"{motion}\t{filename_year}\t{scraped_year}\t{diff}"
                logger.debug(f"Year mismatch >1: {motion} (filename={filename_year}, scraped={scraped_year})")
                self.__class__.mismatch_log.write(msg + "\n")

        if self.total_checked == 0:
            self.fail("No motions were checked.")

        ratio = self.within_range / self.total_checked
        logger.info(f"Within ±1 year: {self.within_range}/{self.total_checked} ({ratio:.2%})")
        self.assertGreaterEqual(ratio, 0.90, f"Only {ratio:.2%} of motions within ±1 year of filename year")


    def test_motion_ordering_within_year(self):
        """Check that motion numbers correlate with chronological order of dates within each parliament year grouping."""
        motions_by_year_committee = defaultdict(list)

        for motion in tqdm(self.motions, desc="Collecting motions for rank check"):
            if motion in self.no_dates:
                continue

            root, ns = parse_tei(motion)
            dates = self._find_motion_dates(root, ns, motion)
            if not dates:
                continue

            scraped_year = dates[0].year
            metadata = infer_metadata(motion)
            parliament_year, chamber, committee = self._get_parliament_year_and_chamber(scraped_year, motion, metadata)

            if parliament_year < 1971:
                group_key = (parliament_year, chamber or "unknown", committee or "unknown")
            else:
                group_key = (parliament_year, committee or "unknown")

            mnum_match = re.search(r"-(\d+)\.xml$", motion)
            if not mnum_match:
                continue
            mnum = int(mnum_match.group(1))

            motions_by_year_committee[group_key].append((mnum, dates[0], motion))

        low_corr_dict = {}

        for group_key, motion_list in motions_by_year_committee.items():
            if len(motion_list) < 2:
                continue

            motion_list.sort(key=lambda x: x[0])
            nums = [m[0] for m in motion_list]
            dates = [m[1].toordinal() for m in motion_list]

            if len(set(dates)) <= 1:
                corr = 1.0
            else:
                corr, _ = spearmanr(nums, dates)

            low_corr_dict[group_key] = {
                "correlation": corr,
            }

        self.__class__.low_corr = [
            {"group": k, **v} for k, v in low_corr_dict.items()
        ]
        
        total_groups = len(motions_by_year_committee)
        low_corr_count = sum(1 for row in self.low_corr if row["correlation"] < 0.9)

        if self.low_corr:
            logger.warning(
                f"Low correlation between motion number and date in {low_corr_count}/{total_groups} groups "
                f"({low_corr_count / total_groups:.2%})"
            )

        if self.outliers:
            logger.warning(f"Year mismatches >1 year found: {len(self.outliers)} motions")
        
        if self.unparsable_dates:
            logger.warning(f"Unparsable motion dates found: {len(self.unparsable_dates)}")


    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "mismatch_log"):
            cls.mismatch_log.close()

        if hasattr(cls, "per_group_stats"):
            csv_file = "test/results/result-dates/motion-date-year-check-by-group.csv"
            with open(csv_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["year","chamber","committee","checked","within_range","ratio"])
                writer.writeheader()
                for group, stats in sorted(cls.per_group_stats.items()):
                    year, chamber, committee = group
                    ratio = stats["within_range"] / stats["checked"] if stats["checked"] else 0
                    writer.writerow({
                        "year": year,
                        "chamber": chamber,
                        "committee": committee,
                        "checked": stats["checked"],
                        "within_range": stats["within_range"],
                        "ratio": ratio,
                    })
            logger.info(f"CSV written to {csv_file} containing ±1-year accuracy by year/chamber/committee")
        
        if cls.no_dates:
            no_date_file = "test/results/result-dates/motion-has-no-date.csv"
            with open(no_date_file, "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["motion_file"])
                for motion in sorted(cls.no_dates):
                    writer.writerow([motion])
            logger.info(f"CSV written to {no_date_file} listing all motion files that had no date information.")
        
        if hasattr(cls, "low_corr") and cls.low_corr:
            low_corr_file = "test/results/result-dates/motion-date-correlation.csv"
            with open(low_corr_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=["year","chamber","committee","correlation","dates"])
                writer.writeheader()
                for row in cls.low_corr:
                    row_copy = row.copy()
                    group = row_copy.pop("group")
                    if len(group) == 3:
                        row_copy["year"], row_copy["chamber"], row_copy["committee"] = group
                    elif len(group) == 2:
                        row_copy["year"], row_copy["committee"] = group
                        row_copy["chamber"] = ""
                    else:
                        row_copy["year"] = group[0]
                        row_copy["chamber"] = ""
                        row_copy["committee"] = ""
                    row_copy["dates"] = ";".join(row_copy.get("dates", [])) if row_copy.get("dates") else ""
                    writer.writerow(row_copy)
            logger.info(f"CSV written to {low_corr_file} containing motions with low correlation between expected year and parsed dates, grouped by year/chamber/committee.")

        unparsable_file = "test/results/result-dates/motion-unparsable-date-content.csv"
        with open(unparsable_file, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "content_that_could_not_be_parsed"])
            for motion, content in sorted(cls.unparsable_dates):
                writer.writerow([motion, content])
        logger.info(f"CSV written to {unparsable_file} containing motions where date content could not be parsed.")


if __name__ == "__main__":
    unittest.main()
