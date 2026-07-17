from __future__ import annotations

import ast
from typing import Any, Mapping


ARCHETYPE = "group-risk-threshold-bubble"
PANEL_IDS = ("risk-composition", "metric-threshold-bubbles")


def validate_chart_intent(intent: Mapping[str, Any]) -> None:
    errors: list[str] = []
    if intent.get("archetype") != ARCHETYPE:
        errors.append(f"archetype must be {ARCHETYPE}")
    role_map = intent.get("role_map")
    required_roles = {"entity", "group", "metric", "baseline", "risk_band"}
    if not isinstance(role_map, Mapping) or not required_roles.issubset(role_map):
        errors.append("role_map must define entity/group/metric/baseline/risk_band")
    group_role = (
        str(role_map.get("group", "group")) if isinstance(role_map, Mapping) else "group"
    )
    risk_role = (
        str(role_map.get("risk_band", "risk_band"))
        if isinstance(role_map, Mapping)
        else "risk_band"
    )
    baseline_role = (
        str(role_map.get("baseline", "baseline"))
        if isinstance(role_map, Mapping)
        else "baseline"
    )
    weight_role = (
        str(role_map.get("weight", "entity_count"))
        if isinstance(role_map, Mapping)
        else "entity_count"
    )
    panels = intent.get("panels")
    by_id = (
        {item.get("id"): item for item in panels if isinstance(item, Mapping)}
        if isinstance(panels, list)
        else {}
    )
    composition = by_id.get(PANEL_IDS[0], {})
    bubbles = by_id.get(PANEL_IDS[1], {})
    if composition.get("mark") != "stacked_bar":
        errors.append("risk-composition must use stacked_bar")
    composition_grain = composition.get("grain")
    if composition_grain not in (["group", "risk_band"], [group_role, risk_role]):
        errors.append("risk-composition grain must be group/risk_band")
    if composition.get("measure") not in {"entity_count", weight_role}:
        errors.append("risk-composition measure must encode entity count/weight")
    if bubbles.get("mark") != "bubble":
        errors.append("metric-threshold-bubbles must use bubble")
    bubbles_grain = bubbles.get("grain")
    if bubbles_grain not in (["group", "risk_band"], [group_role, risk_role]):
        errors.append("metric-threshold-bubbles grain must be group/risk_band")
    if bubbles.get("area") not in {"entity_count", weight_role} or bubbles.get("color") not in {
        "risk_band",
        risk_role,
    }:
        errors.append("bubble area/color must encode entity_count/risk_band")
    references = bubbles.get("references", [])
    has_baseline = isinstance(references, list) and (
        "baseline" in references or baseline_role in references
    )
    thresholds = intent.get("thresholds")
    has_threshold = isinstance(references, list) and (
        any(
            "threshold" in str(reference).casefold() or reference == "prompt_thresholds"
            for reference in references
        )
        or (isinstance(thresholds, list) and len(references) >= len(thresholds) >= 2)
    )
    if not has_baseline or not has_threshold:
        errors.append("bubble panel must reference baseline and prompt_thresholds")
    if not isinstance(thresholds, list) or len(thresholds) < 2:
        errors.append("thresholds must include baseline and at least one threshold")
    if errors:
        raise AssertionError("Invalid chart intent: " + "; ".join(errors))


def validate_render_metadata(payload: Mapping[str, Any]) -> None:
    if payload.get("visual_archetype") != ARCHETYPE:
        raise AssertionError(f"visual_archetype must be {ARCHETYPE}")
    if payload.get("panel_ids") != list(PANEL_IDS):
        raise AssertionError(f"panel_ids must be {list(PANEL_IDS)}")


def validate_render_source(source: str) -> dict[str, bool]:
    tree = ast.parse(source)
    calls = [node for node in ast.walk(tree) if isinstance(node, ast.Call)]

    def method_name(call: ast.Call) -> str | None:
        return call.func.attr if isinstance(call.func, ast.Attribute) else (
            call.func.id if isinstance(call.func, ast.Name) else None
        )

    def has_keyword(call: ast.Call, name: str) -> bool:
        return any(item.arg == name for item in call.keywords)

    group_risk_aggregation = any(
        method_name(call) == "groupby"
        and bool(call.args)
        and isinstance(call.args[0], (ast.List, ast.Tuple))
        and len(call.args[0].elts) >= 2
        for call in calls
    )
    stacked_bar = any(
        method_name(call) == "bar" and has_keyword(call, "bottom") for call in calls
    ) or any(method_name(call) == "rectangle" for call in calls)
    aggregate_bubbles = any(
        method_name(call) == "scatter" and has_keyword(call, "s") for call in calls
    ) or any(method_name(call) == "ellipse" for call in calls)
    reference_lines = any(
        method_name(call) in {"plot", "axhline", "hlines", "draw_dashed_line"}
        for call in calls
    )
    features = {
        "group_risk_aggregation": group_risk_aggregation,
        "stacked_bar": stacked_bar,
        "aggregate_bubbles": aggregate_bubbles,
        "reference_lines": reference_lines,
    }
    missing = [name for name, present in features.items() if not present]
    if missing:
        raise AssertionError("Render source misses archetype features: " + ", ".join(missing))
    return features
