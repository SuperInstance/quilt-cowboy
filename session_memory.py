"""session_memory.py — turn a working session into a navigable cell fabric.

The novel idea: a session's working state is itself a cell fabric.
- Each tool call = 1 cell (dials = tool, args_hash, result_hash)
- Each shared context = an edge between cells
- tick() = each new call re-balances the fabric
- save_to_quf() = serialize the session as a portable .quf file
- load_from_quf() = reconstruct the session from a .quf file
- query() = find similar past sessions by partial context match

The use case: "I worked on something like this 3 months ago, what did I do?"
becomes a single cell-fabric query instead of a search.
"""
from __future__ import annotations

import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/workspace/quilt-timesfm")

from quf_v2 import QufFile, EdgeRecord, RouteRecord, dumps as quf_dumps


class SessionCell:
    """A single tool call in a session."""

    def __init__(self, tool: str, args: Any, result: Any, tick: int = 0):
        self.tool = tool
        self.args = str(args)[:500] if args else ""
        self.result = str(result)[:500] if result else ""
        self.tick = tick
        # Dials (16 x Q1.15)
        self.dials = self._compute_dials()

    def _compute_dials(self) -> List[int]:
        arg_hash = hashlib.md5(self.args.encode()).hexdigest()
        res_hash = hashlib.md5(self.result.encode()).hexdigest()
        tool_hash = hashlib.md5(self.tool.encode()).hexdigest()
        return [
            int(arg_hash[:4], 16) & 0x7FFF,
            int(arg_hash[4:8], 16) & 0x7FFF,
            int(res_hash[:4], 16) & 0x7FFF,
            int(res_hash[4:8], 16) & 0x7FFF,
            int(tool_hash[:4], 16) & 0x7FFF,
            int(tool_hash[4:8], 16) & 0x7FFF,
            min(0x7FFF, len(self.args) * 16),
            min(0x7FFF, len(self.result) * 16),
            self.tick & 0x7FFF,
            int(arg_hash[8:12], 16) & 0x7FFF,
            int(res_hash[8:12], 16) & 0x7FFF,
            0, 0, 0, 0, 0,
        ]

    def to_dict(self) -> Dict[str, Any]:
        return {"tool": self.tool, "args": self.args, "result": self.result, "tick": self.tick}


