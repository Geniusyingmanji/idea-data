"""Fill missing dynamics labels on L2 transitions via narrative-only LLM judgment.

Targets transitions/*.json with dynamics in {None, "?", "Unspecified"} (mostly
from 02b/02c sources that lack gene_diff backbone). Uses the same prompt as
audit_dynamics_consistency.py but writes the label back into the record under
`narrative_dynamics` (kept separate from the structural `dynamics` field to
preserve provenance).
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import TRANSITIONS, LOGS, log, chat55, parse_json_block, parallel_map, write_json


SYSTEM = """You are an expert in evolutionary biology applied to scientific lineage \
reasoning. Given a transition narrative between two scientific papers, classify the \
evolutionary dynamics into ONE of these five mutually-exclusive categories:

1. Mutation — Mechanism inherited with local modification; same problem niche.
   Example: BERT -> RoBERTa
2. Adaptive Radiation — Core mechanism inherited but applied to a NEW problem domain.
   Example: Transformer (NLP) -> ViT (vision)
3. Speciation — Same problem niche, but mechanism is COMPLETELY REPLACED by a novel approach.
   Example: CNN detection -> DETR
4. Hybridization — Ideas from >=2 distinct lineages fused into one work.
   Example: NeRF + Diffusion -> DreamFusion
5. Niche Competition — Same niche, INDEPENDENT mechanisms, no genuine inheritance.

Output ONE JSON object (no markdown, no commentary):
{"dynamics": "<one of the 5 categories>", "confidence": <0-1>, "rationale": "<one-line>"}
"""


def build_prompt(rec):
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
Output the dynamics JSON per system instructions.
"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": user}]


def process_one(path):
    rec = json.loads(path.read_text())
    if rec.get("narrative_dynamics"):
        return {"status": "skip_already"}
    if not rec.get("transition_record"):
        return {"status": "skip_no_narrative"}
    msgs = build_prompt(rec)
    raw = chat55(msgs, max_tokens=600)
    obj = parse_json_block(raw)
    rec["narrative_dynamics"] = {
        "dynamics": obj.get("dynamics", "?"),
        "confidence": obj.get("confidence", 0),
        "rationale": obj.get("rationale", "")[:300],
        "extracted_by": "gpt-5.5",
        "extracted_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_json(path, rec)
    return {"status": "ok", "dynamics": obj.get("dynamics")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    candidates = []
    for p in TRANSITIONS.glob("*.json"):
        try:
            rec = json.loads(p.read_text())
        except Exception:
            continue
        if rec.get("narrative_dynamics"):
            continue
        dyn = rec.get("dynamics")
        if dyn in (None, "", "?", "Unspecified"):
            candidates.append(p)
    log("L2 dynamics fill candidates", n=len(candidates))

    import random
    random.shuffle(candidates)
    work = candidates[: args.max]

    results = parallel_map(process_one, work, max_workers=args.workers,
                           desc="L2-dyn", logfile=LOGS / "l2_dynamics_fill_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status", "").startswith("skip"))
    fail = sum(1 for _, r, e in results if e is not None)

    # Distribution of newly assigned dynamics
    from collections import Counter
    dist = Counter()
    for _, r, e in results:
        if e is None and (r or {}).get("status") == "ok":
            dist[r.get("dynamics", "?")] += 1
    log("L2 dynamics fill done", ok=ok, skip=skip, fail=fail, dist=dict(dist))


if __name__ == "__main__":
    main()
