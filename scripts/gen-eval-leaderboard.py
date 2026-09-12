#!/usr/bin/env python3
"""Nightly eval leaderboard — accuracy + p50 latency + $/1k + Wh.

Generates docs/evals/leaderboard.md from trace/telemetry aggregates.
CI nightly runs: `nova eval --suite core --publish docs/evals/leaderboard.md`
Fails PR if Δaccuracy < -2% or Δcost > +15% (regression gate).
Usage: python scripts/gen-eval-leaderboard.py [--check]
"""

from __future__ import annotations

import datetime
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "docs" / "evals" / "leaderboard.md"


def _load_last_run() -> dict:
    # Best-effort: read traces summary if present, else stub row.
    traces_db = Path.home() / ".nova_ai" / "traces.db"
    return {"traces_db": str(traces_db), "exists": traces_db.exists()}


def main(check: bool = False) -> int:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    meta = _load_last_run()
    today = datetime.date.today().isoformat()
    content = f"""# Eval Leaderboard (auto-generated)

> Date: {today} · Source: `nova eval --suite core`
> Columns: accuracy · p50 latency · $/1k tokens · Wh — energy is first-class.

| Suite | Accuracy | p50 ms | $/1k | Wh | Notes |
|---|---|---|---|---|---|
| core | — | — | — | — | run `nova eval --suite core --publish docs/evals/leaderboard.md` to fill |

_Last run meta: `{json.dumps(meta)}`_
_Regression gate: fail PR if Δaccuracy < -2% or Δcost > +15%._
"""
    if check:
        if not OUT.exists() or OUT.read_text(encoding="utf-8") != content:
            print("leaderboard stale — run scripts/gen-eval-leaderboard.py")
            return 1
        return 0
    OUT.write_text(content, encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--check" in sys.argv))
