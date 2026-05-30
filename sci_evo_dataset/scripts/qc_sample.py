"""QC sampling: pick stratified samples across L1/L2/L3/L4, summarize key quality signals."""
from __future__ import annotations

import json
import random
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import PAPER_ATOMS, TRANSITIONS, LINEAGES, AGENTIC, validate_closed_loop

random.seed(33)


def qc_l1(n_per_dom=3):
    print("\n========== L1 QC (PaperAtom) ==========")
    by_dom = defaultdict(list)
    for p in PAPER_ATOMS.rglob("*.json"):
        try: d = json.load(open(p))
        except: continue
        by_dom[d.get("domain","?")].append((p, d))
    action_dist = Counter()
    step_lengths = []
    fail_counts = []
    for dom, items in sorted(by_dom.items()):
        random.shuffle(items)
        for p, d in items[:n_per_dom]:
            cl = d.get("closed_loop_record", {})
            traj = cl.get("02_agent_trajectory", [])
            fm = cl.get("04_failure_modes", [])
            step_lengths.append(len(traj))
            fail_counts.append(len(fm))
            for s in traj:
                action_dist[s.get("action","?")] += 1
            errs = validate_closed_loop(d)
            print(f"  [{dom:14s}] {len(traj):2d} steps  {len(fm)} fails  schema_ok={not errs}  parse={(d.get('source') or {}).get('parse_tool')}  '{d.get('title','')[:60]}'")
    print(f"\n  action vocab used (sample): {dict(action_dist)}")
    if step_lengths:
        print(f"  mean steps: {sum(step_lengths)/len(step_lengths):.1f}, mean failures: {sum(fail_counts)/len(fail_counts):.2f}")


def qc_l2(n=15):
    print("\n========== L2 QC (TransitionAtom) ==========")
    paths = list(TRANSITIONS.glob("*.json"))
    random.shuffle(paths)
    by_src = Counter()
    for p in paths[:n]:
        try: d = json.load(open(p))
        except: continue
        src = (d.get("construction") or {}).get("source","02_main")
        by_src[src] += 1
        tr = d.get("transition_record", {})
        fr = tr.get("is_failure_recovery")
        dyn = d.get("dynamics") or "?"
        st = d.get('source_title') or ""
        tt = d.get('target_title') or ""
        print(f"  [{src:30s}] dyn={dyn:20s} failure_recovery={fr}  '{st[:40]}' -> '{tt[:40]}'")
    print(f"\n  source distribution (sample): {dict(by_src)}")


def qc_l3(n=10):
    print("\n========== L3 QC (LineageTrajectory) ==========")
    paths = list(LINEAGES.glob("*.json"))
    random.shuffle(paths)
    domains = Counter()
    for p in paths[:n]:
        try: d = json.load(open(p))
        except: continue
        domains[d.get("domain","?")] += 1
        ct = d.get("chain_trajectory") or []
        cir = d.get("chain_initial_request") or {}
        print(f"  [{d.get('domain','?'):14s}] chain_len={len(d.get('papers',[]))} narrated={len(ct)} provenance={d.get('provenance')}")
        print(f"    open_problem: {(cir.get('open_problem') or '')[:130]}")
        if ct:
            print(f"    milestone 1: role={ct[0].get('contribution_role','?')} rationale={(ct[0].get('rationale') or '')[:130]}")
    print(f"\n  sampled domains: {dict(domains)}")


def qc_l4(n=8):
    print("\n========== L4 QC (AgenticEpisode) ==========")
    if not (AGENTIC / "episodes.jsonl").exists():
        print("  no episodes.jsonl")
        return
    lines = [l for l in (AGENTIC / "episodes.jsonl").open()]
    random.shuffle(lines)
    arch = Counter()
    turn_lens = []
    for line in lines[:n]:
        try:
            d = json.loads(line)
        except: continue
        arch[d.get("archetype","?")] += 1
        turn_lens.append(len(d.get("trajectory") or []))
        tools = [t.get("tool") for t in (d.get("trajectory") or []) if t.get("role") == "assistant" and t.get("tool")]
        print(f"  [{d.get('archetype','?')[:30]:30s}] turns={len(d.get('trajectory') or []):2d} tools={tools[:6]} gt={d.get('ground_truth_next_paper_id','?')[:40]}")
        print(f"    user_prompt: {(d.get('user_prompt') or '')[:120]}")
    print(f"\n  archetype distribution (sample): {dict(arch)}")
    if turn_lens:
        print(f"  mean turns: {sum(turn_lens)/len(turn_lens):.1f}")


def main():
    qc_l1(n_per_dom=2)
    qc_l2(n=15)
    qc_l3(n=8)
    qc_l4(n=8)


if __name__ == "__main__":
    main()
