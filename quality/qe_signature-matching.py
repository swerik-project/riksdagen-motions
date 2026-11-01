#!/usr/bin/env python3
"""
Estimate motion signature matching quality against manually annotated signees.

The estimator compares the gold-standard IDs in
``quality/data/qe_motion_id_signee.csv`` with ``who`` IDs on
``item type="signature"`` elements. It writes records-style versioned decade
estimates plus diagnostic TSVs for missed and extra signatures.
"""
import json
import os
import re
from pathlib import Path

os.environ.setdefault("MPLBACKEND", "Agg")
os.environ.setdefault("MPLCONFIGDIR", "/tmp/riksdagen-motions-mpl")

import matplotlib.pyplot as plt
import polars as pl
from packaging.version import Version
from pyriksdagen.io import parse_tei
from pyriksdagen.utils import get_data_location, infer_metadata
from scipy.stats import beta
from trainerlog import get_logger

REPO = Path(__file__).resolve().parents[1]
LOGGER = get_logger(name="qe-signature-matching")
SIGNEE_COLUMN = "SWERIK_ID_MPs_signee"
SWERIK_ID_RE = re.compile(r"^i-[A-Za-z0-9]+$")
QUALITY_METRICS = ["precision", "recall", "f1", "exact_match"]
ID_COLUMNS = [
    "gold_ids", "xml_predicted_ids", "true_positive_ids", "false_positive_ids",
    "false_negative_ids", "xml_body_ids", "xml_metadata_ids",
    "non_swerik_who_values", "metadata_non_swerik_values",
]


def split_refs(value):
    if value is None:
        return []
    return value.replace(";", " ").split()


def matching_scores(df):
    """Calculate matching scores from TP/FP/FN, using zero for empty denominators."""
    tp = pl.col("true_positives")
    fp = pl.col("false_positives")
    fn = pl.col("false_negatives")
    return df.with_columns(
        precision=pl.when(tp + fp > 0).then(tp / (tp + fp)).otherwise(0.0),
        recall=pl.when(tp + fn > 0).then(tp / (tp + fn)).otherwise(0.0),
        f1=pl.when(2 * tp + fp + fn > 0)
        .then(2 * tp / (2 * tp + fp + fn)).otherwise(0.0),
    )


def motion_path(motion):
    motion = str(motion).strip()
    for marker in ("/blob/main/", "/blob/dev/"):
        if marker in motion:
            return motion.split(marker, 1)[1]
    return "data/" + motion.split("/data/", 1)[1] if "/data/" in motion else motion


def parliament_year(path):
    metadata = infer_metadata(path)
    sitting = metadata.get("sitting")
    year = sitting if sitting is not None else metadata["year"]
    if year is None:
        raise ValueError(f"Could not infer a parliament year from {path}")
    return str(year)


def default_person_data():
    candidates = [REPO.parent / "riksdagen-persons" / "data"]
    if os.environ.get("METADATA_PATH"):
        candidates.insert(0, Path(get_data_location("metadata")))
    for path in candidates:
        if (path / "person.csv").exists():
            return path.resolve()
    raise FileNotFoundError("Could not find riksdagen-persons/data/person.csv")


def person_tables(person_data):
    persons = pl.read_csv(person_data / "person.csv", columns=["person_id"])
    names = pl.read_csv(
        person_data / "name.csv",
        columns=["person_id", "name", "primary_name"],
        schema_overrides={"primary_name": pl.Boolean},
    )
    primary = names.filter(pl.col("primary_name")).unique(
        subset="person_id", keep="first", maintain_order=True,
    )
    return set(persons["person_id"]), dict(primary.select("person_id", "name").iter_rows())


