# How to contribute?

## Quick start

1. Clone or fork the repository
	- clone the repository if your user has write access in the SWERIK organization, i.e. if the SWERIK project is listed under your organizations on GitHub.
	- otherwise create a fork
2. Create a new branch from the current `dev` branch
3. Make edits and run tests locally
	- it should already be emphasized here that edits leading to a pull request should address _one_ issue. Pull requests with edits relaing to multiple issues are difficult to evaluate. Feel free to open an issue in the repo to discuss proposed changes already at this stage.
	- look in the `test/` folder to see which tests are available. All tests are Python scripts or `unittest` classes. 
	- if tests pass proceed to step 4
	- if tests fail, address the failures before proceeding to step 4. Feel free to reach out to us for advice and assistance at this stage
4. commit and push
	- watch github actions and if all the tests that run pass, proceed to (5)
5. Open Pull Request
	- if any significant amount of time has passed since creating your fork/branch, it's advisable to fetch the most recent changes from our upstream dev branch before opening a pull request.
	- Pull requests should be opened into the `dev` branch. Any PR into `main` will be automatically rejected.
	- if all automated tests pass at the pull request phase, we manually evaluate a sample of edits and decide how to proceed with merging. See [Yrjänäinen, Jonasson, & Magnusson 2025](https://arxiv.org/abs/2510.11428) for a description of how we evaluate samples at this stage.
	

## Good to observe

### Evaluation of edits

When deciding whether to merge a PR, we evaluate a sample of edits, which means we rely on git diffs to see proposed changes to the repository. There are some things to keep in mind in order to make evaluation of the proposal as straightforward as possible:
 - Check that your software isn't rewriting end-line characters or replacing tabs with spaces or spaces with tabs. This will cause a diff to show that every line is edited and your PR to be rejected.
 - Formatting and sorting: use the [pyriksdagen](https://pypi.org/project/pyriksdagen/) module `pyriksdagen.io.write_tei`  to write xml documents, carefully observe column sort order in csv files (to be documented). Changes to sort order and formatting obfuscate substantive changes in a PR.
 - Isolate types of edits: It's generally better to have one pull request per proposed change so that the edits can be evaluated. If one would, for example, add mandate periods to `member_of_parliament.csv` and at the same time merge consecutive mandates into a single row, it becomes more difficult to evaluate the additions, particularly if two types of changes occur disproportionately. We strongly recommend incoming PRs address a single issue. 