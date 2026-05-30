"""Persistent task queues + failure blacklist + cost tracking for the pipeline.

Replaces the "blind shuffle every batch" pattern with:
  - todo / done JSONL queues per layer
  - claim-atomically via fcntl file locks
  - blacklist file persists permanent failures
  - cost.json accumulates (input_tokens, output_tokens, cost_usd)
"""
from __future__ import annotations

import fcntl
import json
import os
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).parent))
from common import ROOT, log

STATE = ROOT / "_state"
STATE.mkdir(parents=True, exist_ok=True)
QUEUE_DIR = STATE / "queues"
QUEUE_DIR.mkdir(parents=True, exist_ok=True)
BLACKLIST_DIR = STATE / "blacklists"
BLACKLIST_DIR.mkdir(parents=True, exist_ok=True)
COST_FILE = STATE / "cost.json"
ORCHESTRATOR_STATE = STATE / "orchestrator.json"


# ── Queue ─────────────────────────────────────────────────────────────────────
class Queue:
    """JSONL-backed task queue with fcntl locking for safe concurrent claim."""

    def __init__(self, name: str):
        self.name = name
        self.todo_path = QUEUE_DIR / f"{name}.todo.jsonl"
        self.done_path = QUEUE_DIR / f"{name}.done.jsonl"
        self.lock_path = QUEUE_DIR / f"{name}.lock"
        for p in (self.todo_path, self.done_path):
            if not p.exists():
                p.touch()

    def _lock(self):
        f = open(self.lock_path, "w")
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        return f

    def seed(self, items: list[dict], key_fn):
        """Seed the queue with items. Only adds those not already in todo/done.
        key_fn extracts a stable key string from each item."""
        done_keys = set()
        for line in self.done_path.open():
            try:
                done_keys.add(json.loads(line).get("_key"))
            except Exception:
                pass
        todo_keys = set()
        for line in self.todo_path.open():
            try:
                todo_keys.add(json.loads(line).get("_key"))
            except Exception:
                pass
        added = 0
        with self._lock(), open(self.todo_path, "a") as f:
            for it in items:
                k = key_fn(it)
                if k in done_keys or k in todo_keys:
                    continue
                rec = dict(it)
                rec["_key"] = k
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
                added += 1
        log(f"queue[{self.name}] seeded", added=added, total_todo=len(todo_keys) + added)
        return added

    def claim(self, n: int = 1) -> list[dict]:
        """Atomically claim up to n items from todo. Moves them out of todo;
        caller MUST call mark_done() or mark_failed()."""
        with self._lock():
            lines = self.todo_path.read_text().splitlines()
            if not lines:
                return []
            head, tail = lines[:n], lines[n:]
            self.todo_path.write_text("\n".join(tail) + ("\n" if tail else ""))
        items = []
        for line in head:
            try:
                items.append(json.loads(line))
            except Exception:
                pass
        return items

    def mark_done(self, item: dict):
        with self._lock(), open(self.done_path, "a") as f:
            f.write(json.dumps({"_key": item.get("_key"), "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ")},
                              ensure_ascii=False) + "\n")

    def requeue(self, item: dict):
        """Push item back to head of todo (e.g. transient error)."""
        with self._lock():
            existing = self.todo_path.read_text()
            self.todo_path.write_text(json.dumps(item, ensure_ascii=False) + "\n" + existing)

    def stats(self) -> dict:
        n_todo = sum(1 for _ in self.todo_path.open())
        n_done = sum(1 for _ in self.done_path.open())
        return {"todo": n_todo, "done": n_done}


