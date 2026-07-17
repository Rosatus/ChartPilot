# Goose SY135 Failure Analysis

## Compared Runs

- Original Goose task: `workspace/tasks/sy135_fuel_analysis/`
- Updated forward-test task: `workspace/tasks/csv-20260717-060417-860d8938/`
- Equivalent accepted regression: `scripts/agent/test-sy135-adaptive.py`
- Human reference inputs and output remain external and are not tracked.

## Original Failure Evidence

1. Inspect succeeded and correctly identified 59,278 rows, 6,523 machines, and 11 gears.
2. Analysis needed two attempts because the first `result_schema` did not declare every CSV
   column. The second attempt produced the accepted totals: 96 machines above 25% and none above
   50%.
3. Render attempts 1-4 read upstream files from the attempt-specific `output_dir`; those files
   existed only at named task paths, so all four attempts failed with `FileNotFoundError`.
4. The failure tool response exposed only an execution-record path. Goose used its generic shell
   to inspect the record, first sending PowerShell syntax to a `cmd` shell and receiving mojibake.
5. Attempt 5 removed the template font bootstrap. It exited successfully but emitted 25 distinct
   Matplotlib missing-glyph warnings. The bridge accepted the nonblank PNG, and Goose never called
   its image-reading tool. The final chart displayed Chinese as square boxes.
6. The chart drew all 6,523 machine rows as points. The human report instead used gear/risk
   aggregates so population, average consumption, and thresholds could be compared directly.
7. Generated code wrote supporting CSVs in staging and the summary advertised them, but the fixed
   commit list discarded them. The final task directory did not contain the advertised files.

## Implemented Prevention

- Critical path semantics now live in the main Skill and templates: `output_dir` is write-only,
  while upstream inputs use named context paths.
- Generated-process errors return bounded traceback diagnostics and are marked recoverable after
  execution begins.
- Matplotlib missing-glyph warnings fail render with `RENDER_TEXT_UNREADABLE`; replacement
  characters in report text are rejected.
- The render template configures a discovered Windows CJK font globally.
- Analysis may declare task-local auxiliary text artifacts. The bridge validates, atomically
  commits, hashes, and records them; stale prior-stage artifacts are removed transactionally.
- Skill guidance separates detail grain from visual grain and requires actual image inspection
  plus committed-artifact reconciliation before completion.

## Updated Forward-Test Evidence

- Goose loaded both the revised main Skill and `adaptive-task-contract.md`.
- Inspect succeeded on its first attempt.
- Analysis succeeded on its first attempt with 6,523 result rows and the accepted 96/0 threshold
  counts.
- Goose declared and successfully committed `gear_baseline.csv`, `fuel_exceptions.csv`, and
  `methodology.md`; these appear in `analysis_result.json.artifacts.auxiliary`.
- The provider was intermittently unavailable. The initial headless run stalled after preparation
  and ended with a stream-decode network error. A later run reached analysis before the bounded CLI
  process ended; resuming the same session completed render on its first attempt with zero stderr
  and explicitly called `read_image`.
- The first real Goose render fixed unreadable Chinese, missing files, missing thresholds, and the
  weak summary panel, but still plotted all 6,523 entities in the largest panel and collided a
  section title with legend text. This residual led to stronger general Skill guidance: exception
  discovery does not imply plotting every entity, dense primary views must aggregate to a
  decision-ready grain, and opaque marks or text collisions require another render after image
  inspection.
- After the strengthened Skill was synchronized, Goose reloaded it, read the existing image, and
  produced `render-002`. Its image review found a remaining title/description collision, so Goose
  produced `render-003`, read that image, and explicitly passed strict visual review.
- The final 3,060 x 1,870 PNG aggregates the primary panel to 11 gear bubbles and limits the
  secondary panel to the 96 machines above the 25% threshold. Chinese text, threshold lines,
  labels, legends, and three highest-risk annotations are readable without overlap or clipping.
  An independent final `view_image` review confirmed the result.
- Final chart SHA-256:
  `5fce22bdf471a04739c3bfe7becab8e18f336d26e00033e7f2828e176ec5cbca`.

## Equivalent End-To-End Evidence

The bundled-runtime regression completed all three stages and directly inspected its PNG. It
confirmed exact source/machine/gear/threshold totals, three committed auxiliary CSVs, readable
Chinese, two populated analytical panels, aggregated bubbles by gear and risk band, and zero
render stderr warnings.
