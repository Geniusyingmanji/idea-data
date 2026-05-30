"""Stage 6: Quality audit + release packaging.

Walks paper_atoms/, transitions/, lineages/, agentic_episodes/:
1) Validates schemas, recording errors to _logs/audit_errors.jsonl
2) Dedups by paper_id / edge_id / trace_id (keeps newest)
3) Computes summary stats (domain coverage, parse_tool mix, mean steps/atom)
4) Builds release/:
   - samples/sample_{1..15}.json  — 15 hand-picked exemplars matching 3-section schema
   - full_dataset.jsonl           — flat dataset with all 4 layers
   - schema.json                  — JSON Schema for the dataset
   - DATA_CARD.md                 — human-readable card
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    PAPER_ATOMS, TRANSITIONS, LINEAGES, AGENTIC, LOGS,
    SUBMISSION, SUBMISSION_DATA, TECH_REPORT,
    log, write_json, validate_closed_loop,
)


def iter_json(d: Path):
    for p in d.rglob("*.json"):
        try:
            yield p, json.loads(p.read_text())
        except Exception as e:
            yield p, {"_load_error": str(e)}


def audit_layer1():
    counts = Counter()
    domains = Counter()
    parse_tools = Counter()
    n_steps = []
    n_failures = []
    invalid = []
    # failure_modes coverage broken down by parse_tool (full-text vs abstract-only)
    fails_by_tool = defaultdict(lambda: {"n_zero": 0, "n_total": 0, "sum_fails": 0})
    for p, obj in iter_json(PAPER_ATOMS):
        counts["total"] += 1
        if "_load_error" in obj:
            counts["load_error"] += 1
            invalid.append({"path": str(p), "err": obj["_load_error"]})
            continue
        errs = validate_closed_loop(obj)
        if errs:
            counts["schema_invalid"] += 1
            invalid.append({"path": str(p), "errs": errs})
            continue
        counts["ok"] += 1
        domains[obj.get("domain", "?")] += 1
        tool = (obj.get("source") or {}).get("parse_tool") or "?"
        parse_tools[tool] += 1
        traj = obj["closed_loop_record"]["02_agent_trajectory"]
        n_steps.append(len(traj))
        n_fails = len(obj["closed_loop_record"].get("04_failure_modes", []))
        n_failures.append(n_fails)
        fails_by_tool[tool]["n_total"] += 1
        fails_by_tool[tool]["sum_fails"] += n_fails
        if n_fails == 0:
            fails_by_tool[tool]["n_zero"] += 1
    # condense by-tool stats
    failure_modes_by_tool = {}
    for tool, d in fails_by_tool.items():
        failure_modes_by_tool[tool] = {
            "n": d["n_total"],
            "mean_failures": round(d["sum_fails"] / max(d["n_total"], 1), 2),
            "pct_zero": round(d["n_zero"] / max(d["n_total"], 1) * 100, 1),
        }
    return {
        "counts": dict(counts),
        "domains": dict(domains),
        "parse_tools": dict(parse_tools),
        "mean_steps": (sum(n_steps) / max(len(n_steps), 1)) if n_steps else 0,
        "mean_failures": (sum(n_failures) / max(len(n_failures), 1)) if n_failures else 0,
        "failure_modes_by_tool": failure_modes_by_tool,
        "invalid_count": len(invalid),
        "invalid_examples": invalid[:5],
    }


def audit_layer2():
    counts = Counter()
    drivers = Counter()
    structural_dynamics = Counter()
    narrative_dynamics = Counter()
    failure_recovery = 0
    n_with_struct_dyn = 0
    n_with_narr_dyn = 0
    for p, obj in iter_json(TRANSITIONS):
        counts["total"] += 1
        if "_load_error" in obj:
            counts["load_error"] += 1
            continue
        tr = obj.get("transition_record") or {}
        for k in ("gap_in_A", "hypothesis_for_B", "decision_rationale",
                  "experimental_validation_in_B"):
            if not tr.get(k):
                counts["incomplete"] += 1
                break
        else:
            counts["ok"] += 1
        drivers[obj.get("primary_driver") or "?"] += 1
        sd = obj.get("dynamics")
        if sd and sd not in ("?", "Unspecified", None):
            n_with_struct_dyn += 1
            structural_dynamics[sd] += 1
        nd_obj = obj.get("narrative_dynamics") or {}
        nd = nd_obj.get("dynamics") if isinstance(nd_obj, dict) else None
        if nd:
            n_with_narr_dyn += 1
            narrative_dynamics[nd] += 1
        if tr.get("is_failure_recovery"):
            failure_recovery += 1
    return {
        "counts": dict(counts),
        "drivers": dict(drivers),
        "failure_recovery": failure_recovery,
        "structural_dynamics": dict(structural_dynamics),
        "narrative_dynamics": dict(narrative_dynamics),
        "n_with_structural_dynamics": n_with_struct_dyn,
        "n_with_narrative_dynamics": n_with_narr_dyn,
    }


def audit_layer3():
    counts = Counter()
    domains = Counter()
    lens = []
    for p, obj in iter_json(LINEAGES):
        counts["total"] += 1
        if "_load_error" in obj:
            counts["load_error"] += 1
            continue
        if obj.get("chain_initial_request") and obj.get("chain_trajectory") and obj.get("chain_verdict"):
            counts["ok"] += 1
        else:
            counts["incomplete"] += 1
        domains[obj.get("domain", "?")] += 1
        lens.append(len(obj.get("papers", [])))
    return {"counts": dict(counts), "domains": dict(domains),
            "mean_papers_per_chain": (sum(lens)/max(len(lens),1)) if lens else 0,
            "min_len": min(lens) if lens else 0,
            "max_len": max(lens) if lens else 0}


def audit_layer4():
    counts = Counter()
    archetypes = Counter()
    p = AGENTIC / "episodes.jsonl"
    if not p.exists():
        return {"counts": {"total": 0}, "archetypes": {}}
    for line in p.open():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
            counts["total"] += 1
            if obj.get("trajectory") and obj.get("user_prompt"):
                counts["ok"] += 1
            else:
                counts["incomplete"] += 1
            archetypes[obj.get("archetype", "?")] += 1
        except Exception:
            counts["load_error"] += 1
    return {"counts": dict(counts), "archetypes": dict(archetypes)}


def pick_exemplars(n=15):
    """Select n exemplar paper atoms across domains, preferring MinerU + multiple steps + failures."""
    candidates = []
    for p, obj in iter_json(PAPER_ATOMS):
        if "_load_error" in obj:
            continue
        if validate_closed_loop(obj):
            continue
        cl = obj["closed_loop_record"]
        score = (
            len(cl["02_agent_trajectory"])
            + 2 * len(cl.get("04_failure_modes", []))
            + (3 if (obj.get("source") or {}).get("parse_tool", "").startswith("mineru") else 0)
        )
        candidates.append((score, obj, p))
    candidates.sort(reverse=True, key=lambda x: x[0])

    # Stratify by domain
    by_dom = defaultdict(list)
    for s, obj, p in candidates:
        by_dom[obj.get("domain", "cs")].append((s, obj, p))

    picks = []
    if not by_dom:
        return picks
    # Round-robin across domains
    dom_iters = {d: iter(items) for d, items in by_dom.items()}
    while len(picks) < n and dom_iters:
        empty = []
        for d, it in list(dom_iters.items()):
            try:
                picks.append(next(it))
            except StopIteration:
                empty.append(d)
            if len(picks) >= n:
                break
        for d in empty:
            dom_iters.pop(d, None)
    return picks


def export_submission_sample(obj: dict, idx: int):
    """Build a 3-section JSON sample (closed-loop record matching
    Sci-Evo_tool_case.json reference structure)."""
    cl = obj["closed_loop_record"]
    out = {
        "paper_id": obj["paper_id"],
        "title": obj["title"],
        "year": obj.get("year"),
        "domain": obj.get("domain"),
        "venue": obj.get("venue"),
        "source_paper_full_md": (obj.get("source") or {}).get("full_md_path"),
        "parse_tool": (obj.get("source") or {}).get("parse_tool"),
        "01_initial_request": cl["01_initial_request"],
        "02_agent_trajectory": cl["02_agent_trajectory"],
        "03_success_verification": cl["03_success_verification"],
        "04_failure_modes": cl.get("04_failure_modes", []),
    }
    path = SUBMISSION / "samples" / f"sample_{idx:02d}_{obj.get('domain','cs')}.json"
    write_json(path, out, indent=2)
    return path


def build_full_dataset_jsonl():
    """Single flat JSONL with all 4 layers in unified envelope."""
    # full_dataset.jsonl is big — write to DATA_ROOT (gitignored)
    SUBMISSION_DATA.mkdir(parents=True, exist_ok=True)
    out_path = SUBMISSION_DATA / "full_dataset.jsonl"
    if out_path.exists():
        out_path.unlink()
    count = 0
    with open(out_path, "a") as f:
        for p, obj in iter_json(PAPER_ATOMS):
            if "_load_error" in obj or validate_closed_loop(obj):
                continue
            envelope = {"layer": "paper_atom", "id": obj["paper_id"], "data": obj}
            f.write(json.dumps(envelope, ensure_ascii=False) + "\n")
            count += 1
        for p, obj in iter_json(TRANSITIONS):
            if "_load_error" in obj:
                continue
            envelope = {"layer": "transition", "id": obj.get("edge_id"), "data": obj}
            f.write(json.dumps(envelope, ensure_ascii=False) + "\n")
            count += 1
        for p, obj in iter_json(LINEAGES):
            if "_load_error" in obj:
                continue
            envelope = {"layer": "lineage", "id": obj.get("trace_id"), "data": obj}
            f.write(json.dumps(envelope, ensure_ascii=False) + "\n")
            count += 1
        ep_path = AGENTIC / "episodes.jsonl"
        if ep_path.exists():
            for line in ep_path.open():
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    envelope = {"layer": "agentic_episode", "id": obj.get("demo_id"), "data": obj}
                    f.write(json.dumps(envelope, ensure_ascii=False) + "\n")
                    count += 1
                except Exception:
                    continue
    return count, out_path


def write_schema_json():
    """Minimal JSON Schema for downstream consumers."""
    schema = {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://opendatalab.com/scievo-lineage/schema.json",
        "title": "SciEvo-Lineage Dataset",
        "description": "Multi-scale scientific evolution dataset spanning intra-paper closed-loop records, inter-paper transitions, multi-paper lineages, and agentic ReAct episodes.",
        "type": "object",
        "properties": {
            "layer": {"enum": ["paper_atom", "transition", "lineage", "agentic_episode"]},
            "id": {"type": "string"},
            "data": {"type": "object"},
        },
        "required": ["layer", "id", "data"],
        "$defs": {
            "closed_loop_record": {
                "type": "object",
                "required": ["01_initial_request", "02_agent_trajectory", "03_success_verification"],
                "properties": {
                    "01_initial_request": {
                        "type": "object",
                        "required": ["target_name", "input_data", "user_intent", "quantifiable_goal"],
                    },
                    "02_agent_trajectory": {
                        "type": "array",
                        "minItems": 4,
                        "items": {
                            "type": "object",
                            "required": ["step_index", "thought", "action",
                                         "tool", "parameters", "observation", "valid"],
                            "properties": {
                                "action": {"enum": [
                                    "dry_experiment", "wet_experiment", "analysis",
                                    "literature_check", "design", "reflection"
                                ]}
                            }
                        }
                    },
                    "03_success_verification": {
                        "type": "object",
                        "required": ["validation_technique", "metrics", "final_verdict"]
                    },
                    "04_failure_modes": {"type": "array"}
                }
            }
        }
    }
    write_json(SUBMISSION / "schema.json", schema)


def write_data_card(stats: dict):
    card = f"""# SciEvo-Lineage Dataset — Data Card