def gold_problems(sample, person_ids):
    rows = []
    for csv_row, row in enumerate(sample.iter_rows(named=True), start=2):
        path = motion_path(row["motion"])
        for entry_number, entry in enumerate(split_refs(row[SIGNEE_COLUMN]) or [None], start=1):
            problem = None
            if entry is None:
                problem = "blank-signee-cell"
            elif not SWERIK_ID_RE.fullmatch(entry):
                problem = "not-a-swerik-id"
            elif entry not in person_ids:
                problem = "id-not-in-person-database"
            if problem:
                rows.append({
                    "problem": problem,
                    "csv_row": csv_row,
                    "parliament_year": parliament_year(path),
                    "motion_path": path,
                    "entry_number": entry_number,
                    "signee_entry": entry,
                    "motion": row["motion"],
                    "raw_signee_cell": row[SIGNEE_COLUMN],
                })
    return pl.DataFrame(rows, schema={
        "problem": pl.String,
        "csv_row": pl.Int64,
        "parliament_year": pl.String,
        "motion_path": pl.String,
        "entry_number": pl.Int64,
        "signee_entry": pl.String,
        "motion": pl.String,
        "raw_signee_cell": pl.String,
    })


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
    root, ns = parse_tei(str(path))
    tei, body_refs, metadata_refs = ns["tei_ns"], [], []
    missing_who_count = 0
    signatures = root.findall(f".//{tei}item[@type=\"signature\"]")
    for item in signatures:
        refs = split_refs(item.get("who"))
        missing_who_count += int(not refs)
        body_refs.extend(refs)
    for idno in root.findall(f".//{tei}particDesc/{tei}listPerson/{tei}person/{tei}idno"):
        metadata_refs.extend(split_refs(idno.text))

    body_ids, unknown_count, body_bad = parse_refs(body_refs)
    metadata_ids, placeholder_count, metadata_bad = parse_refs(metadata_refs)
    return {
        "body_ids": body_ids,
        "metadata_ids": metadata_ids,
        "unknown_signature_count": unknown_count,
        "missing_who_count": missing_who_count,
        "non_swerik_who_values": body_bad,
        "metadata_placeholder_count": placeholder_count,
        "metadata_non_swerik_values": metadata_bad,
        "signature_item_count": len(signatures),
    }


def prediction_set(xml, source):
    if source == "metadata":
        return xml["metadata_ids"]
    if source == "union":
        return xml["body_ids"] | xml["metadata_ids"]
    return xml["body_ids"]


def comparison_rows(sample, source):
    """Compare person sets per motion, then derive counts and scores in Polars."""
    rows = []
    for csv_row, row in enumerate(sample.iter_rows(named=True), start=2):
        path = motion_path(row["motion"])
        gold = {ref for ref in split_refs(row[SIGNEE_COLUMN]) if SWERIK_ID_RE.fullmatch(ref)}
        xml = xml_signees(REPO / path)
        pred = prediction_set(xml, source)
        tp, fp, fn = gold & pred, pred - gold, gold - pred
        rows.append({
            "csv_row": csv_row,
            "parliament_year": parliament_year(path),
            "motion_path": path,
            "exact_match": gold == pred,
            "gold_ids": sorted(gold),
            "xml_predicted_ids": sorted(pred),
            "true_positive_ids": sorted(tp),
            "false_positive_ids": sorted(fp),
            "false_negative_ids": sorted(fn),
            "xml_body_ids": sorted(xml["body_ids"]),
            "xml_metadata_ids": sorted(xml["metadata_ids"]),
            "body_metadata_agree": xml["body_ids"] == xml["metadata_ids"],
            "signature_item_count": xml["signature_item_count"],
            "unknown_signature_count": xml["unknown_signature_count"],
            "missing_who_count": xml["missing_who_count"],
            "non_swerik_who_values": sorted(xml["non_swerik_who_values"]),
            "metadata_placeholder_count": xml["metadata_placeholder_count"],
            "metadata_non_swerik_values": sorted(xml["metadata_non_swerik_values"]),
            "motion": row["motion"],
        })
    df = pl.DataFrame(rows, schema_overrides={col: pl.List(pl.String) for col in ID_COLUMNS})
    df = df.with_columns(
        true_positives=pl.col("true_positive_ids").list.len(),
        false_positives=pl.col("false_positive_ids").list.len(),
        false_negatives=pl.col("false_negative_ids").list.len(),
        gold_signee_count=pl.col("gold_ids").list.len(),
        xml_predicted_signee_count=pl.col("xml_predicted_ids").list.len(),
    )
    df = matching_scores(df).with_columns(
        miss_rate=pl.when(pl.col("gold_signee_count") > 0)
        .then(pl.col("false_negatives") / pl.col("gold_signee_count")).otherwise(0.0),
        coverage=pl.col("recall"),
        extra_rate=pl.when(pl.col("xml_predicted_signee_count") > 0)
        .then(pl.col("false_positives") / pl.col("xml_predicted_signee_count")).otherwise(0.0),
    )
    return df.select(
        "csv_row", "parliament_year", "motion_path", "exact_match",
        "precision", "recall", "f1", "true_positives", "false_positives",
        "false_negatives", "gold_signee_count", "xml_predicted_signee_count",
        "miss_rate", "coverage", "extra_rate", "gold_ids", "xml_predicted_ids",
        "true_positive_ids", "false_positive_ids", "false_negative_ids",
        "xml_body_ids", "xml_metadata_ids", "body_metadata_agree",
        "signature_item_count", "unknown_signature_count", "missing_who_count",
        "non_swerik_who_values", "metadata_placeholder_count",
        "metadata_non_swerik_values", "motion",
    )


