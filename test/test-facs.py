# tests/test_pdf_redirects.py
"""
Test all pg elem facs attrib urls redirect to a pdf.
"""
from glob import glob
from pyriksdagen.io import parse_tei
from pathlib import Path
from tqdm import tqdm
from trainerlog import get_logger
from urllib.parse import urljoin

import pandas as pd
import re
import requests
import unittest



LOGGER = get_logger("url test")
FAILURE_LOG = Path("test/results/pdf_redirect_failures.tsv")


REDIRECT_PATTERNS = [
    re.compile(r'window\.location(?:\.href)?\s*=\s*[\'"]([^\'"]+)[\'"]'),
    re.compile(r'location\.href\s*=\s*[\'"]([^\'"]+)[\'"]'),
    re.compile(r'location\.replace\([\'"]([^\'"]+)[\'"]\)'),
    re.compile(
        r'<meta[^>]+http-equiv=["\']refresh["\'][^>]+url=([^"\'>]+)',
        re.I,
    ),
]



def extract_redirect_target(html: str, base_url: str) -> str | None:
    for pattern in REDIRECT_PATTERNS:
        match = pattern.search(html)

        if match:
            return urljoin(base_url, match.group(1).strip())

    return None


def check_pdf_redirect(source_url: str,
                        session: requests.Session,
                        ) -> tuple[bool, str, str | None]:
    try:
        # 1. Fetch redirect page
        r = session.get(source_url, timeout=15)

        if r.status_code != 200:
            return (
                False,
                f"source returned HTTP {r.status_code}",
                None,
            )

        # 2. Extract JS/meta redirect
        target_url = extract_redirect_target(r.text, source_url)

        if not target_url:
            return (
                False,
                "no JS/meta redirect target found",
                None,
            )

        # 3. Probe PDF without downloading whole file
        p = session.get(
            target_url,
            headers={"Range": "bytes=0-4"},
            stream=True,
            timeout=20,
        )

        if p.status_code not in {200, 206}:
            return (
                False,
                f"target returned HTTP {p.status_code}",
                target_url,
            )

        first_bytes = next(p.iter_content(chunk_size=5), b"")

        if first_bytes != b"%PDF-":
            return (
                False,
                f"target does not start with %PDF-: {first_bytes!r}",
                target_url,
            )

        return (
            True,
            "ok",
            target_url,
        )

    except requests.RequestException as e:
        return (
            False,
            f"{type(e).__name__}: {e}",
            None,
        )





class TestPdfRedirects(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        def fetch_urls():
            LOGGER.info("Loading URL data.")
            motions = sorted(glob("data/*/*.xml"))
            motions = [m for m in motions if "reg" not in m]
            motions = [m for m in motions if "fort" not in m]
            for motion in tqdm(motions):
                root, ns = parse_tei(motion)
                pbs = root.findall(f".//{ns['tei_ns']}pb")
                for pb in pbs:
                    if "facs" in pb.attrib:
                        url = pb.attrib["facs"]
                        cls.urls.append((motion, url))
                    else:
                        LOGGER.warning(f"pb w/o facs attrib in {motion}")
                        cls.failures.append([motion, None, None, "pb w/o facs attrib"])

        cls.session = requests.Session()
        cls.session.headers.update({
            "User-Agent": "pdf-redirect-test/1.0"
        })
        cls.urls = []
        fetch_urls()
        cls.failures = []

    @classmethod
    def tearDownClass(cls):
        failuredf = pd.DataFrame(cls.failures, columns=["motion", "src_url", "tgt_url", "Failure_type"], index=False)
        failuredf.to_csv(FAILURE_LOG, sep='\t')
        cls.session.close()






    def test_pdf_redirects(self):
        LOGGER.info(f"Testing {len(self.urls)} URLs")
        for motion, source_url in tqdm(self.urls):

            ok, message, target_url = check_pdf_redirect(source_url,
                                                         self.session,)

            if not ok:
                LOGGER.warning(f"{source_url}, {target_url}, {message}")
                self.failures.append([motion,
                                      source_url,
                                      target_url,
                                      message,])

        self.assertEqual(len(self.failures), 0,
            (f"{len(self.failures)} failures found. "
            f"See {FAILURE_LOG}"),)




if __name__ == "__main__":
    unittest.main()
