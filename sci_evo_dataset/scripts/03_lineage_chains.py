"""Layer-3 lineage trajectories.

Two responsibilities:

1) Wrap each IdeaEvolving golden_trace into a LineageTrajectory with chain-level
   closed-loop narrative (chain_initial_request / chain_trajectory / chain_verdict).
2) Optionally: build NEW lineages from the paper_pool for under-served domains
   using a simple citation+title-similarity grouping. (Defer to next iteration —
   reuse trace_graph_agent if time permits.)

Output: lineages/{trace_id_safe}.json
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    LINEAGES, POOL, LOGS, IDEA_TRACES, IDEA_PAPER_DB, IDEA_ROOT,
    log, write_json, chat55, parse_json_block, parallel_map,
    jsonl_iter, slugify,
)
from extract_prompts import build_chain_narrative_prompt

# Extra trace pools beyond IDEA_TRACES (golden_traces_main.json)
EXTRA_TRACE_FILES = [
    IDEA_ROOT / "data/traces/golden_traces_science.json",       # 500 science traces (life_science etc)
    IDEA_ROOT / "data/traces/supplementary_noncs_traces.json",  # 115 non-CS traces
    IDEA_ROOT / "data/traces/golden_traces_cs_final.json",      # 1033 alt CS traces
    IDEA_ROOT / "data/traces/golden_traces_refined.json",       # 200 refined
    IDEA_ROOT / "data/traces/golden_traces_200_enriched.json",  # 500 enriched
]


def _safe_id(s):
    return s.replace(":", "__").replace("/", "_")[:200]


def load_pool_lookup_titles():
    """Map title-lower → pool record (for cross-linking trace papers to pool)."""
    out = {}
    for r in jsonl_iter(POOL / "paper_pool.jsonl"):
        t = (r.get("title") or "").lower().strip()
        if t:
            out.setdefault(t, r)
    return out


def process_one(args_tuple):
    trace_key, trace_obj, pool_by_title = args_tuple
    domain = trace_obj.get("domain") or "cs"
    chain_name = trace_obj.get("chain_name") or f"chain_{trace_key}"
    trace_id = f"trace:{domain}:{slugify(chain_name)}:v1"
    out_path = LINEAGES / f"{_safe_id(trace_id)}.json"
    if out_path.exists():
        return {"status": "skip", "trace_id": trace_id}

    papers = trace_obj.get("papers", [])
    if len(papers) < 3:
        raise ValueError(f"chain too short: {len(papers)}")

    # Build chain summary for prompt
    chain_summary = []
    paper_ids_resolved = []
    for p in papers:
        t = (p.get("title") or "").lower().strip()
        pool_rec = pool_by_title.get(t)
        pid = (pool_rec or {}).get("paper_id") or f"paper:{slugify(p.get('title',''))}:{p.get('year',0)}"
        paper_ids_resolved.append(pid)
        chain_summary.append({
            "paper_id": pid,
            "title": p.get("title", ""),
            "year": p.get("year"),
            "abstract": (pool_rec or {}).get("abstract", "") or p.get("evolution_focus", ""),
        })

    msgs = build_chain_narrative_prompt(chain_summary)
    raw = chat55(msgs, max_tokens=4000)
    obj = parse_json_block(raw)
    for k in ("chain_initial_request", "chain_trajectory", "chain_verdict"):
        if k not in obj:
            raise ValueError(f"missing {k}")

    lineage = {
        "trace_id": trace_id,
        "domain": domain,
        "subfield": trace_obj.get("subfield") or "",
        "chain_name": chain_name,
        "papers": paper_ids_resolved,
        "edges": [f"edge:{paper_ids_resolved[i]}:{paper_ids_resolved[i+1]}"
                  for i in range(len(paper_ids_resolved)-1)],
        **obj,
        "provenance": "ideaevolving_v1_seed",
        "construction": {
            "extractor_model": "gpt-5.5",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    write_json(out_path, lineage)
    return {"status": "ok", "trace_id": trace_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--min-chain-len", type=int, default=4)
    args = ap.parse_args()

    log("loading golden_traces + pool")
    items_iter = []
    seen_keys = set()
    # Main file first (highest priority)
    raw = json.loads(IDEA_TRACES.read_text())
    src_iter = raw.items() if isinstance(raw, dict) else enumerate(raw)
    for k, v in src_iter:
        kk = f"main_{k}"
        if kk in seen_keys:
            continue
        seen_keys.add(kk)
        items_iter.append((kk, v))
    log("main traces", n=len(items_iter))
    # Extra trace pools (science, supplementary_noncs, cs_final, refined, enriched)
    for tp in EXTRA_TRACE_FILES:
        if not tp.exists():
            continue
        try:
            xraw = json.loads(tp.read_text())
        except Exception as e:
            log("skip extra trace file", file=tp.name, err=str(e)[:100])
            continue
        src_iter = xraw.items() if isinstance(xraw, dict) else enumerate(xraw)
        added = 0
        for k, v in src_iter:
            kk = f"{tp.stem}_{k}"
            if kk in seen_keys:
                continue
            # Dedupe by chain_name + first paper title if possible
            cname = (v.get("chain_name") or "") if isinstance(v, dict) else ""
            firstp = ""
            if isinstance(v, dict):
                papers = v.get("papers") or []
                if papers and isinstance(papers[0], dict):
                    firstp = papers[0].get("title", "")
            dedup_key = (cname.lower().strip(), firstp.lower().strip())
            if dedup_key in seen_keys:
                continue
            seen_keys.add(kk)
            seen_keys.add(dedup_key)
            items_iter.append((kk, v))
            added += 1
        log(f"added from {tp.name}", n=added)
    log("traces loaded TOTAL", n=len(items_iter))

    pool_by_title = load_pool_lookup_titles()
    log("pool title lookup", n=len(pool_by_title))

    filtered = []
    for k, v in items_iter:
        if not isinstance(v, dict):
            continue
        if len(v.get("papers", [])) < args.min_chain_len:
            continue
        filtered.append((str(k), v, pool_by_title))
    log("filtered traces", n=len(filtered))

    import random
    random.shuffle(filtered)
    work = filtered[: args.max]
    log("layer3 start", n=len(work), workers=args.workers)
    results = parallel_map(process_one, work, max_workers=args.workers,
                           desc="L3", logfile=LOGS / "layer3_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip")
    fail = sum(1 for _, r, e in results if e is not None)
    log("layer3 done", ok=ok, skip=skip, fail=fail)


if __name__ == "__main__":
    main()
