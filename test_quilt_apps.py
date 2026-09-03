"""test_quilt_apps.py — Tests for the 4 novel Quilt applications."""
import sys
import unittest
import json
import tempfile
from pathlib import Path

sys.path.insert(0, "/workspace/quilt-timesfm")
sys.path.insert(0, "/workspace/cell-runtime/src")
sys.path.insert(0, "/workspace/_scouts")

from live_canon import LiveCanon, parse_paper, paper_to_quf, CANON_DIR
from session_memory import SessionFabric, SessionCell
from cell_merger import merge_fabrics, join_score, conflict_score, ghost_cell
from quf_v2 import QufFile, EdgeRecord, RouteRecord


class TestLiveCanon(unittest.TestCase):
    def setUp(self):
        self.canon = LiveCanon()
        if CANON_DIR.exists():
            self.canon.load(max_papers=50)

    def test_loads_papers(self):
        if not CANON_DIR.exists():
            self.skipTest("canon dir not found")
        self.assertGreater(len(self.canon.papers), 0)

    def test_navigate_works(self):
        if 425 not in self.canon.papers:
            self.skipTest("paper-425 not loaded")
        path = self.canon.navigate(425, depth=1)
        self.assertGreater(len(path), 0)
        self.assertEqual(path[0]["paper"]["number"], 425)

    def test_lineage_traces_F_series(self):
        lineage = self.canon.lineage(115)
        for p in lineage:
            self.assertIn(115, p["ref_f_numbers"])

    def test_ghost_finds_neighbors(self):
        if 425 not in self.canon.papers:
            self.skipTest("paper-425 not loaded")
        ghost = self.canon.ghost(425, k_neighbors=3)
        self.assertGreater(len(ghost["neighbors"]), 0)
        # F115's neighbors should be in the polyformalism family
        # (p0426, p0427, p0428, p0429 — F116, F117, F118, F119)
        valid = {"p0426", "p0427", "p0428", "p0429"}
        top_neighbor = ghost["neighbors"][0]["id"]
        self.assertIn(top_neighbor, valid,
            f"top neighbor {top_neighbor} not in polyformalism family")

    def test_confluence_produces_ghost(self):
        sample = [n for n in list(self.canon.papers.keys())[:3]]
        conf = self.canon.confluence(sample)
        self.assertIn("ghost_paper", conf)

    def test_tick_runs(self):
        result = self.canon.tick()
        self.assertGreater(result["ticked_cells"], 0)


class TestSessionMemory(unittest.TestCase):
    def test_add_creates_cell(self):
        s = SessionFabric()
        idx = s.add("read", "test.txt", "content")
        self.assertEqual(idx, 0)
        self.assertEqual(len(s.cells), 1)
        self.assertEqual(len(s.edges), 0)  # first cell, no auto-edge

    def test_add_two_creates_edge(self):
        s = SessionFabric()
        s.add("read", "a", "x")
        s.add("read", "b", "y")
        self.assertEqual(len(s.cells), 2)
        self.assertEqual(len(s.edges), 1)  # sequence edge
        self.assertEqual(s.edges[0], (0, 1, "sequence"))

    def test_add_with_context(self):
        s = SessionFabric()
        s.add("read", "shape_rag.py", "16-dial cell")
        s.add_with_context("read", "shape_store.py", "5 indices", context="16-dial")
        # Should have 1 sequence + 1 context edge
        self.assertEqual(len(s.edges), 2)

    def test_save_load_roundtrip(self):
        s = SessionFabric(name="test")
        s.add("read", "a", "x")
        s.add("read", "b", "y")
        s.add("bash", "echo", "ok")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "test.quf"
            s.save(path)
            loaded = SessionFabric.load(path)
            self.assertEqual(loaded.name, "test")
            self.assertEqual(len(loaded.cells), 3)
            self.assertEqual(len(loaded.edges), 2)

    def test_query_finds_matches(self):
        s = SessionFabric()
        s.add("read", "live_canon.py", "5 operations")
        s.add("bash", "python3", "PASS")
        s.add("read", "test_live_canon", "12 tests")

        results = s.query("live_canon", k=3)
        self.assertGreater(len(results), 0)
        # First result should mention live_canon
        for r in results:
            self.assertIn("live_canon", r["tool"] + s.cells[r["idx"]].args)

    def test_similarity(self):
        s1 = SessionFabric()
        s1.add("read", "a", "x")
        s1.add("bash", "b", "y")
        s2 = SessionFabric()
        s2.add("read", "c", "z")
        s2.add("bash", "d", "w")
        sim = s1.similarity(s2)
        self.assertGreater(sim, 0.5)  # same tool distribution

        s3 = SessionFabric()
        s3.add("write", "totally different", "diff")
        sim2 = s1.similarity(s3)
        self.assertLess(sim2, sim)

    def test_to_quf_serializes(self):
        s = SessionFabric(name="test")
        s.add("read", "a", "x")
        qf = s.to_quf()
        self.assertEqual(qf.header["cell_count"], 1)
        self.assertEqual(len(qf.dials), 1)
        self.assertEqual(len(qf.dials[0]), 16)