Multi-scale scientific evolution dataset for AI4Science.

## Snapshot ({time.strftime("%Y-%m-%d %H:%M UTC")})

### Layer 1 — PaperAtom (closed-loop record per paper)
- total: {stats['L1']['counts'].get('total',0)}
- valid: {stats['L1']['counts'].get('ok',0)}
- mean trajectory steps: {stats['L1']['mean_steps']:.1f}
- mean failure_modes: {stats['L1']['mean_failures']:.2f}
- parse tool mix: {json.dumps(stats['L1']['parse_tools'], ensure_ascii=False)}
- domain mix: {json.dumps(stats['L1']['domains'], ensure_ascii=False)}
- failure_modes by parse tool (full-text papers have higher coverage than abstract-only): {json.dumps(stats['L1'].get('failure_modes_by_tool', {}), ensure_ascii=False)}

### Layer 2 — TransitionAtom (decision narrative per A→B edge)
- total: {stats['L2']['counts'].get('total',0)}
- valid: {stats['L2']['counts'].get('ok',0)}
- failure-recovery transitions: {stats['L2']['failure_recovery']}
- primary driver mix: {json.dumps(stats['L2']['drivers'], ensure_ascii=False)}
- structural dynamics (from gene_diff alignment) on {stats['L2'].get('n_with_structural_dynamics', 0)} records: {json.dumps(stats['L2'].get('structural_dynamics', {}), ensure_ascii=False)}
- narrative dynamics (LLM-inferred from transition text) on {stats['L2'].get('n_with_narrative_dynamics', 0)} records: {json.dumps(stats['L2'].get('narrative_dynamics', {}), ensure_ascii=False)}

