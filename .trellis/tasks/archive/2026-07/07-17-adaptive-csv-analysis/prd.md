# Generalize adaptive CSV analysis workflow

## Goal

Generalize ChartPilot's prompt-plus-CSV workflow so an Agent can understand the intent of a
real fuel-consumption analysis request, adapt compact task Python templates, execute the
task-specific code with the bundled portable interpreter, and produce a chart comparable in
analytical usefulness and presentation quality to the supplied SY135 manual-practice result.

## Background

- The reference case is the user-supplied external SY135 case root and must not be copied into
  Git or release artifacts.
- A human received `输入原csv数据\原prompt.md` and the raw SY135 gear/fuel CSV, manually
  selected relevant records into an XLSX workbook, wrote `process.py`, and produced the final
  chart.
- ChartPilot should learn the reusable reasoning and presentation pattern rather than encode
  SY135-specific columns, thresholds, labels, or chart geometry.
- The automated path should stay CSV-first and should not create an intermediate XLSX file.
- The reference CSV contains 59,278 rows for 6,523 machines across gears 1 through 11. Under
  the manual script's stated tie-break and arithmetic-mean baseline, 96 machines exceed their
  dominant-gear baseline by 25%, none exceed it by 50%, and the per-gear machine totals are
  316, 19, 83, 413, 1,103, 1,825, 1,456, 862, 190, 221, and 35.
- The reference PNG is a two-panel report: stacked risk-count bars by dominant gear, followed
  by a bubble/threshold view of average fuel consumption with baseline, +25%, +50%, and +75%
  lines plus a concise interpretation panel.
- The current three stage scripts are fixed implementations rather than editable templates:
  `profile_csv.py` is about 59 KB, `run_analysis.py` about 99 KB, and `render_chart.py` about
  59 KB. The current `generated_analysis.py` only prints the validated JSON plan, while
  `generated_chart.py` is an audit snapshot; neither is the task-specific program that
  calculates or renders the result.
- The portable Goose MCP currently exposes profile, allowlisted analysis-plan execution, and
  fixed rendering. These three deterministic tools and their routing Skills must be removed
  from the product surface so they cannot intercept an adaptive request.
- Bundled `numpy`, `pandas`, `matplotlib`, and `Pillow` cover the reference CSV-to-PNG
  workflow. `openpyxl` is absent, but is required only by the deliberately omitted XLSX path;
  no missing runtime dependency has yet been identified for the intended workflow.

## Requirements

### R1. Reproduce the reference intent

- Inspect the prompt, raw CSV, manual XLSX, `process.py`, and final image as evidence.
- Convert the human workflow into reusable analysis and visualization decisions.
- Add an end-to-end regression case that starts from the original prompt and CSV and produces
  a materially similar result without relying on the manual XLSX as an execution input.

### R2. Preserve task adaptability

- Update the relevant product Skills so the Agent treats the new compact task Python templates
  as adaptable starting points rather than immutable implementations.
- Permit the Agent to copy and modify templates into a task-local generated script according
  to each prompt, dataset schema, and presentation need.
- Avoid hard-coded SY135 rules in reusable Skills or templates.
- Make adaptable execution available through the portable Goose tool surface; changing Skill
  prose alone is insufficient while Goose has no way to save and execute Agent-authored code.
- Use one adaptive route for every prompt-plus-CSV task. Remove the three deterministic MCP
  tools and their product Skills rather than retaining a simple-task or compatibility path.
- Keep only implementation-neutral source validation, hashing, execution recording, and output
  contract validation in the MCP bridge; business profiling, analysis, and rendering belong to
  Agent-editable task code.

### R3. Evolve the Python templates

- Add three compact task templates for supplemental CSV inspection, prompt-specific analysis,
  and prompt-specific rendering. Package them as reusable Skill assets rather than asking the
  Agent to edit the current 59-99 KB production runners.
- Let the Agent request a template, edit any task-specific logic, and submit the resulting
  source through the ChartPilot MCP extension for task-local execution.
- Preserve useful artifact/manifests where they improve interoperability, but do not retain the
  allowlisted operation DSL or fixed chart selector as an alternate execution route.
- Keep generated task code inspectable and runnable through the designated bundled
  WinPython interpreter.
- Prefer direct CSV processing throughout the workflow.

### R4. Runtime dependencies

- Audit the reference workflow and intended generalized implementation for missing packages.
- Pin, download, install, license-check, and package any required dependency through the
  existing portable-runtime workflow; do not rely on system Python.
- Do not install packages at task execution time. Add a package only when a reusable template
  or accepted reference workflow requires it, not merely because the manual XLSX path imported
  it.

### R5. Current risk posture

- Do not make sandboxing or arbitrary-code restrictions a goal of this task.
- Retain basic reproducibility, clear task-local paths, failure reporting, and output
  validation so generated-code failures remain diagnosable.

### R6. Prompt and artifact flow

- Accept the analysis request as inline text or a bounded local Markdown/text file alongside
  the source CSV and persist its exact content as task-local `request.md`.
- Preserve generated source, its SHA-256, bounded stdout/stderr, runtime identity, elapsed time,
  and exit status in task-local execution records.
- Require adaptive analysis to emit a plot-ready CSV plus structured findings/chart intent and
  adaptive rendering to emit a valid nonblank PNG plus a concise summary. Build compatible
  manifests around these outputs so existing consumers can continue to audit artifacts.

## Acceptance Criteria

- [x] Given the original SY135 prompt and raw CSV, ChartPilot produces a task-local analysis
      and chart without using the manually filtered XLSX as an input.
- [x] The reproduced result captures the same primary risk findings and is visually comparable
      to the manual reference chart, with objective assertions documented in the test.
- [x] The relevant Skills explicitly guide the Agent to adapt task-local copies of the three
      Python templates when prompt-specific logic or presentation requires it.
- [x] Goose exposes a prompt-aware task preparation operation and a task-local Python execution
      operation; the standard adaptive workflow works without enabling Goose Developer or a
      system shell.
- [x] The three compact templates are returned/staged with explicit editable sections and run
      successfully unchanged on their documented minimal contract before task customization.
- [x] A second fixture or variation demonstrates that the workflow is not hard-coded to the
      SY135 file name or a single fixed schema/value set.
- [x] Generated Python runs only through the bundled interpreter and its complete pinned
      dependency set passes `pip check`, imports, licensing, and release packaging checks.
- [x] Goose lists exactly the two adaptive MCP tools; the removed deterministic tools and their
      three routing Skills are absent from staged Skills, release contents, and documentation.

## Out Of Scope

- Reproducing the manual intermediate XLSX step.
- Hard-coding the supplied file name, machine model, date range, or manual thresholds.
- Treating generated Python as sandboxed or enforcing a strict security boundary in this task.
- Replacing Goose or WinPython.
- Per-task package installation or fallback to a system interpreter.
- Backward compatibility for the removed deterministic MCP tools, business Skills, plans, or
  fixed renderer contracts.
