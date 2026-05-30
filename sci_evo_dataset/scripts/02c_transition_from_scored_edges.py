"""Stage 2c: Generate L2 transitions from IdeaEvolving scored_edges.jsonl (12,201 edges).

Filters: keep edges with citation_role in {idea_inheritance, weak_inheritance,
limitation_pressure} OR confidence >= 0.5. Look up source/target paper abstracts
via the pool (by s2_id), then GPT-5.5 generate transition_record.

Output transitions/{safe_edge_id}.json — minimal envelope without gene_diff fields.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    TRANSITIONS, POOL, LOGS, IDEA_ROOT,
    log, write_json, chat55, parse_json_block, parallel_map,
    jsonl_iter,
)
from extract_prompts import build_transition_prompt

SCORED_EDGES = IDEA_ROOT / "data/traces/scored_edges.jsonl"

ALLOWED_ROLES = {"idea_inheritance", "weak_inheritance", "limitation_pressure",
                 "methodology"}  # methodology often signals real method transfer
MIN_CONF = 0.4


def _safe(s):
    return s.replace(":", "__").replace("/", "_")[:200]


def load_pool_by_s2():
    out = {}
    for r in jsonl_iter(POOL / "paper_pool.jsonl"):
        if r.get("s2_id"):
            out[r["s2_id"]] = r
    return out


def get_text(s2_id, by_s2, max_chars=4000):
    """Return (title, abstract-or-md). For short abstract, try full.md."""
    r = by_s2.get(s2_id)
    if not r:
        return "", ""
    title = r.get("title", "")
    abs_ = r.get("abstract") or ""
    md_path = r.get("full_md")
    if md_path and Path(md_path).exists():
        try:
            md = Path(md_path).read_text(errors="ignore")
            if len(md) > max_chars:
                head = md[: int(max_chars * 0.6)]
                tail = md[-int(max_chars * 0.35):]
                md = head + "\n\n[...truncated...]\n\n" + tail
            return title, md
        except Exception:
            return title, abs_
    return title, abs_


def process_one(args_tuple):
    edge, by_s2 = args_tuple
    src = edge["source_s2_id"]
    tgt = edge["target_s2_id"]
    edge_id = f"edge:s2:{src}:s2:{tgt}"
    out_path = TRANSITIONS / f"{_safe(edge_id)}.json"
    if out_path.exists():
        return {"status": "skip", "edge_id": edge_id}

    title_a, text_a = get_text(src, by_s2)
    title_b, text_b = get_text(tgt, by_s2)
    if not title_a:
        title_a = edge.get("source_title", "")
    if not title_b:
        title_b = edge.get("target_title", "")
    if not text_a or not text_b or len(text_a) < 100 or len(text_b) < 100:
        raise ValueError(f"missing text for {src}/{tgt}: lenA={len(text_a)} lenB={len(text_b)}")

    msgs = build_transition_prompt(text_a, text_b, title_a, title_b, max_chars_each=4000)
    raw = chat55(msgs, max_tokens=2500)
    obj = parse_json_block(raw)
    for k in ("gap_in_A", "hypothesis_for_B", "decision_rationale",
              "experimental_validation_in_B", "is_failure_recovery"):
        if k not in obj:
            raise ValueError(f"missing key {k}")

    merged = {
        "edge_id": edge_id,
        "source_paper_id": f"s2:{src}",
        "target_paper_id": f"s2:{tgt}",
        "source_s2_id": src,
        "target_s2_id": tgt,
        "source_title": title_a,
        "target_title": title_b,
        "citation_role": edge.get("citation_role"),
        "role_score": edge.get("role_score"),
        "edge_confidence": edge.get("confidence"),
        "is_influential": edge.get("is_influential"),
        "trace_id_hint": edge.get("trace_id"),
        "domain": edge.get("domain"),
        "subfield": edge.get("subfield"),
        "dynamics": None,  # no gene_diff alignment for these
        "primary_driver": None,
        "transition_record": obj,
        "construction": {
            "extractor_model": "gpt-5.5",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "source": "02c_transition_from_scored_edges",
        },
    }
    write_json(out_path, merged)
    return {"status": "ok", "edge_id": edge_id}


def collect_eligible_edges():
    """Read scored_edges, filter to inheritance-style with abstracts available."""
    edges = []
    with open(SCORED_EDGES) as f:
        for line in f:
            try:
                e = json.loads(line)
            except Exception:
                continue
            if not e.get("source_s2_id") or not e.get("target_s2_id"):
                continue
            role = (e.get("citation_role") or "").lower()
            conf = e.get("confidence", 0)
            # Include high-confidence inheritance OR high-confidence methodology citations
            if role in ALLOWED_ROLES or conf >= MIN_CONF:
                edges.append(e)
    return edges


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--workers", type=int, default=4)
    args = ap.parse_args()

    log("loading scored_edges + pool")
    by_s2 = load_pool_by_s2()
    log("pool indexed", n=len(by_s2))
    eligible = collect_eligible_edges()
    log("eligible scored edges", n=len(eligible))

    import random
    random.shuffle(eligible)
    work = eligible[: args.max]
    items = [(e, by_s2) for e in work]

    log("L2c start", n=len(items), workers=args.workers)
    results = parallel_map(process_one, items, max_workers=args.workers,
                           desc="L2c", logfile=LOGS / "layer2c_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip")
    fail = sum(1 for _, r, e in results if e is not None)
    log("L2c done", ok=ok, skip=skip, fail=fail)


if __name__ == "__main__":
    main()
