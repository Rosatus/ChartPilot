# Portable Runtime Guidelines

## Scenario: Build And Invoke WinPython

### Scope

Use this contract when changing Python versions, dependencies, templates, process invocation,
runtime tests, or release packaging. Generated `runtime/`, `wheelhouse/`, `workspace/`, `build/`,
and `dist/` directories remain outside Git.

### Source Contracts

- `runtime.lock.json`: WinPython asset, size/hash, CPython version/architecture, interpreter path,
  dependency files, and child environment.
- `requirements.txt`: exact direct pins.
- `requirements.runtime.lock.txt`: complete CPython 3.13 Windows x64 wheel set with SHA-256.
- `runtime/runtime-manifest.json`: installed identity, distributions, wheels, hashes, environment,
  and health.
- `release.files.json`: explicit release root-file allowlist.

Canonical interpreter:

```text
runtime/winpython/python/python.exe
```

Invoke task code only as an argument array:

```text
<absolute-bundled-python> -I <absolute-task-script> --context <absolute-context-json>
```

Never search `PATH`, `py.exe`, the registry, Conda, venvs, or user site-packages. Never install a
dependency on the target machine.

### Child Environment

Apply the runtime manifest:

```text
set: PYTHONNOUSERSITE=1, PYTHONUTF8=1, PYTHONDONTWRITEBYTECODE=1, MPLBACKEND=Agg
unset: PYTHONHOME, PYTHONPATH, VIRTUAL_ENV, CONDA_PREFIX, CONDA_DEFAULT_ENV
workspace paths: HOME, TEMP, TMP, MPLCONFIGDIR, PYTHONPYCACHEPREFIX
```

Build PowerShell must stay ASCII for Windows PowerShell 5.1. Store non-ASCII filenames in UTF-8
JSON or Python source.

### Required Validation

- Verify WinPython ZIP size/SHA-256 and CPython 3.13.13 x64 identity.
- Regenerate dependency lock from wheelhouse and compare to the committed lock.
- Run `pip check` and import pandas, numpy, matplotlib, Pillow, mcp, and PyYAML.
- Run all three adaptive template `--help` commands with bundled Python.
- Run Agent unit tests and adaptive CSV-to-PNG smoke.
- Validate the single product Skill with `quick_validate.py`.
- Inspect release ZIP required/forbidden files and third-party licenses.

If build/install/tests fail, keep staging and the prior runtime. Replace the complete runtime only
after every check succeeds; restore it on placement failure.

## Scenario: Adaptive Prompt-Plus-CSV Execution

### 1. Scope / Trigger

Apply this contract whenever a change touches prompt-plus-CSV routing, the ChartPilot MCP bridge,
task templates, product Skills, stage artifacts, or generated-code execution. Every request uses
one adaptive route; there is no deterministic, simple-task, or compatibility route.

### 2. Signatures

The product stages exactly one Skill:

```text
chartpilot-run-python
```

The stdio MCP server exposes exactly:

```text
chartpilot_prepare_adaptive_task(source_path, request_text?, request_path?, task_id?)
chartpilot_run_task_python(task_id, stage, source_code)
```

Do not reintroduce `chartpilot_profile_csv`, `chartpilot_analyze_data`,
`chartpilot_render_chart`, their three Skills, their deterministic runners, an analysis-plan DSL,
or a fixed chart renderer. There is no simple-task or compatibility route.

### 3. Contracts

Valid execution stages are `inspect`, `analysis`, and `render`, in order. Invoke submitted source
only with the manifest-resolved interpreter and an argument array:

```text
<absolute-bundled-python> -I <absolute-task-script> --context <absolute-context-json>
```

#### Skill Resources

`skills/chartpilot-run-python/` owns:

```text
SKILL.md
agents/openai.yaml
assets/templates/inspect_csv.py
assets/templates/analyze_csv.py
assets/templates/render_chart.py
references/adaptive-task-contract.md
references/runtime-contract.md
references/visual-archetypes.md
```

Keep SKILL instructions concise and high-freedom. Templates are editable starting points, must run
unchanged, and must not contain case-specific fields, thresholds, paths, or layout.

The Skill owns an evidence-backed, role-matched visual-archetype reference. The only current
archetype is `group-risk-threshold-bubble`: use it when entities belong to comparison groups,
numeric metrics are compared with group/peer baselines, ordered threshold bands exist, and the
report must coordinate population composition with aggregate bubble severity. Match on roles, not
keywords or field names. Nonmatching tasks keep a reasoned free-form plan.

#### Task Preparation

Preparation accepts one CSV and exactly one inline request or bounded UTF-8 `.md`/`.txt` request
file. It validates configured read roots, creates a unique task, persists exact `request.md`, and
writes `task_context.json` with source hash/metadata, runtime inventory, paths, and template
hashes. It returns all three template sources. It performs no business analysis.

#### Stage Execution

Stages are `inspect`, `analysis`, and `render`, in order. For every attempt:

1. Save exact source as `generated_inspect.py`, `generated_analysis.py`, or
   `generated_chart.py`.
