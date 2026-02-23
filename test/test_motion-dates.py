#!/usr/bin/env python3
"""
Check that at least 90% of scraped motion dates are within +-1 year
of the year encoded in the filename.
"""

from collections import defaultdict
import csv
from datetime import datetime
from glob import glob
import json
import locale
import os
from pyriksdagen.io import parse_tei
import re
from scipy.stats import spearmanr
import sys
from trainerlog import get_logger
import unittest
from tqdm import tqdm

try:
    locale.setlocale(locale.LC_TIME, 'sv_SE.UTF-8')
except locale.Error:
    try:
        locale.setlocale(locale.LC_TIME, 'Swedish_Sweden')
    except locale.Error:
        print(
            "WARNING: Swedish locale not available. Month names may not parse correctly.",
            file=sys.stderr
        )

log_level = os.environ.get("LOGLEVEL", "INFO").upper()
logger = get_logger(name="motion-date-year-check", level=log_level)


class TestMotionDateVsFilenameYear(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.motions = sorted(glob("data/*/*.xml"))
        cls.motions = [
            p for p in cls.motions
            if p.startswith("data/1") or p.startswith("data/2")
        ]

        os.makedirs("test/results", exist_ok=True)

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


    def _get_parliament_year_and_chamber(self, scraped_year, motion_path):
        """
        Return the official parliament year for grouping (from filename), without changing the motion date.
        Chamber info only for pre-1975 motions.
        """
        m_ch = re.search(r"--(fk|ak)--", os.path.basename(motion_path))
        chamber = m_ch.group(1) if m_ch else None

        fname = os.path.basename(motion_path)
        m_py = re.match(r"mot-(\d{4,8})-", fname)
        if m_py:
            parliament_year = int(m_py.group(1))
        else:
            parliament_year = scraped_year

        return parliament_year, chamber


    def _find_motion_dates(self, root, ns):
        """
        Returns a tuple (date_obj, unparsable_content) for a motion.
        1. Prefer <p type="date"> in the body.
        2. Fallback to <correspAction>/<date> elements with 'when' attribute.
        3. Returns (None, content) if no valid date found.
        """
        try:
            body_dates = root.findall(f".//{ns['tei_ns']}p[@type='date']")
        except Exception:
            body_dates = root.findall(".//p[@type='date']")

        for d in body_dates:
            if d.text:
                full_text = d.text.strip()
                m = re.search(r"(\d{1,2} \w+ (?:1[0-9]{3}|20[0-9]{2}))", full_text)
                if m:
                    try:
                        date_obj = datetime.strptime(m.group(1), "%d %B %Y")
                        return date_obj, None
                    except ValueError:
                        return None, full_text
                else:
                    return None, full_text

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
                        return date_obj, None
                    except ValueError:
                        return None, when

        return None, None


    def test_date_within_filename_year_range(self):
        for motion in tqdm(self.motions):
            filename_year = self._extract_filename_year(motion)

            if filename_year is None:
                logger.debug(f"Could not parse filename year: {motion}")
                continue

            root, ns = parse_tei(motion)
            date_obj, unparsable_content = self._find_motion_dates(root, ns)

            if date_obj:
                scraped_year = date_obj.year
            elif unparsable_content:
                self.__class__.unparsable_dates.append((motion, unparsable_content))
                self.__class__.no_date_count += 1
                self.__class__.total_checked += 1
                continue
            else:
                self.__class__.no_dates.append(motion)
                self.__class__.no_date_count += 1
                self.__class__.total_checked += 1
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

                logger.debug(
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

        self.assertGreaterEqual(ratio, 0.90, f"Only {ratio:.2%} of motions within ±1 year of filename year")


    def test_motion_ordering_within_year(self):
        motions_by_year_committee = defaultdict(list)

        for motion in tqdm(self.motions, desc="Collecting motions for rank check"):
            if motion in self.no_dates:
                continue

            root, ns = parse_tei(motion)
            date_obj, unparsable_content = self._find_motion_dates(root, ns)
            if not date_obj:
                if unparsable_content:
                    self.__class__.unparsable_dates.append((motion, unparsable_content))
                    logger.debug(f"[SKIPPED] Could not parse a date for motion {motion}")
                continue

            scraped_year = date_obj.year
            parliament_year, chamber = self._get_parliament_year_and_chamber(scraped_year, motion)

            m_com = re.match(r"mot-\d{4,8}-(\w+)-\d+", os.path.basename(motion))
            committee = m_com.group(1) if m_com else "unknown"

            if parliament_year < 1975:
                group_key = (parliament_year, chamber or "unknown", committee or "unknown")
            else:
                group_key = (parliament_year, committee or "unknown")

            mnum_match = re.search(r"-(\d+)\.xml$", motion)
            if not mnum_match:
                continue
            mnum = int(mnum_match.group(1))

            motions_by_year_committee[group_key].append((mnum, date_obj, motion))

        for group_key, motion_list in motions_by_year_committee.items():
            if len(motion_list) < 2:
                continue

            motion_list.sort(key=lambda x: x[0])
            nums = [m[0] for m in motion_list]
            dates = [m[1].toordinal() for m in motion_list]
            # date_strings = [m[1].strftime("%Y-%m-%d") for m in motion_list] -> optional for debuggin in case the correlation seems weird

            corr, _ = spearmanr(nums, dates)
            if corr < 0.9:
                logger.debug(f"Low correlation {corr:.2f} for group {group_key} (motions={len(motion_list)})")
                self.__class__.low_corr.append({
                    "group": group_key,
                    "correlation": corr,
                    # "dates": date_strings -> optional for debugging in case the correlation seems weird
                })
            
        if self.outliers:
            logger.warning(f"Year mismatches >1 year found: {len(self.outliers)} motions")
        
        if self.unparsable_dates:
            logger.warning(f"Unparsable motion dates found: {len(self.unparsable_dates)}")

        total_groups = len(motions_by_year_committee)
        if self.low_corr:
            logger.warning(
                f"Low correlation between motion number and date in {len(self.low_corr)}/{total_groups} groups "
                f"({len(self.low_corr)/total_groups:.2%})"
            )


    @classmethod
    def tearDownClass(cls):
        if hasattr(cls, "mismatch_log"):
            cls.mismatch_log.close()

        summary = {
            "total_checked": cls.total_checked,
            "within_range": cls.within_range,
            "no_date_count": cls.no_date_count,
            "ratio": (
                cls.within_range / cls.total_checked
                if cls.total_checked > 0 else 0
            ),
            "outliers": len(cls.outliers),
        }

        with open("test/results/result-dates/motion-date-year-check-summary.json", "w") as f:
            json.dump(summary, f, indent=4)
        
        if cls.no_dates:
            with open("test/results/result-dates/motion-has-no-date.csv", "w", newline='', encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["motion_file"])
                for motion in sorted(cls.no_dates):
                    writer.writerow([motion])
        
        if hasattr(cls, "low_corr") and cls.low_corr:
            with open("test/results/result-dates/motion-low-correlation.csv", "w", newline="", encoding="utf-8") as f:
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
                    row_copy["dates"] = ";".join(row_copy.get("dates", []))
                    writer.writerow(row_copy)

        with open("test/results/result-dates/motion-unparsable-date-content.csv", "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(["file", "content_that_could_not_be_parsed"])
            for motion, content in sorted(cls.unparsable_dates):
                writer.writerow([motion, content])

        logger.info("Saved test summary")
        logger.info("Results written to test/results/result-dates/")


if __name__ == "__main__":
    unittest.main()