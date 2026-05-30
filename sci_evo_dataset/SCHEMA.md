# SciEvo-Lineage Dataset Schema

Three-layer architecture aligned with the Sci-Evo competition official sample
(`Sci-Evo_tool_case.json`), IdeaEvolving paper/genome/diff/trace schema,
and idea_train agentic ReAct trajectory format.

## Conventions

- All files JSON or JSONL, UTF-8, NFC.
- `paper_id` is `paper:slug:year` (matches IdeaEvolving) or `s2:<sha1>` when no slug.
- `edge_id` is `edge:<src_id>:<tgt_id>`.
- `trace_id` is `trace:<domain>:<slug>:<v>`.
- Timestamps are ISO-8601 UTC.

## Layer 1 — PaperAtom (`paper_atoms/{paper_id}.json`)

```jsonc
{
  "paper_id": "paper:directed_evolution_luciferase:2023",
  "s2_id": "...",
  "external_ids": {"arxiv": "...", "doi": "..."},
  "title": "...",
  "year": 2023,
  "venue": "Nature",
  "authors": ["..."],
  "fields_of_study": ["Biology", "Chemistry"],
  "domain": "biology",
  "subfield": "directed_evolution",
  "abstract": "...",

  // Cross-link to IdeaEvolving genome card (Layer 1 ↔ Layer 2 join key)
  "genome_card_id": "paper_xxx",
  "genome": {
    "niche_genome": "...",
    "mechanism_genome": "...",
    "limitation_genome": "...",
    "observation_genome": "..."
  },

  // === Sci-Evo official 3-section closed-loop record ===
  "closed_loop_record": {
    "01_initial_request": {
      "target_name": "...",
      "input_data": "...",
      "user_intent": "...",
      "quantifiable_goal": "..."
    },
    "02_agent_trajectory": [
      {
        "step_index": 1,
        "thought": "[Background] ... [Gap] ... [Decision] ...",
        "action": "dry_experiment | wet_experiment | analysis | literature_check",
        "tool": {"name": "...", "version": ""},
        "parameters": { "...": "..." },
        "observation": "...",
        "valid": true,
        "references": []
      }
    ],
    "03_success_verification": {
      "validation_technique": "...",
      "metrics": {
        "<metric>": {"value": "...", "unit": "...", "interpretation": "..."}
      },
      "final_verdict": "..."
    },
    // === SciEvo-Lineage extension: explicit failure/correction records ===
    "04_failure_modes": [
      {
        "step_index_ref": 4,
        "what_failed": "...",
        "diagnosis": "...",
        "correction": "..."
      }
    ]
  },

  // Provenance
  "source": {
    "pdf_path": ".../pdfs/xxx.pdf",
    "parse_tool": "mineru | mineru_cloud | docling",
    "parse_mapping": "yqh/parse_mapping_batch.json",
    "full_md_path": "..."
  },
  "construction": {
    "extractor_model": "gpt-5.5",
    "extractor_version": "2024-12-01-preview",
    "ts": "2026-05-27T..."
  }
}
```

## Layer 2 — TransitionAtom (`transitions/{edge_id}.json`)

```jsonc
{
  "edge_id": "edge:paper_A:paper_B",
  "source_paper_id": "paper_A",
  "target_paper_id": "paper_B",
  "dynamics": "Mutation | AdaptiveRadiation | Speciation | Hybridization | NicheCompetition",
  "primary_driver": "mechanism | niche | observation | limitation",
  "driver_gene": "G1",
  "gene_fates": { "G1": "MUTATED", "G2": "INHERITED" },
  "alignments": [/* IdeaEvolving alignment objects */],

  // === SciEvo-Lineage extension: narrative transition record ===
  "transition_record": {
    "gap_in_A": "What limitation/failure did A explicitly identify?",
    "hypothesis_for_B": "What did B's authors hypothesize would resolve it?",
    "decision_rationale": "Why this mechanism choice over alternatives?",
    "experimental_validation_in_B": "How did B's experiments confirm/refute the hypothesis?",
    "is_failure_recovery": true,
    "transferred_methods": ["..."],
    "newly_introduced_mechanisms": ["..."]
  },

  "construction": { "extractor_model": "gpt-5.5", "ts": "..." }
}
```

## Layer 3 — LineageTrajectory (`lineages/{trace_id}.json`)

```jsonc
{
  "trace_id": "trace:biology:directed_evolution_luciferase:v1",
  "domain": "biology",
  "subfield": "directed_evolution",
  "chain_name": "De novo luciferase design via compute-driven directed evolution",
  "papers": ["paper_A", "paper_B", "paper_C", "..."],   // ordered
  "edges": ["edge:A:B", "edge:B:C", "..."],

  // Meta-level Sci-Evo trajectory — the FIELD's exploration loop
  "chain_initial_request": {
    "open_problem": "...",
    "field_context": "...",
    "quantifiable_target": "..."
  },
  "chain_trajectory": [
    {
      "milestone_index": 1,
      "paper_id": "paper_A",
      "contribution_role": "scaffold | catalyst | refinement | speciation | hybrid",
      "rationale": "What this paper contributed and why it mattered next",
      "remaining_gap": "What problem this paper left open"
    }
  ],
  "chain_verdict": {
    "state_of_field": "...",
    "remaining_open_problems": ["..."]
  },

  "provenance": "ideaevolving_v1_seed | newly_built_via_trace_graph_agent",
  "construction": { "extractor_model": "gpt-5.5", "ts": "..." }
}
```

## Layer 4 — AgenticEpisode (`agentic_episodes/{archetype}_{n}.jsonl`)

JSONL — one demo per line, format compatible with idea_train SFT loader:

```jsonc
{
  "demo_id": "epi_w3_0042",
  "archetype": "W3_multi_paper_synthesis",
  "lineage_id": "trace:biology:...:v1",
  "user_prompt": "...",
  "trajectory": [
    {"role":"assistant", "thought":"...", "tool":"search", "input":"..."},
    {"role":"tool",      "name":"search", "output":"..."},
    {"role":"assistant", "thought":"...", "tool":"extract_genome", "input":"..."},
    /* ... */
    {"role":"assistant", "thought":"...", "tool":"propose", "input":"... structured next-step idea ..."}
  ],
  "ground_truth_next_paper_id": "paper_B"
}
```

## Domain taxonomy (8 domains)

- `cs` — computer science (LLM reasoning, agents, vision, RL, systems)
- `biology` — directed evolution, protein design, drug discovery, gene editing
- `chemistry` — retrosynthesis, catalysis, reaction design, materials chemistry
- `materials` — energy materials, battery, photovoltaic, alloy
- `medicine` — diagnostics, drug discovery, clinical prediction
- `physics` — quantum, high-energy, condensed matter, photonics
- `earth_science` — climate, geoscience, atmosphere, ocean
- `cross_domain` — AI4Bio, AI4Chem, AI4Mat bridge work
