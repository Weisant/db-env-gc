# db-env-gc

`db-env-gc` is an agent project for generating database Docker environments.

The current main pipeline has four agents:

1. `parser`: parses user input and collects external evidence with evidence tools when the task contains a CVE
2. `profiler`: inherits the parser task, database inference, relevance classification, and evidence to produce a structured reproduction profile
3. `planner`: consumes only the profiler profile, performs required artifact probes, and selects the build path, build template, and build plan
4. `generator`: generates complete Docker project files only from the planner build blueprint and writes them directly to disk

The project no longer includes separate `artifact_plan`, `validator`, or `state` writing stages. The run ends when the generator writes project files to the output directory.

## Build Paths

The planner chooses one of these build paths:

- `official_image_direct`: use an available official image directly
- `official_image_extended`: install extra tools or dependencies on top of an official image
- `custom_package_repo`: use a specific URL, historical package source, `.deb`, or `.rpm`
- `language_package_repo`: install from a language package repository such as Maven, npm, PyPI/pip, RubyGems, Cargo, Go modules, or NuGet
- `system_package_repo`: install from system package repositories
- `prebuilt_binary`: use an official prebuilt binary package
- `source_compile`: use source code, a Git tag/commit, patches, or custom compilation

High-level delivery semantics are still preserved:

- `compose_only`
- `dockerfile_plus_compose`
- `source_build`

## Usage

```bash
python main.py
```

You can also specify an output directory:

```bash
python main.py ./output

python main.py --parser-only --cve CVE-XXXX-XXXX
```

After startup, enter natural language directly, or enter a task description in JSON / key-value form.

Generate a Docker environment for reproducing CVE-2022-0543.

## Output

Each run creates a separate directory under `output/`, usually containing:

- `docker-compose.yml`
- `Dockerfile` when required by the planner `requires_dockerfile` value
- `.env.example`
- `README.md`
- optional initialization scripts, configuration files, or helper scripts

The project root records:

- `terminal_log.txt`
- `agents_log.txt`

`agents_log.txt` stores structured logs for parser, profiler, planner, and generator. Project output directories no longer contain `state/` state files.
