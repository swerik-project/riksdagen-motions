#!/usr/bin/env python3

from glob import glob
from lxml import etree
from pyriksdagen.utils import (
    parse_protocol,
)
import pandas as pd
import unittest
import warnings

class Test(unittest.TestCase):

    def fetch_data_location(self):
        return sorted(list(glob("data/*/*.xml")))


    def test_file_names(self):
        mots = self.fetch_data_location()
        None_in_filename = 0
        for mot in mots:
            if "-None-" in mot:
                None_in_filename += 1
                print(mot)
        print(len(mots))
        self.assertEqual(None_in_filename, 0)


    #@unittest.skip
    def test_auhor_exists(self):
        no_author = 0
        counter = 0
        mots = self.fetch_data_location()
        rows = []
        cols = ["mot", "problem"]
        for mot in mots:
            counter += 1
            root, ns = parse_protocol(mot, get_ns=True)

            try:
                author = root.find(f".//{ns['tei_ns']}titleStmt/{ns['tei_ns']}author")
            except:
                no_author += 1
                rows.append([mot, "author elem not found"])
            else:
                if author is None or author.text is None or author.text == '':
                    no_author += 1
                    if author is None:
                        rows.append([mot, "author is None"])
                    else:
                        rows.append([mot, "author text is None or empty string"])
        if len(rows) > 0:
            df = pd.DataFrame(rows, columns = cols)
            [print(r['mot']) for i, r in df.iterrows()]
            print(df.problem.value_counts())
        print("total:", counter)
        #self.assertEqual(no_author, 0)


    def test_title_exists(self):
        no_title = 0
        counter = 0
        mots = self.fetch_data_location()
        rows = []
        cols = ["mot", "problem"]
        for mot in mots:
            counter += 1
            root, ns = parse_protocol(mot, get_ns=True)

            try:
                title = root.find(f".//{ns['tei_ns']}titleStmt/{ns['tei_ns']}title")
            except:
                no_title += 1
                rows.append([mot, "title elem not found"])
            else:
                if title is None or title.text is None or title.text == '':
                    no_title += 1
                    if title is None:
                        rows.append([mot, "title is None"])
                    else:
                        rows.append([mot, "title text is None or empty string"])
        if len(rows) > 0:
            df = pd.DataFrame(rows, columns = cols)
            [print(r['mot']) for i, r in df.iterrows()]
            print(df.problem.value_counts())
        print("total:", counter)
        self.assertEqual(no_title, 0)


if __name__ == '__main__':
    unittest.main()
