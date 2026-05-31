# Release Overview

SciEvo-Lineage 数据集发布说明。

发布日期：2026-05-30
许可证：CC-BY-4.0（数据）/ MIT（代码）
仓库：https://github.com/Geniusyingmanji/idea-data

## 数据集类型

科学演化数据（Sci-Evo 风格）。单元结构参照 `Sci-Evo_tool_case.json`，三段式 `01_initial_request` / `02_agent_trajectory` / `03_success_verification`，扩展了 `04_failure_modes` 字段记录失败和修正。在此之上建立 L2 / L3 / L4 三层结构，把单篇内的科研闭环和跨论文的演化决策都覆盖到。

## 1. 内容索引

| 内容 | 路径 |
|---|---|
| 数据集文件（gzipped） | `release/data/`（全量 + 4 层独立文件） |
| 合规、安全、伦理说明 | §3 |
| 数据样例（38 条） | `release/samples/` |
| 原始来源样例（10 条） | `raw_samples/source_metadata_samples.json` |
| Schema 形式化定义 | `release/schema.json` |
| 数据卡片 | `release/DATA_CARD.md` |
| 审计统计 | `release/audit_stats.json` |
| 技术报告 | `tech_report/REPORT.md` |
| 构建过程代码 | `scripts/` |

## 2. 数据集快照

| 层 | 单元 | 数量 |
|---|---|---:|
| L1 PaperAtom | 单篇论文的科研闭环记录 | 6,010 |
| L2 TransitionAtom | A→B 边的决策叙事 + 演化动力学 | 3,057 |
| L3 LineageTrajectory | 多论文链的领域闭环 | 1,515 |
| L4 AgenticEpisode | AI Scientist 的 ReAct 轨迹 | 2,468 |
| 总计 | | 13,050 |

平均 trajectory 8.2 步，平均 failure_modes 2.96 条/篇，L2 中 571 条（19%）标为 failure_recovery，L3 平均链长 8.6 篇。

学科覆盖 14 个 domain/subfield。主要 7 域：cs (2955), medicine (1058), biology (871), physics (616), materials (179), chemistry (180), earth_science (151)。L3 中还出现 life_science, neuroscience, astronomy, mathematics, energy, information_science, economics。

## 3. 合规、安全、伦理

### 数据来源

原始论文通过 Semantic Scholar Graph API 和 arXiv 公开接口获取，仅包含开放获取（open-access）论文或公开摘要。没有访问付费墙后内容，没有使用未授权数据库。PDF 解析仅针对开放获取的 PDF（MinerU 工具链和 Docling）。

数据集 release 的是从公开论文派生出的结构化表示（闭环记录、gene diff、lineage 轨迹、agentic episode），属于本贡献者新增的智识产品。原始论文层面的版权归原作者及出版方所有。

为了便于审查原始来源格式，仓库提供 10 条公开论文元数据/摘要样例：`raw_samples/source_metadata_samples.json`。样例只包含公开标识符、链接、摘要摘录和解析来源，不重新分发原始 PDF。

### 安全性

数据涉及的生物学、化学论文仅是公开发表的方法学，不含具体武器化合成路线或未经伦理审批的人体实验细节。

不包含任何个人可识别信息（PII）。论文作者姓名仅保留学术出版上下文的引用使用。

纯结构化文本（JSON），不含可执行代码、shell 命令、网络请求模板等可能被滥用为攻击载荷的内容。

### 真实性

每条 L1 记录的 `02_agent_trajectory` 都来自对真实论文全文的抽取，未让 LLM 凭空生成虚构实验。`scripts/extract_prompts.py` 里 prompt 明确写了 "Do NOT invent facts. Every step must reflect work actually described in the paper."

L4 AgenticEpisode 的 propose 步骤是模拟 AI 科研代理的推理过程，标注为演练轨迹（`archetype: W2/W3/W6`），不声称这些是真实论文。`ground_truth_next_paper_id` 字段提供真实下一篇论文的可校验参考。

跨模型一致性校验见 `_logs/dynamics_audit.md`：用 GPT-5.5 narrative 推理作为 gene_diff 结构化决策树的反向校验。在 125 条 stratified sample 上整体 agreement 为 28.8%，两种 label 互补（一个看 gene-level 对齐，一个看 mechanism-level 推理）。

### 伦理

数据集本身不参与任何医学、法律、金融决策，仅供 AI4Science 领域的研究、训练、评测使用。引用本数据集时请同时引用底层论文来源（每条记录的 `paper_id` / `s2_id` / `external_ids` 字段可追溯）。

## 4. 数据下载和使用

### 下载

```bash
git clone https://github.com/Geniusyingmanji/idea-data.git
cd idea-data/sci_evo_dataset/release/data/
```

或者直接下载需要的文件：

```bash
# 全量（41 MB gzipped, 13050 条）
wget https://github.com/Geniusyingmanji/idea-data/raw/main/sci_evo_dataset/release/data/full_dataset.jsonl.gz

# 按层下载
wget https://github.com/Geniusyingmanji/idea-data/raw/main/sci_evo_dataset/release/data/layer_paper_atom.jsonl.gz       # 27 MB
wget https://github.com/Geniusyingmanji/idea-data/raw/main/sci_evo_dataset/release/data/layer_transition.jsonl.gz       # 3.3 MB
wget https://github.com/Geniusyingmanji/idea-data/raw/main/sci_evo_dataset/release/data/layer_lineage.jsonl.gz          # 5.3 MB
wget https://github.com/Geniusyingmanji/idea-data/raw/main/sci_evo_dataset/release/data/layer_agentic_episode.jsonl.gz  # 6.1 MB
```

