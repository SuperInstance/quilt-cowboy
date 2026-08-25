"""cowboy.py — The Cowboy.

The cowboy is the human (or the agent acting as human) who keeps the
system in shape. The cowboy is not the AI. The cowboy is the rider.

The cowboy's job is to read what happened, decide what to do, and
write the morning report.

This module implements the cowboy as a CLI:
- `cowboy run` — runs the morning (read witness, nightcycle, refine, report)
- `cowboy report` — prints the morning report
- `cowboy retire` — marks a failing alignment for retirement
- `cowboy promote` — pins an earned-keep alignment
- `cowboy state` — shows the cowboy's current state

The cowboy has memory. The cowboy remembers what it learned yesterday
so the morning can compare today to yesterday. The cowboy's memory
is JSONL, append-only, hash-chained (FNV-1a64).
"""
from __future__ import annotations
import argparse
import json
import os
import re
import sys
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Reuse FNV-1a64 from bridge (same hash as saddle)
FNV_OFFSET = 0xcbf29ce484222325
FNV_PRIME = 0x100000001b3
FNV_MASK = 0xffffffffffffffff


def fnv1a64(data: bytes) -> int:
    """FNV-1a 64-bit hash, matches saddle's TypeScript implementation."""
    h = FNV_OFFSET
    for b in data:
        h ^= b
        h = (h * FNV_PRIME) & FNV_MASK
    return h


# ---------------------------------------------------------------------------
# Cowboy memory — append-only, hash-chained
# ---------------------------------------------------------------------------

@dataclass
class CowboyAction:
    """A single cowboy action (one per morning, one per retire, one per promote)."""
    ts: float = 0.0
    kind: str = ""           # "morning" | "retire" | "promote" | "note"
    target: str = ""         # alignmentId or "system"
    reason: str = ""
    payload: Dict[str, Any] = field(default_factory=dict)
    prev_hash: str = ""      # hex
    hash: str = ""           # hex

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    def compute_hash(self) -> str:
        body = json.dumps({k: v for k, v in asdict(self).items()
                            if k not in ("hash",)}, sort_keys=True, default=str)
        return f"{fnv1a64(body.encode()):016x}"


class CowboyMemory:
    """Append-only cowboy memory, hash-chained, JSONL on disk."""

    def __init__(self, path: str):
        self.path = Path(path)
        self.actions: List[CowboyAction] = []
        self._load()

    def _load(self):
        if not self.path.exists():
            return
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                d = json.loads(line)
                self.actions.append(CowboyAction(**d))

    def append(self, action: CowboyAction) -> CowboyAction:
        """Append a new action, computing its hash from the previous."""
        if not self.actions:
            action.prev_hash = "0" * 16
        else:
            action.prev_hash = self.actions[-1].hash
        if not action.ts:
            action.ts = time.time()
        action.hash = action.compute_hash()
        self.actions.append(action)
        # Atomic write: write to temp, then rename
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        with open(tmp, "w") as f:
            for a in self.actions:
                f.write(json.dumps(a.to_dict(), default=str) + "\n")
        tmp.rename(self.path)
        return action

    def verify_chain(self) -> Tuple[bool, str]:
        """Verify the hash chain. Returns (ok, message)."""
        prev_hash = "0" * 16
        for a in self.actions:
            body = json.dumps({k: v for k, v in asdict(a).items()
                                if k not in ("hash",)}, sort_keys=True, default=str)
            expected = f"{fnv1a64(body.encode()):016x}"
            if a.hash != expected:
                return False, f"hash mismatch at ts={a.ts}: stored {a.hash}, computed {expected}"
            if a.prev_hash != prev_hash:
                return False, f"prev_hash mismatch at ts={a.ts}"
            prev_hash = a.hash
        return True, f"chain valid across {len(self.actions)} actions"

    def last_morning(self) -> Optional[CowboyAction]:
        for a in reversed(self.actions):
            if a.kind == "morning":
                return a
        return None

    def retired(self) -> List[str]:
        return [a.target for a in self.actions if a.kind == "retire"]

    def promoted(self) -> List[str]:
        return [a.target for a in self.actions if a.kind == "promote"]


