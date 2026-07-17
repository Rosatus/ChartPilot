# ChartPilot Skill 开发说明

## 目标

ChartPilot 使用一个高自由度产品 Skill，把自然语言需求和本地 CSV 转化为任务特定的
Python 分析与图表。Skill 不把需求压入固定操作词表，而是指导 Agent 修改三份轻量模板，
并始终通过项目携带的 WinPython 执行。

## 唯一产品 Skill

产品只 staging：

```text
skills/chartpilot-run-python/
```

已删除独立的 profile、analysis-plan、fixed-render Skills，避免 Goose 根据相似描述路由到
不同工具。Trellis 开发 Skills 位于 `.agents/skills/`，不得复制到产品 Goose 状态或 ZIP。

目录结构：

```text
chartpilot-run-python/
  SKILL.md
  agents/openai.yaml
  assets/templates/
    inspect_csv.py
    analyze_csv.py
    render_chart.py
  references/
    adaptive-task-contract.md
    runtime-contract.md
```

`SKILL.md` 只保留决策流程和工具顺序；详细 JSON 契约放在 `references/`；供 Agent 复制、
修改并提交的代码放在 `assets/templates/`。

## 两个 MCP 工具

ChartPilot stdio MCP 必须且只能暴露：

- `chartpilot_prepare_adaptive_task`
- `chartpilot_run_task_python`

`chartpilot_prepare_adaptive_task` 接收 CSV 和 inline prompt 或本地 UTF-8 prompt 文件，创建
任务目录、保存 `request.md`、记录源文件哈希与运行时清单，并返回 inspect、analysis、render
三份模板源码。

`chartpilot_run_task_python` 接收任务 ID、阶段和完整 Python 源码。阶段固定为：

1. `inspect`
2. `analysis`
3. `render`

工具把源码保存为 `generated_inspect.py`、`generated_analysis.py` 或
`generated_chart.py`，再用捆绑解释器和 `-I` 直接执行。每次提交都是完整替换源码，不传
补丁或 Python 表达式。

## 模板设计原则

三份模板必须：

- 使用 `--context <task_context.json>` 获取所有路径和运行时信息；
- 有清楚、范围小的可编辑函数；
- 可以原样运行，便于冒烟测试；
- 不包含特定机型、字段、阈值或图表布局；
- 只使用运行时清单中的依赖；
- 使用 UTF-8，模块可安全导入，入口返回退出码；
- 把产物写到 `context.paths.output_dir`，不能假设重试时 staging 路径不变。

Agent 不应机械保留模板逻辑。遇到嵌套分组、主类别选择、同群基准、复杂派生指标、多区域
图表或高密度标注时，应重写对应函数，使代码忠实反映 prompt 和数据。

## 阶段产物

### Inspect

必需 `inspection.json`，schema 为 `chartpilot.inspection/v1`。可选输出 `prepared.csv`。
该阶段负责字段、质量、语义角色和任务需要的补充探查，不生成 XLSX 中间文件。

### Analysis

必需：

- `result.csv`
- `adaptive_analysis.json`

后者包含问题、假设、与 CSV 表头一致的 result schema、带 evidence 的 findings 和 chart
intent。MCP 验证后生成 `analysis_result.json`；所有业务计算由生成代码负责。

### Render

必需：

- 非空 `chart.png`
- `summary.md`
- `adaptive_chart.json`

Agent 可以自由使用单图或多区域布局。MCP 检查 PNG 签名、尺寸、文件大小和前景像素，再
生成 `chart_result.json`。

## 执行记录与失败

每次执行记录保存在 `workspace/tasks/<task-id>/executions/`，包括：

- 阶段和 attempt；
- 脚本路径、字节数和 SHA-256；
- runtime ID 与 manifest SHA-256；
- 开始/结束时间、耗时、退出码；
- 受限 stdout/stderr；
- 已提交产物及哈希；
- 失败错误对象。

阶段输出先写 staging，验证通过后才替换任务目录中的上一版，completion manifest 最后
安装。源 CSV 在每个阶段前重新校验 SHA-256。失败后必须修改代码再重试。

## 自由度与边界

- 不使用业务操作白名单、AST/import 白名单或固定图表选择器。
- 不提供旧的确定性备用工具，也不启用 Goose Developer 或通用 shell。
- 任务代码可使用 runtime manifest 中的全部包，但不得在目标机运行 pip。
- 代码执行不是安全沙箱，拥有当前 Windows 用户权限；路径组织和产物验证主要服务于
  可复现性与故障定位。
- 原始 CSV 保持只读，运行时、源码仓库和依赖锁不得由任务代码修改。

## 开发与验证

修改 Skill 后运行：

```powershell
runtime\winpython\python\python.exe -I `
  "$env:USERPROFILE\.codex\skills\.system\skill-creator\scripts\quick_validate.py" `
  skills\chartpilot-run-python
```

还必须验证：

- MCP 恰好枚举两个工具；
- Goose portable 状态只发现一个产品 Skill；
- 三份模板可原样运行；
- 匿名变化字段/阈值用例能通过修改模板生成双区域图；
- SY135 外部案例得到 6,523 台、指定档位分布、96 台高于 25%、0 台高于 50%；
- 发布 ZIP 不包含已删除 Skills、旧工具、项目元数据或用户 workspace。
