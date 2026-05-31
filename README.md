# SciEvo-Lineage / idea-data

面向 AI4Science 的 **Sci-Evo 类型**科研演化数据集。数据集把单篇论文内的实验闭环、相邻论文之间的演化决策、多论文领域演化链，以及链上的 ReAct 智能体轨迹统一成可训练、可评测、可追溯的 JSON/JSONL 数据。

- 开源地址：https://github.com/Geniusyingmanji/idea-data
- 数据规模：13,050 条结构化记录
- 学科覆盖：14 个规范化学科/子领域标签
- 数据许可：CC-BY-4.0
- 代码许可：MIT

## 数据集设计

SciEvo-Lineage 采用四层结构：

| 层 | 单元 | 数量 | 说明 |
|---|---|---:|---|
| L1 PaperAtom | 单篇论文 | 6,010 | 按 Sci-Evo 官方样例抽取 `01_initial_request` / `02_agent_trajectory` / `03_success_verification`，并补充 `04_failure_modes` |
| L2 TransitionAtom | A->B 论文边 | 3,057 | 标注前作缺口、后作假设、决策理由、验证方式和 failure recovery |
| L3 LineageTrajectory | 多论文链 | 1,515 | 描述一个领域问题如何随多篇论文推进 |
| L4 AgenticEpisode | ReAct 轨迹 | 2,468 | 面向科研 Agent 训练的 search/read/extract/diff/propose 轨迹 |

核心设计原则是：只基于公开论文和开放摘要构建，不伪造实验事实；每条记录保留来源、解析工具、构建脚本和时间戳；用 schema validation、去重、抽样质检保证格式和可用性。

## 仓库结构

```
idea-data/
├── README.md                         # 参赛提交入口和数据集简介
├── Sci-Evo-Sample.pdf                # 官方 Sci-Evo 参考样例
├── Sci-Evo_tool_case.json            # 官方 Sci-Evo schema 参考样例
├── materials/                        # PPT、视频和讲解稿
└── sci_evo_dataset/
    ├── README.md                     # 数据集使用说明
    ├── SCHEMA.md                     # 字段定义和标注规范
    ├── LICENSE                       # 数据 CC-BY-4.0
    ├── raw_samples/                  # 原始来源数据样例
    ├── scripts/                      # 构建、解析、审计和打包代码
    ├── tech_report/REPORT.md         # 完整技术报告
    └── release/
        ├── data/                     # gzip 全量数据 + 4 层独立数据
        ├── samples/                  # 38 条完整 L1 数据样例
        ├── OVERVIEW.md               # 发布说明、合规和 MinerU 使用说明
        ├── DATA_CARD.md              # 数据卡片和统计摘要
        ├── schema.json               # JSON Schema
        └── audit_stats.json          # 审计统计
```

## 数据文件

| 文件 | 内容 |
|---|---|
| `sci_evo_dataset/release/data/full_dataset.jsonl.gz` | 全量 13,050 条记录 |
| `sci_evo_dataset/release/data/layer_paper_atom.jsonl.gz` | L1 单篇科研闭环 |
| `sci_evo_dataset/release/data/layer_transition.jsonl.gz` | L2 论文间转换记录 |
| `sci_evo_dataset/release/data/layer_lineage.jsonl.gz` | L3 领域演化链 |
| `sci_evo_dataset/release/data/layer_agentic_episode.jsonl.gz` | L4 ReAct 轨迹 |

每行是一个 JSON envelope：

```json
{"layer": "paper_atom", "id": "...", "data": {...}}
```

## 数据样例

- 完整样例：`sci_evo_dataset/release/samples/`，共 38 条，均包含完整的 `01_initial_request`、`02_agent_trajectory`、`03_success_verification` 和 `04_failure_modes`。
- 原始来源样例：`sci_evo_dataset/raw_samples/source_metadata_samples.json`，提供 10 条公开论文元数据/摘要样例，包含 Semantic Scholar ID、arXiv/DOI 链接、摘要、学科和解析工具来源。

## 数据使用

```python
import gzip
import json

with gzip.open("sci_evo_dataset/release/data/full_dataset.jsonl.gz", "rt", encoding="utf-8") as f:
    for line in f:
        rec = json.loads(line)
        layer = rec["layer"]
        data = rec["data"]
        if layer == "paper_atom":
            closed_loop = data["closed_loop_record"]
```

## 应用场景

- 训练 LLM 的科学实验闭环推理能力
- 训练科研 Agent 的 ReAct 工具使用和多论文综合能力
- 构建科学演化 RAG / lineage graph
- 评测模型对论文间 gap、hypothesis、decision、validation 的推断能力
- 分析跨学科方法迁移和 failure recovery 模式

## 参赛材料索引

| 比赛要求 | 仓库位置 |
|---|---|
| Sci-Evo 类型说明和数据集简介 | `README.md`, `sci_evo_dataset/release/OVERVIEW.md` |
| 互联网可访问数据链接 | `https://github.com/Geniusyingmanji/idea-data` |
| 原始数据样例 | `sci_evo_dataset/raw_samples/source_metadata_samples.json` |
| 技术报告 | `sci_evo_dataset/tech_report/REPORT.md` |
| 字段定义、数据来源、标注规范 | `sci_evo_dataset/SCHEMA.md`, `sci_evo_dataset/tech_report/REPORT.md` |
| 不少于 10 条完整样例 | `sci_evo_dataset/release/samples/` |
| 数据构建和加工代码 | `sci_evo_dataset/scripts/` |
| MinerU 使用方式 | `sci_evo_dataset/release/OVERVIEW.md`, `sci_evo_dataset/tech_report/REPORT.md` |
| 合规、安全、伦理说明 | `sci_evo_dataset/release/OVERVIEW.md` |
| 数据卡片和质量统计 | `sci_evo_dataset/release/DATA_CARD.md`, `sci_evo_dataset/release/audit_stats.json` |
| PDF 版 PPT 和视频介绍 | `materials/SciEvo-Lineage_Submission.pdf`, `materials/SciEvo-Lineage_Overview.mp4` |

## 许可证

数据 CC-BY-4.0，代码 MIT。底层论文版权归原作者及出版方所有；本仓库发布的是基于公开论文和开放摘要构建的结构化派生数据。
