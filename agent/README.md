# Agent Package

`agent/` implements the four-agent main pipeline for `db-env-gc`:

`user input -> parser(+evidence tools) -> profiler -> planner(+artifact tools) -> generator(+file tools)`

## parser

Location: [parser.py](/db-env-gc/agent/parser.py)
Prompt: [prompts/parser.md](/db-env-gc/agent/prompts/parser.md)

Responsibilities:

- Standardize user input into `TaskInput`
- Call `tools/evidence_tools.py` directly to collect external evidence when the task contains a CVE
- Output `ParsedTaskBundle`

## profiler

Location: [profiler.py](/db-env-gc/agent/profiler.py)
Prompt: [prompts/profiler.md](/db-env-gc/agent/prompts/profiler.md)

Responsibilities:

- Generate `EnvironmentProfile` from the standardized task, database type inference, relevance classification, and parser evidence context
- Decide the affected asset, final version, version ecosystem, runtime configuration, artifact requirements, vulnerability conditions, and build semantic constraints
- Do not select Docker build paths or call image/source probing tools

## planner

Location: [planner.py](/db-env-gc/agent/planner.py)
Runtime rules: `strategy-selection/decision_graph.yaml`, `templates/db_build_path_catalog.jsonl`, `templates/dockerhub_repository_catalog.jsonl`

Responsibilities:

- Consume only the profiler profile
- Execute the decision graph and read local template indexes
- Select an image candidate at DockerHub nodes and call tools to verify the tag
- Output `EnvironmentPlan` for the generator

Planner build paths include:

- `official_image_direct`
- `official_image_extended`
- `custom_package_repo`
- `language_package_repo`
- `system_package_repo`
- `prebuilt_binary`
- `source_compile`

## generator

Location: [generator.py](/db-env-gc/agent/generator.py)
Prompt: [prompts/generator/core.md](/db-env-gc/agent/prompts/generator/core.md)

Responsibilities:

- Generate complete Docker project files only from the `EnvironmentPlan` build blueprint assembled by the planner
- Call file tools inside the generator to create the run directory and write files
- Output `ProjectArtifacts`, the run directory, and the list of written files

## Data Flow

The core data flow is:

`TaskInput + Evidence -> EnvironmentProfile -> EnvironmentPlan -> ProjectArtifacts`

The main flow no longer uses separate `artifact_plan`, `validator`, or `state` writing modules.
