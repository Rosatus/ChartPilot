# ChartPilot Windows 离线部署方案

## 目标

在 Windows 原生环境中部署 ChartPilot，使其在无外网、无 WSL、无 Docker 依赖的情况下运行，仅保留对 LLM API 的网络访问能力。

## 约束

- 目标平台：Windows 10 / Windows 11
- 运行方式：原生 Windows，不依赖 WSL
- 网络条件：默认无外网，仅允许访问 LLM API
- 部署方式：可拷贝、可解压、可离线安装
- 运行能力：本地读取 CSV，执行 Python 数据处理，输出图表图片

## 推荐总体架构

建议采用“三层打包”：

1. Agent 底座
   - 选择一个原生 CLI agent 作为编排内核
   - 负责对话、工具调用、任务分解、错误重试

2. 本地 Python 运行时
   - 随包附带一个可移植 Python 环境
   - 用于执行 pandas、matplotlib、numpy 等代码

3. 业务能力层
   - 自定义 skill
   - 包含 CSV 读取、数据分析、图表绘制、结果摘要逻辑

## 底座选择建议

优先选择满足以下条件的 CLI agent：

- 原生支持 Windows
- 不要求 WSL
- 能直接配置 OpenAI 兼容 API 或其他 LLM API
- 支持本地命令执行
- 允许自定义工具/skill/workflow

当前更适合的方向是：

- 首选：Open Interpreter
- 备选：Goose

## 离线部署包内容

建议将安装包组织为如下内容：

```text
ChartPilot/
  bin/
    agent.exe
    python/
  skills/
    csv_reader/
    analysis/
    charting/
  libs/
    wheels/
  config/
    model.yaml
    runtime.yaml
  workspace/
```

## 关键安装步骤

### 1. 准备 Python 运行时

建议使用可移植 Python 或者打包好的嵌入式 Python。

要求：

- 能离线解压使用
- 能通过 `python.exe` 直接执行脚本
- 能预装 pandas、matplotlib、numpy、openpyxl 等依赖

### 2. 准备离线依赖包

提前在有网环境下载 wheel 包：

- pandas
- numpy
- matplotlib
- seaborn
- pyarrow（可选）
- openpyxl（如要读 xlsx）
- duckdb（可选）

然后在离线机器上本地安装。

### 3. 配置 LLM API

仅保留对 LLM API 的访问。

建议提供配置项：

- API Base URL
- API Key
- Model Name
- Timeout
- Retry Count

### 4. 配置工作目录

将 CSV 文件统一放入工作目录，所有分析输出都写入本地 workspace。

建议生成：

- 清洗后的中间数据
- 分析结果表
- 图表图片
- 日志文件
- 代码快照

## 离线安装流程建议

1. 解压 ChartPilot 压缩包
2. 初始化 Python 环境
3. 安装本地 wheel 依赖
4. 配置 LLM API
5. 运行健康检查
6. 执行示例 CSV 分析任务

## Windows 兼容性要求

需要注意以下点：

- 路径分隔符必须使用 Windows 兼容写法
- 命令行编码要处理中文文件名
- 文件锁和权限错误要显式报错
- 临时目录和缓存目录要可配置
- 图表保存路径要避免空格和特殊字符问题

## 安全要求

- 禁止访问外部网络，除 LLM API 外
- 仅允许受控目录读写
- Python 代码执行要有限制
- 所有执行命令要留日志
- 对生成代码做简单静态检查

## 验收标准

部署完成后应满足：

- Windows 原生可启动
- 无需 WSL
- 无需 Docker
- 能打开本地 CSV
- 能运行 pandas 分析
- 能生成图表图片
- 能输出文本摘要
- 能稳定连接指定 LLM API
