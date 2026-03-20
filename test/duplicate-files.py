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
        try:
            assert len(self.motions) == len(set(self.motions))
            lower_motions = [f.lower() for f in self.motions]
            assert len(lower_motions) == len(set(lower_motions))
            logger.info("...No duplicate file names. 👍👍👍")
        except:
            logger.error(f"DUPLICATE FILE NAMES :: {len(self.motions)} is not {len(set(self.motions))}")


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

        # group files by size
        size_groups = defaultdict(list)
        for m in self.motions:
            size_groups[Path(m).stat().st_size].append(m)
        # hash files in size groups
        hashed_files = defaultdict(list)
        for group in size_groups.values():
            if len(group) > 1:
                for m in group:
                    hashed_files[file_hash(m)].append(m)
        duplicates = {h: ps for h, ps in hashed_files.items() if len(ps) > 1}
        try:
            assert not duplicates, duplicates
            logger.info("...No duplicate file hashes. 👍👍👍")
        except:
            logger.error(f"DUPLICATE FILE HASHES :: {duplicates}")




if __name__ == '__main__':
    unittest.main()
