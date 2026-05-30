"""8h pipeline orchestrator.

Watches paper_atoms/, transitions/, lineages/, agentic_episodes/ counts.
Whenever a layer has < TARGET items AND no in-flight process, launches a new batch.

Run in background:
    nohup python orchestrator.py > _logs/orchestrator.log 2>&1 &
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import (
    PAPER_ATOMS, TRANSITIONS, LINEAGES, AGENTIC, LOGS, SCRIPTS,
    POOL, log,
)
from state_manager import load_orchestrator_state, save_orchestrator_state

PY = "/home/azureuser/.conda/envs/idea/bin/python"

# Target record counts per layer
TARGETS = {
    "L1": 6000,
    "L2": 3000,
    "L3": 1500,
    "L4": 2400,
}

# Per-batch sizes — small enough that scheduler can re-balance, big enough to not thrash
BATCH = {
    "L1_mineru": 200,    # workers 8 - PRIORITIZED (satisfies competition MinerU requirement)
    "L1_docling": 200,   # workers 8
    "L1_domain": 150,    # workers 6 - by-domain, biology/chem/materials/medicine
    "L2": 60,            # workers 4
    "L3": 50,            # workers 3
    "L4": 25,            # workers 4 (smaller so flush is more frequent)
}

CYCLE_SECONDS = 180  # check every 3 minutes


def count_files(d: Path, pattern="*.json"):
    return sum(1 for _ in d.rglob(pattern))


def count_jsonl_lines(p: Path):
    if not p.exists():
        return 0
    return sum(1 for _ in p.open())


def is_running(name_substr: str) -> bool:
    """Check if a python process running our script is alive."""
    try:
        out = subprocess.run(["ps", "-ef"], capture_output=True, text=True).stdout
        for line in out.splitlines():
            if "grep" in line or "orchestrator" in line:
                continue
            if name_substr in line and "python" in line:
                return True
        return False
    except Exception:
        return False


def launch(name: str, cmd: list[str], logfile: Path):
    log(f"launching {name}", cmd=" ".join(cmd))
    logfile.parent.mkdir(parents=True, exist_ok=True)
    with open(logfile, "a") as lf:
        lf.write(f"\n\n=== launch {time.strftime('%H:%M:%S')} {name} ===\n")
        subprocess.Popen(cmd, stdout=lf, stderr=subprocess.STDOUT,
                         start_new_session=True)


def main():
    start_ts = time.time()
    state = load_orchestrator_state()
    last_audit = state.get("last_audit", 0)  # persisted across restarts
    cycle = state.get("total_cycles", 0)
    log("orchestrator boot", restored_last_audit_ago_s=int(time.time() - last_audit) if last_audit else None,
        prior_cycles=cycle)
    while True:
        cycle += 1
        elapsed = (time.time() - start_ts) / 3600
        l1 = count_files(PAPER_ATOMS)
        l2 = count_files(TRANSITIONS)
        l3 = count_files(LINEAGES)
        l4 = count_jsonl_lines(AGENTIC / "episodes.jsonl")
        log(f"cycle {cycle}  elapsed={elapsed:.2f}h",
            L1=l1, L2=l2, L3=l3, L4=l4,
            L1_target=TARGETS["L1"], L2_target=TARGETS["L2"],
            L3_target=TARGETS["L3"], L4_target=TARGETS["L4"])

        # Decision: launch a fresh batch IF the layer is under target AND no in-flight
        # ---- L1 main: any-tool batch when below target ----
        if l1 < TARGETS["L1"] and not is_running("01_extract_layer1.py"):
            cmd = [PY, str(SCRIPTS / "01_extract_layer1.py"),
                   "--max", str(BATCH["L1_docling"]),
                   "--workers", "8",
                   "--tool", "mineru_cloud,mineru_pipeline,docling",
                   "--shuffle"]
            launch("L1_main", cmd, LOGS / "layer1_main_loop.log")

        # ---- L2 ----
        if l2 < TARGETS["L2"] and not is_running("02_transition_records.py"):
            cmd = [PY, str(SCRIPTS / "02_transition_records.py"),
                   "--max", str(BATCH["L2"]),
                   "--workers", "4",
                   "--shuffle"]
            launch("L2", cmd, LOGS / "layer2_loop.log")

        # ---- L3 ----
        if l3 < TARGETS["L3"] and not is_running("03_lineage_chains.py"):
            cmd = [PY, str(SCRIPTS / "03_lineage_chains.py"),
                   "--max", str(BATCH["L3"]),
                   "--workers", "3",
                   "--min-chain-len", "4"]
            launch("L3", cmd, LOGS / "layer3_loop.log")

        # ---- L4 (only when L3 has produced enough) ----
        if l3 >= 30 and l4 < TARGETS["L4"] and not is_running("04_agentic_episodes.py"):
            cmd = [PY, str(SCRIPTS / "04_agentic_episodes.py"),
                   "--max-lineages", str(BATCH["L4"]),
                   "--workers", "4",
                   "--archetypes", "W2_single_paper_extension,W3_multi_paper_synthesis,W6_cross_domain_bridge"]
            launch("L4", cmd, LOGS / "layer4_loop.log")

        # ---- L3b refresh narratives for s2_seed lineages ----
        if not is_running("03b_fill_chain_narratives.py"):
            cmd = [PY, str(SCRIPTS / "03b_fill_chain_narratives.py"),
                   "--max", "50", "--workers", "3"]
            launch("L3b", cmd, LOGS / "layer3b_loop.log")

        # ---- L1b abstract-only batches (bumps non-CS domain coverage) ----
        if l1 < TARGETS["L1"] and not is_running("01b_extract_layer1_from_abstract.py"):
            # round-robin through under-served domains
            import random
            dom_pick = random.choice(["biology", "physics", "medicine",
                                      "chemistry", "materials", "earth_science"])
            cmd = [PY, str(SCRIPTS / "01b_extract_layer1_from_abstract.py"),
                   "--max", "80", "--workers", "4",
                   "--domain", dom_pick,
                   "--min-citations", "5",
                   "--shuffle"]
            launch(f"L1b_{dom_pick}", cmd, LOGS / f"layer1b_{dom_pick}_loop.log")

        # ---- L2b transitions from s2_seed lineages (uses abstracts only) ----
        if l2 < TARGETS["L2"] and not is_running("02b_transition_from_lineage.py"):
            cmd = [PY, str(SCRIPTS / "02b_transition_from_lineage.py"),
                   "--max-pairs", "150", "--workers", "4"]
            launch("L2b", cmd, LOGS / "layer2b_loop.log")

        # ---- L2c transitions from IdeaEvolving scored_edges.jsonl (12K eligible edges) ----
        if l2 < TARGETS["L2"] and not is_running("02c_transition_from_scored_edges.py"):
            cmd = [PY, str(SCRIPTS / "02c_transition_from_scored_edges.py"),
                   "--max", "120", "--workers", "4"]
            launch("L2c", cmd, LOGS / "layer2c_loop.log")

        # ---- Hourly audit + repackage ----
        if (time.time() - last_audit) > 3600 and not is_running("06_audit_and_pack.py"):
            cmd = [PY, str(SCRIPTS / "06_audit_and_pack.py")]
            launch("audit", cmd, LOGS / "audit_loop.log")
            last_audit = time.time()
            save_orchestrator_state({"last_audit": last_audit, "total_cycles": cycle})

        # Stop when all targets hit
        if l1 >= TARGETS["L1"] and l2 >= TARGETS["L2"] and l3 >= TARGETS["L3"] and l4 >= TARGETS["L4"]:
            log("all targets reached, exiting orchestrator")
            # Run one final audit + packaging
            cmd = [PY, str(SCRIPTS / "06_audit_and_pack.py")]
            launch("audit_final", cmd, LOGS / "audit_final.log")
            time.sleep(60)
            # Also run idea_train integration
            cmd = [PY, str(SCRIPTS / "08_idea_train_integration.py")]
            launch("idea_train_integration", cmd, LOGS / "integration.log")
            break

        # Safety stop after 9h
        if elapsed > 9.0:
            log("9h elapsed, exiting orchestrator")
            break

        # Persist cycle counter every ~5 cycles
        if cycle % 5 == 0:
            save_orchestrator_state({"last_audit": last_audit, "total_cycles": cycle})

        time.sleep(CYCLE_SECONDS)


if __name__ == "__main__":
    main()
