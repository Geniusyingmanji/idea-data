# SciEvo-Lineage Dataset — Data Card

Multi-scale scientific evolution dataset for AI4Science.

## Snapshot (2026-05-30 13:07 UTC)

### Layer 1 — PaperAtom (closed-loop record per paper)
- total: 6010
- valid: 6010
- mean trajectory steps: 8.2
- mean failure_modes: 2.96
- parse tool mix: {"none": 1758, "docling": 3011, "mineru_pipeline": 1096, "mineru_cloud": 145}
- domain mix: {"chemistry": 180, "physics": 616, "medicine": 1058, "materials": 179, "cs": 2955, "earth_science": 151, "biology": 871}
- failure_modes by parse tool (full-text papers have higher coverage than abstract-only): {"none": {"n": 1758, "mean_failures": 0.56, "pct_zero": 67.4}, "docling": {"n": 3011, "mean_failures": 3.86, "pct_zero": 3.4}, "mineru_pipeline": {"n": 1096, "mean_failures": 4.19, "pct_zero": 3.0}, "mineru_cloud": {"n": 145, "mean_failures": 4.01, "pct_zero": 5.5}}

### Layer 2 — TransitionAtom (decision narrative per A→B edge)
- total: 3057
- valid: 3057
- failure-recovery transitions: 571
- primary driver mix: {"?": 1283, "mechanism": 1010, "niche": 627, "limitation": 125, "observation": 12}
- structural dynamics (from gene_diff alignment) on 1774 records: {"Mutation": 310, "Speciation": 762, "Niche Competition": 68, "Hybridization": 188, "Adaptive Radiation": 446}
- narrative dynamics (LLM-inferred from transition text) on 1283 records: {"Niche Competition": 206, "Adaptive Radiation": 300, "Speciation": 169, "Hybridization": 216, "Mutation": 392}

### Layer 3 — LineageTrajectory (multi-paper field-evolution chain)
- total: 1515
- valid: 1515
- mean chain length: 8.6 (range 4-15)
- domain mix: {"cs": 829, "earth_science": 98, "biology": 79, "physics": 72, "materials": 85, "medicine": 60, "chemistry": 98, "CS": 38, "energy": 24, "mathematics": 20, "information_science": 24, "neuroscience": 26, "life_science": 38, "astronomy": 23, "economics": 1}

### Layer 4 — AgenticEpisode (ReAct demos for agent SFT)
- total: 2468
- archetype mix: {"W3_multi_paper_synthesis": 1024, "W2_single_paper_extension": 1021, "W6_cross_domain_bridge": 423}

## License
CC-BY-4.0. Source papers via open access (arXiv / Semantic Scholar / openAccessPdf), parsed with MinerU and Docling, structured with GPT-5.5.

## Files
- `samples/sample_*.json`     — exemplars matching the 3-section schema
- `data/full_dataset.jsonl.gz` — unified 4-layer dataset, one JSON per line
- `data/layer_*.jsonl.gz`     — per-layer split for selective download
- `schema.json`               — JSON Schema (Draft 2020-12)
- `../tech_report/REPORT.md`  — detailed methodology
