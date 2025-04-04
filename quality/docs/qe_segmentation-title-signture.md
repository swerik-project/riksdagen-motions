# Quality estimation of core components of the Motion: title block and signature block

## Summary

We want to know the general quality of the dimensions of the motions corpus. The first step in that is to quality control the segmentation of documents


## What is the problem

We want to estimate the quality of the corpus by core dimensions, namely:

1. The Signature Block the motion
2. The Title Blocks of the Motion
3. Document date


## Estimation procedure

A stratified random sample will be generated that will be manually annotated by experts at the library. Then these annotations will be compared with the data to estimate differences compared with the data. This annotations will stored in two files under `quality/data/title-blocks.csv` and `quality/data/signature-blocks.csv`. 


### Sampling plan

A random sample of three motions per chamber and per year. 

The final estimate will based on a stratified random sample.

### Annotation guidelines

The annotator read the original motion document and write down the following in a CSV file, as one column of motion ID and additional columns for annotated data `title_block`, `signature_block`:

1. The Title Block of the motion. Title block contains the subtitle and title, e.g.:

		av herr Swännson om midsommarstångsbidrag till villaägare
	
	In the case when the title block is a single xml element, it is enough to copy the text into the csv file. When there are multiple elements, copy them all to the csv file.
	
2. The signature block of the motion, e.g.:

		Svän Svänsson i Lilla Vamba

Follow a similar principle as in (1) for single/multi xml elements.

3. No specific segmentation checks are done on the doc date elements (following the signature block), however accurate segmentation of the date element will be a byproduct of the date quality estimation (see `./qe_signing_date.md`)