"""Layer-1 closed-loop extractor.

For each paper in _pool/paper_pool.jsonl with has_full_md=true:
- Load full.md
- Call GPT-5.5 to extract Sci-Evo schema closed-loop record
- Validate, then write paper_atoms/{paper_id}.json

Checkpointable: skips papers already in paper_atoms/ and records failures.

Usage:
    python 01_extract_layer1.py --max 500 --workers 8
    python 01_extract_layer1.py --domain biology --max 200
    python 01_extract_layer1.py --tool mineru_pipeline,mineru_cloud --max 1000
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    POOL, PAPER_ATOMS, LOGS, CKPT, log, write_json, jsonl_iter,
    chat55, parse_json_block, validate_closed_loop, parallel_map,
)
from extract_prompts import build_extraction_prompt


def load_pool_filtered(domain=None, tools=None, min_chars=2000, max_chars_md=None):
    pool = []
    for rec in jsonl_iter(POOL / "paper_pool.jsonl"):
        if not rec.get("has_full_md"):
            continue
        if domain and rec.get("domain") != domain:
            continue
        if tools and rec.get("parse_tool") not in tools:
            continue
        pool.append(rec)
    return pool


def extract_one(rec: dict) -> dict:
    """Returns the saved paper_atom dict, or raises."""
    paper_id = rec["paper_id"]
    out_path = PAPER_ATOMS / rec["domain"] / f"{paper_id.replace(':','__')}.json"
    if out_path.exists():
        return {"status": "skip_exists", "paper_id": paper_id}

    md_path = Path(rec["full_md"])
    if not md_path.exists():
        raise FileNotFoundError(md_path)
    md = md_path.read_text(errors="ignore")
    if len(md) < 2000:
        raise ValueError(f"full_md too short: {len(md)}")

    title = rec.get("title") or "Untitled"
    domain = rec.get("domain") or "cs"
    messages = build_extraction_prompt(md, title, domain)
    raw = chat55(messages, max_tokens=8000)
    try:
        obj = parse_json_block(raw)
    except Exception as e:
        raise ValueError(f"json parse failed: {e}; head: {raw[:300]}")

    # Wrap into PaperAtom
    atom = {
        "paper_id": paper_id,
        "s2_id": rec.get("s2_id"),
        "external_ids": {
            "arxiv": rec.get("arxiv_id"),
            "doi": rec.get("doi"),
        },
        "title": title,
        "year": rec.get("year"),
        "venue": rec.get("venue"),
        "authors": rec.get("authors") or [],
        "fields_of_study": rec.get("fields_of_study") or [],
        "domain": domain,
        "subfield": "",
        "abstract": rec.get("abstract") or "",
        "genome_card_id": rec.get("idea_evolving_genome_card_id"),
        "closed_loop_record": obj,
        "source": {
            "pdf_path": None,
            "parse_tool": rec.get("parse_tool"),
            "parse_mapping": "yqh_workspace",
            "full_md_path": rec.get("full_md"),
        },
        "construction": {
            "extractor_model": "gpt-5.5",
            "extractor_version": "2024-12-01-preview",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    errors = validate_closed_loop(atom)
    if errors:
        # Save invalid output anyway under _logs for inspection but raise to caller
        bad = LOGS / "layer1_invalid" / f"{paper_id.replace(':','__')}.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text(json.dumps({"errors": errors, "atom": atom}, ensure_ascii=False, indent=2))
        raise ValueError(f"schema errors: {errors}")
    write_json(out_path, atom)
    return {"status": "ok", "paper_id": paper_id, "path": str(out_path)}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--workers", type=int, default=8)
    ap.add_argument("--domain", type=str, default=None)
    ap.add_argument("--tool", type=str, default=None, help="comma-separated parse_tool filter")
    ap.add_argument("--shuffle", action="store_true")
    ap.add_argument("--min-citations", type=int, default=0)
    args = ap.parse_args()

    tools = set(args.tool.split(",")) if args.tool else None
    pool = load_pool_filtered(domain=args.domain, tools=tools)
    if args.min_citations:
        pool = [r for r in pool if (r.get("citation_count") or 0) >= args.min_citations]
    if args.shuffle:
        import random
        random.shuffle(pool)  # fresh seed each run
    pool = pool[: args.max]

    log("layer1 start",
        n=len(pool), workers=args.workers, domain=args.domain or "*",
        tool=args.tool or "*")

    logfile = LOGS / "layer1_errors.jsonl"
    results = parallel_map(
        extract_one, pool, max_workers=args.workers,
        desc=f"L1[{args.domain or '*'}/{args.tool or '*'}]",
        logfile=logfile,
    )
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip_exists")
    fail = sum(1 for _, r, e in results if e is not None)
    log("layer1 done", ok=ok, skip=skip, fail=fail, total=len(results), errors_log=str(logfile))


if __name__ == "__main__":
    main()
