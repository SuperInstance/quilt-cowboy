"""JEV substance gate — jev-quilt's live judgment on every generated paper.

The cowboy's admission proxy has always been length: a paper over 300 chars
enters the canon. RD_QUILT_3_0.md admits it — "the current length-as-
concreteness proxy is a stand-in." This module replaces the stand-in with
the fleet's substance noul, sourced from SuperInstance/jev-quilt:

    Does this text describe concrete, verifiable engineering content (named
    file, function, test, PR, artifact, or — for a cowboy paper — a named
    cell, mechanism, gold term, or checkable claim), as opposed to vague
    activity no one could check?

Protocol: the noul and the 0.6 admit threshold are jev-quilt's (the fleet's
JEV doctrine home); the substrate is any duck-typed backend exposing
available() + decide_batch(state, questions) — jev_quilt's TypeSafeBackend
satisfies it directly. Offline backends abstain with a labeled receipt and
the orchestrator keeps shipping (abstention is not condemnation); set
COWBOY_JEV_ENFORCE=1 to hard-hold papers the gate refuses.
"""
from __future__ import annotations

import os
import sys
from dataclasses import dataclass, field
from typing import Any, List, Optional, Protocol

NOUL = (
    "Does this text describe concrete, verifiable content (a named file, "
    "function, test, PR, artifact — or for a cowboy paper, a named cell, "
    "mechanism, gold term, or checkable claim), as opposed to vague activity "
    "that no one could check?"
)
# admit threshold from jev-quilt's JevLens verdict line (mean >= 0.6 reads
# VERIFIABLE). Keep in sync with SuperInstance/jev-quilt.
ADMIT_THRESHOLD = 0.6
CITATION = "SuperInstance/jev-quilt (substance noul + threshold); substrate: typesafe jev backend"


class SubstanceBackend(Protocol):
    def available(self) -> bool: ...
    def decide_batch(self, state: dict, questions: list[dict],
                     model: str = "jev-latest") -> tuple[list, dict]: ...


@dataclass
class GateVerdict:
    admitted: bool
    mean_substance: float
    threshold: float
    judged: int
    backend: str
    enforced: bool = False
    receipts: dict = field(default_factory=dict)


def _default_backend() -> Optional[SubstanceBackend]:
    """jev_quilt's TypeSafeBackend if reachable: installed package first,
    then a JEV_QUILT_PATH checkout (fleet convention). None otherwise."""
    try:
        from jev_quilt.typesafe_client import TypeSafeBackend  # type: ignore
        return TypeSafeBackend()
    except Exception:
        pass
    checkout = os.environ.get("JEV_QUILT_PATH")
    if checkout:
        try:
            sys_path_inserted = checkout not in sys.path
            if sys_path_inserted:
                sys.path.insert(0, checkout)
            from jev_quilt.typesafe_client import TypeSafeBackend  # type: ignore
            return TypeSafeBackend()
        except Exception:
            return None
    return None


def judge(text: str, backend: Optional[SubstanceBackend] = None,
          sample_chars: int = 4000) -> GateVerdict:
    """Judge one paper's substance. Abstains honestly when no backend."""
    backend = backend if backend is not None else _default_backend()
    enforced = os.environ.get("COWBOY_JEV_ENFORCE") == "1"
    if backend is None or not backend.available():
        # abstention is not condemnation: neutral 0.5, admit, label it
        return GateVerdict(admitted=True, mean_substance=0.5,
                           threshold=ADMIT_THRESHOLD, judged=0,
                           backend="offline", enforced=enforced,
                           receipts={"jev": "skipped", "citation": CITATION})
    sample = text[:sample_chars]
    state = {"commits": [{"subject": sample}]}  # noul-shaped state, text-as-claim
    questions = [{"name": "substance", "type": "noul", "instructions": NOUL}]
    judgments, meta = backend.decide_batch(state, questions)
    scores = [float(j.value) for j in judgments]
    mean = sum(scores) / len(scores) if scores else 0.5
    admitted = mean >= ADMIT_THRESHOLD
    return GateVerdict(
        admitted=admitted, mean_substance=round(mean, 4),
        threshold=ADMIT_THRESHOLD, judged=len(scores),
        backend=backend.__class__.__name__, enforced=enforced,
        receipts={"judged": len(scores), "mean_substance": round(mean, 4),
                  "latency_ms": meta.get("latency_ms"), "citation": CITATION,
                  "model": meta.get("model", "jev-latest")})


def gate_out(out: dict, backend: Optional[SubstanceBackend] = None) -> GateVerdict:
    """Gate one orchestrator output dict; returns the verdict with receipts
    and stamps the log fields. Meter mode by default: a refused paper is
    flagged (jev_admitted=False) but the worklog entry is still written;
    COWBOY_JEV_ENFORCE=1 upgrades the flag to a hard hold."""
    verdict = judge(out.get("synthesis") or "", backend=backend)
    out["jev_substance"] = verdict.mean_substance
    out["jev_admitted"] = verdict.admitted
    out["jev_backend"] = verdict.backend
    out["jev_citation"] = CITATION
    return verdict


def audit_worklog(log_path: str, backend: Optional[SubstanceBackend] = None) -> List[dict]:
    """Re-judge past worklog entries (they carry only metadata, not paper
    text — judge the topic+mode receipt as the claim). Returns one row per
    entry: {timestamp, topic, mean_substance, admitted}."""
    import json
    rows: List[dict] = []
    with open(log_path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            e = json.loads(line)
            claim = f"{e.get('mode','?')} paper on topic {e.get('topic','?')}"
            v = judge(claim, backend=backend)
            rows.append({"timestamp": e.get("timestamp"), "topic": e.get("topic"),
                         "mean_substance": v.mean_substance, "admitted": v.admitted})
    return rows