# ── Blacklist ─────────────────────────────────────────────────────────────────
class Blacklist:
    """Persistent failure counter. After max_fails attempts, key is permanently skipped."""

    def __init__(self, name: str, max_fails: int = 2):
        self.name = name
        self.path = BLACKLIST_DIR / f"{name}.json"
        self.max_fails = max_fails
        if self.path.exists():
            try:
                self.data = json.loads(self.path.read_text())
            except Exception:
                self.data = {}
        else:
            self.data = {}

    def is_blacklisted(self, key: str) -> bool:
        rec = self.data.get(key)
        return bool(rec and rec.get("count", 0) >= self.max_fails)

    def record_failure(self, key: str, err: str):
        rec = self.data.get(key, {"count": 0, "errs": []})
        rec["count"] = rec.get("count", 0) + 1
        rec["errs"] = (rec.get("errs") or [])[-2:] + [err[:200]]
        rec["ts"] = time.strftime("%Y-%m-%dT%H:%M:%SZ")
        self.data[key] = rec
        self._flush()

    def _flush(self):
        tmp = self.path.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=2))
        os.replace(tmp, self.path)

    def stats(self) -> dict:
        n_total = len(self.data)
        n_perma = sum(1 for v in self.data.values() if v.get("count", 0) >= self.max_fails)
        return {"tracked": n_total, "blacklisted": n_perma}


# ── Cost tracker ──────────────────────────────────────────────────────────────
# GPT-5.5 Azure pricing (approximate, May 2026):
#   input  : $5 / 1M tokens
#   output : $15 / 1M tokens
COST_IN_PER_M = 5.0
COST_OUT_PER_M = 15.0

class CostTracker:
    """Per-process accumulator. add() takes file lock, reloads-from-disk,
    merges deltas, writes back — safe under concurrent multi-process use."""

    LOCK_PATH = STATE / "cost.lock"

    def __init__(self):
        # We DON'T cache disk state across calls — always re-read under lock.
        pass

    def add(self, input_tokens: int, output_tokens: int, script: str | None = None):
        with open(self.LOCK_PATH, "w") as lock_f:
            fcntl.flock(lock_f.fileno(), fcntl.LOCK_EX)
            # Reload from disk under lock
            if COST_FILE.exists():
                try:
                    data = json.loads(COST_FILE.read_text())
                except Exception:
                    data = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "by_script": {}}
            else:
                data = {"input_tokens": 0, "output_tokens": 0, "calls": 0, "by_script": {}}
            data["input_tokens"] += input_tokens
            data["output_tokens"] += output_tokens
            data["calls"] += 1
            if script:
                data.setdefault("by_script", {})
                s = data["by_script"].setdefault(script, {"in": 0, "out": 0, "calls": 0})
                s["in"] += input_tokens
                s["out"] += output_tokens
                s["calls"] += 1
            data["estimated_list_price_usd"] = round(
                data["input_tokens"] / 1e6 * COST_IN_PER_M
                + data["output_tokens"] / 1e6 * COST_OUT_PER_M, 4)
            data["note"] = "Azure keyless via managed identity — no user billing. Number above is a TOKEN-CONSUMPTION PROXY based on public Azure OpenAI list pricing."
            tmp = COST_FILE.with_suffix(".json.tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2))
            os.replace(tmp, COST_FILE)


_cost = None
def cost() -> CostTracker:
    global _cost
    if _cost is None:
        _cost = CostTracker()
    return _cost


# ── Orchestrator persistence ──────────────────────────────────────────────────
def load_orchestrator_state() -> dict:
    if ORCHESTRATOR_STATE.exists():
        try:
            return json.loads(ORCHESTRATOR_STATE.read_text())
        except Exception:
            pass
    return {"last_audit": 0, "total_cycles": 0, "launches": {}}


def save_orchestrator_state(state: dict):
    tmp = ORCHESTRATOR_STATE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    os.replace(tmp, ORCHESTRATOR_STATE)


if __name__ == "__main__":
    # Self test
    q = Queue("test_queue")
    q.seed([{"id": 1, "x": "a"}, {"id": 2, "x": "b"}], key_fn=lambda r: str(r["id"]))
    items = q.claim(1)
    print("claimed:", items)
    if items:
        q.mark_done(items[0])
    print("stats:", q.stats())
    bl = Blacklist("test")
    bl.record_failure("paper_xxx", "schema error")
    bl.record_failure("paper_xxx", "schema error")
    print("blacklisted?", bl.is_blacklisted("paper_xxx"))
    print("blacklist stats:", bl.stats())
    cost().add(1000, 2000, script="test")
    print("cost:", json.loads(COST_FILE.read_text()))
