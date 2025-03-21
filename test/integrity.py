#!/usr/bin/env python3
"""
.. include:: docs/general-integrity-tests.md
"""
from glob import glob
from lxml import etree
from pyriksdagen.utils import parse_tei
import os
import pandas as pd
import unittest
import warnings




class EmptyBodyWarning(Warning):
    def __init__(self, m):
        self.message = m

    def __str__(self):
        return self.message


class NoMotBodyWarning(Warning):
    def __init__(self, m):
        self.message = m

    def __str__(self):
        return self.message


class GeneralIntegrityTest(unittest.TestCase):
    """
    TestCase class for running general data integrity tests. The following test functions are defined:
    """
    @classmethod
    def setUpClass(cls):
        """
        Set up common variables for all test cases.
        """
        super(GeneralIntegrityTest, cls).setUpClass()
        motions = []
        dirs = sorted(os.listdir("data"))
        pys = [_ for _ in dirs if _ not in ["reg", "fort"] and os.path.isdir(f"data/{_}")]
        [motions.extend(list(glob(f"data/{py}/*.xml"))) for py in pys]
        cls.motions = motions
        cls.N_motions = len(motions)
        cls.prerelease_nr = os.environ.get("RELEASE_NR", None)
        if cls.prerelease_nr is None:
            cls.prerelease_nr = "v99.99.99"
        df = pd.read_csv("test/results/integrity-results.tsv", sep='\t')
        df.set_index("result", inplace=True)
        df[cls.prerelease_nr] = None
        cls.integrity_results = df


    @classmethod
    def tearDownClass(cls):
        """
        Write summary output when appropriate.
        """
        print("\n\ntear down")
        print(cls.__dict__.keys())
        cls.integrity_results.at["total_motions", cls.prerelease_nr] = len(cls.motions)
        cls.integrity_results.to_csv("test/results/integrity-results.tsv", sep='\t')


    #@unittest.skip
    def test_file_names(self):
        """
        Checks that no motion filename contains the string 'None".
        """
        None_in_filename = 0
        for mot in self.motions:
            if "-None-" in mot:
                None_in_filename += 1
        if self.prerelease_nr:
            self.integrity_results.at["none_in_filename", self.prerelease_nr] = None_in_filename
        self.assertEqual(0, None_in_filename)


    #@unittest.skip
    def test_has_header(self):
        """
        Check that every motion has a `teiHeader` element.
        """
        no_header = []
        for mot in self.motions:
            root, ns = parse_tei(mot)
            header = root.find(f"{ns['tei_ns']}teiHeader")
            if header is None:
                no_header.append(mot)
        if self.prerelease_nr is not None:
            self.integrity_results.at["has_header", self.prerelease_nr]  = self.N_motions - len(no_header)
            if len(no_header) > 0:
                with open(f"test/results/integrity_{self.prerelease_nr}_no-header.txt", "w+") as out:
                    [out.write(f"{_}\n") for _ in sorted(no_header)]
        self.assertEqual(0, len(no_header))


    #@unittest.skip
    def test_has_body(self):
        """
        Check that every motion has a `body` element.
        """
        no_body = []
        for mot in self.motions:
            root, ns = parse_tei(mot)
            body = root.find(f".//{ns['tei_ns']}div[@type=\"motBody\"]")
            if body is None:
                no_body.append(mot)

        if self.prerelease_nr is not None:
            self.integrity_results.at["has_body", self.prerelease_nr] = self.N_motions - len(no_body)
            if len(no_body) > 0:
                msg = f"There are {len(no_body)} motions without a div of type 'motBody'. Should be 0"
                warnings.warn(msg, NoMotBodyWarning)
                with open(f"test/results/integrity_{self.prerelease_nr}_no-body.txt", "w+") as out:
                    [out.write(f"{_}\n") for _ in sorted(no_body)]
        self.assert(len(no_body) < 300)


    #@unittest.skip
    def test_auhor_exists(self):
        """
        Checks that the author element under `titleStmt` exists and is not empty.
        """
        no_author = 0
        rows = []
        cols = ["mot", "problem"]
        for mot in self.motions:
            root, ns = parse_tei(mot)
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
        if self.prerelease_nr:
            self.integrity_results.at["has_author", self.prerelease_nr] = self.N_motions - no_author
            if len(rows) > 0:
                df = pd.DataFrame(rows, columns = cols)
                df.to_csv(f"test/results/integrity_{self.prerelease_nr}_no-author.tsv", sep='\t', index=False)
        #self.assertEqual(0, no_author)


    #@unittest.skip
    def test_title_exists(self):
        """
        Checks that the title element under `titleStmt` exists and is not empty.
        """
        no_title = 0
        rows = []
        cols = ["mot", "problem"]
        for mot in self.motions:
            root, ns = parse_tei(mot)
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
        if self.prerelease_nr:
            self.integrity_results.at["has_title", self.prerelease_nr] = self.N_motions - no_title
            if len(rows) > 0:
                df = pd.DataFrame(rows, columns = cols)
                df.to_csv(f"test/results/integrity_{self.prerelease_nr}_no-title.tsv", sep='\t', index=False)
        #self.assertEqual(0, no_title)


    #@unittest.skip
    def test_body_not_empty(self):
        """
        Check that each motion's body element is not empty.
        """
        empty_body = 0
        empty_bodies = []
        for mot in self.motions:
            root, ns = parse_tei(mot)
            body = root.find(f".//{ns['tei_ns']}div[@type=\"motBody\"]")
            if body is None or len(body) == 0 or body.text is not None:
                empty_body += 1
                empty_bodies.append(mot)
        if self.prerelease_nr:
            self.integrity_results.at["body_not_empty", self.prerelease_nr] = self.N_motions - empty_body
            if empty_body > 0:
                msg = f"There are {empty_body} motions with an empty <div type=\"motBody\"> element. Should be 0."
                warnings.warn(msg, EmptyBodyWarning)
                with open(f"test/results/integrity_{self.prerelease_nr}_empty-body.txt", "w+") as out:
                    [out.write(f"{_}\n") for _ in sorted(empty_bodies)]
        self.assert(empty_body < 300)




if __name__ == '__main__':
    unittest.main()