def metrics(df, source):
    totals = df.select(pl.col(
        "true_positives", "false_positives", "false_negatives",
        "unknown_signature_count", "missing_who_count", "signature_item_count",
    ).sum())
    return {
        "prediction_source": source,
        "exact_match": df["exact_match"].mean(),
        **matching_scores(totals).row(0, named=True),
        "macro_precision": df["precision"].mean(),
        "macro_recall": df["recall"].mean(),
        "macro_f1": df["f1"].mean(),
        "mean_miss_rate": df["miss_rate"].mean(),
        "mean_extra_rate": df["extra_rate"].mean(),
        "motions_with_missed_signees": df.filter(pl.col("false_negatives") > 0).height,
        "motions_with_extra_signees": df.filter(pl.col("false_positives") > 0).height,
        "motions_with_full_miss": df.filter(
            (pl.col("false_negatives") > 0) & (pl.col("true_positives") == 0)
        ).height,
        "motions_with_partial_miss": df.filter(
            (pl.col("false_negatives") > 0) & (pl.col("true_positives") > 0)
        ).height,
        "motions_with_no_xml_prediction": df.filter(
            (pl.col("false_negatives") > 0) & (pl.col("xml_predicted_signee_count") == 0)
        ).height,
        "exact_matches": df["exact_match"].sum(),
        "body_metadata_disagreements": (~df["body_metadata_agree"]).sum(),
        "non_swerik_who_values": (df["non_swerik_who_values"].list.len() > 0).sum(),
        "gold_positive_ids": df["gold_signee_count"].sum(),
        "predicted_positive_ids": df["xml_predicted_signee_count"].sum(),
    }


def decade_estimates(df, version):
    by_decade = df.with_columns(
        decade=pl.col("parliament_year").str.slice(0, 4).cast(pl.Int64) // 10 * 10,
    )
    by_decade = by_decade.group_by("decade").agg(
        motions=pl.len(),
        exact_matches=pl.col("exact_match").sum(),
        true_positives=pl.col("true_positives").sum(),
        false_positives=pl.col("false_positives").sum(),
        false_negatives=pl.col("false_negatives").sum(),
        gold_positive_ids=pl.col("gold_signee_count").sum(),
        predicted_positive_ids=pl.col("xml_predicted_signee_count").sum(),
        macro_precision=pl.col("precision").mean(),
        macro_recall=pl.col("recall").mean(),
        macro_f1=pl.col("f1").mean(),
        mean_miss_rate=pl.col("miss_rate").mean(),
        mean_extra_rate=pl.col("extra_rate").mean(),
    )
    correct = by_decade["exact_matches"].to_numpy()
    incorrect = (by_decade["motions"] - by_decade["exact_matches"]).to_numpy()
    return matching_scores(by_decade).with_columns(
        version=pl.lit(version),
        exact_match=pl.col("exact_matches") / pl.col("motions"),
        exact_match_lower=pl.Series(beta.ppf(0.05, correct + 1, incorrect + 1)),
        exact_match_upper=pl.Series(beta.ppf(0.95, correct + 1, incorrect + 1)),
    ).select("version", pl.exclude("version")).sort("decade")


def update_difference(upper, estimate_path, version):
    path = estimate_path / "difference.csv"
    if path.exists():
        old = pl.read_csv(path)
        if version == "v99.99.99":
            old = old.filter(pl.col("version") != "v99.99.99")
        elif version in set(old["version"]):
            LOGGER.info(f"Version {version} already exists in {path}, skipping append.")
            return old
        if not old.is_empty() and old.columns == upper.columns:
            upper = pl.concat([old, upper], how="vertical_relaxed")
        elif not old.is_empty():
            LOGGER.info(f"Existing {path} uses a different schema, rewriting with decade estimates.")
    upper.write_csv(path)
    return upper


def plot_versions(df, estimate_path):
    versions = sorted(
        [v for v in df["version"].unique() if "rc" not in v.lower()],
        key=lambda v: (v == "v99.99.99", Version(v)),
        reverse=True,
    )[:6]
    for metric in QUALITY_METRICS:
        fig, ax = plt.subplots(figsize=(12, 6))
        for index, version in enumerate(versions):
            data = df.filter(pl.col("version") == version).sort("decade")
            ax.plot(
                data["decade"].to_numpy(), data[metric].to_numpy(),
                linewidth=1.75, label=version, color=list("bgrcmyk")[index % 7],
            )
        ax.set(
            title=f"signature-matching-{metric.replace('_', '-')}",
            xlabel="Beginning of decade", ylabel=metric, ylim=(0, 1),
        )
        ax.legend(loc="upper left")
        fig.tight_layout()
        fig.savefig(estimate_path / f"signature-matching-{metric.replace('_', '-')}.png")
        plt.close(fig)


