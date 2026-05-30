"""Prompt templates for closed-loop extraction across domains.

The prompt asks GPT-5.5 to produce a Sci-Evo-schema-compliant JSON from a
paper's full markdown. Domain-conditioned to emphasize the right tool vocabulary.
"""
from __future__ import annotations

DOMAIN_GUIDANCE = {
    "cs": {
        "tool_examples": "transformer architectures, RL algorithms (PPO/DPO), pretraining pipelines, fine-tuning frameworks, benchmark suites, ablation tooling",
        "step_kinds": "(model design) → (pretraining/finetuning runs) → (benchmark evaluation) → (ablation) → (analysis)",
        "metric_examples": "accuracy, perplexity, throughput, parameter count, FLOPs, ELO, win-rate",
    },
    "biology": {
        "tool_examples": "AlphaFold2/3, RoseTTAFold, ProteinMPNN, RFdiffusion, RFAA, cryo-EM, CRISPR-Cas9, FACS, NGS, site-saturation mutagenesis, directed evolution rounds, in vitro/in vivo assays",
        "step_kinds": "(target hypothesis) → (dry: computational design / docking / prediction) → (wet: cloning, expression, screening) → (characterization) → (iterative optimization)",
        "metric_examples": "kcat/Km, Kd, EC50, fold-enrichment, thermostability (Tm), photon flux, percent identity, expression yield",
    },
    "chemistry": {
        "tool_examples": "DFT calculations, retrosynthesis planners (Synthia/ASKCOS), reaction databases, high-throughput screening, kinetic profiling, NMR/MS characterization, catalyst libraries",
        "step_kinds": "(target/route hypothesis) → (DFT/MD simulation) → (synthesis attempt) → (characterization) → (yield/selectivity optimization)",
        "metric_examples": "yield (%), ee (%), TON, TOF, conversion, selectivity ratio, activation energy",
    },
    "materials": {
        "tool_examples": "DFT (VASP/Quantum ESPRESSO), MD (LAMMPS), CALPHAD, X-ray diffraction, electron microscopy, electrochemical cycling, mechanical testing",
        "step_kinds": "(composition/structure hypothesis) → (DFT/MD prediction) → (synthesis route) → (characterization) → (performance benchmarking)",
        "metric_examples": "energy density, capacity retention, hardness, conductivity, bandgap, fatigue cycles",
    },
    "medicine": {
        "tool_examples": "cohort design, biomarker discovery, drug-target screening, clinical-trial simulation, survival analysis, deep-learning diagnostic models, pathway analysis",
        "step_kinds": "(clinical hypothesis) → (data collection / cohort) → (analytical model) → (validation cohort) → (clinical interpretation)",
        "metric_examples": "AUC, sensitivity/specificity, hazard ratio, IC50, p-value, fold-change",
    },
    "physics": {
        "tool_examples": "Monte Carlo simulation, lattice gauge theory, detector readout, optical-cavity measurement, quantum-state tomography, interferometry, finite-element solver",
        "step_kinds": "(theory hypothesis) → (numerical simulation) → (experimental measurement) → (data fit) → (theory revision)",
        "metric_examples": "signal/noise, coherence time, fidelity, cross-section, decay rate, resolution",
    },
    "earth_science": {
        "tool_examples": "GCM (CESM/ICON), reanalysis datasets (ERA5), satellite remote sensing, in-situ sensor networks, data assimilation, statistical downscaling",
        "step_kinds": "(climate/geo hypothesis) → (model simulation or data extraction) → (statistical analysis) → (validation against observations) → (interpretation)",
        "metric_examples": "RMSE, bias, correlation, return period, trend slope, anomaly magnitude",
    },
    "cross_domain": {
        "tool_examples": "ML models for science (AlphaFold-type), foundation models for science, simulator-in-the-loop optimization",
        "step_kinds": "(scientific target) → (ML/AI tool design) → (in silico evaluation) → (wet validation) → (iterative refinement)",
        "metric_examples": "task-specific accuracy + scientific KPIs",
    },
}


