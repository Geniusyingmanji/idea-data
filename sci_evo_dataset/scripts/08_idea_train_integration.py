"""Stage 8: Copy & adapt our agentic_episodes/episodes.jsonl into idea_train's
SFT data format under idea_train/data/scievo/sft_demos.jsonl.

Maps our episode trajectory ([role, thought, tool, input] turns) into the
chat-completions format idea_train expects: list of {role, content} messages
plus a 'metadata' dict.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from common import AGENTIC, log

IDEA_TRAIN_DATA = Path("/home/azureuser/workspace-gzy/zyf/idea_train/data/scievo")
IDEA_TRAIN_DATA.mkdir(parents=True, exist_ok=True)


def episode_to_sft(rec: dict) -> dict | None:
    traj = rec.get("trajectory") or []
    if not traj:
        return None
    messages = []
    user_prompt = rec.get("user_prompt") or "Propose a research next step based on the lineage."
    messages.append({"role": "user", "content": user_prompt})
    # Assemble alternating assistant (thought+tool call) and tool responses
    for turn in traj:
        if turn.get("role") == "assistant":
            content = json.dumps({
                "thought": turn.get("thought", ""),
                "action": turn.get("tool", ""),
                "input": turn.get("input", ""),
            }, ensure_ascii=False)
            messages.append({"role": "assistant", "content": content})
        elif turn.get("role") == "tool":
            content = json.dumps({
                "tool": turn.get("name", ""),
                "output": turn.get("output", ""),
            }, ensure_ascii=False)
            messages.append({"role": "tool", "content": content})
    return {
        "demo_id": rec.get("demo_id"),
        "archetype": rec.get("archetype"),
        "lineage_id": rec.get("lineage_id"),
        "messages": messages,
        "metadata": {
            "source": "SciEvo-Lineage L4",
            "ground_truth_next_paper_id": rec.get("ground_truth_next_paper_id"),
        },
    }


def main():
    src = AGENTIC / "episodes.jsonl"
    if not src.exists():
        log("no episodes.jsonl yet", path=str(src))
        return

    out = IDEA_TRAIN_DATA / "sft_demos.jsonl"
    n_in = n_out = 0
    with open(out, "w") as f:
        for line in src.open():
            line = line.strip()
            if not line:
                continue
            n_in += 1
            try:
                rec = json.loads(line)
            except Exception:
                continue
            sft = episode_to_sft(rec)
            if not sft:
                continue
            f.write(json.dumps(sft, ensure_ascii=False) + "\n")
            n_out += 1
    log("integration done", in_=n_in, out=n_out, path=str(out))

    # Index file for the dataset
    summary = {
        "name": "scievo",
        "source_path": str(src),
        "n_demos": n_out,
        "format": "chat-completions messages with assistant turns encoding {thought, action, input}",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    (IDEA_TRAIN_DATA / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
