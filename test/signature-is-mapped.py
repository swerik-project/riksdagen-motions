#!/usr/bin/env python3
"""
Test whether each signature is mapped to a person_id
"""
from cycler import cycler
from glob import glob
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import version_number_is_valid
from tqdm import tqdm
import matplotlib.pyplot as plt
import os
import pandas as pd
import sys
import unittest


VERSION = "v99.99.99"
# copy sys.argv
argv = sys.argv[:]
# keep only script name + module name for unittest
sys.argv = argv[:2]
# everything after that are "custom" args
if len(argv) > 2:
    VERSION = argv[2]
_ = version_number_is_valid(VERSION)




class Test(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.version = VERSION
        cls.motions = sorted(glob("data/*/*.xml"))
        cls.motions = [_ for _ in cls.motions if _.startswith('data/1') or _.startswith('data/2')]
        cls.not_mapped = []
        cls.counts_by_year = {}
        cls.not_mapped_by_year = {}


    @classmethod
    def tearDownClass(cls):

        def _generate_plots(df):
            versions = list(set([v.split('_')[0] for v in df.columns if v.startswith('v')]))
            if cls.version != "v99.99.99" and "v99.99.99" in versions:
                versions.remove("v99.99.99")
            versions = sorted(versions, key=lambda s: list(map(int, s[1:].split('.'))), reverse=True)
            colors = list('kbgrcmy')
            default_cycler = (cycler(color=colors) +
                            cycler(linestyle=(['-', '--', ':', '-.']*2)[:len(colors)]))
            plt.rc('axes', prop_cycle=default_cycler)
            f, ax = plt.subplots()

            X = df['parliament_year'].tolist()
            baseline = df[f"{cls.version}_total"].tolist()
            x, baseline = zip(*sorted(zip(X,baseline),key=lambda x: x[0]))
            plt.plot(x, baseline, linewidth=1.75)

            for version in versions:
                y = df[f"{version}_mapped"].to_list()
                #r[version] = [_/baseline[i] for i, _ in enumerate(y)]
                x, y = zip(*sorted(zip(X,y),key=lambda x: x[0]))
                plt.plot(x, y, linewidth=1.75)
            plt.title('Coverage of mapped Signatures')
            plt.legend([f"Baseline_{cls.version}"]+versions, loc ="upper left")
            plt.xticks(rotation=90)
            labs = [_.get_text()[:4] for _ in ax.xaxis.get_ticklabels()]
            ax.set_xticklabels(labs)
            for label in ax.xaxis.get_ticklabels():
                if not int(label.get_text()) % 10 == 0:
                    label.set_visible(False)
            f.subplots_adjust(bottom=0.2)
            ax.set_xlabel('Year')
            ax.set_ylabel('Coverage')
            plt.savefig("test/results/plot/mapped-signature-coverage.png", dpi=300)

            f, ax = plt.subplots()
            for version in versions:
                y = df[f"{version}_mapped_percent"].to_list()
                #r[version] = [_/baseline[i] for i, _ in enumerate(y)]
                x, y = zip(*sorted(zip(X,y),key=lambda x: x[0]))
                plt.plot(x, y, linewidth=1.75)
            plt.title('Coverage of mapped Signatures')
            plt.legend(versions, loc ="lower right")
            plt.xticks(rotation=90)
            labs = [_.get_text()[:4] for _ in ax.xaxis.get_ticklabels()]
            ax.set_xticklabels(labs)
            for label in ax.xaxis.get_ticklabels():
                if not int(label.get_text()) % 10 == 0:
                    label.set_visible(False)
            f.subplots_adjust(bottom=0.2)
            ax.set_xlabel('Year')
            ax.set_ylabel('Coverage')
            plt.savefig("test/results/plot/mapped-signature-coverage-ratio.png", dpi=300)
            return True

        not_mapped_cols = ["motion", "elem_id", "problem", "text"]
        df = pd.DataFrame(cls.not_mapped, columns=not_mapped_cols)
        df.to_csv("test/results/unmapped_signatures.tsv", sep="\t", index=False)
        df = pd.DataFrame(cls.counts_by_year.items(), columns=["parliament_year",f"{cls.version}_total"])
        df["parliament_year"] = df["parliament_year"].astype(str)
        df[f"{cls.version}_not_mapped"] = df["parliament_year"].apply(lambda x: cls.not_mapped_by_year[x] if x in cls.not_mapped_by_year else 0)
        df[f"{cls.version}_mapped"] = df.apply(lambda x: x[f"{cls.version}_total"]-x[f"{cls.version}_not_mapped"], axis=1)
        for col in df.columns:
            if col != "parliament_year" and not col.endswith("_percent"):
                df[col] = df[col].fillna(0).astype(int)
        df[f"{cls.version}_mapped_percent"] = df.apply(lambda x: x[f"{cls.version}_mapped"]/x[f"{cls.version}_total"], axis=1)

        if os.path.exists("test/results/unmapped_signatures_by_year.csv"):
            df_hist = pd.read_csv("test/results/unmapped_signatures_by_year.csv")
            print("found df_hist")
            df_hist["parliament_year"] = df_hist["parliament_year"].astype(str)
            for col in df_hist.columns:
                if col != "parliament_year":
                    if not col.endswith("_percent"):
                        df_hist[col] = df_hist[col].fillna(0).astype(int)
                    else:
                        df_hist[col] = df_hist[col].fillna(0).astype(float)
                if col.startswith(cls.version):
                    df_hist.drop([col], axis=1, inplace=True)
            df = pd.merge(df, df_hist, on="parliament_year", how="outer")
        for col in df.columns:
            if df[col].dtype == int:
                df[col] = df[col].fillna(0).astype(int)
            elif df[col].dtype == float:
                df[col] = df[col].fillna(0).astype(float)
        df.to_csv("test/results/unmapped_signatures_by_year.csv", index=False)

        if _generate_plots(df):
            print("Generated Plots for signature mapping")
            sys.exit(0)

    def test_signature_is_mapped(self):
        for motion in tqdm(self.motions):
            py = str(motion.split("/")[1])
            if py not in self.counts_by_year:
                self.counts_by_year[py] = 0
            if py not in self.not_mapped_by_year:
                self.not_mapped_by_year[py] = 0

            root, ns = parse_tei(motion)
            signatures = root.findall(f".//{ns['tei_ns']}item[@type=\"signature\"]")
            for signature in signatures:
                self.counts_by_year[py] += 1
                nm = False
                problem = None
                if "who" not in signature.attrib:
                    nm = True
                    problem = "no who"
                else:
                    if signature.attrib["who"] == "unknown":
                        nm = True
                        problem = "unknown"

                if nm:
                    self.not_mapped_by_year[py] += 1
                    self.not_mapped.append([motion,
                                            signature.attrib[f"{ns['xml_ns']}id"],
                                            problem,
                                            ' '.join([_.strip() for _ in signature.text.splitlines() if _.strip() != ""])])




if __name__ == '__main__':
    unittest.main()
