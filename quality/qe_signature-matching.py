#!/usr/bin/env python3
"""
Estimate motion signature matching quality against manually annotated signees.

The estimator compares the gold-standard IDs in
``quality/data/qe_motion_id_signee.csv`` with ``who`` IDs on
``item type="signature"`` elements. It writes records-style versioned yearly
estimates plus diagnostic TSVs for missed and extra signatures.
"""
import argparse, json, os, re, sys
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/riksdagen-motions-mpl")

import matplotlib.pyplot as plt
import pandas as pd
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import get_data_location, infer_metadata
from scipy.stats import beta
from trainerlog import get_logger

LOGGER = get_logger(name="qe-signature-matching")
COL = "SWERIK_ID_MPs_signee"
ID = re.compile(r"^i-[A-Za-z0-9]+$")


def root(): return Path(__file__).resolve().parents[1]
def p(path): return path if (path := Path(path).expanduser()).is_absolute() else root() / path
def split(v): return [] if v is None or pd.isna(v) else [x.strip() for x in str(v).replace(";", " ").split() if x.strip()]
def join(v): return "; ".join(sorted(v))
def div(a, b): return a / b if b else 0.0
def f1(pr, rc): return div(2 * pr * rc, pr + rc)
def first_year(v): return int(m.group(0)) if (m := re.search(r"\d{4}", str(v))) else 0
def py(path): return str((m := infer_metadata(path)).get("sitting") or m.get("year") or "")
def ids_with_names(ids, names): return "; ".join(f"{pid} ({names[pid]})" if pid in names else pid for pid in split(ids))


def version_number_is_valid(v):
    v = v or "v99.99.99"
    if v == "v99.99.99" or re.fullmatch(r"v\d+\.\d+\.\d+(?:b|rc\d+)?", v): return v
    sys.exit(f"{v} is not a valid version number. Exiting.")


def version_key(v):
    return [999, 999, 999] if v == "v99.99.99" else [int(x) for x in re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:b|rc\d+)?", str(v)).groups()]


def default_person_data():
    candidates = [root().parent / "riksdagen-persons" / "data"]
    if os.environ.get("METADATA_PATH"): candidates.insert(0, Path(get_data_location("metadata")))
    for path in candidates:
        if (path / "person.csv").exists(): return path.resolve()
    raise FileNotFoundError("Could not find riksdagen-persons/data/person.csv")


def motion_path(motion):
    motion = str(motion).strip()
    for marker in ("/blob/main/", "/blob/dev/"):
        if marker in motion: return motion.split(marker, 1)[1]
    return "data/" + motion.split("/data/", 1)[1] if "/data/" in motion else motion


def person_tables(person_data):
    persons = set(pd.read_csv(person_data / "person.csv", dtype=str)["person_id"].dropna())
    names = pd.read_csv(person_data / "name.csv", dtype=str).fillna("")
    primary = names[names["primary_name"].str.casefold().eq("true")]
    return persons, primary.drop_duplicates("person_id").set_index("person_id")["name"].to_dict()


def gold_problems(sample, person_ids):
    rows = []
    for i, r in sample.iterrows():
        path = motion_path(r["motion"])
        for j, entry in enumerate(split(r[COL]) or [""], start=1):
            problem = "blank-signee-cell" if entry == "" else "not-a-swerik-id" if not ID.fullmatch(entry) else "id-not-in-person-database" if entry not in person_ids else None
            if problem: rows.append(dict(problem=problem, csv_row=i + 2, parliament_year=py(path), motion_path=path, entry_number=j, signee_entry=entry, motion=r["motion"], raw_signee_cell=r[COL]))
    return pd.DataFrame(rows)


def parse_refs(refs):
    ids, bad, unknown = set(), set(), 0
    for ref in refs:
        if ref in {"unknown", "#unknown"} or ref.startswith("r-"): unknown += 1; continue
        ref = ref[1:] if ref.startswith("#") else ref
        ids.add(ref) if ID.fullmatch(ref) else bad.add(ref)
    return ids, unknown, bad


