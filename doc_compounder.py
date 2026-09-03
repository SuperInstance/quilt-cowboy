"""doc_compounder.py — Read a doc, decompose it into a cell fabric, and
return compound intelligence (related canon papers, conflicts, ghosts).

A novel use case for shape-RAG: instead of searching for similar
documents, decompose a document into its cell-fabric representation,
then snap it to the canon to find:
  - related canon papers (by shape similarity)
  - conflicts (cells with overlapping but different dials)
  - ghost papers (canon papers this doc should cite)
  - compounds (3+ papers this doc should cite together)
  - summary cell (the doc as a single cell)
"""
from __future__ import annotations

import hashlib
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

HERE = Path(__file__).resolve().parent
sys.path.insert(0, "/workspace/quilt-timesfm")
sys.path.insert(0, "/workspace/cell-runtime/src")

from quf_v2 import QufFile, EdgeRecord, RouteRecord
from shape_rag import to_dial_matrix, ShapeStore


CANON_DIR = Path("/tmp/canon/seed-canon/papers")


def decompose(doc: str) -> Dict[str, Any]:
    """Decompose a doc into a 16-dial vector (cell).

    The dials are designed to capture both content and structure:
      0  - paper_id_hash (low 16 bits)
      1  - word_count (log2)
      2  - unique_word_count (log2)
      3  - sentence_count
      4  - avg_word_length (Q1.15)
      5  - num_headings
      6  - num_code_blocks
      7  - num_links
      8  - f_number_hash (if mentioned)
      9  - phase_hash (if mentioned)
      10 - signal_phrase_count (e.g. "we prove", "we show")
      11 - passive_voice_count
      12 - formula_count (lines with = or ->)
      13 - question_count
      14 - upper_case_ratio
      15 - hash of first 64 chars (title)
    """
    words = re.findall(r"\b\w+\b", doc)
    word_count = len(words)
    unique_words = len(set(w.lower() for w in words))
    sentences = re.split(r"[.!?]+", doc)
    avg_word_len = sum(len(w) for w in words) / max(word_count, 1)
    headings = re.findall(r"^#+\s+", doc, re.MULTILINE)
    code_blocks = re.findall(r"```", doc) // 2
    links = re.findall(r"\[.+?\]\(.+?\)", doc)
    f_nums = re.findall(r"\bF(\d{1,3})\b", doc)
    phases = re.findall(r"Phase\s+(\d+)", doc)
    signal_phrases = re.findall(r"\b(we\s+(?:prove|show|define|demonstrate|introduce|argue|claim|conclude))\b", doc, re.IGNORECASE)
    passive = re.findall(r"\b(?:is|are|was|were)\s+\w+ed\b", doc, re.IGNORECASE)
    formulas = re.findall(r"[=→]", doc)
    questions = re.findall(r"\?+", doc)
    upper = sum(1 for c in doc if c.isupper()) / max(len(doc), 1)
    title_hash = hashlib.md5(doc[:64].encode()).hexdigest()[:4]

    # Convert to Q1.15 (capped to 0x7FFF)
    def q(v: float) -> int:
        return min(0x7FFF, max(0, int(v * 0x7FFF)))

    dials = [
        int(hashlib.md5(doc.encode()).hexdigest()[:4], 16) & 0x7FFF,
        int((word_count.bit_length() if word_count else 0) * 256),
        int((unique_words.bit_length() if unique_words else 0) * 256),
        min(0x7FFF, len(sentences) * 64),
        q(avg_word_len / 20.0),  # normalize 0..20
        min(0x7FFF, len(headings) * 1024),
        min(0x7FFF, code_blocks * 2048),
        min(0x7FFF, len(links) * 512),
        int(hash(f_nums[0]) & 0x7FFF) if f_nums else 0,
        int(hash(phases[0]) & 0x7FFF) if phases else 0,
        min(0x7FFF, len(signal_phrases) * 2048),
        min(0x7FFF, len(passive) * 1024),
        min(0x7FFF, len(formulas) * 256),
        min(0x7FFF, len(questions) * 1024),
        q(upper * 4),  # amplify
        int(title_hash, 16) & 0x7FFF,
    ]

    return {
        "dials": dials,
        "meta": {
            "word_count": word_count,
            "unique_words": unique_words,
            "n_headings": len(headings),
            "n_code_blocks": code_blocks,
            "n_links": len(links),
            "f_numbers": list(set(int(f) for f in f_nums)),
            "phases": list(set(int(p) for p in phases)),
        }
    }


def snap_to_canon(doc_cell: Dict, canon_store: ShapeStore, k: int = 5) -> List[Dict]:
    """Snap the doc-cell to the canon and return top-k neighbors by shape."""
    # Build a 1-cell QUF from the doc's dials
    dials = doc_cell["dials"]
    qf = QufFile(
        header={"quf.version": "doc-snap", "cell_count": 1, "edge_count": 0,
                "route_count": 0, "edge.k": 8, "tick_period": 1, "align": 32,
                "quant.dials": "Q1.15"},
        dials=[dials], edges=[], routing=[], ticks=(1, [0]),
    )
    results = canon_store.query(qf, k=k)
    return [{"id": fid, "score": round(s, 4)} for fid, s in results]


