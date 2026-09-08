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


LOGGER, SIGNEE_COLUMN = get_logger(name="qe-signature-matching"), "SWERIK_ID_MPs_signee"
SWERIK_ID_RE, UNKNOWN_REFS = re.compile(r"^i-[A-Za-z0-9]+$"), {"unknown", "#unknown"}
ESTIMATE_PATH = "quality/estimates/signature-matching"


def repo_root(): return Path(__file__).resolve().parents[1]


def resolve_path(path):
    path = Path(path).expanduser()
    return path if path.is_absolute() else repo_root() / path


def version_number_is_valid(version):
    version = version or "v99.99.99"
    if version == "v99.99.99" or re.fullmatch(r"v\d+\.\d+\.\d+(?:b|rc\d+)?", version):
        return version
    sys.exit(f"{version} is not a valid version number. Exiting.")


def version_key(version):
    if version == "v99.99.99":
        return [999, 999, 999]
    return [int(part) for part in re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:b|rc\d+)?", str(version)).groups()]


def default_person_data():
    root = repo_root()
    candidates = [root.parent / "riksdagen-persons" / "data"]
    if os.environ.get("METADATA_PATH"):
        candidates.insert(0, Path(get_data_location("metadata")))
    for path in candidates:
        if (path / "person.csv").exists():
            return path.resolve()
    raise FileNotFoundError("Could not find riksdagen-persons/data/person.csv")


def motion_path(motion):
    motion = str(motion).strip()
    for marker in ("/blob/main/", "/blob/dev/"):
        if marker in motion:
            return motion.split(marker, 1)[1]
    return "data/" + motion.split("/data/", 1)[1] if "/data/" in motion else motion


def parliament_year(path):
    md = infer_metadata(path)
    return str(md.get("sitting") or md.get("year") or "")


def year(value):
    match = re.search(r"\d{4}", str(value))
    return int(match.group(0)) if match else 0


def split_refs(value, separator=";"):
    return [] if value is None or pd.isna(value) else [p.strip() for p in str(value).replace(separator, " ").split() if p.strip()]


def stable_join(values): return "; ".join(sorted(values))


def safe_div(numerator, denominator): return numerator / denominator if denominator else 0.0


def f1(precision, recall): return safe_div(2 * precision * recall, precision + recall)


def person_tables(person_data):
    persons = pd.read_csv(person_data / "person.csv", dtype=str)
    names = pd.read_csv(person_data / "name.csv", dtype=str).fillna("")
    primary = names[names["primary_name"].str.casefold().eq("true")]
    primary = primary.drop_duplicates("person_id").set_index("person_id")["name"].to_dict()
    return set(persons["person_id"].dropna()), primary


def ids_with_names(ids, primary_names):
    return "; ".join(f"{pid} ({primary_names[pid]})" if pid in primary_names else pid for pid in split_refs(ids))


def problem_entries(sample, person_ids):
    rows = []
    for csv_row, row in sample.iterrows():
        path = motion_path(row["motion"])
        for entry_number, entry in enumerate(split_refs(row[SIGNEE_COLUMN]) or [""], start=1):
            problem = (
                "blank-signee-cell" if entry == "" else
                "not-a-swerik-id" if not SWERIK_ID_RE.fullmatch(entry) else
                "id-not-in-person-database" if entry not in person_ids else None
            )
            if problem:
                rows.append(dict(problem=problem, csv_row=csv_row + 2, parliament_year=parliament_year(path),
                                 motion_path=path, entry_number=entry_number, signee_entry=entry,
                                 motion=row["motion"], raw_signee_cell=row[SIGNEE_COLUMN]))
    return pd.DataFrame(rows)


def add_ref(ref, ids, unknown_counter, invalid):
    if ref in UNKNOWN_REFS or ref.startswith("r-"):
        unknown_counter[0] += 1
        return
    ref = ref[1:] if ref.startswith("#") else ref
    ids.add(ref) if SWERIK_ID_RE.fullmatch(ref) else invalid.add(ref)


