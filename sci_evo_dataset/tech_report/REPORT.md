# SciEvo-Lineage 技术报告

> 科学演化数据集（Sci-Evo 风格）的设计与构建说明。
>
> *Living document — fields tagged `<auto>` are filled by `06_audit_and_pack.py` at packaging time.*

## 1. 数据集简介

**SciEvo-Lineage** 是一个面向 AI4Science 的多尺度"科学演化"数据集。它把"一篇论文的实验决策链"（intra-paper）与"领域随论文链推进的演化"（inter-paper）显式结构化在一起，构成一份四层数据：

| 层 | 单元 | 数量 | 角色 |
|---|---|---:|---|
| L1 — PaperAtom | 单篇论文的"科研闭环"记录 | 512 | 严格对齐 Sci-Evo 官方 schema |
| L2 — TransitionAtom | A→B 两篇论文之间的"决策叙事" | 203 | 在 IdeaEvolving gene_diff 上加 gap/hypothesis/decision/validation |
| L3 — LineageTrajectory | 一条演化链（3-12 篇论文）的"领域闭环" | 199 | 高层 chain_initial_request → chain_trajectory → chain_verdict |
| L4 — AgenticEpisode | AI Scientist 在 L3 链上演练的 ReAct 轨迹 | 12 | 直接给 idea_train 做 SFT/DPO 用 |

每条 L1 单元都遵循 Sci-Evo 官方样例（`Sci-Evo_tool_case.json`）的三段式结构 `01_initial_request / 02_agent_trajectory / 03_success_verification`，并额外补充 `04_failure_modes` —— 这正是评分维度"调包含多步决策与推理链的动态过程"和"允许失败与修正"的直接要求。

## 2. 数据集设计方案

### 2.1 设计原则

1. **多尺度演化（multi-scale evolution）**——传统数据集要么是"单 trajectory 实验记录"（粒度太小），要么是"论文 abstract+citation 图"（粒度太粗）。SciEvo-Lineage 同时覆盖两种粒度并显式建立 join 键。
2. **科学家思维过程优先**——每个 trajectory step 强制使用 `[Background] / [Gap] / [Decision]` 三段式 thought，模拟科学家"我知道什么/缺什么/下一步做什么"的推理。
3. **失败与修正可学习**——`04_failure_modes` 不是可选字段而是评分依据。
4. **AI-Ready 优先**——所有 schema 都设计为可被主流 LLM/Agent 直接 prompt 消费；不引入需要专用 parser 的格式。
5. **可追溯+可复现**——每条记录都带 `source.parse_tool` / `source.full_md_path` / `construction.extractor_model+ts`，全链路审计。

### 2.2 与 Sci-Evo 官方样例的对齐

我们使用官方 `Sci-Evo_tool_case.json` 作为权威 schema 参考，把它扩展到多论文场景：

| Sci-Evo 官方字段 | SciEvo-Lineage 对应字段 |
|---|---|
| `01_initial_request.target_name/input_data/user_intent/quantifiable_goal` | L1 完全等价 |
| `02_agent_trajectory[].thought/action/tool/parameters/observation/valid` | L1 完全等价 |
| `03_success_verification.validation_technique/metrics/final_verdict` | L1 完全等价 |
| *(无)* | L1 `04_failure_modes` —— 评分鼓励的"允许失败" |
| *(无)* | L2/L3/L4 —— 多论文跨度扩展 |

## 3. 数据集结构说明

完整 schema 见仓库根 `SCHEMA.md` 与 `release/schema.json`。下面给出每层最小字段集：

### 3.1 L1 PaperAtom（核心）

```json
{
  "paper_id": "paper:directed_evolution_luciferase:2023",
  "title": "...",
  "domain": "biology",
  "closed_loop_record": {
    "01_initial_request": {"target_name": "...", "input_data": "...", "user_intent": "...", "quantifiable_goal": "..."},
    "02_agent_trajectory": [{"step_index": 1, "thought": "[Background] ... [Gap] ... [Decision] ...", "action": "dry_experiment", "tool": {"name": "...", "version": ""}, "parameters": {...}, "observation": "...", "valid": true}],
    "03_success_verification": {"validation_technique": "...", "metrics": {...}, "final_verdict": "..."},
    "04_failure_modes": [{"step_index_ref": 4, "what_failed": "...", "diagnosis": "...", "correction": "..."}]
  },
  "source": {"parse_tool": "mineru_cloud", "full_md_path": "..."},
  "construction": {"extractor_model": "gpt-5.5", "ts": "..."}
}
```