SYSTEM_PROMPT = """You are an expert scientific data engineer extracting structured \
"research closed-loop" records from peer-reviewed papers for the Sci-Evo dataset.

You will be given the full-text Markdown of one paper. Your job is to produce ONE \
JSON object matching the Sci-Evo schema below. The schema captures the research \
trajectory inside this single paper: from the problem the authors framed, through \
the steps they actually took (computational or experimental), to how they verified \
success and what failure modes they observed.

OUTPUT FORMAT — return ONLY a JSON object (no commentary, no markdown fences) \
with EXACTLY these top-level keys:

{
  "01_initial_request": {
    "target_name": "<the concrete thing the authors set out to make / answer>",
    "input_data": "<what data, materials, prior knowledge, or scaffolds they started from — be specific, include numbers>",
    "user_intent": "<why they pursued this — limitation of prior art they wanted to address>",
    "quantifiable_goal": "<numeric / measurable target stated or implied — include units and thresholds>"
  },
  "02_agent_trajectory": [
    {
      "step_index": 1,
      "thought": "[Background] <what is already known/done at this point> [Gap] <what is still missing> [Decision] <what they chose to do next and why>",
      "action": "<one of: dry_experiment | wet_experiment | analysis | literature_check | design | reflection>",
      "tool": {"name": "<concrete method/tool name — algorithm, instrument, model, assay>", "version": "<if stated, else empty string>"},
      "parameters": {"<param_name>": "<value with units when applicable>"},
      "observation": "<what the step actually produced — quantitative when possible, include negative results>",
      "valid": true,
      "references": []
    }
    /* more steps — REQUIRED at least 4 steps total; aim for 5-10 capturing the real workflow */
  ],
  "03_success_verification": {
    "validation_technique": "<how the final claim was tested — specific assays/benchmarks>",
    "metrics": {
      "<metric_name>": {"value": "<numeric>", "unit": "<unit>", "interpretation": "<what this number means in context>"}
    },
    "final_verdict": "<one-paragraph summary of whether the original quantifiable_goal was met, partially met, or missed>"
  },
  "04_failure_modes": [
    {
      "step_index_ref": <int matching a step that failed or had to be revised>,
      "what_failed": "<concise description>",
      "diagnosis": "<why it failed, per the paper>",
      "correction": "<what the authors did to recover or what they noted as future work>"
    }
    /* if no failures are reported, return an empty list [] */
  ]
}

CRITICAL RULES:
1. Do NOT invent facts. Every step must reflect work actually described in the paper.
   If the paper does not report failures, return failure_modes: [].
2. Use the paper's actual numbers and tool names. Avoid generic phrases like
   "experiment was conducted" — name the algorithm, the dataset, the assay, the metric.
3. The trajectory must show INTERMEDIATE REASONING — each thought block must have
   explicit [Background] / [Gap] / [Decision] markers.
4. For ML/CS papers, an "action: wet_experiment" is rare — most steps are
   "design" or "dry_experiment" or "analysis". For wet-lab papers, mix dry/wet.
5. Output must be valid JSON. No trailing commas. No comments.
6. Include AT LEAST 4 steps. Cap at 12 steps to stay focused on key decisions.
"""


def build_extraction_prompt(paper_md: str, title: str, domain: str, max_chars: int = 60000) -> list[dict]:
    g = DOMAIN_GUIDANCE.get(domain, DOMAIN_GUIDANCE["cs"])
    # Truncate paper to fit context: prefer beginning (abstract+intro+method) and end (results+discussion)
    if len(paper_md) > max_chars:
        head = paper_md[: int(max_chars * 0.6)]
        tail = paper_md[-int(max_chars * 0.35):]
        paper_md = head + "\n\n[...mid-section truncated...]\n\n" + tail

    user = f"""# Paper Title
{title}

# Domain
{domain}

# Domain Guidance
- Typical tools to look for: {g['tool_examples']}
- Typical step pattern: {g['step_kinds']}
- Typical metrics: {g['metric_examples']}

# Paper Full Text (Markdown, possibly truncated)

{paper_md}

# Task
Extract the Sci-Evo closed-loop record for this paper, following the system instructions exactly. Output ONLY the JSON object.
"""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": user},
    ]