def xml_signees(path):
    xml = dict(body_ids=set(), metadata_ids=set(), unknown_signature_count=0, missing_who_count=0,
               non_swerik_who_values=set(), metadata_placeholder_count=0,
               metadata_non_swerik_values=set(), signature_item_count=0, xml_read_error="")
    try:
        root, ns = parse_tei(str(path))
    except Exception as err:
        xml["xml_read_error"] = repr(err)
        return xml

    tei = ns["tei_ns"]
    signatures = root.findall(f".//{tei}item[@type=\"signature\"]")
    xml["signature_item_count"] = len(signatures)
    for signature in signatures:
        refs = split_refs(signature.get("who"))
        xml["missing_who_count"] += int(not refs)
        counter = [0]
        for ref in refs:
            add_ref(ref, xml["body_ids"], counter, xml["non_swerik_who_values"])
        xml["unknown_signature_count"] += counter[0]

    counter = [0]
    for idno in root.findall(f".//{tei}particDesc/{tei}listPerson/{tei}person/{tei}idno"):
        for ref in split_refs(idno.text):
            add_ref(ref, xml["metadata_ids"], counter, xml["metadata_non_swerik_values"])
    xml["metadata_placeholder_count"] = counter[0]
    return xml


def predicted_ids(xml, source):
    return {"metadata": xml["metadata_ids"], "union": xml["body_ids"] | xml["metadata_ids"]}.get(source, xml["body_ids"])


def compare(sample, source):
    rows = []
    for csv_row, row in sample.iterrows():
        path = motion_path(row["motion"])
        gold = {pid for pid in split_refs(row[SIGNEE_COLUMN]) if SWERIK_ID_RE.fullmatch(pid)}
        xml = xml_signees(repo_root() / path)
        pred = predicted_ids(xml, source)
        tp, fp, fn = gold & pred, pred - gold, gold - pred
        precision, recall = safe_div(len(tp), len(tp) + len(fp)), safe_div(len(tp), len(tp) + len(fn))
        body_ids, metadata_ids = xml["body_ids"], xml["metadata_ids"]
        rows.append(dict(
            csv_row=csv_row + 2, parliament_year=parliament_year(path), motion_path=path,
            exact_match=gold == pred, precision=precision, recall=recall, f1=f1(precision, recall),
            true_positives=len(tp), false_positives=len(fp), false_negatives=len(fn),
            gold_signee_count=len(gold), xml_predicted_signee_count=len(pred),
            miss_rate=safe_div(len(fn), len(gold)), coverage=recall, extra_rate=safe_div(len(fp), len(pred)),
            gold_ids=stable_join(gold), xml_predicted_ids=stable_join(pred),
            true_positive_ids=stable_join(tp), false_positive_ids=stable_join(fp),
            false_negative_ids=stable_join(fn), xml_body_ids=stable_join(body_ids),
            xml_metadata_ids=stable_join(metadata_ids), body_metadata_agree=body_ids == metadata_ids,
            signature_item_count=xml["signature_item_count"], unknown_signature_count=xml["unknown_signature_count"],
            missing_who_count=xml["missing_who_count"], non_swerik_who_values=stable_join(xml["non_swerik_who_values"]),
            metadata_placeholder_count=xml["metadata_placeholder_count"],
            metadata_non_swerik_values=stable_join(xml["metadata_non_swerik_values"]),
            xml_read_error=xml["xml_read_error"], motion=row["motion"]))
    return pd.DataFrame(rows)


