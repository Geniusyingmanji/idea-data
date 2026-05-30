"""Offline domain reclassification using GPT-5.5 for ambiguous entries.

For each paper in pool with multi-label fields_of_study OR domain="cs" assigned
by heuristic (which catches everything not matching biology/chem/etc keywords),
batch-call GPT-5.5 to pick the BEST domain from a fixed taxonomy based on
title + abstract.

Output: _pool/domain_overrides.json — {paper_id: new_domain}
Downstream L1 scripts can consult this override when present.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import POOL, LOGS, log, chat55, parse_json_block, parallel_map, jsonl_iter

DOMAINS = ["cs", "biology", "chemistry", "materials", "medicine",
           "physics", "earth_science", "neuroscience", "mathematics",
           "engineering", "energy", "social_science", "cross_domain"]

OVERRIDES_PATH = POOL / "domain_overrides.json"

SYSTEM = """You are classifying scientific papers into ONE of these domains based on \
the paper's title and abstract. Pick the single best fit. If a paper genuinely spans \
two domains (e.g. AI4Bio), pick "cross_domain".

Allowed domains:
  cs                  — computer science, machine learning, NLP, vision, systems
  biology             — molecular biology, protein design, genetics, microbiology
  chemistry           — organic/inorganic chemistry, reactions, catalysis (not pure CS-with-chemistry-data)
  materials           — materials science, batteries, photovoltaics, alloys
  medicine            — clinical medicine, diagnostics, drugs, surgery (NOT methodology-only)
  physics             — physics, quantum, photonics, particle, cosmology
  earth_science       — climate, atmosphere, ocean, geology
  neuroscience        — brain, neural circuits, fMRI, cognition
  mathematics         — pure or applied math, theorems, proofs
  engineering         — control systems, robotics, aerospace, civil
  energy              — energy systems, renewables, power grid
  social_science      — economics, sociology, psychology, education
  cross_domain        — AI4Bio, AI4Chem, biophysics, etc. (genuinely interdisciplinary)

Output ONE JSON object (no markdown, no commentary):

{"domain": "<one of the above>", "confidence": <float 0-1>}
"""


def build_prompt(rec: dict) -> list[dict]:
    user = f"""# Title
{rec.get('title','')}

# Abstract
{(rec.get('abstract') or '')[:1200]}

# Currently assigned (heuristic)
{rec.get('domain','?')}

# S2 fieldsOfStudy
{rec.get('fields_of_study', [])}

# Task
Pick the best domain per system instructions. Output JSON only.
"""
    return [{"role": "system", "content": SYSTEM},
            {"role": "user", "content": user}]


def is_ambiguous(rec: dict) -> bool:
    """Heuristic: needs reclassification if (a) abstract short, (b) multi-label fields, (c) field/domain mismatch."""
    abs_ = rec.get("abstract") or ""
    if len(abs_) < 200:
        return False  # not enough to classify
    fos = rec.get("fields_of_study") or []
    if not fos:
        return False  # nothing to confirm/correct
    # Multi-label OR "cs" + non-cs field present (suggests heuristic picked cs by default)
    if len(fos) >= 2:
        return True
    return False


def process_one(rec: dict) -> dict:
    msgs = build_prompt(rec)
    raw = chat55(msgs, max_tokens=300)
    obj = parse_json_block(raw)
    return {
        "paper_id": rec["paper_id"],
        "old_domain": rec.get("domain"),
        "new_domain": obj.get("domain", "cs"),
        "confidence": obj.get("confidence", 0.5),
        "title": (rec.get("title") or "")[:120],
    }


def load_existing_overrides():
    if OVERRIDES_PATH.exists():
        try:
            return json.loads(OVERRIDES_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_overrides(d: dict):
    tmp = OVERRIDES_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=2))
    import os
    os.replace(tmp, OVERRIDES_PATH)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=2000)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--shuffle", action="store_true")
    args = ap.parse_args()

    overrides = load_existing_overrides()
    log("loaded existing overrides", n=len(overrides))

    pool = []
    for r in jsonl_iter(POOL / "paper_pool.jsonl"):
        if not is_ambiguous(r):
            continue
        if r["paper_id"] in overrides:
            continue
        pool.append(r)
    log("candidates for reclassify", n=len(pool))

    if args.shuffle:
        import random
        random.shuffle(pool)
    pool = pool[: args.max]
    log("processing batch", n=len(pool), workers=args.workers)

    results = parallel_map(process_one, pool, max_workers=args.workers,
                           desc="reclass", logfile=LOGS / "domain_reclass_errors.jsonl")

    n_changed = 0
    for _, r, e in results:
        if e or not r:
            continue
        if r["new_domain"] != r["old_domain"]:
            n_changed += 1
        overrides[r["paper_id"]] = {
            "old": r["old_domain"],
            "new": r["new_domain"],
            "confidence": r["confidence"],
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }

    save_overrides(overrides)
    log("done", processed=len(pool), changed=n_changed, total_overrides=len(overrides),
        path=str(OVERRIDES_PATH))


if __name__ == "__main__":
    main()
