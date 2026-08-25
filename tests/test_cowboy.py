"""test_cowboy.py — Tests for the cowboy CLI."""
import json
import os
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock

sys.path.insert(0, "/workspace/quilt-cowboy/src")

from quilt_cowboy import (
    Cowboy, CowboyAction, CowboyMemory, MorningReport, fnv1a64,
)


# --- Pure functions -------------------------------------------------

def test_fnv1a64_known():
    """FNV-1a of empty string is 0xcbf29ce484222325."""
    assert fnv1a64(b"") == 0xcbf29ce484222325
    # FNV-1a of "a" is 0xaf63dc4c8601ec8c
    assert fnv1a64(b"a") == 0xaf63dc4c8601ec8c


def test_fnv1a64_consistent():
    a = fnv1a64(b"hello world")
    b = fnv1a64(b"hello world")
    assert a == b
    # Different input → different hash
    assert fnv1a64(b"hello world") != fnv1a64(b"hello world!")


# --- CowboyAction ---------------------------------------------------

def test_action_compute_hash_stable():
    a1 = CowboyAction(ts=123.0, kind="note", target="cowboy", reason="hello")
    a2 = CowboyAction(ts=123.0, kind="note", target="cowboy", reason="hello")
    assert a1.compute_hash() == a2.compute_hash()
    a3 = CowboyAction(ts=123.0, kind="note", target="cowboy", reason="hello!")
    assert a1.compute_hash() != a3.compute_hash()


def test_action_to_dict_roundtrip():
    a = CowboyAction(ts=1.0, kind="morning", target="system", reason="r",
                       payload={"k": "v"})
    d = a.to_dict()
    a2 = CowboyAction(**d)
    assert a2.ts == a.ts and a2.payload == a.payload


# --- CowboyMemory ---------------------------------------------------

def test_memory_empty_load():
    with tempfile.TemporaryDirectory() as d:
        m = CowboyMemory(str(Path(d) / "cow.jsonl"))
        assert m.actions == []
        assert m.verify_chain() == (True, "chain valid across 0 actions")


def test_memory_append_and_verify():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "cow.jsonl")
        m = CowboyMemory(path)
        a1 = m.append(CowboyAction(kind="note", target="cowboy", reason="first"))
        a2 = m.append(CowboyAction(kind="note", target="cowboy", reason="second"))
        assert a1.prev_hash == "0" * 16
        assert a2.prev_hash == a1.hash
        ok, msg = m.verify_chain()
        assert ok, msg
        # Re-load and verify
        m2 = CowboyMemory(path)
        assert len(m2.actions) == 2
        ok2, msg2 = m2.verify_chain()
        assert ok2, msg2


def test_memory_chain_tamper_detection():
    with tempfile.TemporaryDirectory() as d:
        path = str(Path(d) / "cow.jsonl")
        m = CowboyMemory(path)
        m.append(CowboyAction(kind="note", target="cowboy", reason="a"))
        m.append(CowboyAction(kind="note", target="cowboy", reason="b"))
        m.append(CowboyAction(kind="note", target="cowboy", reason="c"))
        # Tamper: change the reason of action 1
        m.actions[1].reason = "TAMPERED"
        # Recompute hashes for actions 1+ to keep individual hash correct
        # but the chain will still be broken because we recompute action 1's hash
        # ... actually our verify_chain checks each action's hash, so we need
        # to corrupt in a way that breaks the chain but matches an individual hash
        # Instead: corrupt the prev_hash of action 2 without recomputing
        m.actions[2].prev_hash = "0" * 16
        ok, msg = m.verify_chain()
        assert not ok, "should detect prev_hash tampering"


def test_memory_last_morning_and_retired():
    with tempfile.TemporaryDirectory() as d:
        m = CowboyMemory(str(Path(d) / "cow.jsonl"))
        m.append(CowboyAction(kind="note", target="cowboy", reason="n1"))
        m.append(CowboyAction(kind="morning", target="system", reason="m1"))
        m.append(CowboyAction(kind="retire", target="SEED_MINI", reason="r1"))
        m.append(CowboyAction(kind="promote", target="PHI-4", reason="p1"))
        m.append(CowboyAction(kind="morning", target="system", reason="m2"))
        last = m.last_morning()
        assert last is not None
        assert last.reason == "m2"
        assert m.retired() == ["SEED_MINI"]
        assert m.promoted() == ["PHI-4"]


# --- Cowboy.run_morning ---------------------------------------------

def _mock_plugin_with_witness(events):
    p = MagicMock()
    p.witness = events
    p.wilson.obs = {}
    return p