2. Recheck the source CSV SHA-256.
3. Create an attempt-specific staging directory and context whose output path targets staging.
4. Invoke bundled Python with `-I`, finite timeout, bounded stdout/stderr, and sanitized child
   environment.
5. Validate only task identity and stage interoperability artifacts.
6. Replace prior outputs transactionally, with completion manifest last.
7. Append an execution record containing script/runtime hashes, timing, exit status, output,
   errors, and artifact hashes.

Inspect requires `inspection.json` and may emit `prepared.csv`. Analysis requires `result.csv` and
`adaptive_analysis.json`; the bridge creates `analysis_result.json`. Render requires nonblank
`chart.png`, nonempty `summary.md`, and `adaptive_chart.json`; the bridge creates
`chart_result.json`.

The attempt context's `paths.output_dir` is write-only and changes on every retry. Generated code
must read upstream inputs from `source.path`, `paths.prepared_csv`, `paths.result_csv`, or
`paths.analysis_result`, never by joining input names beneath `output_dir`.

Analysis may declare up to 32 unique, case-insensitively distinct, plain task-local filenames in
`adaptive_analysis.json.artifacts`. Allowed extensions are `.csv`, `.json`, `.md`, and `.txt`;
files must be nonempty UTF-8 text and at most 64 MiB. Standard analysis filenames may be listed but
are not duplicated as auxiliary artifacts. The bridge commits validated auxiliary files before
`analysis_result.json`, records path/size/SHA-256 under `artifacts.auxiliary`, discards undeclared
staging files, and transactionally removes prior stage artifacts that are no longer declared.

Stage tool responses include a bounded `process` object with exit code, duration, timeout/output
flags, stdout/stderr tails, and truncation flags. Once generated code has started, execution and
stage-output correction errors are recoverable. Render must fail with
`RENDER_TEXT_UNREADABLE` when Matplotlib reports missing font glyphs; UTF-8 render text containing
U+FFFD is `INVALID_STAGE_OUTPUT`. A nonblank PNG remains only a transport check: the Agent must
read the actual image and retry opaque point clouds, text collisions, clipping, or a visual grain
that does not answer the request.

The bridge does not validate business correctness. Prompt-specific tests and Agent reasoning own
field mapping, calculations, thresholds, findings, and visual design.

Generated analysis code records archetype/fallback, match reason, role map, panel grain/marks,
thresholds, ordering, and annotation strategy in `chart_intent`. Generated render code must
implement that plan and record the archetype plus panel IDs in `adaptive_chart.json`. These fields
are auditable Agent planning data, not an MCP-executed DSL. Review the complete render source before
execution; image review is a second gate and cannot approve a different chart family.

Baseline population grain and volume weights are independent contracts. A count used for dominant
group selection, record-volume reporting, or bubble area must not silently weight a peer baseline.
For entity-to-group comparisons, use equal entity contribution unless the prompt explicitly
requests or defines weighting, and record a different decision in assumptions.

#### Risk Posture

Generated Python is the intended execution route. Do not apply a business operation allowlist,
AST/import allowlist, or Python sandbox in the current product. Generated code runs with the
current Windows user's permissions and may use every package in the runtime manifest.

Path organization, hashes, staging, timeouts, output bounds, and records provide reproducibility
and diagnostics, not an operating-system security boundary. Deployment ACL and network policy are
external. Do not describe Goose or WinPython as a sandbox.

### 4. Validation & Error Matrix

| Condition | Required result |
| --- | --- |
| Runtime roots or manifest are missing/invalid | `RUNTIME_CONFIGURATION_MISSING` or `RUNTIME_CONFIGURATION_INVALID` |
| CSV/request is outside configured read roots | `PATH_NOT_ALLOWED` |
| Both or neither request forms are supplied | `INVALID_REQUEST` |
| Requested task already exists | `TASK_EXISTS` |
| Stage is not inspect/analysis/render | `INVALID_STAGE` |
| Source hash differs from preparation | `SOURCE_CHANGED` before execution |
| Analysis/render prerequisite is absent | `STAGE_PREREQUISITE_MISSING` |
| Process times out, floods output, or exits nonzero | `PROCESS_TIMEOUT`, `PROCESS_OUTPUT_TOO_LARGE`, or `PYTHON_EXECUTION_FAILED` |
| Declared auxiliary name collides, escapes the task root, has the wrong extension, is missing/empty/oversized, or is not UTF-8 | recoverable `INVALID_STAGE_OUTPUT`; do not commit staged outputs |
| Render stderr reports one or more missing font glyphs | recoverable `RENDER_TEXT_UNREADABLE` with code points and bounded process diagnostics |
| Render summary/metadata contains U+FFFD replacement text | recoverable `INVALID_STAGE_OUTPUT`; do not commit staged outputs |
| Required stage artifact is absent, malformed, or blank | Artifact-specific error or `INVALID_STAGE_OUTPUT`; do not commit staged outputs |

Every attempted process execution writes an append-only record. Commit completion manifests last,
after all outputs validate.

### 5. Good/Base/Bad Cases

