# ChartPilot

[English](README.md) | 简体中文

ChartPilot 是一套面向 Windows 本地数据分析 Agent 的 CSV 分析 Skill。它可以在本地完成 CSV 剖析、声明式分析和 PNG 图表生成，不需要把数据处理或绘图任务交给远程服务。

> [!IMPORTANT]
> 当前仓库包含三个业务 Skill 及其确定性 Python 工具，尚未包含最终 Agent 底座、Windows 离线安装包或图形界面。

## 核心能力

- 识别 UTF-8、UTF-8 BOM、GBK/GB18030、分隔符、字段类型、缺失值、重复记录和候选字段角色。
- 通过白名单分析计划执行清洗、筛选、时间分桶、分组指标、Top N、占比和变化率计算。
- 从 SHA-256 绑定的 `result.csv` 生成折线图、条形图、环形图和散点图，不在绘图阶段重新计算业务指标。
- 保护原始文件，返回结构化错误，并以事务方式提交多文件结果。
- 支持中文路径、中文字段、中文图表标签和离线依赖安装。

## 仓库结构

```text
ChartPilot/
├── skills/
│   ├── chartpilot-profile-csv/
│   ├── chartpilot-analyze-data/
│   └── chartpilot-render-chart/
├── ChartPilot需求规格说明.md
├── Skill开发说明.md
├── Windows离线部署方案.md
└── requirements.txt
```

每个 Skill 都包含精简的 `SKILL.md`、界面元数据、详细契约和确定性 Python 入口；分析 Skill 还包含回归测试。

## 环境要求

- 推荐 Python 3.12
- 目标部署平台为 Windows 10 或 Windows 11
- [`requirements.txt`](requirements.txt) 中的 `pandas`、`matplotlib` 和 `Pillow`

创建本地开发环境：

```bash
python -m venv .venv
```

激活环境后安装依赖：

```bash
python -m pip install -r requirements.txt
```

Windows 离线部署时，应在联网构建机上提前下载兼容的 Windows wheel 包，再从本地目录安装。详见 [Windows离线部署方案.md](Windows离线部署方案.md)。

## 使用流程

剖析 CSV：

```bash
python skills/chartpilot-profile-csv/scripts/profile_csv.py "data/sales.csv" \
  --task-id demo-001 \
  --output-dir "workspace/tasks/demo-001"
```

根据[分析契约](skills/chartpilot-analyze-data/references/contracts.md)创建 `analysis_plan.json`，然后执行：

```bash
python skills/chartpilot-analyze-data/scripts/run_analysis.py \
  --profile "workspace/tasks/demo-001/input_profile.json" \
  --plan "workspace/tasks/demo-001/analysis_plan.json" \
  --output-dir "workspace/tasks/demo-001"
```

绘制已保存的分析结果：

```bash
python skills/chartpilot-render-chart/scripts/render_chart.py \
  --analysis-result "workspace/tasks/demo-001/analysis_result.json"
```

标准产物链路：

```text
input_profile.json
  -> analysis_plan.json
  -> result.csv + analysis_result.json
  -> chart.png + chart_result.json + summary.md
```

## 测试

运行分析回归测试：

```bash
python -m unittest discover -s skills/chartpilot-analyze-data/tests -v
```

所有 CLI 都支持 `--help`。当前实现已在 Python 3.12 环境中完成中文路径和中文 CSV 集成测试；Windows 10/11 原生验收测试仍待执行。

## 安全边界

- 随附的 Python 工具不会发起网络请求，也不会执行模型生成的 Python 表达式。
- 源文件和上游产物通过 SHA-256 绑定，并在下游使用前校验。
- CSV 剖析阶段可以关闭样例输出或对敏感字段进行脱敏。
- API Key 必须保存在运行时配置中，不得写入计划、生成代码、日志或结果。
- Skill 不是操作系统沙箱。最终 Windows 运行时仍需落实目录 ACL、进程超时、资源限制和仅允许访问 LLM API 的网络策略。

## 项目文档

- [需求规格说明](ChartPilot需求规格说明.md)
- [Skill 开发说明](Skill开发说明.md)
- [Windows 离线部署方案](Windows离线部署方案.md)

## 许可证

项目尚未选择软件许可证。仓库公开并不自动授予超出适用法律范围的使用、修改或再分发权限。
