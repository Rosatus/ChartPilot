# 优化 Goose SY135 自适应分析结果

## Goal

使便携版 ChartPilot 中的 Goose 在收到业务 prompt 与原始 CSV 后，能够自主理解分析口径、编写并迭代任务专用 Python，稳定产出与人工实践在业务含义和图表表达上相近的结果；改进必须提升通用 CSV 分析能力，而不是针对 SY135 字段或固定阈值做硬编码。

## Background

- 本次失败运行完整保存在 `workspace/tasks/sy135_fuel_analysis/`，包含 inspect、analysis、render 三阶段生成代码、执行记录以及最终 `chart.png`。
- 对照基线位于 `C:\Users\rosatus\Downloads\SY135油耗分析\`：原始 prompt、原始 CSV、人工 `process.py` 和人工图表均可读取。
- 现有产品只暴露自适应任务准备与 Python 执行两个 MCP 工具；Agent 应在三个可编辑模板基础上生成任务专用代码，并使用内置 WinPython 运行。
- 既有产品决策继续有效：CSV-first、不引入确定性简单任务路由、不限制 Agent 只能照抄模板、当前不考虑沙箱。
- 分析阶段口径基本正确：`workspace/tasks/sy135_fuel_analysis/analysis_result.json` 得到 6,523 台、超 25% 为 96 台、超 50% 为 0 台，与既有 SY135 验收基线一致。
- 图表语义明显偏离：人工图以档位和风险等级聚合，组合“风险构成 + 平均油耗/阈值趋势”；Goose 将 6,523 台全部画成散点，并增加价值较低的档位数量柱图，主要结论被过绘制淹没。
- `render-001.json` 至 `render-004.json` 均因把尝试级 `output_dir` 当作上游输入目录而失败；现有 MCP 错误只返回执行记录路径，没有把 traceback 摘要直接反馈给 Agent。
- `render-005.json` 虽被判成功，但包含 25 次 Matplotlib missing-glyph 警告；最终图中文显示为方框。Windows 已存在微软雅黑和黑体，根因不是缺依赖，而是生成代码删除了模板的字体配置且没有实际查看图片。
- Agent 在摘要中宣称输出 `gear_baseline.csv`、`over_25pct_machines.csv` 和 `over_50pct_machines.csv`，但这些文件未被 MCP 固定提交列表保留，最终目录中不存在。

## Requirements

- R1：逐阶段复盘 Goose 本次实际工具调用、生成代码、失败重试、结构化产物与最终图表，给出可复现的偏差和根因证据。
- R2：把本次结果与原 prompt、原 CSV、人工脚本和人工图表进行数据口径与视觉表达对照。
- R3：优化 Skill、三个 Python 模板及必要的 MCP 反馈契约，使 Agent 更容易正确提取业务口径、验证中间结果并按 prompt 选择合适图表。
- R4：优化应提供指导和自检机制，但不能把 Agent 限制成固定流水线，也不能嵌入 SY135 专用字段名、档位数量或阈值。
- R5：若根因涉及运行时缺包，更新依赖锁定与便携运行时；若现有依赖足够，不增加无必要依赖。
- R6：保留现有 Goose v1.43.0、WinPython CPython 3.13.13、两工具 MCP 边界与离线便携架构。
- R7：允许 Agent 显式声明并保留任务专用辅助产物；最终摘要或清单不得引用未提交的文件。
- R8：执行失败应直接返回有界、可操作的 stdout/stderr 诊断；中文缺字等确定性渲染问题不得仅凭“PNG 非空”判为成功。

## Acceptance Criteria

- [x] AC1：形成基于文件和运行记录的失败复盘，明确错误发生在哪个阶段及为何现有反馈未能让 Goose 自我纠正。
- [x] AC2：使用原 prompt 与原 CSV 重新走 Goose/等价 Agent 自适应链路，关键聚合口径与人工基线一致或有明确、合理且可解释的差异。
- [x] AC3：最终图表表达原 prompt 要求的主要业务结论，内容非空、中文可读，且不再出现本次已识别的主要偏差。
- [x] AC4：新增或更新自动化测试，覆盖会导致本次失败的通用行为；现有单元、集成、Skill 与回归测试继续通过。
- [x] AC5：使用至少一个不同字段名或不同分析要求的合成用例，证明改进没有硬编码 SY135。
- [x] AC6：没有重新引入已删除的确定性工具或 Skill，Agent 仍可自由修改和重试三个阶段的 Python。
- [x] AC7：Agent 声明的辅助 CSV 会被校验、提交并出现在结果 manifest 中；未声明的临时文件不会被误报为交付物。
- [x] AC8：失败工具响应包含有界 traceback/进程诊断，Matplotlib 中文缺字警告触发可恢复的渲染失败，模板使用系统 CJK 字体时可正常通过。
- [x] AC9：Goose 在最终完成前实际读取生成图片并核对业务表达、中文、重叠与密度，而不是把非空校验等同于视觉验收。

## Out of Scope

- 不处理沙箱、Python import allowlist 或业务操作 DSL。
- 不执行发布 ZIP 在中文和空格路径下的搬移验证。
- 不用中间 XLSX 复刻人工流程，分析保持 CSV-first。