# ---------------------------------------------------------------------------
# The Cowboy — runs the morning, writes the report
# ---------------------------------------------------------------------------

@dataclass
class MorningReport:
    """The cowboy's morning report."""
    date: str = ""
    witness_events: int = 0
    ledger_entries: int = 0
    n_alignments: int = 0
    earned_keep: List[str] = field(default_factory=list)
    retirees: List[str] = field(default_factory=list)
    escalations: List[str] = field(default_factory=list)
    refinements: List[str] = field(default_factory=list)
    cost_yesterday: float = 0.0
    quality_yesterday: float = 0.0
    cowboy_action: Optional[str] = None
    cowboy_note: str = ""

    def to_markdown(self) -> str:
        lines = [
            f"# Morning Report — {self.date}",
            "",
            f"*Generated by the cowboy at {time.strftime('%H:%M:%S UTC', time.gmtime())}*",
            "",
            "## Counts",
            f"- Witness events: {self.witness_events}",
            f"- Ledger entries: {self.ledger_entries}",
            f"- Distinct alignments: {self.n_alignments}",
            f"- Yesterday's cost: ${self.cost_yesterday:.4f}",
            f"- Yesterday's quality: {self.quality_yesterday:.3f}",
            "",
            "## Earned-keep (pinned)",
        ]
        if self.earned_keep:
            for a in self.earned_keep:
                lines.append(f"- `{a}`")
        else:
            lines.append("- (none yet — need n≥5 and Wilson lower ≥0.5)")
        lines += [
            "",
            "## Retirees (failing alignments)",
        ]
        if self.retirees:
            for a in self.retirees:
                lines.append(f"- `{a}`")
        else:
            lines.append("- (none)")
        lines += [
            "",
            "## Escalations (need cowboy attention)",
        ]
        if self.escalations:
            for a in self.escalations:
                lines.append(f"- `{a}`")
        else:
            lines.append("- (none)")
        lines += [
            "",
            "## Refinements applied",
        ]
        if self.refinements:
            for r in self.refinements:
                lines.append(f"- {r}")
        else:
            lines.append("- (none)")
        lines += [
            "",
            "## Cowboy's note",
            f"{self.cowboy_note or '(no note)'}",
            "",
            "---",
            "",
            "The cowboy is not the AI. The cowboy is the rider.",
            "The harness is what makes one animal of horse and rider.",
        ]
        return "\n".join(lines)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


