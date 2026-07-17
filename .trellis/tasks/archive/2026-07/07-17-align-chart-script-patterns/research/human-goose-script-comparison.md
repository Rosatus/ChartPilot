# Human And Goose Chart-Script Comparison

## Evidence

- Human request: `C:\Users\rosatus\Downloads\SY135油耗分析\输入原csv数据\原prompt.md`
- Human implementation: `C:\Users\rosatus\Downloads\SY135油耗分析\process.py`
- Human PNG: `C:\Users\rosatus\Downloads\SY135油耗分析\输出结果\e7ea2a690bd4bda4b445174a154ac01b.png`
- Goose task: `workspace/tasks/csv-20260717-060417-860d8938/`
- Existing accepted fixture: `agent/tests/fixtures/sy135_render.py`

External files are read-only evidence and remain outside Git.

## Prompt Semantics

The request has four linked roles rather than a generic request for anomalies:

1. entity: machine;
2. group: each machine's dominant gear;
3. metric and peer baseline: machine fuel versus the mean for the same dominant gear;
4. threshold classification and requested mark: find machines above 25%/50% and use bubbles.

The visualization must therefore explain both population composition and metric severity against
group-specific reference lines. A chart that only lists exceptional entities answers discovery,
but loses the population/risk context expressed by the human script.

## Script-Level Matrix

| Dimension | Human `process.py` | Latest Goose `generated_chart.py` | Target archetype |
| --- | --- | --- | --- |
| Primary aggregation | `groupby([主档位, 风险等级])` with count, mean fuel, and weight | `groupby(dominant_gear)` with machine count, mean fuel, and exception rate | group x ordered risk band |
| Top panel | stacked bars: entity count by group and risk band | one bubble per gear: mean fuel, machine count, exception rate | stacked population composition |
| Bottom panel | one bubble per group/risk band at aggregate mean fuel | one bubble per exceptional machine at excess percentage | aggregate metric bubble by group/risk band |
| Bubble area | entity count in the aggregate | entity record count for each exception | entity count in each group/risk band |
| Bubble color | ordered risk band | continuous excess percentage | ordered risk band |
| Reference lines | peer baseline plus 25%/50%/75% lines by group | only 25%/50% lines; primary panel and exception panel use different y semantics | peer baseline and every requested/derived threshold on the metric panel |
| Risk context | five ordered bands and shaded threshold regions | three labels; normal entities omitted from the exception panel | all ordered bands, including zero-count handling |
| Category domain | derived from observed gears | fixed `range(1, 12)` ticks | derived and sorted from data/intent |
| Explanation | dedicated right-side statistical note | header and two short description lines | dedicated or clearly separated method/encoding note |
| Output-script focus | composition and severity are coordinated in one report | anomaly discovery remains the second-panel story | two panels implement one selected archetype |

## Root Cause

The render result followed the analysis plan. The Goose `analysis_result.json` explicitly declared
the main visual grain as one machine per bubble and described low-opacity entity plotting as its
density strategy. Later image review reduced the entity count to 96 exceptions, but it did not
revisit the selected chart family. The Skill currently describes the human-style composition as
only a useful optional pattern, so a readable but structurally different script can pass.

The existing SY135 and anonymous synthetic fixtures already implement the desired family. They are
test implementations, not a resource that Goose is told to study. This explains why deterministic
regression passes while a real Agent run selects a different chart structure.

## Generalized Intent Signature

Select `group-risk-threshold-bubble` when the request/data provide all of:

- an entity assigned to one comparison group;
- a numeric entity metric and a group/peer baseline;
- ordered threshold bands derived from the metric-to-baseline comparison;
- a need to explain both how many entities occupy each band and how aggregate metric severity
  changes by group;
- a bubble request, or equivalent need to encode both aggregate metric and population size.

Do not select it merely because the request says risk, anomaly, bubble, or threshold. Time series,
single-entity audit, ungrouped outlier discovery, and ordinary category comparison keep the generic
free-form route.

## Planning Conclusion

The minimum mechanism is a Skill-owned visual-archetype reference plus an auditable `chart_intent`
selection. It should provide a generic script blueprint and a reasoned escape route. It must not
become a deterministic renderer, MCP business validator, keyword router, or fourth Python template.

## Forward-Test Finding

The first real Goose analysis selected the correct archetype but used source record counts to
weight the peer baseline, producing 74 entities above 25% instead of the human baseline of 96.
After separating baseline population grain from visual/volume weight, the same task recomputed the
peer baseline as an equal-entity arithmetic mean and returned 6,523 entities, 96 above 25%, and zero
above 50%. The final generated source passed the archetype source contract and Goose read the
actual 2,560 x 1,760 image before completion.

After the revised baseline rule was staged, a fresh Goose session received only the original prompt
path and CSV path. Task `workspace/tasks/csv-20260717-081734-9c75f140/` completed without a reviewer
correction. Goose self-reviewed through two successful analysis attempts and two successful render
attempts. The final result contained 6,523 entities, 96 above 25%, and zero above 50%; selected
`group-risk-threshold-bubble`; used stacked group/risk counts plus one aggregate bubble per
group/risk band; drew the equal-entity peer baseline and 1.25/1.50 references; and called its image
reader before completion. Independent AST/plan checks and image inspection passed.

## Final Validation Evidence

- `scripts/runtime/test-runtime.ps1` passed with CPython 3.13.13, clean dependencies, all three
  templates, 11 tests, and the adaptive smoke test.
- `scripts/agent/test-agent.ps1` passed with Goose 1.43.0 non-CUDA, one product Skill, and two MCP
  tools.
- External task `workspace/sy135-validation/tasks/sy135-34be307c/` passed every aggregate,
  archetype, source-structure, panel, and image-dimension check.
- `dist/ChartPilot-win-x64-goose-py3.13.zip` contains both visual-archetype reference copies and no
  removed tool entries; SHA-256 is
  `024EE6D6CF283B1E769214EF676521678FD6786EC4B6A2535BA8477B54A5D3CF`.
