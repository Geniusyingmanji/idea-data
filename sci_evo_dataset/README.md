# SciEvo-Lineage

科学论文的演化轨迹数据集。

每篇论文的研究过程（问题、方法、结果、失败）被结构化抽取出来，相邻论文之间的演化关系也被显式标注，多篇论文串成领域级演化链，链上还演练了 AI 科研代理的 ReAct 轨迹。

13,050 条记录，14 个学科，全部基于公开论文（arXiv / Semantic Scholar / MinerU 解析）构建。

## 四层结构

每条数据属于以下四层之一：

| 层 | 单元 | 数量 | 内容 |
|---|---|---:|---|
| L1 PaperAtom | 单篇论文 | 6,010 | 该论文的实验闭环：问题、目标、每步推理和工具调用、验证、失败修正 |
| L2 TransitionAtom | A→B 论文边 | 3,057 | A 的缺陷、B 的假设、决策理由、实验验证、是否是 failure recovery |
| L3 LineageTrajectory | 多论文链 | 1,515 | 整条链的开放问题、每篇里程碑的角色、领域当前状态 |
| L4 AgenticEpisode | 智能体轨迹 | 2,468 | 在某条链上模拟 AI 科学家的 ReAct 推理：search/read/extract/diff/propose |

完整字段定义见 [SCHEMA.md](SCHEMA.md)。

## 仓库布局

代码、文档、样例和压缩数据都在 git 仓库里。原始未压缩数据（约 500 MB）保存在本机 `/data/zyf/sci_evo_dataset/`，不进 git。

```
sci_evo_dataset/
├── README.md             本文件
├── SCHEMA.md             字段定义
├── LICENSE               CC-BY-4.0
├── scripts/              15 个构建脚本
├── tech_report/
│   ├── REPORT.md         技术报告
│   └── IDEAEVOLVING_V2_DELTA.md
└── release/
    ├── OVERVIEW.md       数据发布说明
    ├── data/             gzip 全量 + 4 层独立文件
    ├── samples/          38 条范例
    ├── schema.json
    ├── DATA_CARD.md
    └── audit_stats.json
```

## 数据访问

直接 git clone 仓库即可拿到全部数据。数据文件用 gzip 压缩存储：

```python
import gzip, json

with gzip.open("release/data/full_dataset.jsonl.gz", "rt") as f:
    for line in f:
        rec = json.loads(line)
        # rec["layer"], rec["id"], rec["data"]
```

或只读单层：

```python
with gzip.open("release/data/layer_paper_atom.jsonl.gz", "rt") as f:
    for line in f:
        atom = json.loads(line)
        cl = atom["data"]["closed_loop_record"]
        # cl["01_initial_request"], cl["02_agent_trajectory"],
        # cl["03_success_verification"], cl["04_failure_modes"]
```

## 复现

在 `idea` conda 环境下，按顺序跑脚本：

```bash
conda activate idea
cd scripts/
python 00_build_pool.py                 # 一次性建立论文池
python 01_extract_layer1.py --max 200   # L1 抽取
python 02_transition_records.py --max 100 --shuffle
python 03_lineage_chains.py --max 50 --min-chain-len 5
python 05_seed_new_domains.py
python 03b_fill_chain_narratives.py --max 50
python 04_agentic_episodes.py --max-lineages 50
python 06_audit_and_pack.py
```

或者交给 orchestrator 自动跑：

```bash
nohup python scripts/orchestrator.py > _logs/orchestrator.log 2>&1 &
```

orchestrator 每 3 分钟检查一次进度，自动补批次，达标后自动跑 audit 和 idea_train 集成，然后退出。状态持久化在 `_state/orchestrator.json`，中途重启不会丢进度。

路径配置在 `scripts/common.py` 里的 `CODE_ROOT`（仓库根）和 `DATA_ROOT`（数据根）两个常量。如果数据不在 `/data/zyf` 改一下 `DATA_ROOT` 就行。

## 依赖

- Python 3.10+，conda env `idea`
- Azure OpenAI GPT-5.5（managed identity 鉴权）
- Semantic Scholar Graph API
- MinerU 2.5-Pro（Cloud API + 本地模型两条路径）
- Docling（兜底 PDF 解析器）

## 许可证

数据 CC-BY-4.0，代码 MIT。
