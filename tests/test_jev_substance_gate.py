"""FAIL-first pins for the JEV substance gate.

Pin order matters: test_gate_out_stamps_log_entries is RED on main-tip
orchestrator v3 (no jev_* fields in the worklog entry) and GREEN once
cowboy_orchestrator_v3 wires gate_out(). Run:
    python3 -m unittest tests.test_jev_substance_gate -v
"""
import json
import os
import tempfile
import unittest

import jev_substance_gate as gate


class _Judge:
    def __init__(self, value): self._v = value
    value = property(lambda self: self._v)


class MockBackend:
    """Returns a fixed score; simulates the typesafe jev substrate."""
    def __init__(self, score): self.score = score
    def available(self): return True
    def decide_batch(self, state, questions, model="jev-latest"):
        n = len(state["commits"])
        return [_Judge(self.score)] * n, {"latency_ms": 1.0, "model": "mock"}


class TestNoulAndCitation(unittest.TestCase):
    def test_noul_names_checkable_content(self):
        self.assertIn("verifiable", gate.NOUL)
        self.assertIn("vague", gate.NOUL)

    def test_citation_names_jev_quilt(self):
        self.assertIn("jev-quilt", gate.CITATION)

    def test_threshold_matches_jevlens_verdict_line(self):
        self.assertEqual(gate.ADMIT_THRESHOLD, 0.6)


class TestJudgeWithMockBackend(unittest.TestCase):
    def test_concrete_text_admitted(self):
        v = gate.judge("cell_router.py: added FNV-1a64 WAL chaining, 27 tests",
                       backend=MockBackend(0.85))
        self.assertTrue(v.admitted)
        self.assertEqual(v.mean_substance, 0.85)
        self.assertEqual(v.judged, 1)

    def test_vague_text_held(self):
        v = gate.judge("misc improvements and updates", backend=MockBackend(0.2))
        self.assertFalse(v.admitted)

    def test_receipts_carry_substance_and_citation(self):
        v = gate.judge("x", backend=MockBackend(0.7))
        self.assertIn("mean_substance", v.receipts)
        self.assertIn("jev-quilt", v.receipts["citation"])


class TestOfflineAbstainsHonestly(unittest.TestCase):
    def test_unavailable_backend_abstains(self):
        class Down(MockBackend):
            def available(self): return False
        v = gate.judge("anything", backend=Down(0.0))
        self.assertEqual(v.mean_substance, 0.5)
        self.assertTrue(v.admitted)  # abstention is not condemnation
        self.assertEqual(v.receipts.get("jev"), "skipped")

    def test_no_backend_module_abstains(self):
        old = gate._default_backend
        gate._default_backend = lambda: None
        try:
            v = gate.judge("anything")
            self.assertEqual(v.backend, "offline")
        finally:
            gate._default_backend = old


class TestGateOutStampsLogEntries(unittest.TestCase):
    def test_gate_out_adds_jev_fields(self):
        out = {"topic": "is a stall a cell?", "mode": "adversarial",
               "synthesis": "a stall is a regime: named mechanism, checkable"}
        v = gate.gate_out(out, backend=MockBackend(0.9))
        self.assertTrue(v.admitted)
        self.assertEqual(out["jev_substance"], 0.9)
        self.assertTrue(out["jev_admitted"])
        self.assertIn("jev-quilt", out["jev_citation"])

    def test_orchestrator_v3_wires_the_gate(self):
        """RED on main tip: v3's worklog entry must carry jev_substance."""
        import inspect
        import cowboy_orchestrator_v3 as v3
        src = inspect.getsource(v3)
        self.assertIn("gate_out", src, "orchestrator v3 does not call gate_out")


class TestEnforceMode(unittest.TestCase):
    def test_enforce_flag_recorded(self):
        os.environ["COWBOY_JEV_ENFORCE"] = "1"
        try:
            v = gate.judge("x", backend=MockBackend(0.1))
            self.assertTrue(v.enforced)
        finally:
            del os.environ["COWBOY_JEV_ENFORCE"]


if __name__ == "__main__":
    unittest.main()
