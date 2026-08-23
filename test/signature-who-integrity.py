#!/usr/bin/env python3
"""
Semantic integrity tests for motion signature person references.

These tests guard three intended corpus guarantees:

* every signature-item ``@who`` reference points to a person or ``unknown``;
* explicit location suffixes on mapped signature items are supported by
  ``riksdagen-persons/data/location_specifier.csv`` and are reported for
  follow-up curation;
* a signature block does not contain duplicate mapped signers.

Known legacy issues are accepted through explicit current-data baselines. The
tests fail when a change increases those counts; curation PRs should lower the
baselines as the known issues are fixed.

The tests use the local motion XML under ``data/`` and the person catalog at
``../riksdagen-persons`` by default. Set ``PERSONS_ROOT`` to use another checkout.
Full-corpus runs use ``git grep`` when available to avoid opening every XML file.
Detailed failure diagnostics are written to ``test/results/``. 
"""

from __future__ import annotations

import bisect
import csv
import os
import re
import subprocess
import unittest
import unicodedata
from collections import defaultdict
from pathlib import Path

from trainerlog import get_logger


LOGGER = get_logger(name="signature-who-integrity")
LOCATION_SUFFIX_RE = re.compile(r"\b(i|från|fran)\s+([A-ZÅÄÖ][^\d,;:()|]*)\s*$")
WHO_ATTR_RE = re.compile(rb'\bwho="([^"]*)"')
XML_ID_ATTR_RE = re.compile(rb'\bxml:id="([^"]*)"')
SIGNATURE_BLOCK_RE = re.compile(rb"<signatureBlock\b[^>]*>.*?</signatureBlock>", re.DOTALL)
SIGNATURE_ITEM_RE = re.compile(rb"<item\b(?=[^>]*\btype=\"signature\")[^>]*>.*?</item>", re.DOTALL)
START_TAG_RE = re.compile(rb"^<item\b[^>]*>", re.DOTALL)
TAG_RE = re.compile(rb"<[^>]+>")
GREP_LINE_RE = re.compile(r"^(data/.*?\.xml)([:-])(\d+)\2(.*)$")
RESULTS_DIR = Path("test/results")
ACCEPTED_SIGNATURE_WHO_FAILURES = 5
ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS = 515
ACCEPTED_DUPLICATE_MAPPED_SIGNERS = 337


def normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(char for char in text if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def motion_files() -> list[Path]:
    return sorted(
        path for path in Path("data").glob("*/*.xml")
        if path.parts[1].startswith(("1", "2"))
    )


def load_person_ids(persons_root: Path) -> set[str]:
    with (persons_root / "data" / "person.csv").open(encoding="utf-8", newline="") as inf:
        return {row["person_id"] for row in csv.DictReader(inf)}


def load_locations_by_person(persons_root: Path) -> dict[str, set[str]]:
    locations: dict[str, set[str]] = defaultdict(set)
    with (persons_root / "data" / "location_specifier.csv").open(encoding="utf-8", newline="") as inf:
        for row in csv.DictReader(inf):
            person_id = row.get("person_id", "")
            location = row.get("location", "")
            if person_id and location:
                locations[person_id].add(normalize(location))
    return locations


def element_text(elem) -> str:
    text = TAG_RE.sub(b" ", elem)
    return " ".join(text.decode("utf-8", errors="replace").split())


def attr_value(tag: bytes, pattern: re.Pattern[bytes]) -> str:
    match = pattern.search(tag)
    if match is None:
        return ""
    return match.group(1).decode("utf-8", errors="replace")


def attr_value_text(tag: str, name: str) -> str:
    match = re.search(rf"\b{re.escape(name)}=\"([^\"]*)\"", tag)
    if match is None:
        return ""
    return match.group(1)


def element_text_text(elem: str) -> str:
    return " ".join(re.sub(r"<[^>]+>", " ", elem).split())


def parse_grep_line(line: str) -> tuple[Path, str, int, str] | None:
    match = GREP_LINE_RE.match(line.rstrip("\n"))
    if match is None:
        return None
    path, sep, line_number, content = match.groups()
    return Path(path), sep, int(line_number), content


def write_tsv(path: Path, rows: list[dict[str, str]], fieldnames: list[str]) -> None:
    RESULTS_DIR.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as outf:
        writer = csv.DictWriter(outf, fieldnames=fieldnames, delimiter="\t")
        writer.writeheader()
        writer.writerows(rows)


def location_suffix(text: str) -> tuple[str, str] | None:
    match = LOCATION_SUFFIX_RE.search(re.sub(r"\s+", " ", text).strip())
    if match is None:
        return None
    raw_location = match.group(0)
    location_text = re.sub(r"^(i|från|fran)\s+", "", raw_location, flags=re.IGNORECASE).strip()
    tokens = normalize(location_text).split()
    if not 1 <= len(tokens) <= 4:
        return None
    return raw_location, normalize(location_text)


class SignatureWhoIntegrityTest(unittest.TestCase):
    """
    Corpus-wide tests for signature references and signature-block consistency.
    """

    @classmethod
    def setUpClass(cls):
        cls.persons_root = Path(os.environ.get("PERSONS_ROOT", "../riksdagen-persons"))
        cls.motions = motion_files()
        cls.person_ids = load_person_ids(cls.persons_root)
        cls.locations_by_person = load_locations_by_person(cls.persons_root)
        LOGGER.info(f"Loaded {len(cls.person_ids)} person ids from {cls.persons_root}")
        LOGGER.info(f"Checking {len(cls.motions)} motion XML files")
        cls._scan_corpus()
        cls._write_diagnostics()

    @classmethod
    def _scan_corpus(cls) -> None:
        cls.who_failures = []
        cls.total_who_values = 0
        cls.total_signature_items = 0
        cls.unsupported_locations = []
        cls.unknown_locations = []
        cls.checked_locations = 0
        cls.duplicate_signers = []
        if cls._can_use_git_grep():
            LOGGER.info("Using git grep fast scanner for corpus-wide checks")
            cls._scan_corpus_with_git_grep()
            return
        LOGGER.info("Using Python file scanner for corpus-wide checks")
        for motion in cls.motions:
            data = motion.read_bytes()
            cls._scan_signature_blocks_in_file(motion, data)

    @classmethod
    def _can_use_git_grep(cls) -> bool:
        if os.environ.get("SIGNATURE_INTEGRITY_DISABLE_GIT_GREP", "").lower() in {"1", "true", "yes"}:
            return False
        try:
            check = subprocess.run(
                ["git", "rev-parse", "--is-inside-work-tree"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
            )
        except OSError:
            return False
        return check.returncode == 0

    @classmethod
    def _iter_git_grep(cls, args: list[str]):
        with subprocess.Popen(
            ["git", "grep", *args, "--", "data"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        ) as process:
            assert process.stdout is not None
            for line in process.stdout:
                yield line
            stderr = process.stderr.read() if process.stderr is not None else ""
            returncode = process.wait()
        if returncode not in {0, 1}:
            raise RuntimeError(f"git grep failed with exit code {returncode}: {stderr.strip()}")

    @classmethod
    def _scan_corpus_with_git_grep(cls) -> None:
        block_spans = cls._signature_block_spans_with_git_grep()
        cls._scan_signature_items_with_git_grep(block_spans)

    @classmethod
    def _signature_block_spans_with_git_grep(cls) -> dict[Path, list[tuple[int, int, str]]]:
        open_blocks: dict[Path, list[tuple[int, str]]] = defaultdict(list)
        spans: dict[Path, list[tuple[int, int, str]]] = defaultdict(list)
        for line in cls._iter_git_grep(["-n", "-e", "<signatureBlock", "-e", "</signatureBlock>"]):
            parsed = parse_grep_line(line)
            if parsed is None:
                continue
            motion, _, line_number, content = parsed
            if "<signatureBlock" in content:
                if "/>" in content:
                    continue
                block_id = attr_value_text(content, "xml:id")
                open_blocks[motion].append((line_number, block_id))
            if "</signatureBlock>" in content and open_blocks[motion]:
                start_line, block_id = open_blocks[motion].pop()
                spans[motion].append((start_line, line_number, block_id))
        for motion, stack in open_blocks.items():
            for start_line, block_id in stack:
                spans[motion].append((start_line, 10**12, block_id))
        for motion in spans:
            spans[motion].sort()
        return spans

    @classmethod
    def _block_id_for_line(cls, spans: dict[Path, list[tuple[int, int, str]]], motion: Path, line_number: int) -> str:
        motion_spans = spans.get(motion, [])
        starts = [span[0] for span in motion_spans]
        index = bisect.bisect_right(starts, line_number) - 1
        if index < 0:
            return ""
        start_line, end_line, block_id = motion_spans[index]
        if start_line <= line_number <= end_line:
            return block_id
        return ""

    @classmethod
    def _scan_signature_items_with_git_grep(cls, spans: dict[Path, list[tuple[int, int, str]]]) -> None:
        seen_items: set[tuple[Path, int]] = set()
        seen_by_block: dict[tuple[Path, str], dict[str, str]] = defaultdict(dict)
        current_item: dict[str, object] | None = None

        def finish_current_item() -> None:
            nonlocal current_item
            if current_item is None:
                return
            motion = current_item["motion"]
            line_number = current_item["line_number"]
            xml = "\n".join(current_item["lines"])
            cls._scan_signature_item_text(
                motion=motion,
                line_number=line_number,
                xml=xml,
                block_id=cls._block_id_for_line(spans, motion, line_number),
                seen_by_block=seen_by_block,
            )
            current_item = None

        for line in cls._iter_git_grep(["-n", "-A4", "-e", '<item.*type="signature"']):
            if line == "--\n":
                finish_current_item()
                continue
            parsed = parse_grep_line(line)
            if parsed is None:
                continue
            motion, _, line_number, content = parsed
            is_item_start = "<item" in content and 'type="signature"' in content
            if is_item_start:
                finish_current_item()
                key = (motion, line_number)
                if key in seen_items:
                    current_item = None
                    continue
                seen_items.add(key)
                current_item = {"motion": motion, "line_number": line_number, "lines": [content]}
                if "</item>" in content:
                    finish_current_item()
                continue
            if current_item is not None:
                current_item["lines"].append(content)
                if "</item>" in content:
                    finish_current_item()
        finish_current_item()

    @classmethod
    def _scan_signature_item_text(
        cls,
        motion: Path,
        line_number: int,
        xml: str,
        block_id: str,
        seen_by_block: dict[tuple[Path, str], dict[str, str]],
    ) -> None:
        start_tag = xml.split(">", 1)[0]
        item_id = attr_value_text(start_tag, "xml:id")
        who = attr_value_text(start_tag, "who")
        text = element_text_text(xml)
        cls.total_signature_items += 1
        if not who:
            cls.who_failures.append({
                "motion": str(motion),
                "xml_id": item_id,
                "problem": "signature item missing who",
                "who": "",
                "text": text,
            })
        else:
            for value in who.split():
                cls.total_who_values += 1
                if value == "unknown":
                    continue
                if value not in cls.person_ids:
                    cls.who_failures.append({
                        "motion": str(motion),
                        "xml_id": item_id,
                        "problem": "signature item who is not person_id",
                        "who": value,
                        "text": text,
                    })

        cls._scan_signature_location(motion, item_id, who, text)

        block_key = (motion, block_id or f"line-{line_number}")
        seen = seen_by_block[block_key]
        for value in who.split():
            if value == "unknown":
                continue
            if value in seen:
                cls.duplicate_signers.append({
                    "motion": str(motion),
                    "signature_block_id": block_id,
                    "who": value,
                    "first_item_id": seen[value],
                    "duplicate_item_id": item_id,
                    "duplicate_text": text,
                })
            else:
                seen[value] = item_id

    @classmethod
    def _scan_signature_blocks_in_file(cls, motion: Path, data: bytes) -> None:
        for block_match in SIGNATURE_BLOCK_RE.finditer(data):
            block = block_match.group(0)
            block_start_tag = block.split(b">", 1)[0]
            block_id = attr_value(block_start_tag, XML_ID_ATTR_RE)
            seen: dict[str, str] = {}
            for item_match in SIGNATURE_ITEM_RE.finditer(block):
                item = item_match.group(0)
                item_start_tag = START_TAG_RE.match(item).group(0)
                item_id = attr_value(item_start_tag, XML_ID_ATTR_RE)
                who = attr_value(item_start_tag, WHO_ATTR_RE)
                text = element_text(item)

                if not who:
                    cls.who_failures.append({
                        "motion": str(motion),
                        "xml_id": item_id,
                        "problem": "signature item missing who",
                        "who": "",
                        "text": text,
                    })
                else:
                    for value in who.split():
                        cls.total_who_values += 1
                        if value == "unknown":
                            continue
                        if value not in cls.person_ids:
                            cls.who_failures.append({
                                "motion": str(motion),
                                "xml_id": item_id,
                                "problem": "signature item who is not person_id",
                                "who": value,
                                "text": text,
                            })

                cls.total_signature_items += 1
                cls._scan_signature_location(motion, item_id, who, text)

                if not who or who == "unknown":
                    continue
                for value in who.split():
                    if value == "unknown":
                        continue
                    if value in seen:
                        cls.duplicate_signers.append({
                            "motion": str(motion),
                            "signature_block_id": block_id,
                            "who": value,
                            "first_item_id": seen[value],
                            "duplicate_item_id": item_id,
                            "duplicate_text": text,
                        })
                    else:
                        seen[value] = item_id

    @classmethod
    def _scan_signature_location(cls, motion: Path, item_id: str, who: str, text: str) -> None:
        suffix = location_suffix(text)
        if suffix is None:
            return
        raw_location, location_value = suffix
        if who == "unknown":
            cls.unknown_locations.append({
                "motion": str(motion),
                "xml_id": item_id,
                "who": who,
                "location": raw_location,
                "text": text,
            })
        elif who:
            cls.checked_locations += 1
            for value in who.split():
                if value == "unknown":
                    continue
                if location_value not in cls.locations_by_person.get(value, set()):
                    cls.unsupported_locations.append({
                        "motion": str(motion),
                        "xml_id": item_id,
                        "who": value,
                        "location": raw_location,
                        "text": text,
                    })

    @classmethod
    def _write_diagnostics(cls) -> None:
        write_tsv(
            RESULTS_DIR / "signature-who-reference-integrity.tsv",
            cls.who_failures,
            ["motion", "xml_id", "problem", "who", "text"],
        )
        fieldnames = ["motion", "xml_id", "who", "location", "text"]
        write_tsv(RESULTS_DIR / "signature-location-unsupported.tsv", cls.unsupported_locations, fieldnames)
        write_tsv(RESULTS_DIR / "signature-location-unknown.tsv", cls.unknown_locations, fieldnames)
        write_tsv(
            RESULTS_DIR / "signature-block-duplicate-mapped-signers.tsv",
            cls.duplicate_signers,
            ["motion", "signature_block_id", "who", "first_item_id", "duplicate_item_id", "duplicate_text"],
        )

    def test_who_references_resolve_to_person_catalog(self):
        """
        Every signature-item @who value must be a known person id or unknown.
        """
        out = RESULTS_DIR / "signature-who-reference-integrity.tsv"
        LOGGER.info(
            f"Checked {self.total_who_values} signature @who values; invalid rows: {len(self.who_failures)}"
        )
        self.assertLessEqual(
            len(self.who_failures),
            ACCEPTED_SIGNATURE_WHO_FAILURES,
            f"{len(self.who_failures)} invalid signature @who reference(s) found; "
            f"accepted baseline is {ACCEPTED_SIGNATURE_WHO_FAILURES}; see {out}",
        )

    def test_signature_locations_match_mapped_person_locations(self):
        """
        Report mapped signature location suffixes not found in person-location data.
        """
        unsupported_out = RESULTS_DIR / "signature-location-unsupported.tsv"
        LOGGER.info(
            f"Checked {self.checked_locations} mapped signature location suffixes; "
            f"unsupported rows: {len(self.unsupported_locations)}; unknown-location rows: {len(self.unknown_locations)}"
        )
        self.assertGreater(
            self.checked_locations + len(self.unknown_locations),
            0,
            "No signature location suffixes were checked; expected at least one diagnostic row or mapped suffix.",
        )
        self.assertLessEqual(
            len(self.unsupported_locations),
            ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS,
            f"{len(self.unsupported_locations)} mapped signature location(s) are unsupported by person data; "
            f"accepted baseline is {ACCEPTED_UNSUPPORTED_SIGNATURE_LOCATIONS}; see {unsupported_out}",
        )

    def test_signature_blocks_do_not_repeat_mapped_signers(self):
        """
        A single signature block should not repeat the same mapped signer.
        """
        out = RESULTS_DIR / "signature-block-duplicate-mapped-signers.tsv"
        LOGGER.info(f"Duplicate mapped signers in signature blocks: {len(self.duplicate_signers)}")
        self.assertLessEqual(
            len(self.duplicate_signers),
            ACCEPTED_DUPLICATE_MAPPED_SIGNERS,
            f"{len(self.duplicate_signers)} duplicate mapped signer(s) found within signature blocks; "
            f"accepted baseline is {ACCEPTED_DUPLICATE_MAPPED_SIGNERS}; see {out}",
        )


if __name__ == "__main__":
    unittest.main()