def metrics(df, source):
    tp, fp, fn = df["true_positives"].sum(), df["false_positives"].sum(), df["false_negatives"].sum()
    precision, recall = safe_div(tp, tp + fp), safe_div(tp, tp + fn)
    return {
        "prediction_source": source,
        "exact_match": df["exact_match"].mean(),
        "precision": precision,
        "recall": recall,
        "f1": f1(precision, recall),
        "macro_precision": df["precision"].mean(),
        "macro_recall": df["recall"].mean(),
        "macro_f1": df["f1"].mean(),
        "mean_miss_rate": df["miss_rate"].mean(),
        "mean_extra_rate": df["extra_rate"].mean(),
        "motions_with_missed_signees": int((df["false_negatives"] > 0).sum()),
        "motions_with_extra_signees": int((df["false_positives"] > 0).sum()),
        "motions_with_full_miss": int(((df["false_negatives"] > 0) & (df["true_positives"] == 0)).sum()),
        "motions_with_partial_miss": int(((df["false_negatives"] > 0) & (df["true_positives"] > 0)).sum()),
        "motions_with_no_xml_prediction": int(((df["false_negatives"] > 0) & (df["xml_predicted_ids"] == "")).sum()),
        "true_positives": int(tp),
        "false_positives": int(fp),
        "false_negatives": int(fn),
        "exact_matches": int(df["exact_match"].sum()),
        "xml_read_errors": int(df["xml_read_error"].astype(bool).sum()),
        "body_metadata_disagreements": int((~df["body_metadata_agree"]).sum()),
        "unknown_signature_items": int(df["unknown_signature_count"].sum()),
        "missing_who_items": int(df["missing_who_count"].sum()),
        "non_swerik_who_values": int(df["non_swerik_who_values"].astype(bool).sum()),
        "signature_items": int(df["signature_item_count"].sum()),
        "gold_positive_ids": int(df["gold_signee_count"].sum()),
        "predicted_positive_ids": int(df["xml_predicted_signee_count"].sum()),
    }


def by_year(df, version):
    grouped = df.assign(year=df["parliament_year"].apply(year)).query("year > 0")
    grouped = grouped.groupby("year").agg(
        motions=("motion_path", "count"), exact_matches=("exact_match", "sum"),
        true_positives=("true_positives", "sum"), false_positives=("false_positives", "sum"),
        false_negatives=("false_negatives", "sum"), gold_positive_ids=("gold_signee_count", "sum"),
        predicted_positive_ids=("xml_predicted_signee_count", "sum"), macro_precision=("precision", "mean"),
        macro_recall=("recall", "mean"), macro_f1=("f1", "mean"),
        mean_miss_rate=("miss_rate", "mean"), mean_extra_rate=("extra_rate", "mean")).reset_index()
    grouped["precision"] = grouped.apply(lambda r: safe_div(r.true_positives, r.true_positives + r.false_positives), axis=1)
    grouped["recall"] = grouped.apply(lambda r: safe_div(r.true_positives, r.true_positives + r.false_negatives), axis=1)
    grouped["f1"] = grouped.apply(lambda r: f1(r.precision, r.recall), axis=1)
    grouped["exact_match"] = grouped["exact_matches"] / grouped["motions"]
    grouped["exact_match_lower"] = grouped.apply(lambda r: beta.ppf(0.05, r.exact_matches + 1, r.motions - r.exact_matches + 1), axis=1)
    grouped["exact_match_upper"] = grouped.apply(lambda r: beta.ppf(0.95, r.exact_matches + 1, r.motions - r.exact_matches + 1), axis=1)
    grouped.insert(0, "version", version)
    return grouped.sort_values("year")


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


def plot_versions(df, estimate_path, show):
    colors = list("bgrcmyk")
    versions = sorted([v for v in df["version"].unique() if "rc" not in str(v).lower()], key=version_key, reverse=True)[:6]
    for metric in ["f1", "precision", "recall", "exact_match"]:
        fig, ax = plt.subplots(figsize=(12, 6))
        for index, version in enumerate(versions):
            dfv = df[df["version"] == version].sort_values("year")
            ax.plot(dfv["year"], dfv[metric], linewidth=1.75, label=version, color=colors[index % len(colors)])
        ax.set(title=f"signature-matching-{metric.replace('_', '-')}", xlabel="Beginning of parliamentary year", ylabel=metric, ylim=(0, 1))
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(estimate_path / f"signature-matching-{metric.replace('_', '-')}.png")
        if show:
            fig.show()
        plt.close(fig)


