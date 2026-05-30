"""Periodically writes _logs/status.json with current counts.

Allows agents/dashboards to poll for state without needing to scan many dirs.
"""
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    PAPER_ATOMS, TRANSITIONS, LINEAGES, AGENTIC, LOGS, POOL,
)


def count_dir(d, pattern="*.json"):
    return sum(1 for _ in d.rglob(pattern))


def main():
    while True:
        l1 = count_dir(PAPER_ATOMS)
        l2 = count_dir(TRANSITIONS)
        l3 = count_dir(LINEAGES)
        ep = AGENTIC / "episodes.jsonl"
        l4 = sum(1 for _ in ep.open()) if ep.exists() else 0

        # per-domain L1
        domains = {}
        for sub in PAPER_ATOMS.iterdir():
            if sub.is_dir():
                domains[sub.name] = sum(1 for _ in sub.glob("*.json"))

        # narrated lineages
        narrated = 0
        for p in LINEAGES.glob("*.json"):
            try:
                d = json.loads(p.read_text())
                if d.get("chain_trajectory"):
                    narrated += 1
            except Exception:
                pass

        # error counts
        errs = {}
        for f in LOGS.glob("*_errors.jsonl"):
            errs[f.stem] = sum(1 for _ in f.open())

        status = {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "L1": l1,
            "L2": l2,
            "L3": l3,
            "L3_narrated": narrated,
            "L4": l4,
            "domain_breakdown": domains,
            "errors": errs,
            "targets": {"L1": 3000, "L2": 1600, "L3": 600, "L4": 1200},
        }
        (LOGS / "status.json").write_text(json.dumps(status, ensure_ascii=False, indent=2))
        time.sleep(90)


if __name__ == "__main__":
    main()