class TestCellMerger(unittest.TestCase):
    def _make_qf(self, dials, name="test"):
        return QufFile(
            header={"quf.version": name,
                    "cell_count": 1, "edge_count": 0, "route_count": 0,
                    "edge.k": 8, "tick_period": 1, "align": 32,
                    "quant.dials": "Q1.15"},
            dials=[dials], edges=[], routing=[],
            ticks=(1, [0]),
        )

    def test_join_score_identical(self):
        dials = [0x40] * 16
        qf_a = self._make_qf(dials, "a")
        qf_b = self._make_qf(dials, "b")
        sim = join_score(qf_a, qf_b)
        self.assertGreater(sim, 0.99)

    def test_conflict_score_orthogonal(self):
        dials_a = [0x80] + [0x00] * 15
        dials_b = [0x00] * 16
        # Make b have one big value at a different position
        dials_b = [0x00, 0x80] + [0x00] * 14
        qf_a = self._make_qf(dials_a, "a")
        qf_b = self._make_qf(dials_b, "b")
        sim = join_score(qf_a, qf_b)
        self.assertLess(sim, 0.5)
        self.assertGreater(conflict_score(qf_a, qf_b), 0.5)

    def test_merge_creates_synthesis(self):
        dials_a = [0x40] * 16
        dials_b = [0x60] * 16
        qf_a = self._make_qf(dials_a, "a")
        qf_b = self._make_qf(dials_b, "b")
        merged = merge_fabrics(qf_a, qf_b, name="synth")
        self.assertGreater(len(merged.dials), 0)
        # First cell should be averaged
        # (0x40 + 0x60) // 2 = 0x50
        self.assertEqual(merged.dials[0][0], 0x50)

    def test_ghost_cell_detects_disagreements(self):
        dials_a = [0x10] * 16
        dials_b = [0x70] * 16
        qf_a = self._make_qf(dials_a, "a")
        qf_b = self._make_qf(dials_b, "b")
        ghosts = ghost_cell(qf_a, qf_b)
        # The diff is 0x60 = 96, threshold is 0x4000 = 16384
        # So actually NO ghosts at this threshold — that's correct
        # Use a stronger disagreement:
        dials_a2 = [0x10] * 16
        dials_b2 = [0x7000] * 16
        qf_a2 = self._make_qf(dials_a2, "a2")
        qf_b2 = self._make_qf(dials_b2, "b2")
        ghosts2 = ghost_cell(qf_a2, qf_b2)
        self.assertEqual(len(ghosts2), 16)


class TestIntegration(unittest.TestCase):
    """Integration: live_canon + session_memory + cell_merger"""

    def test_session_to_canon_similarity(self):
        # Build a session that does live_canon stuff
        s = SessionFabric()
        s.add("read", "live_canon.py", "5 operations")
        s.add("bash", "python3 live_canon.py", "PASS")
        s.add("read", "shape_rag.py", "16-dial cell")

        # The session's first cell should be a Q1.15 dial-vector
        cell = s.cells[0]
        self.assertEqual(len(cell.dials), 16)
        # All dials are 0..0x7FFF
        for d in cell.dials:
            self.assertGreaterEqual(d, 0)
            self.assertLessEqual(d, 0x7FFF)

    def test_merger_with_canonic_papers(self):
        if not CANON_DIR.exists():
            self.skipTest("canon dir not found")
        # Use two actual canon papers as fabrics
        paths = sorted(CANON_DIR.glob("paper-*.md"))[:2]
        if len(paths) < 2:
            self.skipTest("not enough papers")

        p_a = parse_paper(paths[0])
        p_b = parse_paper(paths[1])
        if p_a is None or p_b is None:
            self.skipTest("could not parse papers")

        qf_a = paper_to_quf(p_a)
        qf_b = paper_to_quf(p_b)
        merged = merge_fabrics(qf_a, qf_b, name="canon-merge")
        self.assertGreater(len(merged.dials), 0)


if __name__ == "__main__":
    unittest.main(verbosity=2)
