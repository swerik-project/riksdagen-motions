# Quality estimation of core components of the Motion: att-satser

## Summary

We want to know the general quality of the dimensions of the motions corpus. The first step in that is to quality control the segmentation of documents


## What is the problem

We want to estimate the quality of the corpus by core dimensions, namely:

1. The Block containing "att-satser"


## Estimation procedure

A stratified random sample will be generated that will be manually annotated by experts at the library. Then these annotations will be compared with the data to estimate differences compared with the data. This annotated file will stored under `quality/data/att-satser.csv`.


### Sampling plan

A random sample of three motions per year. 

The final estimate will based on a stratified random sample.


### Annotation guidelines

The annotator read the original motion document and write down the following in a CSV file, as one column of motion ID and additional columns for annotated data:

	1. att_satser

#### Further explanation:

1. The Title Block of the motion. Title block contains the subtitle and title, e.g.:

		Jag hemställa
		
		  - att subventionera inköp av midsommarstång för varje hushåll en gång under en tioårsperiod med 350 kronor
		  - att bevilja engångsbidrag retroaktivt för hushåll med befintlig midsommarstång
	
	In the case when the att satser block is a single xml element, it is enough to copy the text into the csv file. When there are multiple elements, copy them all to the csv file.
	
	In more recent records, att-satser have been promoted to self-standing section with a head `Förslag till riksdagsbeslut`. For the purpose of this quality dimension, att-satser and förslag... are treated together.