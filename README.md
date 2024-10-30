# Riksdagen motions

Corpus of motions from the Swedish Riksdag.

## Structure of the corpus

The corpus is organized into the following structure:


### `data/`

The motions data is here organized in subdirectories by parliament year.

There is also a `reg/` directory and `fort/` directory containing indexes to the motions in the bicameral period. 

Motions are grouped into chambers by `data/mot-ek.xml`, `data/mot-fk.xml` (not implemented), and `data/mot-ak.xml` (not implemented). 


### `docs/`

HTML documentation about this corpus.


### `test/`

The `test/` directory contains data integrity tests in the form of python scripts. Supplementary data used for these tests is stored under `test/data/`, versioned test results are stored under `test/results/`, and documentation about the tests is stored under `test/docs/`.


### `quality/`

(not implemented) 

The `quality/` directory contains python scripts that estimate quality of the data. The substructure of `quality/` is analogous to `test/`.


## How to cite?

Please refer to the `CITATION.cff` file for more information about how to cite this data set.