"""Layer-4 agentic ReAct episodes.

For each lineage in lineages/, synthesize ReAct-style agentic episodes
demonstrating an "AI scientist" navigating the lineage using the six idea_train
tools: search, read, extract_genome, genome_diff, novelty_check, propose.

Three archetypes per lineage:
  W2_single_paper_extension: anchor on the LAST paper, propose a follow-up
  W3_multi_paper_synthesis: synthesize from 2-3 middle papers
  W6_cross_domain_bridge: only emitted when domain is cross_domain or chain spans
                          multiple subfields

Output: agentic_episodes/episodes.jsonl  (one demo per line)
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    LINEAGES, AGENTIC, LOGS, log, chat55, parse_json_block, parallel_map,
)

SYSTEM_AGENTIC = """You are simulating an AI research-scientist agent that uses tools to study a \
scientific lineage and propose a novel next step. Produce ONE complete ReAct \
trajectory as a JSON object compatible with the idea_train training format.

Allowed tools and their semantics:
- search(query): returns a list of paper titles/abstracts matching the query
- read(paper_id): returns the full abstract + key takeaway of a paper
- extract_genome(paper_id): returns the structured genome card (niche, mechanism, limitation)
- genome_diff(paper_a_id, paper_b_id): returns gene_fates + dynamics classification
- novelty_check(proposal_text): returns related-work matches and novelty score
- propose(structured_idea): commits a final structured research proposal

Output JSON (no markdown, no commentary):

{
  "demo_id": "<unique id you assign>",
  "archetype": "W2_single_paper_extension | W3_multi_paper_synthesis | W6_cross_domain_bridge",
  "lineage_id": "<the trace_id you were given>",
  "user_prompt": "<the natural-language research prompt that triggered this agent>",
  "trajectory": [
    {"role":"assistant","thought":"...","tool":"search","input":"<query>"},
    {"role":"tool","name":"search","output":"<plausible tool result, 1-3 short paper titles>"},
    {"role":"assistant","thought":"...","tool":"read","input":"<paper_id>"},
    {"role":"tool","name":"read","output":"<short abstract+takeaway>"},
    /* ... more steps ... */
    {"role":"assistant","thought":"...","tool":"propose","input":"<structured next-step idea>"}
  ],
  "ground_truth_next_paper_id": "<paper_id from the lineage that real authors would cite as the answer>"
}

Constraints:
- The 'propose' step MUST be a structured idea covering: niche, mechanism, expected_metric, \
  experimental_plan, and ablation_axes.
