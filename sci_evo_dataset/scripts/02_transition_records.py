"""Layer-2 transition records.

Iterates over IdeaEvolving gene_diffs.json (existing pairwise diffs) and adds
"transition_record" narrative via GPT-5.5 using both papers' available context
(prefer full.md, fall back to abstract).

Outputs transitions/{edge_id_safe}.json, joined with the original gene_diff.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    TRANSITIONS, POOL, LOGS, IDEA_GENE_DIFFS, IDEA_PAPER_DB, IDEA_GENE_CARDS,
    log, write_json, jsonl_iter, chat55, parse_json_block, parallel_map,
)
from extract_prompts import build_transition_prompt


def _safe_edge(edge_id: str) -> str:
    return edge_id.replace(":", "__").replace("/", "_")[:200]


def load_pool_lookup():
    by_pid = {}
    by_s2 = {}
    for rec in jsonl_iter(POOL / "paper_pool.jsonl"):
        by_pid[rec["paper_id"]] = rec
        if rec.get("s2_id"):
            by_s2[rec["s2_id"]] = rec
    return by_pid, by_s2


def load_idea_db_lookup():
    db = json.loads(IDEA_PAPER_DB.read_text())
    by_card = {}
    for pid, rec in db.items():
        if rec.get("genome_card_id"):
            by_card[rec["genome_card_id"]] = rec
    # Also load gene_cards as fallback (list of dicts keyed by paper_id field)
    cards = json.loads(IDEA_GENE_CARDS.read_text())
    if isinstance(cards, list):
        by_card_self = {c.get("paper_id"): c for c in cards if c.get("paper_id")}
    else:
        by_card_self = cards
    return db, by_card, by_card_self


def synthesize_text_from_card(card_dict: dict) -> str:
    """When neither full.md nor paper_db abstract is available, build a synthetic
    text snippet from the gene card's legacy_genome + genes."""
    legacy = card_dict.get("legacy_genome", {}) or {}
    parts = []
    for k in ("niche_genome", "mechanism_genome", "limitation_genome", "observation_genome"):
        v = legacy.get(k)
        if v:
            parts.append(f"{k}: {v}")
    for g in (card_dict.get("genes") or [])[:6]:
        parts.append(f"gene[{g.get('gene_type','?')}/{g.get('gene_role','?')}]: {g.get('gene_text','')[:300]}")
    return "\n".join(parts)


def get_paper_text(card_id: str, diff_obj_title: str, by_pid, by_s2, by_card, by_card_self,
                   max_chars=22000) -> tuple[str, str]:
    """Return (title, text). Cascade: full.md > paper_db abstract > synthetic from gene card."""
    title = diff_obj_title or ""
    text = ""
    ie_rec = by_card.get(card_id, {})
    s2_id = ie_rec.get("s2_id")
    if not title:
        title = ie_rec.get("title", "")
    abstract = ie_rec.get("abstract", "")
    pool_rec = by_s2.get(s2_id) if s2_id else None
    if pool_rec and pool_rec.get("has_full_md"):
        try:
            md = Path(pool_rec["full_md"]).read_text(errors="ignore")
            if len(md) > max_chars:
                head = md[: int(max_chars * 0.6)]
                tail = md[-int(max_chars * 0.35):]
                md = head + "\n\n[...truncated...]\n\n" + tail
            text = md
            title = pool_rec.get("title") or title
        except Exception:
            text = abstract
    elif abstract:
        text = abstract
    # Fallback: synthesize from gene card
    if not text or len(text) < 100:
        card = by_card_self.get(card_id)
        if card:
            text = synthesize_text_from_card(card)
            if not title:
                title = card.get("title", "")
    return title or "", text or ""


def process_one(args_tuple):
    diff_obj, by_pid, by_s2, by_card, by_card_self = args_tuple
    edge_id = diff_obj.get("edge_id") or f"edge:{diff_obj.get('source_paper_id')}:{diff_obj.get('target_paper_id')}"
    out_path = TRANSITIONS / f"{_safe_edge(edge_id)}.json"
    if out_path.exists():
        return {"status": "skip", "edge_id": edge_id}

    src = diff_obj.get("source_paper_id")
    tgt = diff_obj.get("target_paper_id")
    title_a, text_a = get_paper_text(src, diff_obj.get("source_title", ""),
                                     by_pid, by_s2, by_card, by_card_self)
    title_b, text_b = get_paper_text(tgt, diff_obj.get("target_title", ""),
                                     by_pid, by_s2, by_card, by_card_self)
    if not text_a or not text_b or len(text_a) < 100 or len(text_b) < 100:
        raise ValueError(f"missing text for {src}/{tgt}: lenA={len(text_a)} lenB={len(text_b)}")

    msgs = build_transition_prompt(text_a, text_b, title_a, title_b)
    raw = chat55(msgs, max_tokens=3500)
    obj = parse_json_block(raw)
    # validate min keys
    for k in ("gap_in_A", "hypothesis_for_B", "decision_rationale",
              "experimental_validation_in_B", "is_failure_recovery"):
        if k not in obj:
            raise ValueError(f"missing key {k} in transition record")

    merged = dict(diff_obj)
    merged["transition_record"] = obj
    merged["edge_id"] = edge_id
    merged["construction"] = {
        "extractor_model": "gpt-5.5",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    write_json(out_path, merged)
    return {"status": "ok", "edge_id": edge_id}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max", type=int, default=200)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--shuffle", action="store_true")
    args = ap.parse_args()

    log("loading gene_diffs + pool + idea_db")
    diffs = json.loads(IDEA_GENE_DIFFS.read_text())
    if isinstance(diffs, dict):
        diff_list = list(diffs.values())
    else:
        diff_list = diffs
    log("gene_diffs loaded", n=len(diff_list))

    by_pid, by_s2 = load_pool_lookup()
    _, by_card, by_card_self = load_idea_db_lookup()
    log("lookups ready", pool_by_pid=len(by_pid), pool_by_s2=len(by_s2),
        idea_by_card=len(by_card), card_self=len(by_card_self))

    if args.shuffle:
        import random
        random.shuffle(diff_list)  # fresh seed each run so batches don't keep hitting same edges
    work = diff_list[: args.max]
    items = [(d, by_pid, by_s2, by_card, by_card_self) for d in work]

    log("layer2 start", n=len(items), workers=args.workers)
    results = parallel_map(process_one, items, max_workers=args.workers,
                           desc="L2", logfile=LOGS / "layer2_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "ok")
    skip = sum(1 for _, r, e in results if e is None and (r or {}).get("status") == "skip")
    fail = sum(1 for _, r, e in results if e is not None)
    log("layer2 done", ok=ok, skip=skip, fail=fail)


if __name__ == "__main__":
    main()