def xml_signees(path):
    out = dict(body_ids=set(), metadata_ids=set(), unknown_signature_count=0, missing_who_count=0, non_swerik_who_values=set(), metadata_placeholder_count=0, metadata_non_swerik_values=set(), signature_item_count=0, xml_read_error="")
    try:
        tei_root, ns = parse_tei(str(path))
    except Exception as err:
        out["xml_read_error"] = repr(err); return out
    tei, body_refs, metadata_refs = ns["tei_ns"], [], []
    signatures = tei_root.findall(f".//{tei}item[@type=\"signature\"]")
    for item in signatures:
        refs = split(item.get("who")); out["missing_who_count"] += int(not refs); body_refs.extend(refs)
    for idno in tei_root.findall(f".//{tei}particDesc/{tei}listPerson/{tei}person/{tei}idno"): metadata_refs.extend(split(idno.text))
    out["signature_item_count"], out["body_ids"], out["unknown_signature_count"], out["non_swerik_who_values"] = len(signatures), *parse_refs(body_refs)
    out["metadata_ids"], out["metadata_placeholder_count"], out["metadata_non_swerik_values"] = parse_refs(metadata_refs)
    return out


def comparison_rows(sample, source):
    rows = []
    for i, r in sample.iterrows():
        path, gold = motion_path(r["motion"]), {x for x in split(r[COL]) if ID.fullmatch(x)}
        x = xml_signees(root() / path)
        pred = {"metadata": x["metadata_ids"], "union": x["body_ids"] | x["metadata_ids"]}.get(source, x["body_ids"])
        tp, fp, fn = gold & pred, pred - gold, gold - pred
        pr, rc = div(len(tp), len(tp) + len(fp)), div(len(tp), len(tp) + len(fn))
        rows.append(dict(csv_row=i + 2, parliament_year=py(path), motion_path=path, exact_match=gold == pred, precision=pr, recall=rc, f1=f1(pr, rc), true_positives=len(tp), false_positives=len(fp), false_negatives=len(fn), gold_signee_count=len(gold), xml_predicted_signee_count=len(pred), miss_rate=div(len(fn), len(gold)), coverage=rc, extra_rate=div(len(fp), len(pred)), gold_ids=join(gold), xml_predicted_ids=join(pred), true_positive_ids=join(tp), false_positive_ids=join(fp), false_negative_ids=join(fn), xml_body_ids=join(x["body_ids"]), xml_metadata_ids=join(x["metadata_ids"]), body_metadata_agree=x["body_ids"] == x["metadata_ids"], signature_item_count=x["signature_item_count"], unknown_signature_count=x["unknown_signature_count"], missing_who_count=x["missing_who_count"], non_swerik_who_values=join(x["non_swerik_who_values"]), metadata_placeholder_count=x["metadata_placeholder_count"], metadata_non_swerik_values=join(x["metadata_non_swerik_values"]), xml_read_error=x["xml_read_error"], motion=r["motion"]))
    return pd.DataFrame(rows)


