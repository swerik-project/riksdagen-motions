# Data Tests

This directory is dedicated to testing the integrity of data under `data/`.


## What's here?

Python unittest test files and


### `./data/`

Contains data used for data tests.


### `./docs/`

Contains documentation about the test files.

- `general-integrity-tests.md`


### `./results/`

Contains versioned results of Data Tests.

- `integrity-results.tsv`: versioned summary results from General Data Integrity Tests
- various files prefixed with `integrity_v*...`: output of individual test cases from the General Data Integrity Test Suite. When the test result is not perfect, problem files are listed.