- Good: adapt all three templates to a new schema and request, declare supporting baseline/exception
  files, then emit evidence-backed analysis plus a task-specific multi-panel chart whose actual
  image is inspected and readable.
- Base: run the unchanged compact templates on their documented minimal CSV contract and produce
  every required artifact.
- Bad: call system `python`, install packages at task time, read upstream files from `output_dir`,
  advertise undeclared staging files, accept missing-glyph warnings, treat a nonblank PNG as visual
  approval, embed fixed business fields/thresholds in the bridge, or expose a removed deterministic
  tool/Skill.

### 6. Tests Required

- Unit: request-form validation, read-root rejection, source-hash rejection, failed execution
  records with recoverable diagnostic tails, stage prerequisites, case-insensitive auxiliary-name
  collisions, auxiliary commit/stale removal, missing-glyph rejection, replacement-character
  rejection, and output validators.
- Contract: MCP `tools/list` returns exactly the two signatures above; Goose stages exactly one
  product Skill and cleans stale removed Skill directories.
- Template: all three templates pass `--help`, run unchanged on the minimal contract, and can be
  customized for the anonymous changed-schema/threshold fixture. The unchanged analysis template
  declares a generic comparison fallback, while the anonymous peer-baseline/threshold fixture
  selects `group-risk-threshold-bubble`.
- End to end: the external SY135 case asserts 59,278 source rows, 6,523 machines, exact gear
  totals, 96 above 25%, zero above 50%, committed auxiliary files, two populated chart regions,
  no render stderr warnings, and generated source containing group-risk aggregation, stacked
  composition, aggregate bubbles, and baseline/threshold references. Forward-test the product
  Skill with Goose and verify source review plus `read_image` occur before completion when provider
  state permits.
- Release: assert `pip check`, imports, locks, licenses, two Skill copies, six template copies,
  both visual-archetype reference copies, zero removed Skill entries, and zero forbidden
  metadata/cache entries.

### 7. Wrong vs Correct

Wrong:

```python
subprocess.run(["python", script_path])
# Or register a fixed business tool for requests judged to be simple.

# output_dir is staging for this attempt, so this input will not exist.
frame = pd.read_csv(Path(context["paths"]["output_dir"]) / "result.csv")
```

Correct:

```python
subprocess.Popen(
    [str(context.python), "-I", str(script_path), "--context", str(attempt_context)],
    shell=False,
    env=context.child_environment(),
)
# Keep only chartpilot_prepare_adaptive_task and chartpilot_run_task_python.

frame = pd.read_csv(context["paths"]["result_csv"], encoding="utf-8-sig")
output_dir = Path(context["paths"]["output_dir"])
```

## Scenario: Portable Goose Base

### Source Contracts

- `goose.lock.json`: Goose v1.43.0 non-CUDA Windows x64 asset and hashes.
- `runtime/goose-manifest.json`: generated critical-file hashes, version, signature observation,
  environment names, and health.
- `agent/config/goose-config.template.json`: Summon plus the two-tool ChartPilot stdio extension.
- `agent/mcp/chartpilot_mcp.py`: only product bridge.

Required environment:

```text
GOOSE_PATH_ROOT=<project>/workspace/goose
CHARTPILOT_ROOT=<trusted project root>
CHARTPILOT_WORKSPACE_ROOT=<project>/workspace
CHARTPILOT_ALLOWED_READ_ROOTS=<os.pathsep-separated roots>
```

Goose v1.43.0 discovers portable product Skills at `GOOSE_PATH_ROOT/config/skills`. Launch from
isolated `workspace/session`; repository `.agents/skills` has higher discovery precedence and must
not leak Trellis development Skills into product sessions.

Initialization must:

- stage only `chartpilot-run-python`;
- remove stale `chartpilot-profile-csv`, `chartpilot-analyze-data`, and
  `chartpilot-render-chart` directories;
- preserve Provider config, credentials, unrelated extensions, and the user's explicit decision
  to disable the ChartPilot extension;
- replace populated Skill directories through backup/move/restore, not `os.replace`.

The MCP server removes proxy- and credential-shaped environment variables before importing or
executing task code. Goose Developer and generic shell remain disabled; adaptive source is passed
only through the ChartPilot MCP tool.

### Required Validation

- Verify Goose archive size/hash, safe ZIP paths, critical hashes, CLI version, and Desktop file.
- Initialize twice and preserve Provider/user extension choices.
- From `workspace/session`, assert exactly one ChartPilot Skill and no Trellis/removed Skills.
- Initialize MCP, assert exactly two tools, and reject input outside read roots.
- Execute unchanged templates and a customized synthetic multi-panel report through MCP.
- Run the opt-in external SY135 case and assert 59,278 rows, 6,523 machines, exact per-gear totals,
  96 above 25%, zero above 50%, and two populated chart regions.
- Inspect release ZIP for both runtimes, one Skill in both product locations, three templates,
  launcher/MCP/licenses, and absence of removed Skills, project metadata, caches, wheelhouse, and
  workspace.

Do not run the explicitly excluded release-ZIP relocation test under Chinese/space paths.
