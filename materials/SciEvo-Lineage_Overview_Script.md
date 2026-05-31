# SciEvo-Lineage Overview Video Script

This script matches `SciEvo-Lineage_Overview.mp4`. The video is a silent slide overview; these notes can be used for live narration or voice-over.

## Slide 1: SciEvo-Lineage

SciEvo-Lineage 是一个面向 AI4Science 的 Sci-Evo 类型数据集。它把单篇论文内的实验闭环和跨论文的领域演化统一成可训练、可评测、可追溯的数据。

## Slide 2: 为什么需要科学演化数据

传统论文数据集要么只保留摘要和引用，要么只记录单次实验过程。Sci-Evo 任务真正需要的是问题、缺口、决策、验证和失败修正如何随研究推进而变化。

## Slide 3: 数据集总览

当前 release 共 13050 条结构化记录，覆盖 14 个规范化学科和子领域标签。数据分为
PaperAtom、TransitionAtom、LineageTrajectory 和 AgenticEpisode 四层。

## Slide 4: L1 PaperAtom: 单篇科研闭环

第一层严格对齐官方 Sci-Evo 样例，包含初始请求、智能体轨迹、成功验证，并额外加入失败模式。平均每条记录 8.2 个 trajectory step。

## Slide 5: L2/L3: 论文间决策与领域演化链

第二层描述相邻论文之间的缺口、假设、决策理由和验证。第三层把多篇论文连成领域演化链，用来学习一个开放问题如何被持续推进。

## Slide 6: L4 AgenticEpisode: 科研 Agent 轨迹

第四层把 lineage 上的推理过程转成 ReAct 轨迹，覆盖 search、read、extract、diff 和 propose 等动作，可直接服务于科研 Agent 的
SFT 或偏好训练。

## Slide 7: 构建流水线

构建流程从 Semantic Scholar、arXiv 和 openAccessPdf 获取公开来源，经 MinerU 或 Docling 解析，再由 GPT-5.5
抽取结构化闭环，最后统一审计和打包。

## Slide 8: MinerU 使用方式

本数据集同时使用 MinerU Cloud API 和本地 MinerU2.5-Pro pipeline。所有 L1 记录都保留 parse_tool 字段，便于复现和来源审计。

## Slide 9: 质量控制与合规

数据构建禁止伪造科学事实。质量控制包括 schema validation、去重、抽样质检和可追溯字段。数据来源限定为公开论文、开放摘要和开放获取 PDF。

## Slide 10: 提交内容与应用价值

仓库包含数据、样例、原始来源样例、技术报告、schema、审计统计和完整构建代码。它可以用于科学推理训练、科研 Agent、演化 RAG 和 Sci-Evo 风格评测。
