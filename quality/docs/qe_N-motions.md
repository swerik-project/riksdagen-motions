# Number of Motions

## Summary

Check that there is a relatively consistent number of motions from version to version, and that the number of motions per year is reasonable in relation to neighboring years and any other information we have.


## What is the problem

Currently, we don't have a baseline of how many motions there _should_ be in the corpus, but we want to (a) make sure that we aren't unintentionally adding or removing wild numbers of motions from version to version, and (b) visualizing the number of motions as a time series can help us identify potential issues with duplicate/missing motions.


## Estimation procedure

1. Check the total number of motions per parliament year as well as individual committee motions at prerelease.

2. For each parliament year / committee, additions / deletions exceeding a 5% tolerance result in a warning.

3. Plots are produced for visual inspection.

