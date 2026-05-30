# idea-data

科研演化数据集 SciEvo-Lineage 的代码和数据。

13,050 条结构化记录，覆盖 14 个学科，分四层：单篇论文的实验闭环、相邻论文之间的演化决策、多篇论文组成的领域演化链、以及在演化链上演练的 ReAct 智能体轨迹。

## 内容

```
idea-data/
├── README.md                — 本文件
├── Sci-Evo-Sample.pdf       — schema 参考样例
├── Sci-Evo_tool_case.json   — schema 参考样例
└── sci_evo_dataset/         — 主体
    ├── README.md            — 数据集介绍
    ├── SCHEMA.md            — 字段定义
    ├── LICENSE              — CC-BY-4.0
    ├── scripts/             — 构建流水线（15 个脚本）
    ├── tech_report/         — 技术报告
    │   ├── REPORT.md
    │   └── IDEAEVOLVING_V2_DELTA.md
    └── release/
        ├── OVERVIEW.md      — 数据发布说明
        ├── data/            — gzip 全量 + 4 层独立文件
        ├── samples/         — 38 条样例
        ├── schema.json
        ├── DATA_CARD.md
        └── audit_stats.json
```

## 下载

```bash
git clone https://github.com/Geniusyingmanji/idea-data.git
cd idea-data/sci_evo_dataset/release/data/
gunzip full_dataset.jsonl.gz
```

只关心某一层：

```bash
gunzip layer_paper_atom.jsonl.gz       # L1: 6010 条单篇闭环记录
gunzip layer_transition.jsonl.gz       # L2: 3057 条转换叙事
gunzip layer_lineage.jsonl.gz          # L3: 1515 条演化链
gunzip layer_agentic_episode.jsonl.gz  # L4: 2468 条 ReAct 轨迹
```

## 读取

```python
import json
with open("full_dataset.jsonl") as f:
    for line in f:
        rec = json.loads(line)
        # rec["layer"] in {paper_atom, transition, lineage, agentic_episode}
        # rec["id"], rec["data"]
```

## 详细文档

- 数据集介绍和使用：`sci_evo_dataset/README.md`
- 字段定义：`sci_evo_dataset/SCHEMA.md`
- 发布说明：`sci_evo_dataset/release/OVERVIEW.md`
- 技术报告（构建方案、工具使用、质量评估）：`sci_evo_dataset/tech_report/REPORT.md`

## 许可证

数据 CC-BY-4.0，代码 MIT。