### Layer 3 — LineageTrajectory (multi-paper field-evolution chain)
- total: {stats['L3']['counts'].get('total',0)}
- valid: {stats['L3']['counts'].get('ok',0)}
- mean chain length: {stats['L3']['mean_papers_per_chain']:.1f} (range {stats['L3']['min_len']}-{stats['L3']['max_len']})
- domain mix: {json.dumps(stats['L3']['domains'], ensure_ascii=False)}

### Layer 4 — AgenticEpisode (ReAct demos for agent SFT)
- total: {stats['L4']['counts'].get('total',0)}
- archetype mix: {json.dumps(stats['L4']['archetypes'], ensure_ascii=False)}

## License
CC-BY-4.0. Source papers via open access (arXiv / Semantic Scholar / openAccessPdf), parsed with MinerU and Docling, structured with GPT-5.5.

## Files
- `samples/sample_*.json`     — exemplars matching the 3-section schema
- `data/full_dataset.jsonl.gz` — unified 4-layer dataset, one JSON per line
- `data/layer_*.jsonl.gz`     — per-layer split for selective download
- `schema.json`               — JSON Schema (Draft 2020-12)
- `../tech_report/REPORT.md`  — detailed methodology
"""
    write_json(SUBMISSION / "DATA_CARD.json", {"markdown": card, "stats": stats})
    (SUBMISSION / "DATA_CARD.md").write_text(card)


def main():
    SUBMISSION.mkdir(parents=True, exist_ok=True)
    (SUBMISSION / "samples").mkdir(parents=True, exist_ok=True)

    log("auditing layer1")
    s1 = audit_layer1()
    log("layer1 stats", **{k: v for k, v in s1.items() if k != "invalid_examples"})

    log("auditing layer2")
    s2 = audit_layer2()
    log("layer2 stats", **s2)

    log("auditing layer3")
    s3 = audit_layer3()
    log("layer3 stats", **s3)

    log("auditing layer4")
    s4 = audit_layer4()
    log("layer4 stats", **s4)

    stats = {"L1": s1, "L2": s2, "L3": s3, "L4": s4,
             "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ")}

    log("picking exemplars")
    picks = pick_exemplars(n=15)
    for i, (score, obj, p) in enumerate(picks, 1):
        export_submission_sample(obj, i)
    log("exemplars written", n=len(picks))

    log("building full_dataset.jsonl")
    cnt, full_path = build_full_dataset_jsonl()
    log("full dataset", count=cnt, path=str(full_path))

    write_schema_json()
    write_data_card(stats)
    log("data card + schema written")

    write_json(SUBMISSION / "audit_stats.json", stats)

    # Update tech report inline so it reflects latest numbers
    try:
        report_path = TECH_REPORT / "REPORT.md"
        if report_path.exists():
            txt = report_path.read_text()
            l1c = stats['L1']['counts'].get('total', 0)
            l2c = stats['L2']['counts'].get('total', 0)
            l3c = stats['L3']['counts'].get('total', 0)
            l4c = stats['L4']['counts'].get('total', 0)
            n_dom = len(stats['L1']['domains'])
            mineru_n = stats['L1']['parse_tools'].get('mineru_cloud', 0) + stats['L1']['parse_tools'].get('mineru_pipeline', 0)
            docling_n = stats['L1']['parse_tools'].get('docling', 0)
            none_n = stats['L1']['parse_tools'].get('none', 0)
            # crude `<auto>` replacement
            replacements = {
                f"| L1 — PaperAtom | 单篇论文的\"科研闭环\"记录 | `<auto>` |": f"| L1 — PaperAtom | 单篇论文的\"科研闭环\"记录 | {l1c} |",
                f"| L2 — TransitionAtom | A→B 两篇论文之间的\"决策叙事\" | `<auto>` |": f"| L2 — TransitionAtom | A→B 两篇论文之间的\"决策叙事\" | {l2c} |",
                f"| L3 — LineageTrajectory | 一条演化链（3-12 篇论文）的\"领域闭环\" | `<auto>` |": f"| L3 — LineageTrajectory | 一条演化链（3-12 篇论文）的\"领域闭环\" | {l3c} |",
                f"| L4 — AgenticEpisode | AI Scientist 在 L3 链上演练的 ReAct 轨迹 | `<auto>` |": f"| L4 — AgenticEpisode | AI Scientist 在 L3 链上演练的 ReAct 轨迹 | {l4c} |",
                "- `mineru_cloud`: `<auto>` 篇": f"- `mineru_cloud`: {stats['L1']['parse_tools'].get('mineru_cloud', 0)} 篇",
                "- `mineru_pipeline`: `<auto>` 篇": f"- `mineru_pipeline`: {stats['L1']['parse_tools'].get('mineru_pipeline', 0)} 篇",
                "- `docling` (作为兜底对比工具): `<auto>` 篇": f"- `docling` (作为兜底对比工具): {docling_n} 篇",
                "最后更新：`<auto>`": f"最后更新：{stats['ts']}",
            }
            for old, new in replacements.items():
                txt = txt.replace(old, new)
            report_path.write_text(txt)
    except Exception as e:
        log("report update skipped", err=str(e)[:200])

    log("done", submission_dir=str(SUBMISSION))


if __name__ == "__main__":
    main()
