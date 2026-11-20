# Riksdagen Motions: Quality Estimation

Here we estimate quality of the Riksdagen motions corpus in various ways.

## What's here

### `./`

Python code for tests:

- qe_*.py : quality estimate tests

Support files:

- `README.md` : this file
- `__init__.py` : used for building the documentation

### `data/`

Contains data necessary to run the quality estimation code.


### `docs/`

Contains explanation and justifications for each quality dimension.


### `estimates/`

Contains versioned output of quality estimations.

## Signature matching

`qe_signature-matching.py` compares annotated person-ID sets with the IDs on
motion signature items. The default prediction source is the body; header and
union comparisons are also available through the comparison functions. Repeated
IDs count once per motion. Unknown mappings do not count as identified persons.
Precision, recall and F1 use zero for empty denominators. Overall and decade
scores pool TP/FP/FN counts; macro scores average the individual motion scores.
Exact-match intervals use the 5th and 95th posterior percentiles under a uniform
Beta(1, 1) prior.


Run the estimator regression checks with:

```sh
python -m unittest quality.test_signature_matching
```

These checks use temporary fixtures and do not rewrite corpus data or saved
estimates. They also run in the quality-estimation workflow for PRs into `dev`.
