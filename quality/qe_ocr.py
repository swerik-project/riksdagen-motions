#!/usr/bin/env python3

from pyriksdagen.io import (
    parse_tei,
)
from torchmetrics.text import WordErrorRate
from tqdm import tqdm
import nltk
import pandas as pd
import unittest

class OCRQualityEstimation(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.objective_reality = pd.read_csv("quality/data/qe_OCR-line-sample.tsv", sep="\t")
        cls.most_probable_lines = pd.DataFrame()
        cls.match_errors = []
        cls.wer_fn = WordErrorRate()
        cls.file_mapping = {
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198586/mot_198586_ju_00623/mot_198586_ju_00623_001.pdf": "data/198586/mot-198586-JuU-00623.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198586/mot_198586_sk_00565/mot_198586_sk_00565_001.pdf": "data/198586/mot-198586-SkU-00565.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198687/mot_198687_k_00112/mot_198687_k_00112_001.pdf": "data/198687/mot-198687-KU-00112.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198687/mot_198687_kr_00107/mot_198687_kr_00107_001.pdf": "data/198687/mot-198687-KrU-00107.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198687/mot_198687_sk_00128/mot_198687_sk_00128_002.pdf": "data/198687/mot-198687-sku-00128.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198788/mot_198788_a_00608/mot_198788_a_00608_001.pdf": "data/198788/mot-198788-AU-00608.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198788/mot_198788_jo_00301/mot_198788_jo_00301_008.pdf": "data/198788/mot-198788-JoU-00301.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198788/mot_198788_so_00614/mot_198788_so_00614_001.pdf": "data/198788/mot-198788-SoU-00614.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198889/mot_198889_jo_00603/mot_198889_jo_00603_004.pdf": "data/198889/mot-198889-JoU-00603.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198889/mot_198889_k_00220/mot_198889_k_00220_004.pdf": "data/198889/mot-198889-KU-00220.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198889/mot_198889_t_00215/mot_198889_t_00215_006.pdf": "data/198889/mot-198889-TU-00215.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198990/mot_198990_bo_00033/mot_198990_bo_00033_005.pdf": "data/198990/mot-198990-BoU-00033.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198990/mot_198990_k_00625/mot_198990_k_00625_002.pdf": "data/198990/mot-198990-KU-00625.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/198990/mot_198990_l_00017/mot_198990_l_00017_002.pdf": "data/198990/mot-198990-LU-00017.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199091/mot_199091_JuU_00028/mot_199091_JuU_00028_001.pdf": "data/199091/mot-199091-JuU-00028.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199091/mot_199091_KrU_00309/mot_199091_KrU_00309_002.pdf": "data/199091/mot-199091-KrU-00309.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199091/mot_199091_KrU_00519/mot_199091_KrU_00519_008.pdf": "data/199091/mot-199091-KrU-00519.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199192/mot_199192_FiU_00015/mot_199192_FiU_00015_010.pdf": "data/199192/mot-199192-FiU-00015.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199192/mot_199192_KU_00315/mot_199192_KU_00315_001.pdf": "data/199192/mot-199192-KU-00315.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199192/mot_199192_UU_00313/mot_199192_UU_00313_001.pdf": "data/199192/mot-199192-UU-00313.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199394/mot_199394_AU_00701/mot_199394_AU_00701_001.pdf": "data/199192/mot-199192-UU-00313.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199394/mot_199394_BoU_00245/mot_199394_BoU_00245_002.pdf": "data/199394/mot-199394-BoU-00245.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199394/mot_199394_UbU_00691/mot_199394_UbU_00691_002.pdf": "data/199394/mot-199394-UbU-00691.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199495/mot_199495_FiU_00032/mot_199495_FiU_00032_027.pdf": "data/199495/mot-199495-FiU-00032.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199495/mot_199495_FöU_00202/mot_199495_FöU_00202_009.pdf": "data/199495/mot-199495-FöU-00202.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199495/mot_199495_JoU_00048/mot_199495_JoU_00048_002.pdf": "data/199495/mot-199495-JoU-00048.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199596/mot_199596_A_00033/mot_199596_A_00033_001.pdf": "data/199495/mot-199495-JoU-00048.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199596/mot_199596_FI_00017/mot_199596_FI_00017_018.pdf": "data/199596/mot-199596-FiU-00017.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199596/mot_199596_FI_00102/mot_199596_FI_00102_002.pdf": "data/199596/mot-199596-FiU-00017.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199697/mot_199697_A_00049/mot_199697_A_00049_002.pdf": "data/199596/mot-199596-FiU-00017.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199697/mot_199697_A_00421/mot_199697_A_00421_003.pdf": "data/199697/mot-199697-AU-00421.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199697/mot_199697_A_00814/mot_199697_A_00814_001.pdf": "data/199697/mot-199697-AU-00814.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199798/mot_199798_A_00020/mot_199798_A_00020_018.pdf": "data/199697/mot-199697-AU-00814.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199798/mot_199798_A_00272/mot_199798_A_00272_001.pdf": "data/199798/mot-199798-AU-00272.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199798/mot_199798_A_00460/mot_199798_A_00460_049.pdf": "data/199798/mot-199798-AU-00460.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199899/mot_199899_A_00601/mot_199899_A_00601_004.pdf": "data/199899/mot-199899-AU-00601.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199899/mot_199899_A_00701/mot_199899_A_00701_002.pdf": "data/199899/mot-199899-AU-00701.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199899/mot_199899_Bo_00237/mot_199899_Bo_00237_012.pdf": "data/199899/mot-199899-BoU-00237.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199900/mot_199900_A_00025/mot_199900_A_00025_002.pdf": "data/19992000/mot-19992000-AU-00025.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199900/mot_199900_Bo_00221/mot_199900_Bo_00221_001.pdf": "data/19992000/mot-19992000-BoU-00221.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/199900/mot_199900_Bo_00231/mot_199900_Bo_00231_011.pdf": "data/19992000/mot-19992000-BoU-00231.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200001/mot_200001_A_00007/mot_200001_A_00007_002.pdf": "data/200001/mot-200001-AU-00007.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200001/mot_200001_A_00243/mot_200001_A_00243_002.pdf": "data/200001/mot-200001-AU-00243.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200001/mot_200001_Bo_00215/mot_200001_Bo_00215_002.pdf": "data/200001/mot-200001-BoU-00215.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200102/mot_200102_A_00315/mot_200102_A_00315_004.pdf": "data/200001/mot-200001-BoU-00215.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200102/mot_200102_A_00390/mot_200102_A_00390_005.pdf": "data/200102/mot-200102-AU-00390.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200102/mot_200102_Bo_00211/mot_200102_Bo_00211_003.pdf": "data/200102/mot-200102-BoU-00211.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200203/mot_200203_A_00215/mot_200203_A_00215_004.pdf": "data/200102/mot-200102-BoU-00211.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200203/mot_200203_A_00270/mot_200203_A_00270_003.pdf": "data/200203/mot-200203-AU-00270.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200203/mot_200203_A_00324/mot_200203_A_00324_007.pdf": "data/200203/mot-200203-AU-00324.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200405/mot_200405_A_00215/mot_200405_A_00215_002.pdf": "data/200405/mot-200405-AU-00215.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200405/mot_200405_A_00332/mot_200405_A_00332_001.pdf": "data/200405/mot-200405-AU-00332.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200405/mot_200405_A_00338/mot_200405_A_00338_006.pdf": "data/200405/mot-200405-AU-00338.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200506/mot_200506_A_00217/mot_200506_A_00217_002.pdf": "data/200405/mot-200405-AU-00338.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200506/mot_200506_A_00420/mot_200506_A_00420_003.pdf": "data/200506/mot-200506-AU-00420.xml",
            "https://pdf.swedeb.se/riksdagen-motions-pdf/200506/mot_200506_A_00420/mot_200506_A_00420_025.pdf": "data/200506/mot-200506-AU-00420.xml",
            }

    @classmethod
    def tearDownClass(cls):
        cls.most_probable_lines.to_csv("quality/estimates/ocr-estimate.tsv", index=False, sep="\t")
        err_df = pd.DataFrame(cls.match_errors, columns=["pdf", "xml", "annotation"])
        err_df.to_csv("quality/estimates/ocr-estimate-mismatched-annotations.tsv", index=False, sep="\t")


    def test_estimate_ocr_quality(self):

        def _text_from_range(root, ns, facs):
            text = ""
            start_pb = root.xpath(f".//tei:pb[contains(@facs, '{facs}')]", namespaces={"tei": ns["tei_ns"][1:-1]})
            if len(start_pb) != 1 :
                for e in root.find(f".//{ns['tei_ns']}body").iter():
                    if e.text is not None:
                        text += f" {' '.join([_.strip() for _ in e.text.splitlines() if _.strip() != ''])}"
            else:
                start_pb = start_pb[0]
                start = False
                for e in root.iter():
                    if start and e.tag.endswith("}pb"):
                        start = False
                        break
                    if e == start_pb:
                        start = True
                    if start:
                        if e.text is not None:
                            text += f" {' '.join([_.strip() for _ in e.text.splitlines() if _.strip() != ''])}"
            return text

        def _mk_string_list(l, text):
            """
            make a list of strings of len == len(annotation)
            """
            str_list = []
            start = 0
            while True:
                str_list.append(text[start:start+l+1])
                start += 1
                if start + l + 1 == len(text):
                    break
            return str_list

        def _get_most_probable_line(annotation, text):
            most_probable_line = None
            prob = None
            l = len(annotation)

            for start in range(0, len(text) - l):
                s = text[start:start + l + 1]
                lev = nltk.edit_distance(annotation.lower().strip(), s.lower().strip())

                if prob is None or lev < prob:
                    prob = lev
                    most_probable_line = s
                    # early exit conditions
                    if prob == 0:
                        break
                    if prob == 1 and annotation.endswith('-') and not s.endswith('-'):
                        break
            return most_probable_line, prob

        rows = []
        cols = [
            "motion",
            "parliament_year",
            "chamber",
            "annotation",
            "most_probable_line",
            "lev",
            "wer",
            "cer"
        ]
        print(self.file_mapping)
        for motion in tqdm([_ for _ in self.objective_reality["file"].unique() if "reg" not in _ and "fört" not in _]):
            facs = motion.split("/")[-1].replace("-", "_").split('_')[-1]
            if motion in self.file_mapping:
                xml_file = self.file_mapping[motion]
                print(motion, "in")
            else:
                print(motion, "not in")
                xml_file = f"data/{'/'.join(motion.split('riksdagen-motions-pdf/')[1].split('/')[:-1]).replace('_', '-')}.xml"
            annotations = [_ for _ in self.objective_reality.loc[self.objective_reality["file"] == motion, "text"].tolist() if pd.notnull(_)]
            py = self.objective_reality.loc[self.objective_reality["file"] == motion, "parliament_year"].unique().tolist()[0]
            chamber = self.objective_reality.loc[self.objective_reality["file"] == motion, "chamber"].unique().tolist()[0]
            root, ns = parse_tei(xml_file)
            candidate_text = _text_from_range(root, ns, facs)

            for annotation in annotations:
                if annotation is None:
                    continue
                most_probable_line, lev = _get_most_probable_line(annotation, candidate_text)
                if most_probable_line is None:
                    self.match_errors.append([motion, xml_file, annotation])
                    continue
                wer = float(self.wer_fn(annotation, most_probable_line))
                cer = lev/len(annotation)
                rows.append([
                    xml_file,
                    py,
                    chamber,
                    annotation,
                    most_probable_line,
                    lev,
                    wer,
                    cer
                ])
                print(xml_file, lev, wer, cer)
        type(self).most_probable_lines = pd.DataFrame(rows, columns = cols)




if __name__ == '__main__':
    unittest.main()
