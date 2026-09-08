#!/usr/bin/env python3
"""
Estimate motion signature matching quality against manually annotated signees.

The quality sample in ``quality/data/qe_motion_id_signee.csv`` stores one or
more semicolon-separated SWERIK person IDs per motion. This script compares
those gold-standard IDs with the signee IDs found in the matching motion XML
files. By default, XML predictions are read from ``who`` attributes on
``item type="signature"`` elements.

The script writes malformed or missing gold IDs to
``quality/estimates/signature-matching/person-id-problems.tsv``, per-motion
precision/recall/F1 and exact-match diagnostics to
``quality/estimates/signature-matching/motion-comparison.tsv``, aggregate
metrics to ``quality/estimates/signature-matching/summary.json``, and
versioned yearly estimates to
``quality/estimates/signature-matching/upper_bound.csv`` and
``quality/estimates/signature-matching/difference.csv``.
Motions with missed gold-standard signees are also written to
``quality/estimates/signature-matching/missed-signatures.tsv``. Motions with
extra XML-matched signees are written to
``quality/estimates/signature-matching/extra-signatures.tsv``.

The check matters because signature-matching quality estimates only make sense
when the gold-standard signee annotations refer to valid corpus person IDs and
can be compared with the corpus XML.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
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
SWERIK_ID_RE = re.compile(r"^i-[A-Za-z0-9]+$")
SIGNEE_COLUMN = "SWERIK_ID_MPs_signee"
DEFAULT_ESTIMATE_PATH = "quality/estimates/signature-matching"


def motions_repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_motions_path(path: str | Path) -> Path:
    path = Path(path).expanduser()
    if path.is_absolute():
        return path
    return motions_repo_root() / path


def resolve_estimate_path(path: str | Path) -> Path:
    return resolve_motions_path(path).expanduser().resolve()


def resolve_output_path(path: str | Path | None, estimate_path: Path, default_name: str) -> Path:
    if path is None:
        return estimate_path / default_name
    return resolve_motions_path(path).expanduser().resolve()


def version_number_is_valid(version: str | None) -> str:
    if not version:
        version = "v99.99.99"
    exp = re.compile(r"v\d+\.\d+\.\d+(?:b|rc\d+)?")
    if exp.fullmatch(version) or version == "v99.99.99":
        return version
    print(f"{version} is not a valid version number. Exiting.")
    sys.exit(1)


def version_key(version: str) -> list[int]:
    if version == "v99.99.99":
        return [999, 999, 999]
    match = re.fullmatch(r"v?(\d+)\.(\d+)\.(\d+)(?:b|rc\d+)?", str(version))
    if match is None:
        raise ValueError(f"Invalid version string: {version!r}")
    return [int(part) for part in match.groups()]


def default_person_data_dir() -> Path:
    root = motions_repo_root()
    candidates = []
    if os.environ.get("METADATA_PATH"):
        candidates.append(Path(get_data_location("metadata")))
    candidates.extend(
        [
            root.parent / "riksdagen-persons" / "data",
            Path.cwd().parent / "riksdagen-persons" / "data",
        ]
    )

    for candidate in candidates:
        candidate = candidate.expanduser().resolve()
        if (candidate / "person.csv").exists():
            return candidate

    tried = "\n".join(str(candidate) for candidate in candidates)
    raise FileNotFoundError(
        "Could not find riksdagen-persons/data/person.csv. "
        "Pass --person-data explicitly. Tried:\n" + tried
    )


def read_required_csv(path: Path, required_columns: set[str]) -> pd.DataFrame:
    df = pd.read_csv(path, dtype=str)
    missing = required_columns.difference(df.columns)
    if missing:
        raise ValueError(f"{path} is missing required columns: {sorted(missing)}")
    return df


def motion_path_from_link(motion: str) -> str:
    motion = str(motion).strip()
    for marker in ("/blob/main/", "/blob/dev/"):
        if marker in motion:
            return motion.split(marker, 1)[1]
    if "/data/" in motion:
        return "data/" + motion.split("/data/", 1)[1]
    return motion


def parliament_year(motion_path: str) -> str:
    metadata = infer_metadata(motion_path)
    if "sitting" in metadata:
        return metadata["sitting"]
    if "year" in metadata:
        return str(metadata["year"])
    return ""


def year_from_parliament_year(value: object) -> int:
    match = re.search(r"\d{4}", str(value))
    if match is None:
        return 0
    return int(match.group(0))


def split_signee_cell(value: object) -> list[str]:
    if pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def split_xml_reference(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).replace(";", " ").split() if part.strip()]


def explode_signee_sample(sample: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for index, row in sample.iterrows():
        motion = str(row["motion"]).strip()
        motion_path = motion_path_from_link(motion)
        raw_cell = row[SIGNEE_COLUMN]
        entries = split_signee_cell(raw_cell)
        if not entries:
            rows.append(
                {
                    "csv_row": index + 2,
                    "motion": motion,
                    "motion_path": motion_path,
                    "parliament_year": parliament_year(motion_path),
                    "entry_number": 1,
                    "raw_signee_cell": "" if pd.isna(raw_cell) else str(raw_cell),
                    "signee_entry": "",
                }
            )
            continue

        for entry_number, entry in enumerate(entries, start=1):
            rows.append(
                {
                    "csv_row": index + 2,
                    "motion": motion,
                    "motion_path": motion_path,
                    "parliament_year": parliament_year(motion_path),
                    "entry_number": entry_number,
                    "raw_signee_cell": str(raw_cell),
                    "signee_entry": entry,
                }
            )

    return pd.DataFrame(rows)


def normalize_name(value: str) -> str:
    return " ".join(value.casefold().split())


def load_person_ids(person_data: Path) -> set[str]:
    persons = read_required_csv(person_data / "person.csv", {"person_id"})
    return set(persons["person_id"].dropna().str.strip())


def load_primary_names(person_data: Path) -> dict[str, str]:
    name_path = person_data / "name.csv"
    if not name_path.exists():
        return {}
    names = read_required_csv(name_path, {"person_id", "name", "primary_name"})
    names["primary_name"] = names["primary_name"].astype(str).str.casefold()
    primary = names.loc[names["primary_name"] == "true", ["person_id", "name"]]
    return dict(primary.dropna().drop_duplicates("person_id").values)


def load_name_candidates(person_data: Path) -> dict[str, list[str]]:
    name_path = person_data / "name.csv"
    if not name_path.exists():
        return {}
    names = read_required_csv(name_path, {"person_id", "name"})
    names = names.dropna(subset=["person_id", "name"])
    candidates: dict[str, set[str]] = {}
    for _, row in names.iterrows():
        candidates.setdefault(normalize_name(row["name"]), set()).add(row["person_id"])
    return {key: sorted(value) for key, value in candidates.items()}


def format_candidates(candidate_ids: list[str], primary_names: dict[str, str]) -> str:
    formatted = []
    for person_id in candidate_ids[:10]:
        name = primary_names.get(person_id, "")
        formatted.append(f"{person_id} ({name})" if name else person_id)
    if len(candidate_ids) > 10:
        formatted.append(f"... {len(candidate_ids) - 10} more")
    return "; ".join(formatted)


def candidate_ids_for_entry(
    entry: str,
    person_ids: set[str],
    name_candidates: dict[str, list[str]],
) -> list[str]:
    if not entry:
        return []
    if entry.startswith("i-"):
        return sorted(person_id for person_id in person_ids if person_id.startswith(entry))
    return name_candidates.get(normalize_name(entry), [])


def find_problem_entries(exploded: pd.DataFrame, person_ids: set[str], person_data: Path) -> pd.DataFrame:
    name_candidates = load_name_candidates(person_data)
    primary_names = load_primary_names(person_data)
    problems = []

    for _, row in exploded.iterrows():
        entry = row["signee_entry"]
        problem = None
        if entry == "":
            problem = "blank-signee-cell"
        elif not SWERIK_ID_RE.fullmatch(entry):
            problem = "not-a-swerik-id"
        elif entry not in person_ids:
            problem = "id-not-in-person-database"

        if problem is not None:
            candidates = candidate_ids_for_entry(entry, person_ids, name_candidates)
            problem_row = row.to_dict()
            problem_row["problem"] = problem
            problem_row["candidate_person_ids"] = format_candidates(candidates, primary_names)
            problems.append(problem_row)

    return pd.DataFrame(problems)


def stable_join(values: set[str] | list[str]) -> str:
    return "; ".join(sorted(values))


def split_stable_joined_ids(value: object) -> list[str]:
    if value is None or pd.isna(value):
        return []
    return [part.strip() for part in str(value).split(";") if part.strip()]


def format_person_ids_with_names(value: object, primary_names: dict[str, str]) -> str:
    formatted = []
    for person_id in split_stable_joined_ids(value):
        name = primary_names.get(person_id, "")
        formatted.append(f"{person_id} ({name})" if name else person_id)
    return "; ".join(formatted)


def safe_divide(numerator: int, denominator: int) -> float:
    if denominator == 0:
        return 0.0
    return numerator / denominator


def f1_score(precision: float, recall: float) -> float:
    if precision + recall == 0:
        return 0.0
    return 2 * precision * recall / (precision + recall)


def empty_xml_signee_record() -> dict[str, object]:
    return {
        "body_ids": set(),
        "metadata_ids": set(),
        "unknown_signature_count": 0,
        "missing_who_count": 0,
        "non_swerik_who_values": [],
        "metadata_placeholder_count": 0,
        "metadata_non_swerik_values": [],
        "signature_item_count": 0,
        "xml_read_error": "",
    }


def extract_xml_signees(motion_path: Path) -> dict[str, object]:
    xml_signees = empty_xml_signee_record()
    try:
        root, ns = parse_tei(str(motion_path))
    except Exception as err:
        xml_signees["xml_read_error"] = repr(err)
        return xml_signees

    tei = ns["tei_ns"]
    body_ids: set[str] = set()
    non_swerik_who_values = set()
    signature_items = root.findall(f".//{tei}item[@type=\"signature\"]")
    xml_signees["signature_item_count"] = len(signature_items)
    for signature in signature_items:
        references = split_xml_reference(signature.get("who"))
        if not references:
            xml_signees["missing_who_count"] += 1
            continue
        for reference in references:
            if reference in {"unknown", "#unknown"} or reference.startswith("r-"):
                xml_signees["unknown_signature_count"] += 1
            elif reference.startswith("#"):
                reference = reference[1:]
                if SWERIK_ID_RE.fullmatch(reference):
                    body_ids.add(reference)
                else:
                    non_swerik_who_values.add(reference)
            elif SWERIK_ID_RE.fullmatch(reference):
                body_ids.add(reference)
            else:
                non_swerik_who_values.add(reference)

    metadata_ids: set[str] = set()
    metadata_non_swerik_values = set()
    idnos = root.findall(
        f".//{tei}particDesc/{tei}listPerson/{tei}person/{tei}idno"
    )
    for idno in idnos:
        references = split_xml_reference(idno.text)
        if not references:
            continue
        for reference in references:
            if reference in {"unknown", "#unknown"} or reference.startswith("r-"):
                xml_signees["metadata_placeholder_count"] += 1
            elif reference.startswith("#"):
                reference = reference[1:]
                if SWERIK_ID_RE.fullmatch(reference):
                    metadata_ids.add(reference)
                else:
                    metadata_non_swerik_values.add(reference)
            elif SWERIK_ID_RE.fullmatch(reference):
                metadata_ids.add(reference)
            else:
                metadata_non_swerik_values.add(reference)

    xml_signees["body_ids"] = body_ids
    xml_signees["metadata_ids"] = metadata_ids
    xml_signees["non_swerik_who_values"] = sorted(non_swerik_who_values)
    xml_signees["metadata_non_swerik_values"] = sorted(metadata_non_swerik_values)
    return xml_signees


def prediction_ids(xml_signees: dict[str, object], prediction_source: str) -> set[str]:
    body_ids = set(xml_signees["body_ids"])
    metadata_ids = set(xml_signees["metadata_ids"])
    if prediction_source == "body":
        return body_ids
    if prediction_source == "metadata":
        return metadata_ids
    if prediction_source == "union":
        return body_ids | metadata_ids
    raise ValueError(f"Unknown prediction source: {prediction_source}")


def compare_gold_to_xml(sample: pd.DataFrame, prediction_source: str) -> tuple[pd.DataFrame, dict[str, object]]:
    comparison_rows = []
    totals = {
        "true_positives": 0,
        "false_positives": 0,
        "false_negatives": 0,
        "exact_matches": 0,
        "xml_read_errors": 0,
        "body_metadata_disagreements": 0,
        "unknown_signature_items": 0,
        "missing_who_items": 0,
        "non_swerik_who_values": 0,
        "signature_items": 0,
        "gold_positive_ids": 0,
        "predicted_positive_ids": 0,
    }

    for index, row in sample.iterrows():
        motion = str(row["motion"]).strip()
        motion_path = motion_path_from_link(motion)
        local_motion_path = motions_repo_root() / motion_path
        gold_ids = {
            entry
            for entry in split_signee_cell(row[SIGNEE_COLUMN])
            if SWERIK_ID_RE.fullmatch(entry)
        }

        xml_signees = extract_xml_signees(local_motion_path)
        predicted_ids = prediction_ids(xml_signees, prediction_source)
        body_ids = set(xml_signees["body_ids"])
        metadata_ids = set(xml_signees["metadata_ids"])

        tp_ids = gold_ids & predicted_ids
        fp_ids = predicted_ids - gold_ids
        fn_ids = gold_ids - predicted_ids
        gold_signee_count = len(gold_ids)
        predicted_signee_count = len(predicted_ids)
        precision = safe_divide(len(tp_ids), len(tp_ids) + len(fp_ids))
        recall = safe_divide(len(tp_ids), len(tp_ids) + len(fn_ids))
        f1 = f1_score(precision, recall)
        exact_match = gold_ids == predicted_ids

        totals["true_positives"] += len(tp_ids)
        totals["false_positives"] += len(fp_ids)
        totals["false_negatives"] += len(fn_ids)
        totals["exact_matches"] += int(exact_match)
        totals["xml_read_errors"] += int(bool(xml_signees["xml_read_error"]))
        totals["body_metadata_disagreements"] += int(body_ids != metadata_ids)
        totals["unknown_signature_items"] += int(xml_signees["unknown_signature_count"])
        totals["missing_who_items"] += int(xml_signees["missing_who_count"])
        totals["non_swerik_who_values"] += len(xml_signees["non_swerik_who_values"])
        totals["signature_items"] += int(xml_signees["signature_item_count"])
        totals["gold_positive_ids"] += len(gold_ids)
        totals["predicted_positive_ids"] += len(predicted_ids)

        comparison_rows.append(
            {
                "csv_row": index + 2,
                "parliament_year": parliament_year(motion_path),
                "motion_path": motion_path,
                "exact_match": exact_match,
                "precision": precision,
                "recall": recall,
                "f1": f1,
                "true_positives": len(tp_ids),
                "false_positives": len(fp_ids),
                "false_negatives": len(fn_ids),
                "gold_signee_count": gold_signee_count,
                "xml_predicted_signee_count": predicted_signee_count,
                "miss_rate": safe_divide(len(fn_ids), gold_signee_count),
                "coverage": recall,
                "extra_rate": safe_divide(len(fp_ids), predicted_signee_count),
                "gold_ids": stable_join(gold_ids),
                "xml_predicted_ids": stable_join(predicted_ids),
                "true_positive_ids": stable_join(tp_ids),
                "false_positive_ids": stable_join(fp_ids),
                "false_negative_ids": stable_join(fn_ids),
                "xml_body_ids": stable_join(body_ids),
                "xml_metadata_ids": stable_join(metadata_ids),
                "body_metadata_agree": body_ids == metadata_ids,
                "signature_item_count": xml_signees["signature_item_count"],
                "unknown_signature_count": xml_signees["unknown_signature_count"],
                "missing_who_count": xml_signees["missing_who_count"],
                "non_swerik_who_values": "; ".join(xml_signees["non_swerik_who_values"]),
                "metadata_placeholder_count": xml_signees["metadata_placeholder_count"],
                "metadata_non_swerik_values": "; ".join(
                    xml_signees["metadata_non_swerik_values"]
                ),
                "xml_read_error": xml_signees["xml_read_error"],
                "motion": motion,
            }
        )

    aggregate_precision = safe_divide(
        totals["true_positives"],
        totals["true_positives"] + totals["false_positives"],
    )
    aggregate_recall = safe_divide(
        totals["true_positives"],
        totals["true_positives"] + totals["false_negatives"],
    )
    comparison = pd.DataFrame(comparison_rows)
    macro_precision = safe_divide(comparison["precision"].sum(), len(comparison))
    macro_recall = safe_divide(comparison["recall"].sum(), len(comparison))
    macro_f1 = safe_divide(comparison["f1"].sum(), len(comparison))
    mean_miss_rate = safe_divide(comparison["miss_rate"].sum(), len(comparison))
    mean_extra_rate = safe_divide(comparison["extra_rate"].sum(), len(comparison))
    missing = comparison.loc[comparison["false_negatives"] > 0]
    extra = comparison.loc[comparison["false_positives"] > 0]
    full_misses = missing.loc[missing["true_positives"] == 0]
    no_prediction_misses = missing.loc[missing["xml_predicted_ids"] == ""]

    metrics = {
        "prediction_source": prediction_source,
        "exact_match": safe_divide(totals["exact_matches"], len(sample)),
        "precision": aggregate_precision,
        "recall": aggregate_recall,
        "f1": f1_score(aggregate_precision, aggregate_recall),
        "macro_precision": macro_precision,
        "macro_recall": macro_recall,
        "macro_f1": macro_f1,
        "mean_miss_rate": mean_miss_rate,
        "mean_extra_rate": mean_extra_rate,
        "motions_with_missed_signees": int(len(missing)),
        "motions_with_extra_signees": int(len(extra)),
        "motions_with_full_miss": int(len(full_misses)),
        "motions_with_partial_miss": int(len(missing) - len(full_misses)),
        "motions_with_no_xml_prediction": int(len(no_prediction_misses)),
        **totals,
    }
    return comparison, metrics


def aggregate_by_year(comparison: pd.DataFrame, version: str) -> pd.DataFrame:
    df = comparison.copy()
    df["year"] = df["parliament_year"].apply(year_from_parliament_year)
    df = df.loc[df["year"] > 0]

    if df.empty:
        return pd.DataFrame(
            columns=[
                "version",
                "year",
                "motions",
                "exact_matches",
                "true_positives",
                "false_positives",
                "false_negatives",
                "gold_positive_ids",
                "predicted_positive_ids",
                "precision",
                "recall",
                "f1",
                "exact_match",
                "macro_precision",
                "macro_recall",
                "macro_f1",
                "mean_miss_rate",
                "mean_extra_rate",
                "exact_match_lower",
                "exact_match_upper",
            ]
        )

    by_year = (
        df.groupby("year")
        .agg(
            motions=("motion_path", "count"),
            exact_matches=("exact_match", "sum"),
            true_positives=("true_positives", "sum"),
            false_positives=("false_positives", "sum"),
            false_negatives=("false_negatives", "sum"),
            gold_positive_ids=("gold_signee_count", "sum"),
            predicted_positive_ids=("xml_predicted_signee_count", "sum"),
            macro_precision=("precision", "mean"),
            macro_recall=("recall", "mean"),
            macro_f1=("f1", "mean"),
            mean_miss_rate=("miss_rate", "mean"),
            mean_extra_rate=("extra_rate", "mean"),
        )
        .reset_index()
        .sort_values("year")
    )
    by_year["precision"] = by_year.apply(
        lambda row: safe_divide(
            int(row["true_positives"]),
            int(row["true_positives"]) + int(row["false_positives"]),
        ),
        axis=1,
    )
    by_year["recall"] = by_year.apply(
        lambda row: safe_divide(
            int(row["true_positives"]),
            int(row["true_positives"]) + int(row["false_negatives"]),
        ),
        axis=1,
    )
    by_year["f1"] = by_year.apply(
        lambda row: f1_score(float(row["precision"]), float(row["recall"])),
        axis=1,
    )
    by_year["exact_match"] = by_year.apply(
        lambda row: safe_divide(int(row["exact_matches"]), int(row["motions"])),
        axis=1,
    )
    by_year["exact_match_lower"] = by_year.apply(
        lambda row: beta.ppf(
            0.05,
            int(row["exact_matches"]) + 1,
            int(row["motions"]) - int(row["exact_matches"]) + 1,
        ),
        axis=1,
    )
    by_year["exact_match_upper"] = by_year.apply(
        lambda row: beta.ppf(
            0.95,
            int(row["exact_matches"]) + 1,
            int(row["motions"]) - int(row["exact_matches"]) + 1,
        ),
        axis=1,
    )
    by_year.insert(0, "version", version)

    return by_year[
        [
            "version",
            "year",
            "motions",
            "exact_matches",
            "true_positives",
            "false_positives",
            "false_negatives",
            "gold_positive_ids",
            "predicted_positive_ids",
            "precision",
            "recall",
            "f1",
            "exact_match",
            "macro_precision",
            "macro_recall",
            "macro_f1",
            "mean_miss_rate",
            "mean_extra_rate",
            "exact_match_lower",
            "exact_match_upper",
        ]
    ]


def update_difference(by_year: pd.DataFrame, estimate_path: Path, version: str) -> pd.DataFrame:
    diff_path = estimate_path / "difference.csv"

    if diff_path.exists():
        existing = pd.read_csv(diff_path)
        if version == "v99.99.99":
            existing = existing[existing["version"] != "v99.99.99"]
            combined = pd.concat([existing, by_year], ignore_index=True)
        elif version in existing["version"].unique():
            print(f"Version {version} already exists in {diff_path}, skipping append.")
            combined = existing
        else:
            combined = pd.concat([existing, by_year], ignore_index=True)
    else:
        combined = by_year

    combined.to_csv(diff_path, index=False)
    return combined


def plot_versions(
    difference: pd.DataFrame,
    output_path: Path,
    metric: str,
    title: str,
    show: bool,
    n_versions: int = 6,
) -> None:
    if difference.empty or metric not in difference.columns:
        print(f"No {metric} estimates available. Cannot plot.")
        return

    df = difference.copy()
    df["version"] = df["version"].astype(str).str.strip()
    valid_versions = [v for v in df["version"].unique() if "rc" not in str(v).lower()]
    version_sorted = sorted(valid_versions, key=version_key, reverse=True)[:n_versions]

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = list("bgrcmyk")
    for index, version in enumerate(version_sorted):
        dfv = df[df["version"] == version].sort_values("year")
        if dfv.empty:
            continue
        ax.plot(
            dfv["year"],
            dfv[metric],
            linewidth=1.75,
            label=version,
            color=colors[index % len(colors)],
        )

    ax.set_title(title)
    ax.set_xlabel("Beginning of parliamentary year")
    ax.set_ylabel(metric)
    ax.legend(loc="upper left")
    ax.set_ylim(0, 1)
    fig.tight_layout()
    fig.savefig(output_path)

    if show:
        fig.show()
    plt.close(fig)


def print_quality_summary(by_year: pd.DataFrame, metrics: dict[str, object], title: str) -> None:
    print(f"Upper bound {title} summary:")
    print(by_year)
    print(f"Average {title} precision:", by_year["precision"].mean())
    print(f"Average {title} recall:", by_year["recall"].mean())
    print(f"Average {title} f1:", by_year["f1"].mean())
    print(f"Average {title} exact match:", by_year["exact_match"].mean())
    print(f"Weighted average {title} precision:", metrics["precision"])
    print(f"Weighted average {title} recall:", metrics["recall"])
    print(f"Weighted average {title} f1:", metrics["f1"])
    print(f"Weighted average {title} exact match:", metrics["exact_match"])
    if not by_year.empty:
        min_idx = by_year["f1"].idxmin()
        min_year = by_year.loc[min_idx, "year"]
        min_value = by_year.loc[min_idx, "f1"]
        print(f"Minimum {title}:", min_value, "at year:", min_year)


def write_continuous_outputs(
    by_year: pd.DataFrame,
    estimate_path: Path,
    version: str,
    show: bool,
) -> dict[str, str]:
    estimate_path.mkdir(parents=True, exist_ok=True)
    upper_path = estimate_path / "upper_bound.csv"
    by_year.to_csv(upper_path, index=False)
    difference = update_difference(by_year, estimate_path, version)

    plot_paths = {}
    for metric in ["f1", "precision", "recall", "exact_match"]:
        output_path = estimate_path / f"signature-matching-{metric.replace('_', '-')}.png"
        plot_versions(
            difference,
            output_path=output_path,
            metric=metric,
            title=f"signature-matching-{metric.replace('_', '-')}",
            show=show,
        )
        plot_paths[metric] = str(output_path)

    return {
        "upper_bound_output": str(upper_path),
        "difference_output": str(estimate_path / "difference.csv"),
        "plot_outputs": plot_paths,
    }


def write_outputs(
    problems: pd.DataFrame,
    comparison: pd.DataFrame,
    summary: dict[str, object],
    output_path: Path,
    comparison_path: Path,
    missing_path: Path,
    extra_path: Path,
    summary_path: Path,
    primary_names: dict[str, str],
) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    comparison_path.parent.mkdir(parents=True, exist_ok=True)
    missing_path.parent.mkdir(parents=True, exist_ok=True)
    extra_path.parent.mkdir(parents=True, exist_ok=True)
    summary_path.parent.mkdir(parents=True, exist_ok=True)

    problem_columns = [
        "problem",
        "csv_row",
        "parliament_year",
        "motion_path",
        "entry_number",
        "signee_entry",
        "candidate_person_ids",
        "motion",
        "raw_signee_cell",
    ]
    if problems.empty:
        pd.DataFrame(columns=problem_columns).to_csv(output_path, sep="\t", index=False)
    else:
        problems[problem_columns].to_csv(output_path, sep="\t", index=False)

    comparison.to_csv(comparison_path, sep="\t", index=False)

    comparison_with_names = comparison.copy()
    comparison_with_names["false_negative_names"] = comparison_with_names[
        "false_negative_ids"
    ].apply(lambda value: format_person_ids_with_names(value, primary_names))
    comparison_with_names["false_positive_names"] = comparison_with_names[
        "false_positive_ids"
    ].apply(lambda value: format_person_ids_with_names(value, primary_names))

    missing_columns = [
        "motion_path",
        "parliament_year",
        "false_negatives",
        "gold_signee_count",
        "miss_rate",
        "coverage",
        "true_positives",
        "false_positives",
        "unknown_signature_count",
        "signature_item_count",
        "false_negative_ids",
        "false_negative_names",
        "xml_predicted_ids",
        "motion",
    ]
    missing = comparison_with_names.loc[
        comparison_with_names["false_negatives"] > 0, missing_columns
    ]
    missing = missing.sort_values(
        ["miss_rate", "gold_signee_count", "motion_path"],
        ascending=[False, False, True],
    )
    missing.to_csv(missing_path, sep="\t", index=False)

    extra_columns = [
        "motion_path",
        "parliament_year",
        "false_positives",
        "xml_predicted_signee_count",
        "extra_rate",
        "precision",
        "true_positives",
        "false_negatives",
        "unknown_signature_count",
        "signature_item_count",
        "false_positive_ids",
        "false_positive_names",
        "gold_ids",
        "motion",
    ]
    extra = comparison_with_names.loc[
        comparison_with_names["false_positives"] > 0, extra_columns
    ]
    extra = extra.sort_values(
        ["extra_rate", "xml_predicted_signee_count", "motion_path"],
        ascending=[False, False, True],
    )
    extra.to_csv(extra_path, sep="\t", index=False)

    with open(summary_path, "w", encoding="utf-8") as outfile:
        json.dump(summary, outfile, indent=2, ensure_ascii=False)
        outfile.write("\n")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--sample",
        default="quality/data/qe_motion_id_signee.csv",
        help="Path to the manually annotated motion signee sample CSV.",
    )
    parser.add_argument(
        "--person-data",
        default=None,
        help="Path to riksdagen-persons/data. Defaults to METADATA_PATH or ../riksdagen-persons/data.",
    )
    parser.add_argument(
        "-o",
        "--estimate-path",
        default=DEFAULT_ESTIMATE_PATH,
        help="Directory where estimate outputs are written.",
    )
    parser.add_argument(
        "-v",
        "--version",
        default="v99.99.99",
        help="Version string for this run.",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Where to write malformed or missing signee IDs.",
    )
    parser.add_argument(
        "--comparison-output",
        default=None,
        help="Where to write per-motion gold-vs-XML comparison metrics.",
    )
    parser.add_argument(
        "--missing-output",
        default=None,
        help="Where to write motions whose XML predictions miss gold-standard signees.",
    )
    parser.add_argument(
        "--extra-output",
        default=None,
        help="Where to write motions whose XML predictions add non-gold signees.",
    )
    parser.add_argument(
        "--summary",
        default=None,
        help="Where to write aggregate check counts and quality metrics.",
    )
    parser.add_argument(
        "--show",
        default="False",
        help="Whether to show plots interactively (True/False).",
    )
    parser.add_argument(
        "--prediction-source",
        choices=["body", "metadata", "union"],
        default="body",
        help="Which XML signee IDs to treat as signature-matching predictions.",
    )
    parser.add_argument(
        "--fail-on-problems",
        action="store_true",
        help="Exit non-zero when malformed or missing signee IDs are found.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    args.show = not args.show.lower().startswith("f")
    version = version_number_is_valid(args.version)
    sample_path = resolve_motions_path(args.sample)
    estimate_path = resolve_estimate_path(args.estimate_path)
    output_path = resolve_output_path(args.output, estimate_path, "person-id-problems.tsv")
    comparison_path = resolve_output_path(
        args.comparison_output,
        estimate_path,
        "motion-comparison.tsv",
    )
    missing_path = resolve_output_path(
        args.missing_output,
        estimate_path,
        "missed-signatures.tsv",
    )
    extra_path = resolve_output_path(
        args.extra_output,
        estimate_path,
        "extra-signatures.tsv",
    )
    summary_path = resolve_output_path(args.summary, estimate_path, "summary.json")
    person_data = Path(args.person_data).expanduser().resolve() if args.person_data else default_person_data_dir()

    sample = read_required_csv(sample_path, {"motion", SIGNEE_COLUMN})
    person_ids = load_person_ids(person_data)
    primary_names = load_primary_names(person_data)
    exploded = explode_signee_sample(sample)
    problems = find_problem_entries(exploded, person_ids, person_data)
    comparison, metrics = compare_gold_to_xml(sample, args.prediction_source)
    by_year = aggregate_by_year(comparison, version)
    continuous_outputs = write_continuous_outputs(
        by_year,
        estimate_path=estimate_path,
        version=version,
        show=args.show,
    )

    problem_counts = problems["problem"].value_counts().to_dict() if not problems.empty else {}
    summary = {
        "sample_path": str(sample_path),
        "person_data": str(person_data),
        "estimate_path": str(estimate_path),
        "version": version,
        "sample_rows": int(len(sample)),
        "signee_entries": int(len(exploded)),
        "unique_signee_entries": int(exploded["signee_entry"].replace("", pd.NA).dropna().nunique()),
        "valid_person_ids_in_database": int(len(person_ids)),
        "problem_entries": int(len(problems)),
        "problem_counts": problem_counts,
        "problem_output": str(output_path),
        "comparison_output": str(comparison_path),
        "missing_signature_output": str(missing_path),
        "extra_signature_output": str(extra_path),
        **continuous_outputs,
        "matching_quality": metrics,
    }

    write_outputs(
        problems,
        comparison,
        summary,
        output_path,
        comparison_path,
        missing_path,
        extra_path,
        summary_path,
        primary_names,
    )
    print_quality_summary(by_year, metrics, title="signature-matching")
    print("Resources cleaned up.")

    LOGGER.info(
        "Checked %s signee entries from %s sampled motions against %s person IDs.",
        summary["signee_entries"],
        summary["sample_rows"],
        summary["valid_person_ids_in_database"],
    )
    if problems.empty:
        LOGGER.info("No malformed or missing signee IDs found.")
    else:
        LOGGER.warning("Found %s problematic signee entries: %s", len(problems), problem_counts)
        LOGGER.warning("Wrote details to %s", output_path)
    LOGGER.info(
        "Signature matching quality from XML %s IDs: exact_match=%.4f precision=%.4f recall=%.4f f1=%.4f",
        args.prediction_source,
        metrics["exact_match"],
        metrics["precision"],
        metrics["recall"],
        metrics["f1"],
    )
    LOGGER.info(
        "Found %s motions with missed gold-standard signees; wrote %s.",
        metrics["motions_with_missed_signees"],
        missing_path,
    )
    LOGGER.info(
        "Found %s motions with extra XML-matched signees; wrote %s.",
        metrics["motions_with_extra_signees"],
        extra_path,
    )

    if args.fail_on_problems and not problems.empty:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
