# OCR Quality Estimate

## Summary

We estimate OCR quality in a sample.
- 3 lines from three pages per year and chamber
- word-error rate (WER)
- character-error rate (CER)
- levenshtein distance (LEV)


## What is the problem

We want to understand how closely OCR-rendered text matches the original. 


## Estimation procedure 

We calculate WER, CER and LEV between manually annotated lines (directly from PDF) and the identified most-likely line (XML).


### Sampling plan [if applicable]

3 lines are annotated from three randomly selected pages per year, per chamber.


### Annotation guidelines [if applicable]

Annotator first counts the lines and adds the number of lines to the `.csv` annotation file. A script then selects a three random, non-repeating numbers from the range 1--number of lines on page. These are the three lines to annotate.

Annotator writes down exactly what is contained in the specified line in the csv file.


## Previous experiences

Couple of workdays. 