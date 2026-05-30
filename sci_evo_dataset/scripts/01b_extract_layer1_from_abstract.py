"""Layer-1 abstract-only fallback extractor.

For papers in the pool without has_full_md=true, generates a Sci-Evo closed-loop
record from title + abstract alone. Output quality is lower than full-text but
still useful for under-served domains (biology, chemistry, materials, etc.) where
PDF parsing hasn't happened yet.

These atoms are marked with construction.input_quality = "abstract_only" so
downstream consumers (audit, exemplar picker) can downrank them.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    POOL, PAPER_ATOMS, LOGS, log, write_json, jsonl_iter,
    chat55, parse_json_block, validate_closed_loop, parallel_map,
)
from extract_prompts import build_extraction_prompt, DOMAIN_GUIDANCE


def load_abstract_pool(domain=None, min_abstract_chars=400, min_citations=0):
    pool = []
    for rec in jsonl_iter(POOL / "paper_pool.jsonl"):
        if rec.get("has_full_md"):
            continue
        if domain and rec.get("domain") != domain:
            continue
        abs_ = rec.get("abstract") or ""
        if len(abs_) < min_abstract_chars:
            continue
        if (rec.get("citation_count") or 0) < min_citations:
            continue
        pool.append(rec)
    return pool


def extract_one(rec: dict) -> dict:
    paper_id = rec["paper_id"]
    out_path = PAPER_ATOMS / rec["domain"] / f"{paper_id.replace(':','__')}.json"
    if out_path.exists():
        return {"status": "skip_exists", "paper_id": paper_id}

    title = rec.get("title") or "Untitled"
    domain = rec.get("domain") or "cs"
    # Synthesize a "mini full text" from title + abstract
    md = f"# {title}\n\n## Abstract\n\n{rec.get('abstract','')}\n"
    messages = build_extraction_prompt(md, title, domain, max_chars=60000)
    raw = chat55(messages, max_tokens=6000)
    obj = parse_json_block(raw)

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
            "parse_tool": "none",
            "parse_mapping": "abstract_only",
            "full_md_path": None,
        },
        "construction": {
            "extractor_model": "gpt-5.5",
            "extractor_version": "2024-12-01-preview",
            "input_quality": "abstract_only",
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
        },
    }
    errors = validate_closed_loop(atom)
    if errors:
        bad = LOGS / "layer1b_invalid" / f"{paper_id.replace(':','__')}.json"
        bad.parent.mkdir(parents=True, exist_ok=True)
        bad.write_text(json.dumps({"errors": errors, "atom": atom}, ensure_ascii=False, indent=2))
        raise ValueError(f"schema errors: {errors}")
    write_json(out_path, atom)
    return {"status": "ok", "paper_id": paper_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=80)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--domain", type=str, default=None)
    ap.add_argument("--min-citations", type=int, default=0)
    ap.add_argument("--shuffle", action="store_true")
    args = ap.parse_args()

    pool = load_abstract_pool(domain=args.domain, min_citations=args.min_citations)
    if args.shuffle:
        import random
        random.shuffle(pool)  # fresh seed each run
    pool = pool[: args.max]

    log("layer1b start", n=len(pool), workers=args.workers,
        domain=args.domain or "*")
    results = parallel_map(extract_one, pool, max_workers=args.workers,
                           desc=f"L1b[{args.domain or '*'}]",
                           logfile=LOGS / "layer1b_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip_exists")
    fail = sum(1 for _, r, e in results if e is not None)
    log("layer1b done", ok=ok, skip=skip, fail=fail)


if __name__ == "__main__":
    main()
