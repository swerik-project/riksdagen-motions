#!/usr/bin/env python3
"""
Test there are no duplicate files
"""
from glob import glob
from trainerlog import get_logger
import unittest




logger = get_logger("lumberjack")




class DuplicateFilesTest(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.motions = [f.lower() for f in glob("data/*/*.xml")]


    @classmethod
    def tearDownClass(cls):
        pass


    def test_no_duplicates(self):
        try:
            assert len(self.motions) == len(set(self.motions))
            logger.info("No duplicate files. 👍👍👍")
        except:
            logger.error(f"{len(self.motions)} is not {len(set(self.motions))}")




if __name__ == '__main__':
    unittest.main()
