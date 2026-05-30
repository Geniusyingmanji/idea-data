"""Stage 2b: Generate L2 transitions directly from s2_seed lineages.

For each lineage in lineages/ with provenance=s2_seed_v1 AND chain_trajectory,
iterate consecutive (paper_i, paper_{i+1}) pairs and generate transition_record
+ a minimal dynamics classification via GPT-5.5 (since there's no gene_diff).

Output: transitions/{safe_edge_id}.json — same envelope as the IdeaEvolving-derived ones,
but with dynamics="Unspecified" until L3-style genome_diff is run.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    TRANSITIONS, LINEAGES, LOGS, log, write_json, chat55, parse_json_block,
    parallel_map,
)
from extract_prompts import build_transition_prompt


def _safe(s):
    return s.replace(":", "__").replace("/", "_")[:200]


def collect_pairs(max_lineages=None):
    """Yield (lineage, paperA_meta, paperB_meta) for each consecutive pair in seed lineages."""
    pairs = []
    paths = sorted(LINEAGES.glob("*.json"))
    if max_lineages:
        paths = paths[:max_lineages]
    for p in paths:
        try:
            obj = json.loads(p.read_text())
        except Exception:
            continue
        if obj.get("provenance") != "s2_seed_v1":
            continue
        if not obj.get("chain_trajectory"):
            continue
        meta_list = obj.get("papers_meta", [])
        for i in range(len(meta_list) - 1):
            a, b = meta_list[i], meta_list[i+1]
            if not a.get("paper_id") or not b.get("paper_id"):
                continue
            # Skip pairs where either abstract is missing/too short — they'll fail anyway
            if len(a.get("abstract") or "") < 200 or len(b.get("abstract") or "") < 200:
                continue
            edge_id = f"edge:{a['paper_id']}:{b['paper_id']}"
            pairs.append((obj, a, b, edge_id))
    return pairs


def process_one(args_tuple):
    lineage, paper_a, paper_b, edge_id = args_tuple
    out_path = TRANSITIONS / f"{_safe(edge_id)}.json"
    if out_path.exists():
        return {"status": "skip", "edge_id": edge_id}

    title_a = paper_a.get("title", "")
    title_b = paper_b.get("title", "")
    text_a = paper_a.get("abstract", "")
    text_b = paper_b.get("abstract", "")
    if not text_a or not text_b or len(text_a) < 100 or len(text_b) < 100:
        raise ValueError(f"missing abstract for {paper_a['paper_id']}/{paper_b['paper_id']}")

    msgs = build_transition_prompt(text_a, text_b, title_a, title_b, max_chars_each=4000)
    raw = chat55(msgs, max_tokens=2000)
    obj = parse_json_block(raw)
    for k in ("gap_in_A", "hypothesis_for_B", "decision_rationale",
              "experimental_validation_in_B", "is_failure_recovery"):
        if k not in obj:
            raise ValueError(f"missing key {k}")

    merged = {
        "edge_id": edge_id,
        "source_paper_id": paper_a["paper_id"],
        "target_paper_id": paper_b["paper_id"],
        "source_title": title_a,
        "target_title": title_b,
        "dynamics": "Unspecified",  # no gene_diff available for s2_seed; could fill via genome_differ later
        "primary_driver": None,
        "lineage_id": lineage.get("trace_id"),
        "transition_record": obj,
        "construction": {
            "extractor_model": "gpt-5.5",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "02b_transition_from_lineage",
        },
    }
    write_json(out_path, merged)
    return {"status": "ok", "edge_id": edge_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-lineages", type=int, default=200)
    ap.add_argument("--max-pairs", type=int, default=400)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    pairs = collect_pairs(args.max_lineages)
    import random
    random.shuffle(pairs)
    if args.max_pairs:
        pairs = pairs[: args.max_pairs]
    log("L2b start", n=len(pairs), workers=args.workers)
    results = parallel_map(process_one, pairs, max_workers=args.workers,
                           desc="L2b", logfile=LOGS / "layer2b_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip")
    fail = sum(1 for _, r, e in results if e is not None)
    log("L2b done", ok=ok, skip=skip, fail=fail)


if __name__ == "__main__":
    main()
