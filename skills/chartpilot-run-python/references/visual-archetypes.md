# Visual Archetypes

Use this reference after inspection and before writing analysis code. Match on analytical roles,
not field names or isolated words in the request. An archetype is a preferred source-code
structure, not a fixed renderer or business DSL.

## Selection Pass

1. Identify the entity, comparison group, metric, peer/group baseline, ordered threshold bands,
   weight/count, and requested visual explanation.
2. Select an archetype only when every required role is supported by the request and inspected
   data.
3. Record the archetype, match reason, role map, panel plan, ordering, thresholds, and annotation
   strategy in `chart_intent` before rendering.
4. If no archetype matches, use a task-specific free-form plan and state why the nearest archetype
   would mislead.

## `group-risk-threshold-bubble`

### Match Signature

Use this archetype when all of these are true:

- each analytical entity belongs to one comparison group;
- the entity has a numeric metric compared with a group or peer baseline;
- that comparison creates ordered threshold/risk bands;
- the report must explain both population composition and aggregate metric severity by group;
- bubbles are requested, or size must encode the number/weight behind an aggregate metric.

Decide baseline weighting independently. A source record count may select the dominant group or
encode aggregate size without weighting the peer baseline. If the request compares entities with a
group average and does not explicitly request a weighted average, use equal entity contribution.

Do not select it for a time series, a single-entity audit, ungrouped outlier discovery, an ordinary
category comparison without peer baselines, or a request where every entity mark is itself the
decision-ready result. Words such as "risk", "threshold", or "bubble" are not sufficient alone.

### Required Plan

Use semantic role names in `chart_intent`, or use the mapped result-column names consistently with
an explicit `role_map`. The role map is the source of truth, so both forms remain auditable:

```json
{
  "archetype": "group-risk-threshold-bubble",
  "match_reason": "Entities are grouped, compared with peer baselines, and classified by thresholds.",
  "role_map": {
    "entity": "<result column>",
    "group": "<result column>",
    "metric": "<result column>",
    "baseline": "<result column>",
    "risk_band": "<result column>",
    "weight": "<optional result column>"
  },
  "risk_order": ["<lowest band>", "<next band>", "<highest band>"],
  "thresholds": [
    {"label": "<baseline label>", "multiplier": 1.0},
    {"label": "<prompt threshold label>", "multiplier": "<prompt-derived number>"}
  ],
  "panels": [
    {
      "id": "risk-composition",
      "purpose": "show entity counts by group and risk band",
      "mark": "stacked_bar",
      "grain": ["group", "risk_band"],
      "measure": "entity_count"
    },
    {
      "id": "metric-threshold-bubbles",
      "purpose": "show aggregate metric, population size, baseline, and thresholds by group",
      "mark": "bubble",
      "grain": ["group", "risk_band"],
      "position": ["group", "aggregate_metric"],
      "area": "entity_count",
      "color": "risk_band",
      "references": ["baseline", "prompt_thresholds"]
    }
  ],
  "ordering": {"group": "semantic_or_data_order", "risk_band": "low_to_high"},
  "annotation_strategy": "aggregate labels and a separated methodology note"
}
```

Threshold entries and band labels come from the current prompt/calculation. A generated task
script may materialize those current values. Never place a business field name, category count,
or threshold value in this reusable reference or the base templates.

### Python Blueprint

Adapt this structure to the task. Do not copy placeholder names into outputs.

```python
intent = analysis["chart_intent"]
roles = intent["role_map"]
group_name = roles["group"]
risk_name = roles["risk_band"]
entity_name = roles["entity"]
metric_name = roles["metric"]
baseline_name = roles["baseline"]
risk_order = intent["risk_order"]

group_order = sorted(frame[group_name].dropna().unique())
summary = (
    frame.groupby([group_name, risk_name], as_index=False, observed=False)
    .agg(
        entity_count=(entity_name, "nunique"),
        aggregate_metric=(metric_name, "mean"),
        baseline=(baseline_name, "first"),
    )
)
composition = (
    summary.pivot_table(
        index=group_name,
        columns=risk_name,
        values="entity_count",
        aggfunc="sum",
        fill_value=0,
    )
    .reindex(index=group_order, columns=risk_order, fill_value=0)
)

# Panel A: stack composition[band] with bottom=<running total>.
# Panel B: for each band, scatter summary rows at
#   x=group, y=aggregate_metric, s=<area scaled from entity_count>, color=band.
# Plot baseline and every intent["thresholds"] multiplier as group-specific lines.
# Add a separate note explaining entity/group/baseline/band and bubble-area semantics.
```

Bubble area must encode `entity_count` or another meaningful aggregate weight, never arbitrary
decoration. Keep exception-level rows in CSV; do not replace either primary panel with jittered
entity points merely because an exception list exists.

### Source Review Before Execution

For this archetype, inspect the complete generated render source and confirm:

- one group x risk-band aggregation feeds both coordinated panels;
- the first panel stacks entity counts by ordered risk band;
- the second panel uses one bubble per group/risk-band aggregate;
- bubble area represents aggregate count/weight and color represents risk band;
- baseline and all requested/derived thresholds use the metric axis;
- observed groups, threshold values, and labels are data/intent driven;
- the methodology note is separated from plot marks;
- entity jitter or an exception scatter is not the primary report structure.

After this source review passes, run render and inspect the actual PNG for text, density, overlap,
clipping, ordering, and whether the implementation matches the declared plan.