- The trajectory must end with a 'propose' assistant step (no tool response after it).
- Use 5-9 assistant turns. Mix tools — don't call search five times in a row.
- Tool outputs you write should be plausible (drawn from the lineage's actual papers); \
  do not invent unrelated paper titles.
"""


def build_episode_prompt(lineage: dict, archetype: str) -> list[dict]:
    chain = lineage.get("chain_trajectory") or []
    papers = lineage.get("papers", [])
    chain_name = lineage.get("chain_name", "")
    domain = lineage.get("domain", "cs")
    chain_initial = lineage.get("chain_initial_request", {})

    # Pick anchors based on archetype
    if archetype == "W2_single_paper_extension":
        anchor_idx = max(0, len(papers) - 2)  # second-to-last as anchor; last is ground truth
        anchors = [papers[anchor_idx]] if anchor_idx < len(papers) else []
        gt = papers[-1] if len(papers) >= 2 else None
        archetype_desc = "Single-paper extension: anchor on one paper, propose a follow-up addressing its limitation."
    elif archetype == "W3_multi_paper_synthesis":
        mid_start = max(0, len(papers)//2 - 1)
        anchors = papers[mid_start: mid_start + 3]
        gt = papers[mid_start + 3] if mid_start + 3 < len(papers) else papers[-1]
        archetype_desc = "Multi-paper synthesis: extract 2-3 genomes, find shared/divergent axes, propose unifying next step."
    else:  # W6
        anchors = papers[:2] + papers[-1:]
        gt = papers[-1]
        archetype_desc = "Cross-domain bridge: transfer method from one paper to a different problem framing."

    summary = ""
    for i, m in enumerate(chain[:8]):
        summary += f"- milestone {m.get('milestone_index', i+1)}: paper_id={m.get('paper_id','?')} role={m.get('contribution_role','?')} :: {m.get('rationale','')[:200]}\n"

    user = f"""# Lineage
trace_id: {lineage.get('trace_id')}
domain: {domain}
chain_name: {chain_name}
open_problem: {chain_initial.get('open_problem','')}
field_context: {chain_initial.get('field_context','')}
quantifiable_target: {chain_initial.get('quantifiable_target','')}

# Milestones (truncated)
{summary}

# Archetype
{archetype}: {archetype_desc}
Anchor papers: {anchors}
Ground-truth next paper (do not reveal in trajectory until propose, but it should guide your proposal): {gt}

# Task
Produce ONE agentic ReAct episode JSON per the system instructions.
"""
    return [
        {"role": "system", "content": SYSTEM_AGENTIC},
        {"role": "user", "content": user},
    ]


import threading
_write_lock = threading.Lock()


def process_one(args_tuple):
    lineage_path, archetype, seed = args_tuple
    lineage = json.loads(Path(lineage_path).read_text())
    # SKIP lineages without chain_trajectory (need L3b to run first)
    if not lineage.get("chain_trajectory"):
        raise ValueError("lineage has no chain_trajectory yet; needs L3b")
    msgs = build_episode_prompt(lineage, archetype)
    raw = chat55(msgs, max_tokens=4500)
    obj = parse_json_block(raw)
    obj.setdefault("lineage_id", lineage.get("trace_id"))
    obj["archetype"] = archetype
    obj["demo_id"] = f"epi_{archetype.split('_')[0].lower()}_{seed:06d}"
    obj["construction"] = {
        "extractor_model": "gpt-5.5",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    # Stream-write so consumers don't wait for full batch to flush
    AGENTIC.mkdir(parents=True, exist_ok=True)
    out_file = AGENTIC / "episodes.jsonl"
    with _write_lock:
        with open(out_file, "a") as f:
            f.write(json.dumps(obj, ensure_ascii=False) + "\n")
            f.flush()
    return obj


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--max-lineages", type=int, default=50)
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--archetypes", type=str, default="W2_single_paper_extension,W3_multi_paper_synthesis")
    args = ap.parse_args()

    archetypes = args.archetypes.split(",")
    # Only pick lineages that already have chain_trajectory (need L3b done for s2_seed)
    candidate_paths = []
    for p in LINEAGES.glob("*.json"):
        try:
            obj = json.loads(p.read_text())
            if obj.get("chain_trajectory"):
                candidate_paths.append(p)
        except Exception:
            continue
    import random
    random.shuffle(candidate_paths)
    paths = candidate_paths[: args.max_lineages]
    if not paths:
        log("no lineages with chain_trajectory found, wait for L3/L3b to produce some")
        return
    AGENTIC.mkdir(parents=True, exist_ok=True)

    items = []
    seed_off = int(time.time()) % 100000  # avoid demo_id collisions across runs
    for i, p in enumerate(paths):
        for j, arch in enumerate(archetypes):
            items.append((str(p), arch, seed_off + i * len(archetypes) + j))

    log("layer4 start", n=len(items), workers=args.workers)
    results = parallel_map(process_one, items, max_workers=args.workers,
                           desc="L4", logfile=LOGS / "layer4_errors.jsonl")
    ok = sum(1 for _, r, e in results if e is None and r is not None)
    fail = sum(1 for _, r, e in results if e is not None)

    out_file = AGENTIC / "episodes.jsonl"
    log("layer4 done", ok=ok, fail=fail, out=str(out_file))


if __name__ == "__main__":
    main()