def metrics(df, source):
    sumcols = ["true_positives", "false_positives", "false_negatives", "gold_signee_count", "xml_predicted_signee_count", "unknown_signature_count", "missing_who_count", "signature_item_count"]
    sums, tp, fp, fn = {c: int(df[c].sum()) for c in sumcols}, df["true_positives"].sum(), df["false_positives"].sum(), df["false_negatives"].sum()
    pr, rc = div(tp, tp + fp), div(tp, tp + fn)
    return dict(prediction_source=source, exact_match=df["exact_match"].mean(), precision=pr, recall=rc, f1=f1(pr, rc), macro_precision=df["precision"].mean(), macro_recall=df["recall"].mean(), macro_f1=df["f1"].mean(), mean_miss_rate=df["miss_rate"].mean(), mean_extra_rate=df["extra_rate"].mean(), motions_with_missed_signees=int((df["false_negatives"] > 0).sum()), motions_with_extra_signees=int((df["false_positives"] > 0).sum()), motions_with_full_miss=int(((df["false_negatives"] > 0) & (df["true_positives"] == 0)).sum()), motions_with_partial_miss=int(((df["false_negatives"] > 0) & (df["true_positives"] > 0)).sum()), motions_with_no_xml_prediction=int(((df["false_negatives"] > 0) & (df["xml_predicted_ids"] == "")).sum()), exact_matches=int(df["exact_match"].sum()), xml_read_errors=int(df["xml_read_error"].astype(bool).sum()), body_metadata_disagreements=int((~df["body_metadata_agree"]).sum()), non_swerik_who_values=int(df["non_swerik_who_values"].astype(bool).sum()), gold_positive_ids=sums.pop("gold_signee_count"), predicted_positive_ids=sums.pop("xml_predicted_signee_count"), **sums)


def yearly(df, version):
    yearly = df.assign(year=df["parliament_year"].apply(first_year)).query("year > 0").groupby("year").agg(motions=("motion_path", "count"), exact_matches=("exact_match", "sum"), true_positives=("true_positives", "sum"), false_positives=("false_positives", "sum"), false_negatives=("false_negatives", "sum"), gold_positive_ids=("gold_signee_count", "sum"), predicted_positive_ids=("xml_predicted_signee_count", "sum"), macro_precision=("precision", "mean"), macro_recall=("recall", "mean"), macro_f1=("f1", "mean"), mean_miss_rate=("miss_rate", "mean"), mean_extra_rate=("extra_rate", "mean")).reset_index()
    yearly["precision"] = yearly.apply(lambda r: div(r.true_positives, r.true_positives + r.false_positives), axis=1)
    yearly["recall"] = yearly.apply(lambda r: div(r.true_positives, r.true_positives + r.false_negatives), axis=1)
    yearly["f1"] = yearly.apply(lambda r: f1(r.precision, r.recall), axis=1)
    yearly["exact_match"] = yearly["exact_matches"] / yearly["motions"]
    yearly["exact_match_lower"] = yearly.apply(lambda r: beta.ppf(0.05, r.exact_matches + 1, r.motions - r.exact_matches + 1), axis=1)
    yearly["exact_match_upper"] = yearly.apply(lambda r: beta.ppf(0.95, r.exact_matches + 1, r.motions - r.exact_matches + 1), axis=1)
    yearly.insert(0, "version", version)
    return yearly.sort_values("year")


def update_difference(upper, estimate_path, version):
    path = estimate_path / "difference.csv"
    if path.exists():
        old = pd.read_csv(path)
        if version == "v99.99.99": old = old[old["version"] != "v99.99.99"]
        elif version in set(old["version"]): print(f"Version {version} already exists in {path}, skipping append."); return old
        upper = pd.concat([old, upper], ignore_index=True)
    upper.to_csv(path, index=False)
    return upper


def plot_versions(df, estimate_path, show):
    versions = sorted([v for v in df["version"].unique() if "rc" not in str(v).lower()], key=version_key, reverse=True)[:6]
    for metric in ["f1", "precision", "recall", "exact_match"]:
        fig, ax = plt.subplots(figsize=(12, 6))
        for i, version in enumerate(versions):
            d = df[df["version"] == version].sort_values("year")
            ax.plot(d["year"], d[metric], linewidth=1.75, label=version, color=list("bgrcmyk")[i % 7])
        ax.set(title=f"signature-matching-{metric.replace('_', '-')}", xlabel="Beginning of parliamentary year", ylabel=metric, ylim=(0, 1)); ax.legend(loc="upper left")
        fig.tight_layout(); fig.savefig(estimate_path / f"signature-matching-{metric.replace('_', '-')}.png")
        if show: fig.show()
        plt.close(fig)


