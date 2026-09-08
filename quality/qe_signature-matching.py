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
from sklearn.metrics import precision_recall_fscore_support
from trainerlog import get_logger

REPO = Path(__file__).resolve().parents[1]
LOGGER = get_logger(name="qe-signature-matching")
SIGNEE_COLUMN = "SWERIK_ID_MPs_signee"
SWERIK_ID_RE = re.compile(r"^i-[A-Za-z0-9]+$")
QUALITY_METRICS = ["precision", "recall", "f1", "exact_match"]


def version_key(version):
    if version == "v99.99.99":
        return [999, 999, 999]
    return [int(part) for part in re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:b|rc\d+)?", str(version)).groups()]


def split_refs(value):
    if value is None or pd.isna(value):
        return []
    return [ref.strip() for ref in str(value).replace(";", " ").split() if ref.strip()]


def precision_recall_f1(tp, fp, fn):
    sample_weight = [int(tp), int(fp), int(fn)]
    if not any(sample_weight):
        return 0.0, 0.0, 0.0
    precision, recall, f1_score, _ = precision_recall_fscore_support(
        [1, 0, 1], [1, 1, 0], sample_weight=sample_weight, average="binary", zero_division=0
    )
    return float(precision), float(recall), float(f1_score)


def motion_path(motion):
    motion = str(motion).strip()
    for marker in ("/blob/main/", "/blob/dev/"):
        if marker in motion:
            return motion.split(marker, 1)[1]
    return "data/" + motion.split("/data/", 1)[1] if "/data/" in motion else motion


def parliament_year(path):
    metadata = infer_metadata(path)
    return str(metadata.get("sitting") or metadata.get("year") or "")


def default_person_data():
    candidates = [REPO.parent / "riksdagen-persons" / "data"]
    if os.environ.get("METADATA_PATH"):
        candidates.insert(0, Path(get_data_location("metadata")))
    for path in candidates:
        if (path / "person.csv").exists():
            return path.resolve()
    raise FileNotFoundError("Could not find riksdagen-persons/data/person.csv")


def person_tables(person_data):
    persons = set(pd.read_csv(person_data / "person.csv", dtype=str)["person_id"].dropna())
    names = pd.read_csv(person_data / "name.csv", dtype=str).fillna("")
    primary = names[names["primary_name"].str.casefold().eq("true")]
    return persons, primary.drop_duplicates("person_id").set_index("person_id")["name"].to_dict()


def gold_problems(sample, person_ids):
    rows = []
    for csv_row, row in sample.iterrows():
        path = motion_path(row["motion"])
        for entry_number, entry in enumerate(split_refs(row[SIGNEE_COLUMN]) or [""], start=1):
            problem = None
            if entry == "":
                problem = "blank-signee-cell"
            elif not SWERIK_ID_RE.fullmatch(entry):
                problem = "not-a-swerik-id"
            elif entry not in person_ids:
                problem = "id-not-in-person-database"
            if problem:
                rows.append(dict(problem=problem, csv_row=csv_row + 2, parliament_year=parliament_year(path), motion_path=path, entry_number=entry_number, signee_entry=entry, motion=row["motion"], raw_signee_cell=row[SIGNEE_COLUMN]))
    return pd.DataFrame(rows)


def parse_refs(refs):
    ids, bad, unknown = set(), set(), 0
    for ref in refs:
        if ref in {"unknown", "#unknown"} or ref.startswith("r-"):
            unknown += 1
            continue
        ref = ref[1:] if ref.startswith("#") else ref
        ids.add(ref) if SWERIK_ID_RE.fullmatch(ref) else bad.add(ref)
    return ids, unknown, bad


def xml_signees(path):
    out = dict(body_ids=set(), metadata_ids=set(), unknown_signature_count=0, missing_who_count=0, non_swerik_who_values=set(), metadata_placeholder_count=0, metadata_non_swerik_values=set(), signature_item_count=0, xml_read_error="")
    try:
        root, ns = parse_tei(str(path))
    except Exception as err:
        out["xml_read_error"] = repr(err)
        return out

    tei, body_refs, metadata_refs = ns["tei_ns"], [], []
    signatures = root.findall(f".//{tei}item[@type=\"signature\"]")
    for item in signatures:
        refs = split_refs(item.get("who"))
        out["missing_who_count"] += int(not refs)
        body_refs.extend(refs)
    for idno in root.findall(f".//{tei}particDesc/{tei}listPerson/{tei}person/{tei}idno"):
        metadata_refs.extend(split_refs(idno.text))

    out["signature_item_count"] = len(signatures)
    out["body_ids"], out["unknown_signature_count"], out["non_swerik_who_values"] = parse_refs(body_refs)
    out["metadata_ids"], out["metadata_placeholder_count"], out["metadata_non_swerik_values"] = parse_refs(metadata_refs)
    return out


def prediction_set(xml, source):
    if source == "metadata":
        return xml["metadata_ids"]
    if source == "union":
        return xml["body_ids"] | xml["metadata_ids"]
    return xml["body_ids"]


