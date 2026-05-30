"""Stage 3b: Fill chain_initial_request / chain_trajectory / chain_verdict
for lineages produced by 05_seed_new_domains.py (provenance=s2_seed_v1).

Those lineages currently have papers + edges + papers_meta but lack the
chain-level closed-loop fields. This script reads each, generates the missing
narrative, and writes back in place.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import LINEAGES, LOGS, log, chat55, parse_json_block, parallel_map, write_json
from extract_prompts import build_chain_narrative_prompt


def needs_narrative(obj: dict) -> bool:
    for k in ("chain_initial_request", "chain_trajectory", "chain_verdict"):
        v = obj.get(k)
        if not v:
            return True
        if isinstance(v, dict) and not v:
            return True
        if isinstance(v, list) and not v:
            return True
    return False


def process_one(path: Path):
    obj = json.loads(path.read_text())
    if not needs_narrative(obj):
        return {"status": "skip", "trace_id": obj.get("trace_id")}

    # Build chain_summary from papers_meta
    chain_summary = []
    for pm in obj.get("papers_meta", []):
        chain_summary.append({
            "paper_id": pm.get("paper_id", "?"),
            "title": pm.get("title", ""),
            "year": pm.get("year"),
            "abstract": (pm.get("abstract") or "")[:1500],
        })
    if not chain_summary:
        # Fall back to papers list with bare titles
        chain_summary = [{"paper_id": pid, "title": pid, "year": None, "abstract": ""} for pid in obj.get("papers", [])]
    if len(chain_summary) < 3:
        raise ValueError(f"chain too short: {len(chain_summary)}")

    msgs = build_chain_narrative_prompt(chain_summary)
    raw = chat55(msgs, max_tokens=4000)
    new_fields = parse_json_block(raw)
    for k in ("chain_initial_request", "chain_trajectory", "chain_verdict"):
        if k not in new_fields:
            raise ValueError(f"missing {k}")
        obj[k] = new_fields[k]
    obj["construction"] = {
        **(obj.get("construction") or {}),
        "narrative_extractor": "gpt-5.5",
        "narrative_ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_json(path, obj)
    return {"status": "ok", "trace_id": obj.get("trace_id")}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=100)
    ap.add_argument("--workers", type=int, default=3)
    args = ap.parse_args()

    paths = sorted([p for p in LINEAGES.glob("*.json")
                    if needs_narrative(json.loads(p.read_text()))])[: args.max]
    log("L3b start", n=len(paths), workers=args.workers)
    results = parallel_map(process_one, paths, max_workers=args.workers,
                           desc="L3b", logfile=LOGS / "layer3b_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip")
    fail = sum(1 for _, r, e in results if e is not None)
    log("L3b done", ok=ok, skip=skip, fail=fail)


if __name__ == "__main__":
    main()