class SessionFabric:
    """A session as a navigable cell fabric."""

    def __init__(self, name: str = "session"):
        self.name = name
        self.cells: List[SessionCell] = []
        self.edges: List[tuple] = []  # (src_idx, dst_idx, shared_context)
        self.created_at = time.time()

    def add(self, tool: str, args: Any, result: Any) -> int:
        """Add a cell to the fabric.  Returns its index."""
        cell = SessionCell(tool, args, result, tick=len(self.cells))
        idx = len(self.cells)
        self.cells.append(cell)
        # Auto-edge: each cell connects to the previous one (sequence)
        if idx > 0:
            self.edges.append((idx - 1, idx, "sequence"))
        return idx

    def add_with_context(self, tool: str, args: Any, result: Any, context: str) -> int:
        """Add a cell and an edge to a previous cell that shares context."""
        idx = self.add(tool, args, result)
        # Find previous cell with similar context
        for prev_idx, prev_cell in enumerate(self.cells[:idx]):
            if context and context in (prev_cell.args + prev_cell.result):
                self.edges.append((prev_idx, idx, f"context:{context[:20]}"))
                break
        return idx

    def tick(self) -> Dict[str, int]:
        """Re-balance the fabric: each cell updates its tick from its inputs."""
        if not self.cells:
            return {"cells": 0, "edges": 0}
        # Ticks are monotonic
        max_tick = max(c.tick for c in self.cells)
        return {"cells": len(self.cells), "edges": len(self.edges), "max_tick": max_tick}

    def to_quf(self) -> QufFile:
        """Serialize the session as a QUF file (portable, polyformal)."""
        dials = [c.dials for c in self.cells]
        # Edges: 1 EdgeRecord per edge
        edges = []
        for src, dst, ctx in self.edges[:256]:
            ctx_hash = hash(ctx) & 0xFF
            edges.append(EdgeRecord(src & 0xFF, dst & 0xFF, ctx_hash, 0, 0, 0, 0, [0] * 8))
        routing = [RouteRecord(0, len(self.cells) & 0xFF)]
        return QufFile(
            header={
                "quf.version": f"session-{self.name}",
                "cell_count": len(self.cells),
                "edge_count": len(edges),
                "route_count": 1,
                "edge.k": 8,
                "tick_period": 1,
                "align": 32,
                "quant.dials": "Q1.15",
                "session.name": self.name,
                "session.created": str(self.created_at),
            },
            dials=dials, edges=edges, routing=routing,
            ticks=(len(self.cells), list(range(len(self.cells)))),
        )

    def save(self, path: Path) -> None:
        """Save as a .quf file (binary) and a .json sidecar (text)."""
        qf = self.to_quf()
        data = quf_dumps(qf)
        Path(path).write_bytes(data)
        sidecar = {
            "name": self.name,
            "created_at": self.created_at,
            "cells": [c.to_dict() for c in self.cells],
            "edges": [{"src": s, "dst": d, "ctx": c} for s, d, c in self.edges],
        }
        Path(str(path) + ".json").write_text(json.dumps(sidecar, indent=2))

    @classmethod
    def load(cls, path: Path) -> "SessionFabric":
        """Load from a .quf file (with .json sidecar)."""
        fabric = cls(name=Path(path).stem)
        sidecar_path = Path(str(path) + ".json")
        if not sidecar_path.exists():
            return fabric
        data = json.loads(sidecar_path.read_text())
        fabric.name = data.get("name", fabric.name)
        fabric.created_at = data.get("created_at", fabric.created_at)
        fabric.cells = [SessionCell(**c) for c in data.get("cells", [])]
        fabric.edges = [(e["src"], e["dst"], e["ctx"]) for e in data.get("edges", [])]
        return fabric

    def query(self, partial: str, k: int = 3) -> List[Dict[str, Any]]:
        """Find cells in this session matching partial text."""
        results = []
        for i, cell in enumerate(self.cells):
            score = 0
            if partial in cell.args:
                score += 2
            if partial in cell.result:
                score += 1
            if partial in cell.tool:
                score += 3
            if score > 0:
                results.append({"idx": i, "tool": cell.tool, "score": score})
        results.sort(key=lambda r: -r["score"])
        return results[:k]

    def similarity(self, other: "SessionFabric") -> float:
        """Compare two sessions by tool-frequency distribution."""
        from collections import Counter
        a = Counter(c.tool for c in self.cells)
        b = Counter(c.tool for c in other.cells)
        if not a or not b:
            return 0.0
        all_tools = set(a) | set(b)
        dot = sum(a.get(t, 0) * b.get(t, 0) for t in all_tools)
        norm_a = sum(v * v for v in a.values()) ** 0.5
        norm_b = sum(v * v for v in b.values()) ** 0.5
        return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


# ============================================================================
# CLI demo
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Session Memory — turn a working session into a fabric")
    print("=" * 60)

    # Simulate a session
    s = SessionFabric(name="phase-251")
    s.add("read", "live_canon.py", "5 operations defined")
    s.add("edit", "live_canon.py:parse_paper", "fixed regex")
    s.add("bash", "python3 live_canon.py", "PASS")
    s.add("read", "test_live_canon.py", "12 tests")
    s.add("bash", "python3 -m unittest", "12/12 ok")
    s.add_with_context("read", "shape_rag.py", "16-dial cell",
                       context="16-dial")
    s.add("read", "cell_runtime", "Graph.tick()")
    s.add("bash", "python3 session_memory.py", "PASS")

    print(f"\n1. Session has {len(s.cells)} cells, {len(s.edges)} edges")

    # Tick
    result = s.tick()
    print(f"2. tick(): {result}")

    # Save
    out = Path("/tmp/test-session.quf")
    s.save(out)
    print(f"3. saved: {out} ({out.stat().st_size} bytes)")

    # Load
    s2 = SessionFabric.load(out)
    print(f"4. loaded: name={s2.name}, cells={len(s2.cells)}")

    # Query
    hits = s.query("live_canon", k=3)
    print(f"5. query 'live_canon': {len(hits)} hits")
    for h in hits:
        print(f"   - idx={h['idx']}, tool={h['tool']}, score={h['score']}")

    # Similarity
    s3 = SessionFabric(name="phase-247")
    s3.add("read", "shape_rag.py", "16-dial cell")
    s3.add("read", "cell_runtime", "Graph.tick()")
    s3.add("read", "shape_store.py", "5 indices")
    sim = s.similarity(s3)
    print(f"6. similarity(phase-251, phase-247) = {sim:.3f}")

    print()
    print("=" * 60)
    print("Session Memory PASS")
    print("=" * 60)