def comparison_rows(sample, source):
    rows = []
    for csv_row, row in sample.iterrows():
        path = motion_path(row["motion"])
        gold = {ref for ref in split_refs(row[SIGNEE_COLUMN]) if SWERIK_ID_RE.fullmatch(ref)}
        xml = xml_signees(REPO / path)
        pred = prediction_set(xml, source)
        tp, fp, fn = gold & pred, pred - gold, gold - pred
        precision, recall, f1_score = precision_recall_f1(len(tp), len(fp), len(fn))
        rows.append(dict(csv_row=csv_row + 2, parliament_year=parliament_year(path), motion_path=path, exact_match=gold == pred, precision=precision, recall=recall, f1=f1_score, true_positives=len(tp), false_positives=len(fp), false_negatives=len(fn), gold_signee_count=len(gold), xml_predicted_signee_count=len(pred), miss_rate=len(fn) / len(gold) if gold else 0, coverage=recall, extra_rate=len(fp) / len(pred) if pred else 0, gold_ids="; ".join(sorted(gold)), xml_predicted_ids="; ".join(sorted(pred)), true_positive_ids="; ".join(sorted(tp)), false_positive_ids="; ".join(sorted(fp)), false_negative_ids="; ".join(sorted(fn)), xml_body_ids="; ".join(sorted(xml["body_ids"])), xml_metadata_ids="; ".join(sorted(xml["metadata_ids"])), body_metadata_agree=xml["body_ids"] == xml["metadata_ids"], signature_item_count=xml["signature_item_count"], unknown_signature_count=xml["unknown_signature_count"], missing_who_count=xml["missing_who_count"], non_swerik_who_values="; ".join(sorted(xml["non_swerik_who_values"])), metadata_placeholder_count=xml["metadata_placeholder_count"], metadata_non_swerik_values="; ".join(sorted(xml["metadata_non_swerik_values"])), xml_read_error=xml["xml_read_error"], motion=row["motion"]))
    return pd.DataFrame(rows)


def metrics(df, source):
    totals = {col: int(df[col].sum()) for col in ["true_positives", "false_positives", "false_negatives", "unknown_signature_count", "missing_who_count", "signature_item_count"]}
    tp, fp, fn = totals["true_positives"], totals["false_positives"], totals["false_negatives"]
    precision, recall, f1_score = precision_recall_f1(tp, fp, fn)
    return dict(prediction_source=source, exact_match=df["exact_match"].mean(), precision=precision, recall=recall, f1=f1_score, macro_precision=df["precision"].mean(), macro_recall=df["recall"].mean(), macro_f1=df["f1"].mean(), mean_miss_rate=df["miss_rate"].mean(), mean_extra_rate=df["extra_rate"].mean(), motions_with_missed_signees=int((df["false_negatives"] > 0).sum()), motions_with_extra_signees=int((df["false_positives"] > 0).sum()), motions_with_full_miss=int(((df["false_negatives"] > 0) & (df["true_positives"] == 0)).sum()), motions_with_partial_miss=int(((df["false_negatives"] > 0) & (df["true_positives"] > 0)).sum()), motions_with_no_xml_prediction=int(((df["false_negatives"] > 0) & (df["xml_predicted_ids"] == "")).sum()), exact_matches=int(df["exact_match"].sum()), xml_read_errors=int(df["xml_read_error"].astype(bool).sum()), body_metadata_disagreements=int((~df["body_metadata_agree"]).sum()), non_swerik_who_values=int(df["non_swerik_who_values"].astype(bool).sum()), gold_positive_ids=int(df["gold_signee_count"].sum()), predicted_positive_ids=int(df["xml_predicted_signee_count"].sum()), **totals)


def yearly_estimates(df, version):
    by_year = df.assign(year=df["parliament_year"].astype(str).str.extract(r"(\d{4})")[0].fillna(0).astype(int)).query("year > 0")
    by_year = by_year.groupby("year").agg(motions=("motion_path", "count"), exact_matches=("exact_match", "sum"), true_positives=("true_positives", "sum"), false_positives=("false_positives", "sum"), false_negatives=("false_negatives", "sum"), gold_positive_ids=("gold_signee_count", "sum"), predicted_positive_ids=("xml_predicted_signee_count", "sum"), macro_precision=("precision", "mean"), macro_recall=("recall", "mean"), macro_f1=("f1", "mean"), mean_miss_rate=("miss_rate", "mean"), mean_extra_rate=("extra_rate", "mean")).reset_index()
    by_year[["precision", "recall", "f1"]] = by_year.apply(lambda row: precision_recall_f1(row["true_positives"], row["false_positives"], row["false_negatives"]), axis=1, result_type="expand")
    by_year["exact_match"] = by_year["exact_matches"] / by_year["motions"]
    by_year["exact_match_lower"] = by_year.apply(lambda row: beta.ppf(0.05, row["exact_matches"] + 1, row["motions"] - row["exact_matches"] + 1), axis=1)
    by_year["exact_match_upper"] = by_year.apply(lambda row: beta.ppf(0.95, row["exact_matches"] + 1, row["motions"] - row["exact_matches"] + 1), axis=1)
    by_year.insert(0, "version", version)
    return by_year.sort_values("year")