def write_diagnostics(df, problems, estimate_path, primary_names):
    df.to_csv(estimate_path / "motion-comparison.tsv", sep="\t", index=False)
    problems.to_csv(estimate_path / "person-id-problems.tsv", sep="\t", index=False)
    named = df.assign(
        false_negative_names=df["false_negative_ids"].apply(lambda value: ids_with_names(value, primary_names)),
        false_positive_names=df["false_positive_ids"].apply(lambda value: ids_with_names(value, primary_names)),
    )
    missed_cols = ["motion_path", "parliament_year", "false_negatives", "gold_signee_count", "miss_rate", "coverage", "true_positives", "false_positives", "unknown_signature_count", "signature_item_count", "false_negative_ids", "false_negative_names", "xml_predicted_ids", "motion"]
    extra_cols = ["motion_path", "parliament_year", "false_positives", "xml_predicted_signee_count", "extra_rate", "precision", "true_positives", "false_negatives", "unknown_signature_count", "signature_item_count", "false_positive_ids", "false_positive_names", "gold_ids", "motion"]
    named[named["false_negatives"] > 0][missed_cols].sort_values(["miss_rate", "gold_signee_count", "motion_path"], ascending=[False, False, True]).to_csv(estimate_path / "missed-signatures.tsv", sep="\t", index=False)
    named[named["false_positives"] > 0][extra_cols].sort_values(["extra_rate", "xml_predicted_signee_count", "motion_path"], ascending=[False, False, True]).to_csv(estimate_path / "extra-signatures.tsv", sep="\t", index=False)


def print_summary(upper, metric):
    print("Upper bound signature-matching summary:")
    print(upper)
    for name in ["precision", "recall", "f1", "exact_match"]:
        print(f"Average signature-matching {name}:", upper[name].mean())
    for name in ["precision", "recall", "f1", "exact_match"]:
        print(f"Weighted average signature-matching {name}:", metric[name])
    min_idx = upper["f1"].idxmin()
    print("Minimum signature-matching:", upper.loc[min_idx, "f1"], "at year:", upper.loc[min_idx, "year"])
    print("Resources cleaned up.")


def parse_args():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("-d", "--annotated-data", default="quality/data/qe_motion_id_signee.csv")
    parser.add_argument("-o", "--estimate-path", default=ESTIMATE_PATH)
    parser.add_argument("-v", "--version", default="v99.99.99")
    parser.add_argument("--person-data", default=None)
    parser.add_argument("--prediction-source", choices=["body", "metadata", "union"], default="body")
    parser.add_argument("--show", default="False")
    parser.add_argument("--fail-on-problems", action="store_true")
    return parser.parse_args()


def main():
    args = parse_args()
    version = version_number_is_valid(args.version)
    estimate_path = resolve_path(args.estimate_path)
    estimate_path.mkdir(parents=True, exist_ok=True)

    sample = pd.read_csv(resolve_path(args.annotated_data), dtype=str).fillna("")
    person_ids, primary_names = person_tables(resolve_path(args.person_data) if args.person_data else default_person_data())
    problems = problem_entries(sample, person_ids)
    comparison = compare(sample, args.prediction_source)
    metric = metrics(comparison, args.prediction_source)
    upper = by_year(comparison, version)
    upper.to_csv(estimate_path / "upper_bound.csv", index=False)
    difference = update_difference(upper, estimate_path, version)
    plot_versions(difference, estimate_path, show=not args.show.lower().startswith("f"))
    write_diagnostics(comparison, problems, estimate_path, primary_names)

    summary = {
        "sample_rows": len(sample),
        "signee_entries": int(sample[SIGNEE_COLUMN].apply(split_refs).apply(len).sum()),
        "valid_person_ids_in_database": len(person_ids),
        "problem_entries": len(problems),
        "matching_quality": metric,
    }
    (estimate_path / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")
    print_summary(upper, metric)

    LOGGER.info("No malformed or missing signee IDs found." if problems.empty else f"Found {len(problems)} problematic signee entries.")
    LOGGER.info(
        "Signature matching quality from XML %s IDs: exact_match=%.4f precision=%.4f recall=%.4f f1=%.4f",
        args.prediction_source,
        metric["exact_match"],
        metric["precision"],
        metric["recall"],
        metric["f1"],
    )
    if args.fail_on_problems and not problems.empty:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
