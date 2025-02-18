# Quality estimation of core aspects of the motions

## Summary
We want to know the general quality of the dimensions of the motions corpus

## What is the problem
We want to estimate the quality of the corpus by core dimensions, namely:
1. The MPs that sign the motion
2. The Title of the Motion
3. The "att-satser" of the motion

## Estimation procedure
A stratified random sample will be generated that will be manually annotated by experts at the library.
Then these annotations will be compared with the data to estimate differences compared with the data.
This annotated file will stored under quality/data/core_dimension.csv.

### Sampling plan
A random sample of three motions per 5-year period (e.g 1867-1869, 1870-1874, etc) and. 
The final estimate will based on a stratified random sample.

### Annotation guidelines
The annotator read the original motion document and write down the following in a CSV file,
as one column of motion ID and additional columns for annotated data:

1. The Swerik-IDs of the MPs that signed the motions, separated by ";"
2. The Title of the Motion (can be copied)
3. The first sentence of each "att-sats", separated by ";"

