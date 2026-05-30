"""Dynamics consistency audit.

For a sample of L2 transitions (with source='02_main' so they carry gene_diff
dynamics), ask GPT-5.5 to independently classify dynamics based ONLY on the
narrative (titles + abstracts + transition_record), without seeing gene_fates.

Compare GPT-5.5's label to the gene_diff label. Report agreement / disagreement
matrix per dynamics class. This validates whether the gene_diff decision tree
agrees with high-level mechanism reasoning.

Usage:
    python audit_dynamics_consistency.py --n 100 --workers 6
Output:
    _logs/dynamics_audit.json
    _logs/dynamics_audit.md
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    TRANSITIONS, LOGS, log, chat55, parse_json_block, parallel_map,
)


SYSTEM = """You are an expert in evolutionary biology applied to scientific lineage \
reasoning. Given a transition narrative between two scientific papers, classify the \
evolutionary dynamics into ONE of these five mutually-exclusive categories:

1. Mutation — Mechanism inherited with local modification; same problem niche.
   Example: BERT -> RoBERTa (same MLM mechanism, refined training)
2. Adaptive Radiation — Core mechanism inherited but applied to a NEW problem domain.
   Example: Transformer (NLP) -> ViT (vision)
3. Speciation — Same problem niche, but mechanism is COMPLETELY REPLACED by a novel approach.
   Example: CNN detection -> DETR (object detection, entirely new paradigm)
4. Hybridization — Ideas from >=2 distinct lineages fused into one work.
   Example: NeRF + Diffusion -> DreamFusion
5. Niche Competition — Same niche, INDEPENDENT mechanisms, no genuine inheritance.

Output ONE JSON object (no markdown, no commentary):

{
  "predicted_dynamics": "<one of: Mutation | Adaptive Radiation | Speciation | Hybridization | Niche Competition>",
  "rationale": "<one-paragraph justification based purely on the narrative>",
  "confidence": <float 0-1>
}

Rules:
- Use only the provided narrative. Do not consult outside knowledge.
- Pick the MOST RESTRICTIVE category that fits (Hybridization > Speciation > Adaptive Radiation > Niche Competition > Mutation in restrictiveness order).
"""


def build_prompt(rec: dict) -> list[dict]:
    tr = rec.get("transition_record", {})
    user = f"""# Paper A
Title: {rec.get('source_title','')}

# Paper B
Title: {rec.get('target_title','')}

# Transition Narrative
gap_in_A: {tr.get('gap_in_A','')}

hypothesis_for_B: {tr.get('hypothesis_for_B','')}

decision_rationale: {tr.get('decision_rationale','')}

experimental_validation_in_B: {tr.get('experimental_validation_in_B','')}

transferred_methods: {tr.get('transferred_methods', [])}

newly_introduced_mechanisms: {tr.get('newly_introduced_mechanisms', [])}

is_failure_recovery: {tr.get('is_failure_recovery')}

# Task
Classify the evolutionary dynamics per system instructions. Output JSON only.
"""
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": user},
    ]


def process_one(rec):
    msgs = build_prompt(rec)
    raw = chat55(msgs, max_tokens=1500)
    obj = parse_json_block(raw)
    return {
        "edge_id": rec.get("edge_id"),
        "ground_dynamics": rec.get("dynamics"),
        "predicted_dynamics": obj.get("predicted_dynamics"),
        "confidence": obj.get("confidence", 0),
        "rationale": obj.get("rationale", ""),
    }


def sample_with_gene_diffs(n_per_class=20):
    """Pick balanced sample across dynamics classes (only 02_main records)."""
    by_dyn = defaultdict(list)
    for p in TRANSITIONS.glob("*.json"):
        try: d = json.load(open(p))
        except: continue
        src = (d.get("construction") or {}).get("source", "02_main")
        if src != "02_main":
            continue
        dyn = d.get("dynamics")
        if not dyn:
            continue
        by_dyn[dyn].append(d)
    sample = []
    for dyn, items in by_dyn.items():
        random.shuffle(items)
        sample.extend(items[:n_per_class])
    return sample


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n-per-class", type=int, default=20)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    random.seed(13)

    sample = sample_with_gene_diffs(n_per_class=args.n_per_class)
    log("audit sample", n=len(sample))

    results = parallel_map(process_one, sample, max_workers=args.workers,
                           desc="dyn_audit", logfile=LOGS / "dynamics_audit_errors.jsonl")
    raw_out = [r for _, r, e in results if e is None and r is not None]
    log("got predictions", n=len(raw_out))

    # Build confusion matrix
    cm = defaultdict(lambda: Counter())
    agree = 0
    for r in raw_out:
        g = r["ground_dynamics"]
        p = r["predicted_dynamics"] or "?"
        cm[g][p] += 1
        if g == p:
            agree += 1
    total = len(raw_out)
    overall = (agree / total * 100) if total else 0

    summary = {
        "total_audited": total,
        "overall_agreement": round(overall, 2),
        "per_class_agreement": {},
        "confusion_matrix": {g: dict(cnt) for g, cnt in cm.items()},
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    for g, cnt in cm.items():
        total_g = sum(cnt.values())
        agree_g = cnt.get(g, 0)
        summary["per_class_agreement"][g] = round(agree_g / total_g * 100, 2) if total_g else 0

    (LOGS / "dynamics_audit.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
    (LOGS / "dynamics_audit_raw.jsonl").write_text("\n".join(json.dumps(r) for r in raw_out))

    # Pretty markdown
    lines = ["# Dynamics Consistency Audit\n",
             f"- audited: {total}",
             f"- overall agreement: **{overall:.1f}%**",
             "",
             "## Confusion matrix (rows = gene_diff label, cols = narrative-only label)",
             ""]
    classes = ["Mutation", "Adaptive Radiation", "Speciation", "Hybridization", "Niche Competition"]
    header = "| gd \\ narr | " + " | ".join(classes) + " | other |"
    sep = "|---|" + "---|" * (len(classes) + 1)
    lines.append(header)
    lines.append(sep)
    for g in classes:
        row_cnt = cm.get(g, Counter())
        cells = []
        for c in classes:
            cells.append(str(row_cnt.get(c, 0)))
        other = sum(v for k, v in row_cnt.items() if k not in classes)
        cells.append(str(other))
        lines.append(f"| **{g}** | " + " | ".join(cells) + " |")
    lines.append("")
    lines.append("## Per-class agreement")
    for k, v in summary["per_class_agreement"].items():
        lines.append(f"- {k}: {v}%")
    (LOGS / "dynamics_audit.md").write_text("\n".join(lines))
    log("done", overall_agree=overall, out=str(LOGS / "dynamics_audit.md"))


if __name__ == "__main__":
    main()