def write_outputs(df, problems, upper, summary, estimate_path, primary_names):
    upper.to_csv(estimate_path / "upper_bound.csv", index=False); df.to_csv(estimate_path / "motion-comparison.tsv", sep="\t", index=False); problems.to_csv(estimate_path / "person-id-problems.tsv", sep="\t", index=False)
    (estimate_path / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    metric = summary["matching_quality"]
    named = df.assign(false_negative_names=df["false_negative_ids"].apply(lambda v: ids_with_names(v, primary_names)), false_positive_names=df["false_positive_ids"].apply(lambda v: ids_with_names(v, primary_names)))
    missed_cols = ["motion_path", "parliament_year", "false_negatives", "gold_signee_count", "miss_rate", "coverage", "true_positives", "false_positives", "unknown_signature_count", "signature_item_count", "false_negative_ids", "false_negative_names", "xml_predicted_ids", "motion"]
    extra_cols = ["motion_path", "parliament_year", "false_positives", "xml_predicted_signee_count", "extra_rate", "precision", "true_positives", "false_negatives", "unknown_signature_count", "signature_item_count", "false_positive_ids", "false_positive_names", "gold_ids", "motion"]
    named[named["false_negatives"] > 0][missed_cols].sort_values(["miss_rate", "gold_signee_count", "motion_path"], ascending=[False, False, True]).to_csv(estimate_path / "missed-signatures.tsv", sep="\t", index=False)
    named[named["false_positives"] > 0][extra_cols].sort_values(["extra_rate", "xml_predicted_signee_count", "motion_path"], ascending=[False, False, True]).to_csv(estimate_path / "extra-signatures.tsv", sep="\t", index=False)
    print("Upper bound signature-matching summary:"); print(upper)
    for name in ["precision", "recall", "f1", "exact_match"]: print(f"Average signature-matching {name}:", upper[name].mean())
    for name in ["precision", "recall", "f1", "exact_match"]: print(f"Weighted average signature-matching {name}:", metric[name])
    print("Minimum signature-matching:", upper.loc[upper["f1"].idxmin(), "f1"], "at year:", upper.loc[upper["f1"].idxmin(), "year"]); print("Resources cleaned up.")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-d", "--annotated-data", default="quality/data/qe_motion_id_signee.csv"); parser.add_argument("-o", "--estimate-path", default="quality/estimates/signature-matching"); parser.add_argument("-v", "--version", default="v99.99.99")
    parser.add_argument("--person-data", default=None); parser.add_argument("--prediction-source", choices=["body", "metadata", "union"], default="body"); parser.add_argument("--show", default="False"); parser.add_argument("--fail-on-problems", action="store_true")
    return parser.parse_args()


def main():
    args, version = parse_args(), None
    version = version_number_is_valid(args.version); estimate_path = p(args.estimate_path); estimate_path.mkdir(parents=True, exist_ok=True)
    sample = pd.read_csv(p(args.annotated_data), dtype=str).fillna("")
    person_ids, primary_names = person_tables(p(args.person_data) if args.person_data else default_person_data())
    problems, df = gold_problems(sample, person_ids), comparison_rows(sample, args.prediction_source)
    metric, upper = metrics(df, args.prediction_source), yearly(df, version)
    plot_versions(update_difference(upper, estimate_path, version), estimate_path, not args.show.lower().startswith("f"))
    write_outputs(df, problems, upper, {"sample_rows": len(sample), "signee_entries": int(sample[COL].apply(split).apply(len).sum()), "valid_person_ids_in_database": len(person_ids), "problem_entries": len(problems), "matching_quality": metric}, estimate_path, primary_names)
    LOGGER.info("No malformed or missing signee IDs found." if problems.empty else f"Found {len(problems)} problematic signee entries.")
    LOGGER.info("Signature matching quality from XML %s IDs: exact_match=%.4f precision=%.4f recall=%.4f f1=%.4f", args.prediction_source, metric["exact_match"], metric["precision"], metric["recall"], metric["f1"])
    return int(args.fail_on_problems and not problems.empty)


if __name__ == "__main__":
    sys.exit(main())