def update_difference(upper, estimate_path, version):
    path = estimate_path / "difference.csv"
    if path.exists():
        old = pd.read_csv(path)
        if version == "v99.99.99":
            old = old[old["version"] != "v99.99.99"]
        elif version in set(old["version"]):
            print(f"Version {version} already exists in {path}, skipping append.")
            return old
        upper = pd.concat([old, upper], ignore_index=True)
    upper.to_csv(path, index=False)
    return upper


def plot_versions(df, estimate_path):
    versions = sorted([v for v in df["version"].unique() if "rc" not in str(v).lower()], key=version_key, reverse=True)[:6]
    for metric in QUALITY_METRICS:
        fig, ax = plt.subplots(figsize=(12, 6))
        for index, version in enumerate(versions):
            data = df[df["version"] == version].sort_values("year")
            ax.plot(data["year"], data[metric], linewidth=1.75, label=version, color=list("bgrcmyk")[index % 7])
        ax.set(title=f"signature-matching-{metric.replace('_', '-')}", xlabel="Beginning of parliamentary year", ylabel=metric, ylim=(0, 1))
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(estimate_path / f"signature-matching-{metric.replace('_', '-')}.png")
        plt.close(fig)


def write_outputs(df, problems, upper, summary, estimate_path, primary_names):
    upper.to_csv(estimate_path / "upper_bound.csv", index=False)
    df.to_csv(estimate_path / "motion-comparison.tsv", sep="\t", index=False)
    problems.to_csv(estimate_path / "person-id-problems.tsv", sep="\t", index=False)
    (estimate_path / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    def with_names(value):
        return "; ".join(f"{pid} ({primary_names[pid]})" if pid in primary_names else pid for pid in split_refs(value))

    named = df.assign(false_negative_names=df["false_negative_ids"].apply(with_names), false_positive_names=df["false_positive_ids"].apply(with_names))
    missed_cols = ["motion_path", "parliament_year", "false_negatives", "gold_signee_count", "miss_rate", "coverage", "true_positives", "false_positives", "unknown_signature_count", "signature_item_count", "false_negative_ids", "false_negative_names", "xml_predicted_ids", "motion"]
    extra_cols = ["motion_path", "parliament_year", "false_positives", "xml_predicted_signee_count", "extra_rate", "precision", "true_positives", "false_negatives", "unknown_signature_count", "signature_item_count", "false_positive_ids", "false_positive_names", "gold_ids", "motion"]
    named[named["false_negatives"] > 0][missed_cols].sort_values(["miss_rate", "gold_signee_count", "motion_path"], ascending=[False, False, True]).to_csv(estimate_path / "missed-signatures.tsv", sep="\t", index=False)
    named[named["false_positives"] > 0][extra_cols].sort_values(["extra_rate", "xml_predicted_signee_count", "motion_path"], ascending=[False, False, True]).to_csv(estimate_path / "extra-signatures.tsv", sep="\t", index=False)

    print("Upper bound signature-matching summary:")
    print(upper)
    for metric in QUALITY_METRICS:
        print(f"Average signature-matching {metric}:", upper[metric].mean())
    for metric in QUALITY_METRICS:
        print(f"Weighted average signature-matching {metric}:", summary["matching_quality"][metric])
    print("Minimum signature-matching:", upper.loc[upper["f1"].idxmin(), "f1"], "at year:", upper.loc[upper["f1"].idxmin(), "year"])
    print("Resources cleaned up.")


def main():
    version = "v99.99.99"
    prediction_source = "body"
    estimate_path = REPO / "quality/estimates/signature-matching"
    sample_path = REPO / "quality/data/qe_motion_id_signee.csv"
    person_data = default_person_data()
    estimate_path.mkdir(parents=True, exist_ok=True)

    sample = pd.read_csv(sample_path, dtype=str).fillna("")
    person_ids, primary_names = person_tables(person_data)
    problems = gold_problems(sample, person_ids)
    comparison = comparison_rows(sample, prediction_source)
    metric = metrics(comparison, prediction_source)
    upper = yearly_estimates(comparison, version)
    plot_versions(update_difference(upper, estimate_path, version), estimate_path)
    write_outputs(comparison, problems, upper, {"sample_rows": len(sample), "signee_entries": int(sample[SIGNEE_COLUMN].apply(split_refs).apply(len).sum()), "valid_person_ids_in_database": len(person_ids), "problem_entries": len(problems), "matching_quality": metric}, estimate_path, primary_names)

    LOGGER.info("No malformed or missing signee IDs found." if problems.empty else f"Found {len(problems)} problematic signee entries.")
    LOGGER.info("Signature matching quality from XML %s IDs: exact_match=%.4f precision=%.4f recall=%.4f f1=%.4f", prediction_source, metric["exact_match"], metric["precision"], metric["recall"], metric["f1"])


if __name__ == "__main__":
    main()
