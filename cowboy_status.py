#!/usr/bin/env python3
"""cowboy_status.py — read-only dashboard for the cowboy orchestrator + pipeline."""
import json
import sys
from datetime import datetime
from pathlib import Path

WORKLOG = Path("/workspace/quilt-cowboy/cowboy_worklog.jsonl")
PAPER_DIR = Path("/workspace/quilt-cowboy/cowboy_papers")
MAPPING = Path("/workspace/quilt-cowboy/cowboy_paper_mapping.json")
PIPELINE_LOG = Path("/workspace/quilt-cowboy/cowboy_pipeline.log")
DAEMON_LOG = Path("/workspace/quilt-cowboy/cowboy_daemon.log")


def read_jsonl(path):
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out


def main():
    print("=" * 60)
    print("COWBOY ORCHESTRATOR + PIPELINE STATUS")
    print("=" * 60)

    # Local
    local_papers = sorted(PAPER_DIR.glob("paper-cowboy-*.md"))
    print(f"\nLocal cowboy papers: {len(local_papers)}")
    total_bytes = sum(p.stat().st_size for p in local_papers)
    print(f"Total bytes: {total_bytes:,}")

    # Mapping
    if MAPPING.exists():
        m = json.loads(MAPPING.read_text()).get("mapping", {})
        print(f"Mapped to canon papers: {len(m)}")
        if m:
            nums = sorted(m.values())
            print(f"  range: {min(nums)}..{max(nums)}")
            unused = sorted(set(nums))
            print(f"  gaps: {[n for n in range(min(nums), max(nums)+1) if n not in set(nums)]}")

    # Worklog
    runs = read_jsonl(WORKLOG)
    print(f"\nWriters' room runs: {len(runs)}")
    if runs:
        total_chars = sum(r.get("synthesis_len", 0) for r in runs)
        total_time = sum(r.get("total_time_s", 0) for r in runs)
        last = runs[-1]
        print(f"  total synthesis: {total_chars:,} chars in {total_time:.0f}s")
        print(f"  last run: {last.get('timestamp', '?')[:19]} — {last.get('topic', '?')[:60]!r}")
        print(f"  last synth: {last.get('synth_provider', '?')} ({last.get('synthesis_len', 0)} chars)")

    # Pipeline log
    if PIPELINE_LOG.exists():
        plines = PIPELINE_LOG.read_text().splitlines()
        last_lines = plines[-5:] if len(plines) > 5 else plines
        print(f"\nPipeline last 5 lines:")
        for line in last_lines:
            print(f"  {line[:120]}")


if __name__ == "__main__":
    main()