TRANSITION_SYSTEM = """You are extracting the "decision narrative" between two scientific papers \
in the same lineage for the SciEvo-Lineage dataset.

Given paper A (predecessor) and paper B (successor in the same line of research), \
write a structured transition record explaining how B's authors responded to A's \
limitations and what new mechanism they introduced.

Output ONE JSON object with EXACTLY these keys (no markdown, no commentary):

{
  "gap_in_A": "<the specific limitation, failure mode, or open problem in A that B addresses — quote or paraphrase A's discussion>",
  "hypothesis_for_B": "<B's authors' hypothesis: 'If we change X, then Y should follow'>",
  "decision_rationale": "<why this approach over alternatives — what made the design choice non-obvious>",
  "experimental_validation_in_B": "<how B tested its hypothesis and what the result was, with numbers where possible>",
  "is_failure_recovery": <true if B exists primarily to address A's failure, false if B is an orthogonal extension>,
  "transferred_methods": ["<methods inherited from A>"],
  "newly_introduced_mechanisms": ["<things genuinely new in B>"]
}

Use only information present in the two papers' content provided. Do NOT invent.
"""


def build_transition_prompt(paper_a_md: str, paper_b_md: str, title_a: str, title_b: str,
                            max_chars_each: int = 22000) -> list[dict]:
    def trim(t):
        if len(t) <= max_chars_each:
            return t
        head = t[: int(max_chars_each * 0.6)]
        tail = t[-int(max_chars_each * 0.35):]
        return head + "\n\n[...mid-section truncated...]\n\n" + tail
    a = trim(paper_a_md or "")
    b = trim(paper_b_md or "")
    user = f"""# Paper A (predecessor)
Title: {title_a}

{a}

---

# Paper B (successor)
Title: {title_b}

{b}

# Task
Produce the transition record JSON per system instructions.
"""
    return [
        {"role": "system", "content": TRANSITION_SYSTEM},
        {"role": "user", "content": user},
    ]


CHAIN_NARRATIVE_SYSTEM = """You are summarizing a multi-paper lineage as a high-level Sci-Evo \
field-evolution trajectory for the SciEvo-Lineage dataset.

Given an ordered list of papers (with titles, years, and short abstracts) that \
constitute one lineage, produce the chain-level closed-loop record.

Output ONE JSON object (no markdown, no commentary):

{
  "chain_initial_request": {
    "open_problem": "<the original field-level problem this lineage formed around>",
    "field_context": "<what was known/possible when the lineage began>",
    "quantifiable_target": "<the measurable target the field has been chasing>"
  },
  "chain_trajectory": [
    {
      "milestone_index": 1,
      "paper_id": "<the paper_id you were given>",
      "contribution_role": "<one of: scaffold | catalyst | refinement | speciation | hybrid>",
      "rationale": "<what this paper contributed and why the next one mattered>",
      "remaining_gap": "<what was still missing after this paper>"
    }
  ],
  "chain_verdict": {
    "state_of_field": "<one-paragraph summary as of the latest paper>",
    "remaining_open_problems": ["<problems still unsolved>"]
  }
}
"""


def build_chain_narrative_prompt(chain_summary: list[dict]) -> list[dict]:
    """chain_summary: list of {paper_id, title, year, abstract}"""
    parts = []
    for i, p in enumerate(chain_summary, 1):
        parts.append(
            f"## Paper {i}\n"
            f"paper_id: {p['paper_id']}\n"
            f"title: {p.get('title','')}\n"
            f"year: {p.get('year','')}\n"
            f"abstract: {(p.get('abstract') or '')[:1500]}\n"
        )
    user = "# Lineage Papers (ordered earliest → latest)\n\n" + "\n".join(parts) + \
           "\n\n# Task\nProduce the chain-level closed-loop JSON per system instructions."
    return [
        {"role": "system", "content": CHAIN_NARRATIVE_SYSTEM},
        {"role": "user", "content": user},
    ]
