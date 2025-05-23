# Date of signature quality estimation

## Summary

We want to know the proportion of signing dates that is correct in the corpus


## What is the problem

We want to know the proportion of the motions that has correct dates where the motions has been signed by the MPs. These dates are important for the Riksdag library to extract the right motions by time periods.


## Estimation procedure

A stratified random sample is manually annotated by experts at the library. 
Then these annotations are compared with the dates extracted. This file is stored under `quality/data/signature-dates.csv`.


### Sampling plan

A random sample of three motions per chamber and per year has been created. 
The final estimate will be a stratified random sample.


### Annotation guidelines

The annotator read the original motion document and write down the date in a CSV file.