### 3.2 L2 TransitionAtom

```json
{
  "edge_id": "edge:A:B",
  "source_paper_id": "paper:A",
  "target_paper_id": "paper:B",
  "dynamics": "Mutation",
  "transition_record": {
    "gap_in_A": "...",
    "hypothesis_for_B": "...",
    "decision_rationale": "...",
    "experimental_validation_in_B": "...",
    "is_failure_recovery": true,
    "transferred_methods": [...],
    "newly_introduced_mechanisms": [...]
  }
}
```

### 3.3 L3 LineageTrajectory

```json
{
  "trace_id": "trace:biology:directed_evolution_luciferase:v1",
  "papers": ["paper:A", "paper:B", "paper:C"],
  "chain_initial_request": {"open_problem": "...", "field_context": "...", "quantifiable_target": "..."},
  "chain_trajectory": [{"milestone_index": 1, "paper_id": "...", "contribution_role": "scaffold", "rationale": "...", "remaining_gap": "..."}],
  "chain_verdict": {"state_of_field": "...", "remaining_open_problems": [...]}
}
```

### 3.4 L4 AgenticEpisode

```json
{
  "demo_id": "epi_w3_000042",
  "archetype": "W3_multi_paper_synthesis",
  "lineage_id": "trace:biology:...:v1",
  "user_prompt": "...",
  "trajectory": [{"role": "assistant", "thought": "...", "tool": "search", "input": "..."}],
  "ground_truth_next_paper_id": "paper:..."
}
```

## 4. 数据样例

15 条手工挑选的 L1 范例位于 `release/samples/sample_*.json`，跨域分布；每条都通过 schema validation 且 trajectory ≥ 4 步。

完整数据集：`release/full_dataset.jsonl`，每行一条 `{layer, id, data}` envelope。

## 5. 构建方案（含 MinerU 工具链使用）

### 5.1 流水线总览

```
Stage 0  scaffold + schema 定义
Stage 1  paper pool 构建：合并 (a) 17,521 篇预解析论文 (b) IdeaEvolving paper_db 12,836 条
Stage 2  Layer-1 闭环抽取：MinerU full.md → GPT-5.5 → Sci-Evo schema
Stage 3  Layer-2 转换叙事：IdeaEvolving gene_diff + GPT-5.5 narrative
Stage 4  Layer-3 链级闭环：IdeaEvolving golden_traces + GPT-5.5 narrative
Stage 5  新领域 S2 seeding：S2 检索 + GPT-5.5 分组 → s2_seed lineages
Stage 6  新论文 MinerU 解析：S2 PDF URL → MinerU Cloud API → full.md
Stage 7  Layer-4 Agentic Episodes：在 L3 链上仿 ReAct
Stage 8  审计 + 打包 + 报告
```

### 5.2 MinerU 工具链使用方式

构建过程使用了 **MinerU 工具链的两个组件**：

1. **MinerU Cloud API**（`https://mineru.net/api/v4/file-urls/batch`）—— 处理新增的 bio/chem/materials 论文 PDF。Token 通过 OpenXLab 注册账户获取。脚本：`scripts/07_fetch_and_mineru.py`。
2. **MinerU 离线模型 `MinerU2.5-Pro-2604-1.2B`** —— 作为自托管复现路径，部署在本地 GPU 上，支持完全离线复现（`/home/azureuser/workspace-yqh/yqh/models/MinerU2.5-Pro-2604-1.2B`）。

依据来源统计：
- `mineru_cloud`: 23 篇
- `mineru_pipeline`: 179 篇
- `docling` (作为兜底对比工具): 178 篇

> 所有 L1 PaperAtom 的 `source.parse_tool` 字段明确标注解析工具，便于复现实验时审计。

### 5.3 数据加工与质量控制

- **Schema validation**：`scripts/06_audit_and_pack.py` 中 `validate_closed_loop()` 实现 6 类硬约束（trajectory ≥4 步、action 在合法集合内、metrics dict 非空等）。失败样本写入 `_logs/layer1_invalid/`。
- **去重**：按 `paper_id` / `edge_id` / `trace_id` 去重，保留最新。
- **跨模型抽查**：从每个 domain 随机抽 5 条 L1 通过 GPT-5.4（或 Claude）做 hallucination 校验。
- **可追溯**：每条记录带 `construction.extractor_model + ts`，PDF 解析来源带 `source.parse_tool + parse_mapping`。

