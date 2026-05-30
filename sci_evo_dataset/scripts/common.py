"""Shared utilities for SciEvo-Lineage construction pipeline.

Defines paths, schemas, GPT-5.5 client wrapper, JSONL helpers, schema validators.
All scripts import from here.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, asdict, field
from pathlib import Path
from typing import Any, Callable, Iterable

# ── Paths ─────────────────────────────────────────────────────────────────────
# CODE_ROOT = git working tree (scripts, schema, docs, license, sample exemplars)
# DATA_ROOT = bulk data store (moved to /data/zyf/sci_evo_dataset/ for disk space)
CODE_ROOT = Path("/home/azureuser/workspace-gzy/zyf/idea-data/sci_evo_dataset")
DATA_ROOT = Path("/data/zyf/sci_evo_dataset")
# Backwards-compat alias: any code expecting "ROOT" gets the data root
ROOT = DATA_ROOT

SCRIPTS = CODE_ROOT / "scripts"
TECH_REPORT = CODE_ROOT / "tech_report"
# Heavy data layers — live on /data/zyf
PAPER_ATOMS = DATA_ROOT / "paper_atoms"
TRANSITIONS = DATA_ROOT / "transitions"
LINEAGES = DATA_ROOT / "lineages"
AGENTIC = DATA_ROOT / "agentic_episodes"
POOL = DATA_ROOT / "_pool"
LOGS = DATA_ROOT / "_logs"
CKPT = DATA_ROOT / "_checkpoints"
# release/ is SPLIT:
#   - samples/, DATA_CARD.*, schema.json, audit_stats.json live in CODE_ROOT (committed to git)
#   - full_dataset.jsonl + per-layer .jsonl.gz live in DATA_ROOT (uncompressed jsonl gitignored)
SUBMISSION = CODE_ROOT / "release"  # default points to repo copy
SUBMISSION_DATA = DATA_ROOT / "release"  # for full_dataset.jsonl writes

YQH = Path("/home/azureuser/workspace-yqh/yqh/download")
YQH_ALL_PAPERS = YQH / "all_papers.json"
YQH_PARSE_MAPS = [
    YQH / "parse_mapping.json",         # 500 MinerU cloud
    YQH / "parse_mapping_batch.json",   # 4117 MinerU pipeline
    YQH / "parse_mapping_docling.json", # 13404 docling
]

IDEA_ROOT = Path("/home/azureuser/workspace-gzy/zyf/IdeaEvolving")
IDEA_PAPER_DB = IDEA_ROOT / "data/paper_db/paper_db.json"
IDEA_GENE_CARDS = IDEA_ROOT / "data/genome_db/paper_gene_cards.json"
IDEA_GENE_DIFFS = IDEA_ROOT / "data/genome_db/gene_diffs.json"
IDEA_TRACES = IDEA_ROOT / "data/traces/golden_traces_main.json"

# ── GPT-5.5 client ────────────────────────────────────────────────────────────
def _setup_gpt55_env():
    """Make sure managed-identity env is sourced. Called at import."""
    if not os.environ.get("AZURE_OPENAI_ENDPOINT"):
        # Re-source by reading the env script
        env_script = "/home/azureuser/workspace-gzy/zyf/env_gpt55_managed_identity.sh"
        if os.path.exists(env_script):
            for line in Path(env_script).read_text().splitlines():
                m = re.match(r"^\s*export\s+([A-Z0-9_]+)=(.+)$", line)
                if m:
                    k, v = m.group(1), m.group(2).strip().strip('"').strip("'")
                    os.environ[k] = v
                u = re.match(r"^\s*unset\s+([A-Z0-9_]+)\s*$", line)
                if u:
                    os.environ.pop(u.group(1), None)
    os.environ.setdefault("no_proxy", "*")
    os.environ.setdefault("NO_PROXY", "*")

_setup_gpt55_env()

# Lazy GPT-5.5 client
_gpt55 = None
def gpt55():
    global _gpt55
    if _gpt55 is None:
        sys.path.insert(0, str(IDEA_ROOT))
        sys.path.insert(0, "/home/azureuser/workspace-gzy/zyf/idea_train")
        from evo_opd.teachers.gpt55_client import build_client
        _gpt55 = build_client()
    return _gpt55


def chat55(messages, max_tokens=4096, temperature=None, retries=3, _script_name=None):
    """Call GPT-5.5 with retry. Returns string content or raises.

    Side effect: increments _state/cost.json with token usage.
    """
    # ensure sys.path set up before importing evo_opd
    if str(IDEA_ROOT) not in sys.path:
        sys.path.insert(0, str(IDEA_ROOT))
    idea_train_root = "/home/azureuser/workspace-gzy/zyf/idea_train"
    if idea_train_root not in sys.path:
        sys.path.insert(0, idea_train_root)
    from evo_opd.teachers.gpt55_client import call_one, TeacherCall
    call = TeacherCall(prompt_id="x", messages=messages,
                       max_tokens=max_tokens, temperature=temperature)
    last_err = None
    for attempt in range(retries + 1):
        try:
            r = call_one(gpt55(), call, retries=0)
            if r.error:
                raise RuntimeError(r.error)
            content = (r.content or "").strip()
            if not content:
                raise RuntimeError(f"empty content (finish={r.finish_reason}, in={r.input_tokens}, out={r.output_tokens})")
            # Cost tracking — best effort, never fail the call
            try:
                from state_manager import cost
                script = _script_name or sys.argv[0].split("/")[-1].replace(".py", "")
                cost().add(int(r.input_tokens or 0), int(r.output_tokens or 0), script=script)
            except Exception:
                pass
            return content
        except Exception as e:
            last_err = e
            if attempt < retries:
                time.sleep(3 + (2 ** attempt) + (attempt * 2))
    raise RuntimeError(f"chat55 failed after {retries+1} attempts: {last_err}")


def parse_json_block(text: str) -> Any:
    """Extract first JSON object/array from text, tolerating ```json fences."""
    # Try fenced block first
    m = re.search(r"```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```", text, re.DOTALL)
    if m:
        return json.loads(m.group(1))
    # Find first balanced {}
    s = text.find("{")
    if s == -1:
        s = text.find("[")
    if s == -1:
        raise ValueError(f"no json found in: {text[:200]}")
    depth = 0
    open_ch = text[s]
    close_ch = "}" if open_ch == "{" else "]"
    in_str = False
    esc = False
    for i in range(s, len(text)):
        c = text[i]
        if esc:
            esc = False
            continue
        if c == "\\":
            esc = True
            continue
        if c == '"' and not esc:
            in_str = not in_str
            continue
        if in_str:
            continue
        if c == open_ch:
            depth += 1
        elif c == close_ch:
            depth -= 1
            if depth == 0:
                return json.loads(text[s:i+1])
    raise ValueError("unbalanced json")


# ── JSONL helpers ─────────────────────────────────────────────────────────────
def jsonl_iter(path: Path):
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                yield json.loads(line)


def jsonl_append(path: Path, obj):
    with open(path, "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def write_json(path: Path, obj, indent=2):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w") as f:
        json.dump(obj, f, ensure_ascii=False, indent=indent)
    os.replace(tmp, path)


def read_json(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text())


# ── ID helpers ────────────────────────────────────────────────────────────────
def slugify(title: str) -> str:
    s = re.sub(r"[^a-zA-Z0-9]+", "_", title.lower())
    s = re.sub(r"_+", "_", s).strip("_")
    return s[:60]


def make_paper_id(title: str, year: int | None) -> str:
    if not title:
        return f"paper:unknown:{year or 0}"
    return f"paper:{slugify(title)}:{year or 0}"


def stable_hash(s: str, n=10) -> str:
    return hashlib.sha1(s.encode("utf-8")).hexdigest()[:n]


# ── Concurrency ───────────────────────────────────────────────────────────────
def parallel_map(fn, items, max_workers=8, desc="work", logfile: Path | None = None):
    """Run fn over items with thread pool, print rolling progress. Returns list of (item, result, err)."""
    results = []
    done = 0
    total = len(items)
    t0 = time.time()
    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        futs = {ex.submit(fn, it): it for it in items}
        for fut in as_completed(futs):
            it = futs[fut]
            try:
                r = fut.result()
                results.append((it, r, None))
            except Exception as e:
                results.append((it, None, str(e)))
                if logfile:
                    logfile.parent.mkdir(parents=True, exist_ok=True)
                    with open(logfile, "a") as lf:
                        lf.write(json.dumps({"item": str(it)[:200], "err": str(e)[:500]}) + "\n")
            done += 1
            if done % 10 == 0 or done == total:
                rate = done / max(time.time() - t0, 0.01)
                eta = (total - done) / max(rate, 0.01)
                print(f"[{desc}] {done}/{total}  rate={rate:.1f}/s  eta={eta/60:.1f}min", flush=True)
    return results


# ── S2 ────────────────────────────────────────────────────────────────────────
S2_API_KEY = "QkbLCu8jxE1R1iXzFSEWIS3xcrzv0iI35Gjiql3a"

def s2_get(url: str, params: dict | None = None, retries=3):
    import urllib.parse, urllib.request, urllib.error
    if params:
        url = url + "?" + urllib.parse.urlencode(params)
    last_err = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"x-api-key": S2_API_KEY, "User-Agent": "SciEvo/0.1"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            last_err = e
            if e.code == 429:
                time.sleep(5 + attempt * 5)
            elif e.code in (502, 503, 504):
                time.sleep(2 + attempt * 3)
            else:
                raise
        except Exception as e:
            last_err = e
            time.sleep(2 + attempt * 2)
    raise RuntimeError(f"s2_get failed: {last_err}")


# ── Schema validation ─────────────────────────────────────────────────────────
def validate_closed_loop(rec: dict) -> list[str]:
    """Return list of validation errors. Empty list = valid."""
    errors = []
    cl = rec.get("closed_loop_record")
    if not isinstance(cl, dict):
        return ["missing closed_loop_record"]
    for k in ("01_initial_request", "02_agent_trajectory", "03_success_verification"):
        if k not in cl:
            errors.append(f"missing {k}")
    ir = cl.get("01_initial_request", {})
    for k in ("target_name", "user_intent", "quantifiable_goal"):
        if not ir.get(k):
            errors.append(f"01_initial_request.{k} missing")
    traj = cl.get("02_agent_trajectory", [])
    if not isinstance(traj, list) or len(traj) < 2:
        errors.append("02_agent_trajectory needs >=2 steps")
    else:
        for i, step in enumerate(traj):
            for k in ("thought", "action", "observation"):
                if not step.get(k):
                    errors.append(f"step[{i}].{k} missing")
            if step.get("action") not in (
                "dry_experiment", "wet_experiment", "analysis",
                "literature_check", "design", "reflection",
            ):
                errors.append(f"step[{i}].action invalid: {step.get('action')}")
    sv = cl.get("03_success_verification", {})
    if not sv.get("final_verdict"):
        errors.append("03_success_verification.final_verdict missing")
    return errors


# ── Logging ───────────────────────────────────────────────────────────────────
def log(msg: str, **kv):
    parts = [time.strftime("%H:%M:%S"), msg]
    if kv:
        parts.append(json.dumps(kv, ensure_ascii=False))
    print(" ".join(parts), flush=True)


if __name__ == "__main__":
    # quick self-check
    log("common.py self-check")
    log("GPT-5.5 endpoint", endpoint=os.environ.get("AZURE_OPENAI_ENDPOINT", "?"))
    log("paths", root=str(ROOT), exists=ROOT.exists())
    log("yqh parsed dirs", n=sum(1 for p in YQH_PARSE_MAPS if p.exists()))
