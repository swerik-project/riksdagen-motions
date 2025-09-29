#!/usr/bin/env python3

from cycler import cycler
from datetime import date
from Levenshtein import distance
from matplotlib.ticker import MaxNLocator
from pyriksdagen.io import parse_tei
from tqdm import tqdm
import matplotlib.pyplot as plt
import pandas as pd
import unicodedata
import unittest




class GoldStandard(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.objective_reality = pd.read_csv("quality/data/docdate-titles_seed+20250328141923.tsv", sep="\t")
        cls.objective_reality["motion"] = cls.objective_reality["motion"].apply(lambda x: x.split("main/")[1])
        cls.date_errors = []
        cls.dedf = pd.DataFrame()
        cls.signature_errors = []
        cls.title_errors = []
        cls.df_cols = ["motion","content", "problem"]
        cls.this_year = int(date.today().strftime("%Y"))

    @classmethod
    def tearDownClass(cls):

        def _plot(df, desc):
            print(df["problem"].value_counts())
            df["parliament_year"] = df["motion"].apply(lambda x: int(x.split('/')[1][:4]))
            result = (df.pivot_table(
                index="parliament_year",
                columns="problem",
                aggfunc="size",
                fill_value=0
                ).reset_index().rename_axis(None, axis=1))
            result = (result.set_index("parliament_year")
                      .reindex(range(1867, cls.this_year), fill_value=0)
                      .reset_index()
                      .rename(columns={"index":"parliament_year"}))
            result.to_csv(f"quality/estimates/{desc}-quality-by-year.csv")
            colors = list('bgrcmy')
            default_cycler = (cycler(color=colors) +
                            cycler(linestyle=(['-', '--', ':', '-.']*2)[:len(colors)]))
            plt.rc('axes', prop_cycle=default_cycler)
            f, ax = plt.subplots()
            r = []
            x = result.parliament_year.to_list()
            for c in result.columns.tolist():
                if c == "parliament_year":
                    continue
                r.append(c)
                y = result[c].tolist()
                plt.plot(x, y, linewidth=1.75)
            plt.title(f'{desc} quality problems')
            plt.legend(r, loc ="upper right")
            plt.xticks(rotation=90)
            labs = [_.get_text()[:4] for _ in ax.xaxis.get_ticklabels()]
            ax.set_xticklabels(labs)
            for label in ax.xaxis.get_ticklabels():
                if not int(label.get_text()) % 10 == 0:
                    label.set_visible(False)
            ax.yaxis.set_major_locator(MaxNLocator(integer=True))
            f.subplots_adjust(bottom=0.2)
            ax.set_xlabel('Year')
            ax.set_ylabel('Quality problems')
            plt.savefig(f"quality/estimates/plot/{desc}-problems.png", dpi=300)


        sedf = pd.DataFrame(cls.signature_errors, columns=cls.df_cols)
        tedf = pd.DataFrame(cls.title_errors, columns=cls.df_cols)
        descr = ["date", "signature", "title"]
        for i, df in enumerate([cls.dedf, sedf, tedf]):
            if not df.empty:
                df.to_csv(f"quality/estimates/{descr[i]}-quality.tsv", sep="\t", index=False)
                _plot(df, descr[i])


    def test_date(self):
        for i, r in tqdm(self.objective_reality.iterrows()):
            if int(r["motion"].split("/")[1][:4]) > 2004:
                continue
            if pd.isna(r["docdate"]):
                self.date_errors.append([r["motion"], None, "docdate is not annotated in goldstandard"])
            else:
                root,ns = parse_tei(r["motion"])
                date_elems = root.findall(f".//{ns['tei_ns']}p[@type=\"date\"]")
                found_gs = False
                for de in date_elems:
                    if r["docdate"] in de.text.strip():
                        found_gs = True
                if found_gs:
                    if len(date_elems) > 1:
                        self.date_errors.append([r["motion"], None, "goldstandard date found among multiple docdate elems"])
                else:
                    self.date_errors.append([r["motion"], r["docdate"], "goldstandard date not found"])
        type(self).dedf = pd.DataFrame(self.date_errors, columns=self.df_cols)
        self.assertEqual(len(self.dedf.loc[self.dedf["problem"]=="goldstandard date not found"]), 0)


    def test_signature(self):
        for i, r in tqdm(self.objective_reality.iterrows()):
            if pd.isna(r["signature_block"]):
                self.signature_errors.append([r["motion"], None, "signature block is not annotated in goldstandard"])
            else:
                root,ns = parse_tei(r["motion"])
                signature_block = root.find(f".//{ns['tei_ns']}div[@type=\"signatureBlock\"]")
                if signature_block is None:
                    self.signature_errors.append([r["motion"], None, "signature block not found"])
                else:
                    sb_text = ' '.join([_.strip() for _ in signature_block.itertext() if _.strip() != ''])
                    if sb_text !=  r["signature_block"]:
                        if sb_text not in r["signature_block"]:
                            elems_in = []
                            for elem in sb_text.split(' '):
                                if elem in r["signature_block"]:
                                    elems_in.append(True)
                                else:
                                    elems_in.append(False)
                            if not all(elems_in):
                                L = distance(sb_text, r["signature_block"])
                                if L > 10:
                                    self.signature_errors.append([r["motion"], f"{L} : {sb_text} ||| {r['signature_block']}", "annotated signature block does not match goldstandard"])
        self.assertEqual(len(self.signature_errors), 0)


    def test_title(self):
        for i, r in tqdm(self.objective_reality.iterrows()):
            if pd.isna(r["title_block"]):
                self.title_errors.append([r["motion"], None, "title block is not annotated in goldstandard"])
            else:
                root,ns = parse_tei(r["motion"])
                title_block = root.find(f".//{ns['tei_ns']}div[@type=\"motTitle\"]")
                if title_block is None:
                    self.title_errors.append([r["motion"], None, "title block not found"])
                else:
                    tb_text = ' '.join([_.strip() for _ in title_block.itertext() if _.strip() != ''])
                    if tb_text != r["title_block"]:
                        self.title_errors.append([r["motion"], f"{tb_text} ||| {r['title_block']}", "annotated title block does not match goldstandard"])
        self.assertEqual(len(self.title_errors), 0)



if __name__ == '__main__':
    unittest.main()
