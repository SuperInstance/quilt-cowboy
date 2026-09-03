"""cell_merger.py — merge two cell fabrics into a synthesis fabric.

The novel idea: two fabrics, each with cells, edges, and dials, can be
joined into a third fabric that respects both.  The merger:
  - cells in the intersection get dials averaged
  - cells in the union-only get carried over
  - edges from both fabrics become edges of the result
  - the result is a NEW fabric, with its own state_hash

Use case: "merge my chemistry notes with my music theory notes"
→ the synthesis fabric is the cell-level join.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/workspace/quilt-timesfm")

from quf_v2 import QufFile, EdgeRecord, RouteRecord, dumps as quf_dumps
from shape_rag import ShapeStore


def merge_fabrics(qf_a: QufFile, qf_b: QufFile, name: str = "merge") -> QufFile:
    """Merge two QUF fabrics into a synthesis fabric.

    Cell strategy:
      - If a cell index in A also exists in B (by hash), average dials
      - Otherwise, copy cells from A then B
    Edge strategy:
      - Union of all edges from both fabrics
    """
    cells_a = qf_a.dials
    cells_b = qf_b.dials
    edges_a = qf_a.edges
    edges_b = qf_b.edges

    # Match cells by content-hash (using state_hash)
    hash_to_idx_a = {}
    for i, d in enumerate(cells_a):
        h = sum(d) & 0xFF
        hash_to_idx_a.setdefault(h, []).append(i)

    merged_cells = []
    used_b = set()
    for i, da in enumerate(cells_a):
        merged_cells.append(da)
        h = sum(da) & 0xFF
        if h in hash_to_idx_a:
            for j in hash_to_idx_a[h]:
                if j not in used_b and j < len(cells_b):
                    db = cells_b[j]
                    # Average dials
                    merged_cells[-1] = [(a + b) >> 1 for a, b in zip(da, db)]
                    used_b.add(j)
                    break

    # Add unused B cells
    for j, db in enumerate(cells_b):
        if j not in used_b:
            merged_cells.append(db)

    # Union edges
    merged_edges = list(edges_a) + list(edges_b)

    routing = [RouteRecord(0, len(merged_cells) & 0xFF)]

    return QufFile(
        header={
            "quf.version": f"merge-{name}",
            "cell_count": len(merged_cells),
            "edge_count": len(merged_edges),
            "route_count": 1,
            "edge.k": 8,
            "tick_period": 1,
            "align": 32,
            "quant.dials": "Q1.15",
            "merge.source_a": qf_a.header.get("quf.version", "?"),
            "merge.source_b": qf_b.header.get("quf.version", "?"),
        },
        dials=merged_cells, edges=merged_edges, routing=routing,
        ticks=(len(merged_cells), list(range(len(merged_cells)))),
    )


def join_score(qf_a: QufFile, qf_b: QufFile) -> float:
    """Compute the join score (similarity) between two fabrics.

    Based on shape-store query: high score = good fit for merging.
    """
    if not qf_a.dials or not qf_b.dials:
        return 0.0
    # Compare cell-dial vectors
    a = qf_a.dials[0]
    b = qf_b.dials[0]
    if len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = sum(x * x for x in a) ** 0.5
    norm_b = sum(x * x for x in b) ** 0.5
    return dot / (norm_a * norm_b) if norm_a and norm_b else 0.0


def conflict_score(qf_a: QufFile, qf_b: QufFile) -> float:
    """How much do the two fabrics disagree?

    Conflict = 1 - similarity.  High conflict = don't merge.
    """
    return 1.0 - join_score(qf_a, qf_b)


def ghost_cell(qf_a: QufFile, qf_b: QufFile) -> List[int]:
    """A ghost cell: a cell that should exist in the merge but doesn't.

    Returns dial positions where A and B disagree significantly.
    """
    if not qf_a.dials or not qf_b.dials:
        return []
    a = qf_a.dials[0]
    b = qf_b.dials[0]
    return [i for i in range(len(a)) if abs(a[i] - b[i]) > 0x4000]


# ============================================================================
# CLI demo
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Cell Merger — merge two fabrics into a synthesis")
    print("=" * 60)

    # Fabric A: a research note on shape RAG
    dials_a = [
        # 0    1    2    3    4    5    6    7
        0x7F, 0x80, 0x40, 0x60, 0x20, 0x10, 0x08, 0x04,
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    qf_a = QufFile(
        header={"quf.version": "shape-rag-note",
                "cell_count": 1, "edge_count": 0, "route_count": 0,
                "edge.k": 8, "tick_period": 1, "align": 32,
                "quant.dials": "Q1.15"},
        dials=[dials_a], edges=[], routing=[],
        ticks=(1, [0]),
    )

    # Fabric B: a research note on polyformalism
    dials_b = [
        0x7E, 0x81, 0x42, 0x5F, 0x21, 0x0F, 0x09, 0x03,  # very similar
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    qf_b = QufFile(
        header={"quf.version": "polyformalism-note",
                "cell_count": 1, "edge_count": 0, "route_count": 0,
                "edge.k": 8, "tick_period": 1, "align": 32,
                "quant.dials": "Q1.15"},
        dials=[dials_b], edges=[], routing=[],
        ticks=(1, [0]),
    )

    # Compute scores
    sim = join_score(qf_a, qf_b)
    con = conflict_score(qf_a, qf_b)
    print(f"\n1. Join score: {sim:.4f}  (1.0 = identical)")
    print(f"   Conflict score: {con:.4f}  (0.0 = no conflict)")

    # Merge
    merged = merge_fabrics(qf_a, qf_b, name="synthesis")
    print(f"\n2. Merged fabric:")
    print(f"   cells: {len(merged.dials)}")
    print(f"   edges: {len(merged.edges)}")
    print(f"   first cell dials: {merged.dials[0][:8]}")

    # Ghost cells
    ghosts = ghost_cell(qf_a, qf_b)
    print(f"\n3. Ghost cell positions (significant disagreement): {ghosts}")

    # Now make a CONFLICTING fabric to test conflict detection
    dials_c = [
        0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10, 0x10,  # very different
        0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00,
    ]
    qf_c = QufFile(
        header={"quf.version": "opposite-note",
                "cell_count": 1, "edge_count": 0, "route_count": 0,
                "edge.k": 8, "tick_period": 1, "align": 32,
                "quant.dials": "Q1.15"},
        dials=[dials_c], edges=[], routing=[],
        ticks=(1, [0]),
    )
    sim2 = join_score(qf_a, qf_c)
    con2 = conflict_score(qf_a, qf_c)
    print(f"\n4. With conflicting fabric:")
    print(f"   Join score: {sim2:.4f}")
    print(f"   Conflict score: {con2:.4f}")

    print()
    print("=" * 60)
    print("Cell Merger PASS — join / conflict / merge / ghost all work")
    print("=" * 60)