def write_outputs(df, problems, upper, summary, estimate_path, primary_names):
    upper.write_csv(estimate_path / "upper_bound.csv")
    df.with_columns(pl.col(ID_COLUMNS).list.join("; ")).write_csv(
        estimate_path / "motion-comparison.tsv", separator="\t",
    )
    problems.write_csv(estimate_path / "person-id-problems.tsv", separator="\t")
    (estimate_path / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n")

    def with_names(ids):
        return "; ".join(
            f"{pid} ({primary_names[pid]})" if primary_names.get(pid) is not None else pid
            for pid in ids
        )

    named = df.with_columns(
        false_negative_names=pl.Series([with_names(ids) for ids in df["false_negative_ids"]]),
        false_positive_names=pl.Series([with_names(ids) for ids in df["false_positive_ids"]]),
    ).with_columns(pl.col(ID_COLUMNS).list.join("; "))
    missed_cols = [
        "motion_path", "parliament_year", "false_negatives", "gold_signee_count",
        "miss_rate", "coverage", "true_positives", "false_positives",
        "unknown_signature_count", "signature_item_count", "false_negative_ids",
        "false_negative_names", "xml_predicted_ids", "motion",
    ]
    extra_cols = [
        "motion_path", "parliament_year", "false_positives", "xml_predicted_signee_count",
        "extra_rate", "precision", "true_positives", "false_negatives",
        "unknown_signature_count", "signature_item_count", "false_positive_ids",
        "false_positive_names", "gold_ids", "motion",
    ]
    named.filter(pl.col("false_negatives") > 0).select(missed_cols).sort(
        ["miss_rate", "gold_signee_count", "motion_path"], descending=[True, True, False],
    ).write_csv(estimate_path / "missed-signatures.tsv", separator="\t")
    named.filter(pl.col("false_positives") > 0).select(extra_cols).sort(
        ["extra_rate", "xml_predicted_signee_count", "motion_path"], descending=[True, True, False],
    ).write_csv(estimate_path / "extra-signatures.tsv", separator="\t")

    LOGGER.info(f"Signature-matching decade summary:\n{upper}")
    for metric in QUALITY_METRICS:
        LOGGER.info(f"Average decade signature-matching {metric}: {upper[metric].mean()}")
    for metric in QUALITY_METRICS:
        LOGGER.info(f"Weighted average signature-matching {metric}: {summary['matching_quality'][metric]}")
    minimum = upper.sort("f1").row(0, named=True)
    LOGGER.info(f"Minimum signature-matching F1: {minimum['f1']} at decade {minimum['decade']}")


def main():
    version = "v99.99.99"
    prediction_source = "body"
    estimate_path = REPO / "quality/estimates/signature-matching"
    sample_path = REPO / "quality/data/qe_motion_id_signee.csv"
    person_data = default_person_data()
    estimate_path.mkdir(parents=True, exist_ok=True)

    sample = pl.read_csv(sample_path)
    person_ids, primary_names = person_tables(person_data)
    problems = gold_problems(sample, person_ids)
    comparison = comparison_rows(sample, prediction_source)
    metric = metrics(comparison, prediction_source)
    upper = decade_estimates(comparison, version)
    plot_versions(update_difference(upper, estimate_path, version), estimate_path)
    summary = {
        "aggregation": "decade",
        "sample_rows": sample.height,
        "signee_entries": sum(len(split_refs(value)) for value in sample[SIGNEE_COLUMN]),
        "valid_person_ids_in_database": len(person_ids),
        "problem_entries": problems.height,
        "matching_quality": metric,
    }
    write_outputs(comparison, problems, upper, summary, estimate_path, primary_names)

    if problems.is_empty():
        LOGGER.info("No malformed or missing signee IDs found.")
    else:
        LOGGER.info(f"Found {problems.height} problematic signee entries.")
    LOGGER.info(
        "Signature matching quality from XML %s IDs: "
        "exact_match=%.4f precision=%.4f recall=%.4f f1=%.4f",
        prediction_source, metric["exact_match"],
        metric["precision"], metric["recall"], metric["f1"],
    )


if __name__ == "__main__":
    main()
