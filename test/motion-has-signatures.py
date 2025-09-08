#!/usr/bin/env python3
"""
Check each motion has a signature block.
"""
from cycler import cycler
from glob import glob
import matplotlib.pyplot as plt
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import version_number_is_valid
from tqdm import tqdm
import json
import os
import pandas as pd
import sys
import unittest
import warnings




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
        cls.tally = {
                "no_signature": 0,
                "meta_signature_only": 0,
                "body_signature_only": 0,
                "meta_body_signature": 0
            }
        cls.no_signature  = []
        cls.year_counts = {}
        cls.no_signature_counts = {}


    @classmethod
    def tearDownClass(cls):

        def update_plot_signature_coverage(df):
            versions = list(set([v.split('_')[0] for v in df.columns if v.startswith('v')]))
            if cls.version != "v99.99.99" and "v99.99.99" in versions:
                versions.remove("v99.99.99")
            versions = sorted(versions, key=lambda s: list(map(int, s[1:].split('.'))), reverse=True)
            colors = list('kbgrcmy')
            default_cycler = (cycler(color=colors) +
                            cycler(linestyle=(['-', '--', ':', '-.']*2)[:len(colors)]))
            plt.rc('axes', prop_cycle=default_cycler)
            f, ax = plt.subplots()
            r = {}
            X = df['parliament_year'].tolist()
            baseline = df[f"{cls.version}_Baseline"].tolist()
            x, baseline = zip(*sorted(zip(X,baseline),key=lambda x: x[0]))
            plt.plot(x, baseline, linewidth=1.75)
            for version in versions:
                y = df[f"{version}_HaveSignature"].to_list()
                r[version] = [_/baseline[i] for i, _ in enumerate(y)]
                x, y = zip(*sorted(zip(X,y),key=lambda x: x[0]))
                plt.plot(x, y, linewidth=1.75)
            plt.title('Coverage of annotated Signatures')
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
            plt.savefig("test/results/plot/signature-coverage.png", dpi=300)

            f, ax = plt.subplots()
            for k, v in r.items():
                x, y = zip(*sorted(zip(X, v),key=lambda x: x[0]))
                plt.plot(x, y, linewidth=1.75)
            plt.title('Coverage of annotated Signatures')
            plt.legend(list(r.keys()), loc ="lower right")
            plt.xticks(rotation=90)
            labs = [_.get_text()[:4] for _ in ax.xaxis.get_ticklabels()]
            ax.set_xticklabels(labs)
            for label in ax.xaxis.get_ticklabels():
                if not int(label.get_text()) % 10 == 0:
                    label.set_visible(False)
            f.subplots_adjust(bottom=0.2)
            ax.set_xlabel('Year')
            ax.set_ylabel('Coverage')
            plt.savefig("test/results/plot/signature-coverage-ratio.png", dpi=300)

            return True


        with open("test/results/motion-has-signature-summary.json", "w+") as outf1:
            json.dump(cls.tally, outf1, indent=4)
        with open("test/results/motion-has-no-signature.txt", "w+") as outf2:
            [outf2.write(f"{_}\n") for _ in sorted(cls.no_signature)]
        df = pd.DataFrame(list(cls.year_counts.items()), columns=["parliament_year", f"{cls.version}_Baseline"])
        df[f"{cls.version}_MissingSignature"] = df["parliament_year"].map(cls.no_signature_counts).fillna(0)
        df[f"{cls.version}_HaveSignature"] = df[f"{cls.version}_Baseline"] - df[f"{cls.version}_MissingSignature"]
        for column in [f"{cls.version}_HaveSignature", f"{cls.version}_MissingSignature", "parliament_year"]:
            df[column] = df[column].fillna(0).astype(int)
        if os.path.exists("test/results/signature-test-by-parliament-year.tsv"):
            df_hist = pd.read_csv("test/results/signature-test-by-parliament-year.tsv", sep="\t")
            print("found df_hist")
            for _ in df_hist.columns:
                df_hist[_] = df_hist[_].fillna(0).astype(int)
                if _.startswith(cls.version):
                    df_hist.drop([_], axis=1, inplace=True)
            df = pd.merge(df, df_hist, on="parliament_year", how="outer")
        for _ in df.columns:
            df[_] = df[_].fillna(0).astype(int)
        df["parliament_year"] = df["parliament_year"].astype(str)
        df.to_csv("test/results/signature-test-by-parliament-year.tsv", index=False, sep="\t")

        if update_plot_signature_coverage(df):
            print("Generated Plot for signature coverage")
            sys.exit(0)


    def test_motion_has_signature(self):
        for motion in tqdm(self.motions):
            py = motion.split("/")[1]
            root, ns = parse_tei(motion)
            meta_title = root.find(f".//{ns['tei_ns']}bibl/{ns['tei_ns']}title")
            if meta_title is not None and meta_title.text == "Motionen utgår.":
                continue
            if py not in self.year_counts:
                self.year_counts[py] = 0
            if py not in self.no_signature_counts:
                self.no_signature_counts[py] = 0
            self.year_counts[py] += 1
            has_metaS = False
            has_bodyS = False
            try:
                meta_signatures = root.findall(f".//{ns['tei_ns']}particDesc/{ns['tei_ns']}listPerson")
                assert len(meta_signatures) > 0
            except:
                meta_signatures = root.findall(f".//paricDesc/listPerson")

            for _ in meta_signatures:
                if len(_) > 0:
                    has_metaS = True
            try:
                body_signatures = root.findall(f".//{ns['tei_ns']}p[@type=\"signatureBlock\"]")
                # print(body_signatures)
                body_signatures.extend(root.findall(f".//{ns['tei_ns']}div[@type=\"motSignatures\"]"))
                # print(body_signatures, len(body_signatures))
                assert len(body_signatures) > 0
            except:
                body_signatures = root.findall(f".//p[@type=\"signatureBlock\"]")
                body_signatures.extend(root.findall(f".//div[@type=\"motSignatures\"]"))

            for _ in body_signatures:
                if _.text is not None and len(_.text) > 0:
                    has_bodyS = True

            if has_bodyS and has_metaS:
                self.tally["meta_body_signature"] += 1
            elif has_bodyS:
                self.tally["body_signature_only"] += 1
            elif has_metaS:
                self.tally["meta_signature_only"] += 1
            else:
                self.tally["no_signature"] += 1
                self.no_signature.append(motion)
                self.no_signature_counts[py] += 1




if __name__ == '__main__':
    unittest.main()