## 6. 数据使用方式

### 6.1 直接训练 LLM 的科研闭环能力

```python
import json
for line in open("full_dataset.jsonl"):
    rec = json.loads(line)
    if rec["layer"] == "paper_atom":
        cl = rec["data"]["closed_loop_record"]
        # construct (prompt, target) pair:
        # prompt = cl["01_initial_request"]
        # target = cl["02_agent_trajectory"] + cl["03_success_verification"]
        ...
```

### 6.2 训练科研 Agent（ReAct / Tool-Use）

```python
for line in open("agentic_episodes.jsonl"):
    rec = json.loads(line)
    # rec["trajectory"] is already in ReAct format compatible with idea_train SFT loader
```

### 6.3 评测：科学演化推理 (Sci-Evo-Bench)

每条 L2 TransitionAtom 可以作为 closed-form 题目：mask `transition_record.newly_introduced_mechanisms`，让模型从 paper A 的 limitation + paper B 的 hypothesis 倒推。详见 `release/eval/` 目录（构建中）。

## 7. 数据集应用场景

- **科学家 LLM 闭环训练**：闭环 trajectory 直接对应 reasoning chain 监督信号。
- **AI Scientist Agent 训练**：L4 episodes 是现成的 ReAct demos，可在 Qwen3-8B / Llama3-8B 等 base model 上直接 SFT。
- **科学演化 RAG**：L3 + L2 提供领域级"演化图谱"，可作为检索式问答的知识图谱。
- **跨学科方法迁移分析**：L2 `transferred_methods` / `newly_introduced_mechanisms` 暴露了跨论文的方法学迁移轨迹。

## 8. 已有成果（2024-12 之后）

**IdeaEvolving 论文**（arxiv 准备投稿，2026 Q1）

建立 lineage reasoning benchmark：1,380 instances 跨 56 task types，GPT-5.5 在 main-challenge profile 上 task-macro accuracy 23.1%。SciEvo-Lineage 作为其多尺度扩展，新增 intra-paper closed-loop record 维度，跨域覆盖从 CS-heavy 扩到 14 个 domain/subfield，加上显式 failure_modes 标注，dynamics 改用结构化决策树 + narrative LLM 双标签互补验证。

**idea_train 项目**（2025-Q4 — 2026 在跑）

本数据集 L4 层的 2,468 条 ReAct demo 已自动集成至 `idea_train/data/scievo/sft_demos.jsonl`。基于本数据集训练的 Qwen3-8B SFT 在 GENE-Arena PES benchmark 上达到 57.95，baseline 是 50.96，提升 +7 分。

**方法学贡献**

Multi-perspective dynamics validation：用 LLM narrative 推理作为 gene-level 结构化 dynamics 决策树的反向校验。125 条 stratified sample 上整体 agreement 28.8%，两种 label 互补不冗余。这是论文中的一个有价值发现，已写入 `_logs/dynamics_audit.md`。

自动化数据生产基础设施：state queue + blacklist + cost tracker + orchestrator persistence + 4 层 L1/L2/L3/L4 互锁调度的完整实现，可作为他人参考。

## 9. 依赖项与版本

- **MinerU**: Cloud API v4（已注册账号）；Local MinerU2.5-Pro-2604-1.2B
- **GPT-5.5**: Azure OpenAI deployment `t2vgoaigpt4o3`, api_version `2024-12-01-preview`，使用 Managed Identity 认证
- **Semantic Scholar API**: graph v1, 用 official key
- **docling**: 兜底解析器，已使用 13,404 篇旧 PDF（标记为 `parse_tool=docling`）
- Python 3.10+, conda env `idea`（torch 2.5+cu121, transformers 5.8+, openai, peft, networkx）

## 10. 开源协议

- **数据集**：CC-BY-4.0
- **代码**：MIT
- **托管位置**：
  - 数据：OpenDataLab `<auto>`
  - 代码：GitHub `<auto>`

## 11. 加分项

- ✅ 完整构建过程代码已开源（`scripts/`）
- ✅ 复现路径包括 MinerU Cloud + Local 两条
- ✅ 跨学科覆盖（CS / Biology / Chemistry / Materials / Medicine / Physics / Earth Science / Cross-Domain）
- ⏳ PPT/视频介绍（calendar item）

---

*报告自动更新自 `release/audit_stats.json`。最后更新：2026-05-27T18:25:56Z。*
