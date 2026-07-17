# Visual Archetype Alignment Design

## Decision Summary

Add one evidence-backed visual archetype, `group-risk-threshold-bubble`, to the existing adaptive
Skill. The Agent selects it by semantic roles before writing analysis code, records the choice in
`chart_intent`, and uses a Skill reference blueprint when writing `generated_chart.py`. The Agent
still authors and executes task-specific Python; no fixed renderer or business router is added.

## Boundaries

### Skill owns

- intent-signature matching and disqualifiers;
- the archetype's coordinated panel responsibilities;
- a field-neutral Python blueprint for aggregation and plotting;
- the rule that render code must implement the analysis-stage chart plan;
- script review followed by actual-image review.

### Generated analysis code owns

- prompt-specific field mapping, entity/group/metric/baseline semantics, thresholds, tie rules,
  invalid-value policy, ordered risk bands, and detailed result rows;
- `chart_intent.archetype`, match reason, role map, panel plans, threshold plan, ordering, and
  annotation strategy.

### Generated render code owns

- task-specific aggregation into group x risk-band plotting data;
- stacked composition, aggregate bubbles, baseline/threshold lines, notes, typography, and layout;
- dynamic category and threshold domains taken from the current task rather than reusable files.

### MCP bridge continues to own

- stage execution, diagnostics, artifact validation, transactions, and manifests only.

The MCP bridge will not select an archetype, interpret panel plans, inspect Python semantics, or
validate business correctness. This preserves the two-tool adaptive boundary.

## Skill Resource

Add `skills/chartpilot-run-python/references/visual-archetypes.md` with:

1. a short selection procedure based on analytical roles;
2. the exact match signature and non-match cases for `group-risk-threshold-bubble`;
3. a required chart-plan shape;
4. a generic Matplotlib/Pandas blueprint using role placeholders, not business field names;
5. a script-review checklist;
6. an explicit escape rule when the data or request makes the archetype misleading.

`SKILL.md` stays concise. It requires reading this reference when the request combines group/peer
baseline, threshold bands, population size, and bubbles, then requires either selecting the
archetype or recording a concrete mismatch reason.

Goose initialization already copies the complete Skill directory, so the new reference is staged
without initialization changes. Release validation must assert it exists in both shipped Skill
copies.

## Chart Intent Shape

The shape is advisory Agent planning data, not a versioned execution DSL:

```json
{
  "archetype": "group-risk-threshold-bubble",
  "match_reason": "The request compares entity metrics with group baselines and threshold bands.",
  "role_map": {
    "entity": "<result column>",
    "group": "<result column>",
    "metric": "<result column>",
    "baseline": "<result column>",
    "risk_band": "<result column>",
    "weight": "<optional result column>"
  },
  "panels": [
    {
      "id": "risk-composition",
      "mark": "stacked_bar",
      "grain": ["group", "risk_band"],
      "measure": "entity_count"
    },
    {
      "id": "metric-threshold-bubbles",
      "mark": "bubble",
      "grain": ["group", "risk_band"],
      "position": ["group", "aggregate_metric"],
      "area": "entity_count",
      "color": "risk_band",
      "references": ["baseline", "prompt_thresholds"]
    }
  ],
  "ordering": {"group": "semantic_or_data_order", "risk_band": "low_to_high"},
  "annotation_strategy": "aggregate labels and separated methodology note"
}
```

Templates show a compact generic example and comments; they do not contain the risk archetype's
business-specific fields or thresholds. Existing payloads remain compatible because the bridge
continues to accept any object as `chart_intent`.

## Render Blueprint

For the selected archetype, task code should follow this data flow:

```text
entity detail result.csv
  -> ordered group and risk domains
  -> group x risk aggregation(entity_count, aggregate_metric, optional weight)
  -> panel A: stacked count composition
  -> panel B: aggregate metric bubbles + baseline/threshold lines
  -> separate methodology/encoding note
  -> source review -> run -> image review -> retry
```

The blueprint may use Matplotlib or another bundled library. Similarity is judged by aggregation,
panel responsibilities, marks, encodings, and references, not by function names, pixels, colors,
or use of PIL versus Matplotlib.

## Verification

- Strengthen SY135 and anonymous 20%/40% fixtures to declare the archetype and panel plan.
- Add script-level assertions against the fixture/generated source and chart metadata: coordinated
  stacked composition, aggregate bubbles, group-risk aggregation, and reference thresholds.
- Keep unchanged-template tests as the generic non-match control.
- Extend external SY135 acceptance beyond two populated regions to inspect generated source and
  assert the expected chart-plan declaration.
- Run a fresh real Goose task after staging the revised Skill. Review `analysis_result.json`,
  `generated_chart.py`, execution records, and the actual PNG.

Static assertions are supporting evidence, not a universal Python semantic parser. The final real
Goose source review verifies that the code implements rather than merely declares the archetype.

## Compatibility And Dependencies

- One Skill, two MCP tools, and three editable Python templates remain.
- The generic fallback remains valid for requests that do not match the archetype.
- No runtime or dependency changes are planned; pandas, NumPy, Matplotlib, Pillow, and fontTools are
  already bundled.
- External SY135 inputs and generated task output stay ignored and untracked.

## Rollback

The change is isolated to Skill guidance/resources, templates, tests, and documentation. If real
Goose over-selects the archetype, revert the selection rule/reference and fixture expectations as
one unit; do not restore deterministic tools or remove the existing visual-readability safeguards.
