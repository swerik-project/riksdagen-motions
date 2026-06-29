#!/usr/bin/env python3
"""
Test there are no duplicate files
"""
from collections import defaultdict
from glob import glob
from pathlib import Path
from trainerlog import get_logger
import hashlib
import unittest
import tqdm


logger = get_logger("lumberjack")




class DuplicateFilesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.motions = glob("data/*/*.xml")


    @classmethod
    def tearDownClass(cls):
        pass


    def test_no_duplicates(self):
        """
        Test no filenames are duplicated
        """
        logger.info("Testing there are no duplicate file names...")
        duplicate_paths = len(self.motions) - len(set(self.motions))
        if duplicate_paths:
            logger.error(f"{duplicate_paths} duplicate motion path(s) found")
        self.assertEqual(len(self.motions), len(set(self.motions)), f"{duplicate_paths} duplicate motion path(s) found")
        lower_motions = [f.lower() for f in self.motions]
        duplicate_casefold_paths = len(lower_motions) - len(set(lower_motions))
        if duplicate_casefold_paths:
            logger.error(f"{duplicate_casefold_paths} case-insensitive duplicate motion path(s) found")
        self.assertEqual(len(lower_motions), len(set(lower_motions)), f"{duplicate_casefold_paths} case-insensitive duplicate motion path(s) found")
        logger.info("...No duplicate file names. 👍👍👍")


    def test_no_duplicated_hases(self):
        """
        Test no duplicate files by hash
        """
        logger.info("Testing there are no duplicate files by hash...")
        def file_hash(path, chunk_size=65536):
            h = hashlib.sha256()
            with open(path, "rb") as f:
                while chunk := f.read(chunk_size):
                    h.update(chunk)
            return h.hexdigest()

        hashed_files = defaultdict(set)
        for m in tqdm.tqdm(self.motions):
            hashed_files[file_hash(m)].add(m)
        duplicates = {h: ps for h, ps in hashed_files.items() if len(ps) > 1}

        for filehash, _ in duplicates.items():
            filenames = hashed_files[filehash]
            logger.error(f"DUPLICATE FILE CONTENTS :: {filenames}")

        self.assertEqual(0, len(duplicates), f"Duplicated files found ({len(duplicates)} duplications)")
        logger.info("...No duplicate file hashes. 👍👍👍")




if __name__ == '__main__':
    unittest.main()