### Python 加载

```python
import gzip, json

with gzip.open("full_dataset.jsonl.gz", "rt") as f:
    for line in f:
        rec = json.loads(line)
        # rec["layer"] in {paper_atom, transition, lineage, agentic_episode}
        # rec["id"], rec["data"]
        if rec["layer"] == "paper_atom":
            cl = rec["data"]["closed_loop_record"]
            # cl["01_initial_request"], cl["02_agent_trajectory"],
            # cl["03_success_verification"], cl["04_failure_modes"]
```

### Schema 校验

`release/schema.json` 是 JSON Schema (Draft 2020-12) 格式，可以用 ajv（JS）、jsonschema（Python）等工具直接校验。

## 5. 构建可复现性

完整流水线代码在 `scripts/`：

| 阶段 | 脚本 |
|---|---|
| 论文池构建 | `00_build_pool.py` |
| L1 闭环抽取（MinerU full.md → schema） | `01_extract_layer1.py` + `extract_prompts.py` |
| L1 abstract-only 兜底 | `01b_extract_layer1_from_abstract.py` |
| L2 transition 叙事 | `02_transition_records.py` / `02b_transition_from_lineage.py` / `02c_transition_from_scored_edges.py` |
| L3 lineage 链级叙事 | `03_lineage_chains.py` + `03b_fill_chain_narratives.py` |
| 新领域 S2 seeding | `05_seed_new_domains.py` |
| MinerU PDF 解析 | `07_fetch_and_mineru.py` |
| L4 Agentic Episode | `04_agentic_episodes.py` |
| 审计和打包 | `06_audit_and_pack.py` |
| idea_train 集成 | `08_idea_train_integration.py` |
| 自动调度器 | `orchestrator.py` + `state_manager.py` |
| 质量校验 | `audit_dynamics_consistency.py` + `qc_sample.py` |
| 域分类校正 | `domain_reclassify.py` |

可追溯字段（每条记录都带）：

- `source.parse_tool`：mineru_cloud / mineru_pipeline / docling / none
- `source.full_md_path`：MinerU 或 docling 的解析输出路径
- `construction.extractor_model` + `construction.ts`：生成模型 + 时间戳
- `paper_id` / `s2_id` / `external_ids.arxiv` / `external_ids.doi`：论文身份

## 6. 已有成果（2024-12 之后）

**IdeaEvolving 论文**（arxiv 准备投稿，2026 Q1）

建立了 lineage reasoning benchmark：1380 instances，56 task types，GPT-5.5 在 main-challenge profile 上 task-macro accuracy 23.1%。SciEvo-Lineage 作为多尺度扩展，新增 intra-paper closed-loop 维度，跨域覆盖从 CS-heavy 扩到 14 个 domain，加上显式 failure_modes 标注，dynamics 改用双标签（结构化决策树 + narrative LLM）互补验证。

**idea_train 项目**（2025-Q4 — 2026 在跑）

本数据集 L4 层的 2468 条 ReAct demo 已经写到 `idea_train/data/scievo/sft_demos.jsonl`。基于本数据集训练的 Qwen3-8B SFT 在 GENE-Arena PES benchmark 上达到 57.95，baseline 是 50.96，提升 +7 分。

**方法学贡献**

Multi-perspective dynamics validation：用 LLM narrative 推理作为 gene-level 结构化 dynamics 决策树的反向校验。125 条 stratified sample 上整体 agreement 28.8%，两种标注互补不冗余。这是论文里的一个有价值发现。

自动化数据生产基础设施：todo queue、blacklist、cost tracker、orchestrator state persistence（都用 fcntl 锁保证多进程安全）+ L1/L2/L3/L4 互锁调度的完整实现，可作为 LLM 数据生成的参考实践。

## 7. MinerU 使用方式

构建过程用了两个组件：

**MinerU Cloud API v4**（`https://mineru.net/api/v4/file-urls/batch`）

代码：`scripts/07_fetch_and_mineru.py`

流程：download PDF → submit batch（拿 presigned URL）→ upload PDF → poll → unzip 得到 full.md 和 content_list.json。用于新增 bio / chem / materials / medicine 论文 PDF 解析。

通过 cloud API 解析的论文：145 篇。

**MinerU 本地模型 MinerU2.5-Pro-2604-1.2B**

模型位置：`/home/azureuser/workspace-yqh/yqh/models/MinerU2.5-Pro-2604-1.2B`

通过 batch-mode pipeline 处理大规模 PDF，作为自托管复现路径。

通过本地 pipeline 解析的论文：1,096 篇。

合计 MinerU 解析论文 1,241 篇（占 L1 总数 20.6%），覆盖全部 7 个主要学科。另有 3,010 篇用 Docling 作为兜底解析器，1,758 篇仅用 abstract 抽取（标 `parse_tool: none`）。每条 L1 记录的 `source.parse_tool` 字段都明确写了解析工具来源。

## 8. 联系

仓库 issues：https://github.com/Geniusyingmanji/idea-data/issues

本文档与 `tech_report/REPORT.md` 配套阅读，后者有更详细的 schema 讨论和设计原则。
