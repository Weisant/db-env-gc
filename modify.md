# Pipeline Notes

This document records the current code shape and prevents old `artifact_plan`, `validator`, and `state` writing pipeline descriptions from spreading further.

## Main Pipeline

The current main flow is:

`parser -> profiler -> planner -> generator`

- `parser`: standardizes user input and collects NVD plus official advisory evidence for CVE tasks.
- `profiler`: inherits the parser task, database type, relevance classification, and evidence context to produce `EnvironmentProfile`.
- `planner`: consumes only `EnvironmentProfile`, reads the strategy graph and local templates, probes DockerHub tags when needed, and produces `EnvironmentPlan`.
- `generator`: consumes only `EnvironmentPlan`, generates complete Docker project files, and writes them to the output directory.

## Removed Legacy Stages

These stages are no longer part of the current main pipeline:

- `artifact_plan`
- `validator`
- `validator_repair`
- `state` directory writing

The run ends when the generator writes project files. The project root still writes `terminal_log.txt` and `agents_log.txt`; project output directories no longer write `state/` state files.