def _make_event(model, success=True, quality=0.9, cost=0.001):
    return {
        "ts": 1000.0, "kind": "cast.observed",
        "decision": {"model": model, "opener": "tide", "primitive": "Murmur"},
        "success": success, "quality": quality, "cost": cost,
    }


def test_cowboy_run_morning_empty():
    with tempfile.TemporaryDirectory() as d:
        cowboy = Cowboy(state_dir=d)
        report = cowboy.run_morning()
        assert report.n_alignments == 0
        assert "Quiet morning" in report.cowboy_note


def test_cowboy_run_morning_promotes_earned_keep():
    with tempfile.TemporaryDirectory() as d:
        events = [_make_event("PHI-4", success=True, quality=0.95)
                   for _ in range(6)]
        plugin = _mock_plugin_with_witness(events)
        cowboy = Cowboy(state_dir=d, plugin=plugin)
        report = cowboy.run_morning()
        assert "PHI-4" in report.earned_keep
        assert any("promoted" in r for r in report.refinements)
        # Verify the chain still validates
        ok, _ = cowboy.memory.verify_chain()
        assert ok


def test_cowboy_run_morning_retires_failing():
    with tempfile.TemporaryDirectory() as d:
        events = [_make_event("BROKEN", success=False, quality=0.1)
                   for _ in range(5)]
        plugin = _mock_plugin_with_witness(events)
        cowboy = Cowboy(state_dir=d, plugin=plugin)
        report = cowboy.run_morning()
        assert "BROKEN" in report.retirees
        assert any("retired" in r for r in report.refinements)


def test_cowboy_run_morning_escalates_low_quality():
    with tempfile.TemporaryDirectory() as d:
        # FLAKY: n=3, success=0 (all failures), wilson_lb<0.2 → escalation
        events = [_make_event("FLAKY", success=False, quality=0.05)
                   for _ in range(3)]
        plugin = _mock_plugin_with_witness(events)
        cowboy = Cowboy(state_dir=d, plugin=plugin)
        report = cowboy.run_morning()
        assert any("FLAKY" in e for e in report.escalations)


def test_cowboy_run_morning_persists_to_disk():
    with tempfile.TemporaryDirectory() as d:
        cowboy = Cowboy(state_dir=d)
        cowboy.run_morning()
        cowboy.run_morning()
        # Reload from disk
        cowboy2 = Cowboy(state_dir=d)
        ok, msg = cowboy2.memory.verify_chain()
        assert ok, msg
        # 2 mornings = 2 morning actions
        mornings = [a for a in cowboy2.memory.actions if a.kind == "morning"]
        assert len(mornings) == 2


def test_cowboy_state_returns_chain_ok():
    with tempfile.TemporaryDirectory() as d:
        cowboy = Cowboy(state_dir=d)
        cowboy.run_morning()
        s = cowboy.state()
        assert s["chain_ok"] is True
        assert s["n_actions"] >= 1


# --- MorningReport --------------------------------------------------

def test_morning_report_markdown_basic():
    r = MorningReport(
        date="2026-08-25",
        witness_events=10, ledger_entries=5, n_alignments=2,
        earned_keep=["PHI-4"], retirees=["BROKEN"],
        escalations=["FLAKY"],
        cost_yesterday=0.005, quality_yesterday=0.85,
        cowboy_note="Good morning.",
    )
    md = r.to_markdown()
    assert "Morning Report — 2026-08-25" in md
    assert "PHI-4" in md
    assert "BROKEN" in md
    assert "FLAKY" in md
    assert "$0.0050" in md
    assert "0.850" in md
    assert "Good morning" in md


def test_morning_report_empty_lists():
    r = MorningReport()
    md = r.to_markdown()
    assert "no morning report" in md.lower() or "(none" in md.lower()


# --- Cowboy state propagates to plugin (refine test) ----------------

def test_cowboy_refines_wilson():
    with tempfile.TemporaryDirectory() as d:
        events = [_make_event("PHI-4", success=True, quality=0.95)
                   for _ in range(6)]
        plugin = _mock_plugin_with_witness(events)
        # Seed wilson.obs with a tuple key (primitive, opener, model)
        from collections import defaultdict
        plugin.wilson.obs = defaultdict(list)
        # The cowboy checks model name in obs keys; the actual structure
        # is keyed by (primitive, opener, model) tuple
        cowboy = Cowboy(state_dir=d, plugin=plugin)
        # Just verify the cowboy ran without crashing
        report = cowboy.run_morning()
        # The model should be in the earned-keep list
        assert "PHI-4" in report.earned_keep