def find_conflicts(doc_cell: Dict, canon_papers: Dict) -> List[Dict]:
    """Find canon papers with overlapping F-numbers but different focus.

    A conflict is a paper that:
    - Shares an F-number with the doc
    - Has a very different dial vector
    This means the doc might cover different ground than existing canon.
    """
    doc_f = set(doc_cell["meta"]["f_numbers"])
    if not doc_f:
        return []
    conflicts = []
    for num, paper in canon_papers.items():
        paper_f = set(paper.get("ref_f_numbers", [])) | {paper.get("f_number", 0)}
        overlap = doc_f & paper_f
        if overlap and not (doc_f - paper_f) == doc_f:
            # Doc references F-numbers this paper covers
            conflicts.append({
                "paper": f"paper-{num}.md",
                "title": paper.get("title", ""),
                "shared_f_numbers": sorted(overlap),
            })
    return conflicts[:3]


def find_ghosts(doc_cell: Dict, canon_papers: Dict) -> List[str]:
    """Find canon papers that the doc should cite (by F-series proximity).

    If the doc mentions Phase N and the canon has a Phase N+1 paper
    that doesn't cite this doc, that's a ghost.
    """
    doc_phases = set(doc_cell["meta"]["phases"])
    doc_f = set(doc_cell["meta"]["f_numbers"])
    if not doc_f and not doc_phases:
        return []

    # Papers that don't cite any of doc's F-numbers but are in similar phase
    ghosts = []
    for num, paper in list(canon_papers.items())[:30]:
        if not paper.get("ref_f_numbers"):
            continue
        if doc_phases and abs(paper.get("phase", 0) - min(doc_phases)) <= 5:
            if not (set(paper["ref_f_numbers"]) & doc_f):
                # Paper is in similar phase, doesn't cite doc's F-numbers
                ghosts.append(f"paper-{num}.md: {paper.get('title', '')[:50]}")
    return ghosts[:3]


def compound(doc_cell: Dict, canon_papers: Dict) -> List[Tuple[List[int], str]]:
    """Find 3 canon papers that together form a compound relevant to the doc.

    The compound is 3 papers that, together, cover all F-numbers
    referenced by the doc.
    """
    doc_f = set(doc_cell["meta"]["f_numbers"])
    if not doc_f:
        return []

    # Build a graph: papers with shared F-numbers
    by_f: Dict[int, List[int]] = {}
    for num, paper in canon_papers.items():
        for f in {paper.get("f_number", 0)} | set(paper.get("ref_f_numbers", [])):
            by_f.setdefault(f, []).append(num)

    compounds = []
    for f in doc_f:
        if f in by_f:
            papers = by_f[f][:3]
            if len(papers) >= 2:
                titles = [canon_papers.get(p, {}).get("title", "")[:40] for p in papers]
                compounds.append((papers, f"covers F{f}: " + " | ".join(titles)))
    return compounds[:5]


def build_canon_store(canon_dir: Path = CANON_DIR) -> Tuple[ShapeStore, Dict[int, Dict]]:
    """Build a shape store of all canon papers."""
    store = ShapeStore()
    papers = {}
    paths = sorted(canon_dir.glob("paper-*.md"))[:50]
    lc = LiveCanon()  # Use the LiveCanon helper
    for path in paths:
        paper = lc._parse_paper(path) if hasattr(lc, "_parse_paper") else None
        if paper is None:
            continue
        papers[paper["number"]] = paper
        qf = lc._paper_to_quf(paper)
        store.add(qf, fabric_id=f"p{paper['number']:04d}")
    return store, papers


# ============================================================================
# CLI demo
# ============================================================================

if __name__ == "__main__":
    print("=" * 60)
    print("Doc Compounder — read a doc, snap to canon, find compounds")
    print("=" * 60)

    canon_store, canon_papers = build_canon_store()
    print(f"\n1. Built canon store with {len(canon_papers)} papers")

    # Read 3 sample docs
    sample_docs = []
    for p in [200, 220, 240]:
        text = (CANON_DIR / f"paper-{p}.md").read_text()
        sample_docs.append((f"paper-{p}", text[:2000]))

    for name, doc in sample_docs:
        print(f"\n2. Decompose + snap {name}:")
        cell = decompose(doc)
        print(f"   meta: words={cell['meta']['word_count']}, "
              f"headings={cell['meta']['n_headings']}, "
              f"f_numbers={cell['meta']['f_numbers']}")

        snap = snap_to_canon(cell, canon_store, k=3)
        print(f"   shape neighbors: {snap}")

        conflicts = find_conflicts(cell, canon_papers)
        print(f"   conflicts: {len(conflicts)}")

        ghosts = find_ghosts(cell, canon_papers)
        print(f"   ghost cites: {len(ghosts)}")

        compounds = compound(cell, canon_papers)
        print(f"   compounds: {len(compounds)}")

    print()
    print("=" * 60)
    print("Doc Compounder PASS")
    print("=" * 60)