class Cowboy:
    """The cowboy. Runs the morning, refines the substrate, writes the report."""

    def __init__(self, state_dir: str, plugin=None, bridge=None, deckhand=None):
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.memory = CowboyMemory(str(self.state_dir / "cowboy.jsonl"))
        self.plugin = plugin
        self.bridge = bridge
        self.deckhand = deckhand

    def run_morning(self) -> MorningReport:
        """Run the morning: read witness, run nightcycle, refine, write report."""
        report = MorningReport(date=time.strftime("%Y-%m-%d", time.gmtime()))

        # 1. Read the witness
        if self.deckhand is not None:
            stats = self.deckhand.stats()
            report.witness_events = stats.get("n_events", 0)
        elif self.plugin is not None and hasattr(self.plugin, "witness"):
            report.witness_events = len(self.plugin.witness)
        else:
            report.witness_events = 0

        # 2. Read the ledger (if bridge present)
        if self.bridge is not None:
            try:
                stats = self.bridge.stats()
                report.ledger_entries = stats.get("n_entries", 0)
            except Exception:
                report.ledger_entries = 0
        else:
            report.ledger_entries = 0

        # 3. Compute aggregates from witness
        events = []
        if self.deckhand is not None and hasattr(self.deckhand, "events"):
            events = self.deckhand.events
        elif self.plugin is not None and hasattr(self.plugin, "witness"):
            events = self.plugin.witness
        alignments = {}
        for e in events:
            model = e.get("decision", {}).get("model") if isinstance(e, dict) else getattr(e, "model", "")
            if not model:
                continue
            if model not in alignments:
                alignments[model] = {"n": 0, "success": 0, "cost": 0.0, "quality": 0.0}
            alignments[model]["n"] += 1
            if e.get("success"):
                alignments[model]["success"] += 1
            alignments[model]["cost"] += e.get("cost", 0.0)
            alignments[model]["quality"] += e.get("quality", 0.0)
        report.n_alignments = len(alignments)
        if events:
            report.cost_yesterday = sum(e.get("cost", 0.0) for e in events)
            total_q = sum(e.get("quality", 0.0) for e in events)
            report.quality_yesterday = total_q / len(events)

        # 4. Apply cowboy's memory (retire/promote from past)
        retired = set(self.memory.retired())
        promoted = set(self.memory.promoted())

        # 5. Decide earned-keep and retirees (Wilson-style, inline)
        # Already-retired alignments stay retired.
        for model, stats in alignments.items():
            n = stats["n"]
            s = stats["success"]
            if n == 0:
                continue
            # Wilson lower bound (95% confidence)
            z = 1.96
            p = s / n
            denom = 1 + z * z / n
            center = (p + z * z / (2 * n)) / denom
            spread = z * ((p * (1 - p) + z * z / (4 * n)) / n) ** 0.5 / denom
            wilson_lb = max(0.0, center - spread)
            # Earned-keep: not retired, n>=5, wilson_lb>=0.5
            if model not in retired and model not in promoted and n >= 5 and wilson_lb >= 0.5:
                # Cowboy promotes it (auto)
                self.memory.append(CowboyAction(
                    kind="promote", target=model,
                    reason=f"auto-earned-keep: n={n} success={s} wilson_lb={wilson_lb:.3f}",
                    payload={"n": n, "success": s, "wilson_lb": wilson_lb},
                ))
                report.refinements.append(f"promoted `{model}` (earned-keep)")
                promoted.add(model)
            # Retire: n>=3, wilson_lb<0.3, not yet retired
            if model not in retired and n >= 3 and wilson_lb < 0.3:
                self.memory.append(CowboyAction(
                    kind="retire", target=model,
                    reason=f"auto-retire: n={n} success={s} wilson_lb={wilson_lb:.3f}",
                    payload={"n": n, "success": s, "wilson_lb": wilson_lb},
                ))
                report.refinements.append(f"retired `{model}` (failing)")
                retired.add(model)
            # Escalation: n>=2, wilson_lb<0.2
            if n >= 2 and wilson_lb < 0.2:
                report.escalations.append(f"`{model}` (n={n}, wilson_lb={wilson_lb:.3f})")

        # 6. Apply cowboy's memory to the plugin (if Wilson is there)
        if self.plugin is not None and hasattr(self.plugin, "wilson"):
            for model in retired:
                if model in self.plugin.wilson.obs:
                    self.plugin.wilson.obs[model]["blacklist"] = True
            for model in promoted:
                if model in self.plugin.wilson.obs:
                    self.plugin.wilson.obs[model]["pin"] = True

        # 7. Write the report
        report.earned_keep = sorted(promoted)
        report.retirees = sorted(retired)
        report.cowboy_note = self._compose_note(report)

        # 8. Persist the morning
        self.memory.append(CowboyAction(
            kind="morning", target="system",
            reason="morning report",
            payload=report.to_dict(),
        ))

        return report

    def _compose_note(self, report: MorningReport) -> str:
        """Compose a short cowboy note for the morning report."""
        if report.n_alignments == 0:
            return "Quiet morning. Nothing to report. The substrate is calm."
        if len(report.escalations) > 0:
            return (f"Busy morning. {len(report.escalations)} alignments need attention. "
                    f"Reading the ledger twice today.")
        if len(report.earned_keep) > 0:
            return (f"Good morning. {len(report.earned_keep)} alignments earned their keep. "
                    f"The substrate is learning.")
        return (f"Routine morning. {report.n_alignments} alignments, no escalations. "
                f"The cowboy kept the rider's seat warm.")

    def state(self) -> Dict[str, Any]:
        return {
            "memory_path": str(self.memory.path),
            "n_actions": len(self.memory.actions),
            "retired": self.memory.retired(),
            "promoted": self.memory.promoted(),
            "chain_ok": self.memory.verify_chain()[0],
        }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(prog="cowboy", description="The cowboy: runs the morning, refines the substrate.")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run the morning")
    p_run.add_argument("--state-dir", default="/workspace/cowboy-state",
                          help="Where to store cowboy memory")

    p_watch = sub.add_parser("watch", help="Watch the bus in real time (replay mode: --bus-log)")
    p_watch.add_argument("--state-dir", default="/workspace/cowboy-state",
                            help="Where to store cowboy memory")
    p_watch.add_argument("--bus-log", default=None,
                            help="Optional path to bus.jsonl to replay (for testing)")
    p_watch.add_argument("--retire-after", type=int, default=3,
                            help="Auto-retire after N consecutive failures")

    p_report = sub.add_parser("report", help="Print the last morning report")
    p_report.add_argument("--state-dir", default="/workspace/cowboy-state")

    p_state = sub.add_parser("state", help="Print cowboy state")
    p_state.add_argument("--state-dir", default="/workspace/cowboy-state")

    p_note = sub.add_parser("note", help="Append a note to cowboy memory")
    p_note.add_argument("text", help="The note text")
    p_note.add_argument("--state-dir", default="/workspace/cowboy-state")

    p_retire = sub.add_parser("retire", help="Manually retire an alignment")
    p_retire.add_argument("target", help="The alignment (model) to retire")
    p_retire.add_argument("--reason", default="manual")
    p_retire.add_argument("--state-dir", default="/workspace/cowboy-state")

    args = parser.parse_args()

    if not args.cmd:
        parser.print_help()
        return

    cowboy = Cowboy(state_dir=args.state_dir)

    if args.cmd == "run":
        report = cowboy.run_morning()
        print(report.to_markdown())
    elif args.cmd == "watch":
        from quilt_substrate.bus import EventBus, BusLogger
        from quilt_substrate.cowboy_reactor import CowboyReactor
        bus = EventBus()
        reactor = CowboyReactor(cowboy, bus, retire_after_failures=args.retire_after)
        bus.subscribe("cast.observed", BusLogger(stdout=True))
        if args.bus_log:
            # Replay mode: load events from JSONL and republish
            print(f"Replaying {args.bus_log}...")
            import json
            n = 0
            with open(args.bus_log) as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    d = json.loads(line)
                    e = type("E", (), d)()
                    e.data = d.get("data", {})
                    e.topic = d.get("topic", "")
                    e.source = d.get("source", "")
                    e.ts = d.get("ts", 0)
                    # Manually call subscribers
                    for fn in bus.subscribers.get(e.topic, []):
                        try:
                            fn(e)
                        except Exception:
                            pass
                    n += 1
            print(f"\nReplayed {n} events.")
            print(f"Auto-retired: {reactor.stats()['auto_retired']}")
            print(f"Recent sizes: {reactor.stats()['recent_sizes']}")
        else:
            # Live mode: wait for events
            print("Watching bus. Press Ctrl+C to stop.")
            try:
                import time
                while True:
                    time.sleep(1)
            except KeyboardInterrupt:
                print("\nStopped watching.")
            finally:
                reactor.stop()
    elif args.cmd == "report":
        last = cowboy.memory.last_morning()
        if last is None:
            print("No morning report yet. Run `cowboy run` first.")
            return
        # Reconstruct the report from the action
        report = MorningReport(**last.payload)
        print(report.to_markdown())
    elif args.cmd == "state":
        s = cowboy.state()
        print(json.dumps(s, indent=2))
    elif args.cmd == "note":
        cowboy.memory.append(CowboyAction(kind="note", target="cowboy", reason=args.text))
        print(f"Note appended. {len(cowboy.memory.actions)} actions in memory.")
    elif args.cmd == "retire":
        cowboy.memory.append(CowboyAction(kind="retire", target=args.target, reason=args.reason))
        print(f"Retired `{args.target}`. {len(cowboy.memory.actions)} actions in memory.")


if __name__ == "__main__":
    main()
