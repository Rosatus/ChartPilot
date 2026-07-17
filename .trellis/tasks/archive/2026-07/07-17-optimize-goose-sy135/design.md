# Goose 自适应 CSV 结果质量优化设计

## Decision Summary

保留“一个 Skill、两个 MCP 工具、三个可编辑 Python 模板”的自适应架构，不增加固定业务路由。改进集中在四个通用边界：Agent 决策提示、模板的安全起点、MCP 可诊断反馈、真实产物/渲染质量契约。

## Failure Model

1. **分析正确但视觉粒度错误**：明细 CSV 适合逐实体审计，不代表图表也应逐实体绘制。Goose 没有区分 detail grain 与 visual grain。
2. **关键路径规则藏得太深**：Skill 主文档把尝试级路径语义放在 reference 中；Goose 没有加载 reference，连续四次从 `output_dir` 读取上游文件。
3. **错误信息不在工具响应中**：`PYTHON_EXECUTION_FAILED` 只给执行记录路径，迫使 Agent 借用 shell；Goose 的 shell 是 `cmd`，却先发送 PowerShell 命令，进一步产生乱码和无效验证。
4. **机械成功被误当成视觉成功**：桥接层只检查 PNG 格式、尺寸和非空像素；Agent 没有调用 `read_image`，missing-glyph 警告也未在成功响应中显露。
5. **临时产物与交付物不一致**：脚本可写任意临时文件，但桥接层只提交固定文件；Agent 没有能力声明辅助表，摘要却引用了已经被删除的文件。

## Product Flow

```text
prompt + CSV
  -> prepare: context + editable templates
  -> inspect: schema/quality evidence
  -> analyze: detail result.csv + optional declared auxiliary artifacts
  -> render: chart.png + summary.md + chart metadata
  -> bridge: technical validation + commit + actionable diagnostics
  -> Agent: read_image(chart.png) + semantic/typography/density review
  -> retry render when visual review fails
```

`output_dir` remains an attempt-specific write destination. Every upstream input must be read from its named `context.paths.*` entry. This invariant appears directly in the main Skill and in all relevant template main functions, not only in a reference document.

## Skill Guidance

Keep `SKILL.md` concise and advisory rather than prescriptive. Add a mandatory decision pass:

- identify entity grain, detail-output grain, and visual grain separately;
- decide which prompt questions require population, severity, trend, threshold, or exception views;
- when entity marks would overcrowd the report, aggregate visual marks while retaining entity detail in CSV;
- encode bubble area with a meaningful weight/count and state what one bubble represents;
- preserve/extend the template bootstrap for paths and fonts;
- after render success, use an available image-reading tool to inspect the actual PNG; nonblank validation is only a transport check;
- reconcile the final file list with committed artifacts returned by the bridge.

The SY135 composition is evidence for these questions, not a fixed template: another task may still correctly choose a single plot or entity-level scatter.

## Template Changes

### Inspect

Keep generic schema inference, but make the editable boundary and context path usage explicit. Encourage notes to capture entity, row grain, weights, metric semantics, tie policy, and invalid-value decisions discovered from the prompt/data.

### Analyze

Keep the generic fallback runnable. Expand starter `chart_intent` to demonstrate task-neutral fields such as detail grain, visual grain, encodings, panel purpose, and density strategy. Document optional auxiliary artifacts and keep all task-specific calculations editable.

### Render

Treat named context paths as read inputs and `output_dir` as write-only. Configure a discovered CJK font globally through Matplotlib so titles, axes, legends, annotations, and suptitles inherit it. Keep chart selection editable. Add a small reusable helper for applying fonts without constraining layout.

No package is added: bundled Matplotlib/Pillow/fontTools plus Windows fonts are sufficient.

## MCP Diagnostics

Extend `ChartPilotBridgeError` with an explicit `recoverable` flag. Execution and generated-output correction errors are recoverable; invalid request/source boundary errors remain non-recoverable.

Build a bounded process diagnostic object containing exit code, duration, stdout tail, stderr tail, and truncation metadata. Include it:

- in failed tool error details, so the Agent sees traceback context without shell access;
- in successful stage responses, so warnings are visible without opening execution records.

Before render outputs are committed, detect Matplotlib `Glyph ... missing from font(s)` warnings in stderr. Return a recoverable `RENDER_TEXT_UNREADABLE` error with missing code points and diagnostic tail. Also reject U+FFFD replacement characters in textual report artifacts. This is a technical readability contract, not business logic.

## Auxiliary Artifact Contract

`adaptive_analysis.json` may declare optional auxiliary artifacts as task-local filenames. The bridge validates that each declaration:

- is a plain relative filename, unique, and not one of the reserved standard artifacts;
- has an allowed analysis-document extension (`.csv`, `.json`, `.md`, `.txt`);
- exists, is nonempty, and remains within size limits.

Declared files are atomically committed with standard analysis outputs and included by name/hash/size in `analysis_result.json`. Unlisted temporary files remain disposable. Threshold lists and baselines should be produced during analysis, not render.

## Compatibility

- MCP tool names and signatures remain unchanged.
- Existing adaptive payloads without auxiliary artifacts remain valid.
- Existing consumers can ignore additional response diagnostics and manifest artifact entries.
- Goose/WinPython versions and release layout remain unchanged.
- No deterministic tools, XLSX intermediate, sandbox, import allowlist, or business DSL is introduced.

## Verification Strategy

- Unit tests cover recoverable diagnostics, missing-glyph rejection, replacement-character rejection, and auxiliary artifact commit/manifest behavior.
- Template tests run with bundled WinPython and assert Chinese rendering produces no glyph warnings.
- Existing synthetic changed-schema regression proves generalized behavior.
- External SY135 regression confirms counts and semantic chart regions; an actual Goose rerun must read the resulting image before completion.
- Existing MCP enumeration, Skill validation, runtime, packaging, and removed-name audits continue to pass.

## Rollback

All schema additions are optional. If diagnostics or auxiliary artifact validation regresses execution, revert the bridge/Skill/template commit as one unit; do not restore deterministic tools. Runtime rollback is unnecessary because dependencies are unchanged.
