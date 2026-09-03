"""negative_space_full.py — the full pipeline.

Game state + sensors + model → ablate each sensor → compose from the rest
→ find leaks via double-entry ledger → find the negative space.

This is the integration of:
  - human_model.py: the player's conscious model of themselves
  - body_graph.py: the body's causal graph (sensors as cells)
  - compose.py: compose a full body model from partial sensors + game state
  - double_entry.py: back-tradable ledger that finds leaks

The 4-move cycle:
  1. READ — observe the current sensor values
  2. DECOMPOSE — ablate each sensor, measure the residual
  3. COMPOSE — reconstruct from the rest + known game state
  4. LEDGER — log the entries, find the negative space
"""
from __future__ import annotations
import json, time, math, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

from human_model import HumanModel, BodyState, GameState, LedgerEntry
from body_graph import BodyGraph, SENSOR_NAMES
from compose import ComposingBody, ComposedBody, GAME_BODY_EDGES
from double_entry import DoubleEntryLedger, negative_space as base_negative_space


@dataclass
class PipelineTick:
    """A single tick of the full pipeline."""
    tick_id: int
    timestamp_ms: int

    # Inputs
    observed: Dict[str, int]    # what we actually saw
    model: HumanModel           # what the player said
    game: GameState             # what the game told us

    # Outputs
    ablations: List[Dict]       # one per sensor
    composed: Dict[str, int]    # full body reconstruction
    leaks: Dict                 # negative-space leaks
    integrity_score: float      # 0-1, 1 = full integrity
    overall_interpretation: str

    def to_dict(self):
        return {
            "tick_id": self.tick_id,
            "timestamp_ms": self.timestamp_ms,
            "observed": self.observed,
            "model": self.model.to_dict(),
            "game": self.game.to_dict(),
            "ablations": self.ablations,
            "composed": self.composed,
            "leaks": self.leaks,
            "integrity_score": self.integrity_score,
            "overall_interpretation": self.overall_interpretation,
        }


class NegativeSpacePipeline:
    """The full pipeline: observed sensors + model + game → integrity + leaks."""

    def __init__(self, body_graph: BodyGraph = None):
        self.body_graph = body_graph or BodyGraph()
        self.composer = ComposingBody(self.body_graph)
        self.ledger = DoubleEntryLedger()
        self.ticks: List[PipelineTick] = []
        self._tick = 0

    def tick_(self,
              observed: Dict[str, int],
              model: HumanModel,
              game: GameState,
              game_history: Optional[List[Tuple[str, int, int]]] = None,
              ) -> PipelineTick:
        """Run one full pipeline tick.

        observed: {sensor: value} for whatever sensors you have
        model:    what the player says about themselves
        game:     what the game knows (ground truth)
        game_history: optional list of (event, value, t_ms) tuples
        """
        self._tick += 1
        ts = int(time.time() * 1000)

        # Set the observed sensors in the body graph
        for n, v in observed.items():
            self.body_graph.cells[n].current_value = v

        # 1. ABLATE — ablate each sensor (including observed ones) and measure residual
        # First, snapshot the body graph's state for ablation
        ablations = self.body_graph.ablate_all()

        # 2. COMPOSE — fill in the missing sensors using body graph + game state
        composed_obj = self.composer.compose(observed, game, game_history)

        # 3. Build a body state from the composed model
        composed_body = composed_obj.to_body_state()

        # 4. LEDGER — log entries
        # For each observation, log: model credits, body debits (they MUST match)
        # For each leak, log: a debt
        for n, v in observed.items():
            self.ledger.add("body", n, debit=0, credit=v, description="observed")
        for n, v in composed_obj.dials.items():
            if n not in observed:
                self.ledger.add("body", n, debit=0, credit=v, description=f"composed: {composed_obj.source[n]}")
        # The game state logs to its own account
        self.ledger.add("game", "score", credit=game.score, description="ground truth")
        self.ledger.add("game", "accuracy", credit=int(game.accuracy * 32767), description="ground truth")
        self.ledger.add("game", "errors", debit=game.errors, description="ground truth")
        # The model logs to its own account
        for i, v in enumerate(model.to_dials()):
            self.ledger.add("model", f"model_dial_{i}", credit=v, description="self-report")

        # 5. NEGATIVE SPACE — find the leaks
        ns = base_negative_space(model, composed_body, game)
        leaks = ns["leaks"]

        # 6. INTEGRITY SCORE — 0 (full leaks) to 1 (no leaks)
        # Number of leaks weighted by gap size
        if not leaks:
            integrity = 1.0
        else:
            # Sum the absolute gaps across all leak dimensions
            gap_sum = 0
            for v in leaks.values():
                gap_str = v.get("gap", "0%").rstrip("%")
                try:
                    gap_sum += abs(float(gap_str))
                except:
                    gap_sum += 10  # default
            # Map 0 gap = 1.0, 100+ gap = 0.0
            integrity = max(0.0, 1.0 - gap_sum / 400.0)

        tick = PipelineTick(
            tick_id=self._tick,
            timestamp_ms=ts,
            observed=observed,
            model=model,
            game=game,
            ablations=ablations,
            composed=composed_obj.dials,
            leaks=leaks,
            integrity_score=integrity,
            overall_interpretation=ns["interpretation"],
        )
        self.ticks.append(tick)
        return tick

    def summary(self) -> Dict:
        """Summary across all ticks."""
        if not self.ticks:
            return {}
        return {
            "n_ticks": len(self.ticks),
            "avg_integrity": sum(t.integrity_score for t in self.ticks) / len(self.ticks),
            "min_integrity": min(t.integrity_score for t in self.ticks),
            "max_integrity": max(t.integrity_score for t in self.ticks),
            "ticks": [t.to_dict() for t in self.ticks],
        }


# === Demonstration: a 4-tick game session with rising/leaking integrity ===
def demo_game_session():
    from human_model import HumanModel, BodyState, GameState

    pipe = NegativeSpacePipeline(BodyGraph(seed=42))
    game = GameState(score=0, accuracy=0.0, reaction_time_ms=0,
                     actions=0, errors=0, duration_s=0, win=False, game="tetris")

    # Helper to make a body state
    def body(alpha, beta, theta, hr, gsr, posture, blink):
        return {
            "eeg_alpha": alpha, "eeg_beta": beta, "eeg_theta": theta,
            "heart_rate": hr, "gsr": gsr, "posture_tension": posture,
            "blink_rate": blink,
        }

    print("=" * 75)
    print("NEGATIVE SPACE PIPELINE — a 4-tick game session")
    print("=" * 75)
    print()
    print("Setup: Player playing Tetris, all 16 sensors available.")
    print("Player's conscious model is what's said (declared).")
    print("Body stream is what's actually read.")
    print("Game state is the ground truth (score, accuracy, etc.)")
    print()

    # Tick 1: Player starts, calm and confident
    print("TICK 1 — Game start, calm and confident")
    game.score = 100; game.accuracy = 0.95; game.actions = 20; game.errors = 1
    game.reaction_time_ms = 180; game.duration_s = 60
    obs1 = body(alpha=24000, beta=8000, theta=20000, hr=12000, gsr=8000,
                posture=8000, blink=12000)
    model1 = HumanModel(perc_focus=20000, self_focus=20000, self_calm=20000,
                        self_effort=16000, pred_will_win=20000, pred_duration=24000)
    t1 = pipe.tick_(obs1, model1, game)
    print(f"  Integrity: {t1.integrity_score:.2f}  Leaks: {len(t1.leaks)}")
    print(f"  {t1.overall_interpretation}")
    print(f"  Critical sensors: {[a['sensor'] for a in t1.ablations if a['verdict'] == 'CRITICAL']}")

    # Tick 2: 10 min in, still going well, but body is starting to ramp up
    print()
    print("TICK 2 — 10 min in, body is ramping up but model says fine")
    game.score = 600; game.accuracy = 0.92; game.actions = 120; game.errors = 9
    game.reaction_time_ms = 200; game.duration_s = 600
    obs2 = body(alpha=20000, beta=14000, theta=18000, hr=16000, gsr=14000,
                posture=12000, blink=10000)
    # model is *slightly* less confident but still optimistic
    model2 = HumanModel(perc_focus=20000, self_focus=20000, self_calm=18000,
                        self_effort=20000, pred_will_win=22000, pred_duration=22000)
    t2 = pipe.tick_(obs2, model2, game)
    print(f"  Integrity: {t2.integrity_score:.2f}  Leaks: {len(t2.leaks)}")
    print(f"  {t2.overall_interpretation}")
    for k, v in t2.leaks.items():
        print(f"    [{k}] claimed {v.get('claimed')}, actual {v.get('actual')}, gap {v.get('gap')}")

    # Tick 3: 20 min in, overdriven but model still says fine (burnout)
    print()
    print("TICK 3 — 20 min in, BODY OVERDRIVEN, model still says 'I am fine'")
    game.score = 1100; game.accuracy = 0.88; game.actions = 240; game.errors = 28
    game.reaction_time_ms = 240; game.duration_s = 1200
    obs3 = body(alpha=10000, beta=24000, theta=12000, hr=22000, gsr=26000,
                posture=20000, blink=4000)
    model3 = HumanModel(perc_focus=26000, self_focus=28000, self_calm=22000,
                        self_effort=24000, pred_will_win=22000, pred_duration=20000)
    t3 = pipe.tick_(obs3, model3, game)
    print(f"  Integrity: {t3.integrity_score:.2f}  Leaks: {len(t3.leaks)}")
    print(f"  {t3.overall_interpretation}")
    for k, v in t3.leaks.items():
        print(f"    [{k}] claimed {v.get('claimed')}, actual {v.get('actual')}, gap {v.get('gap')}")

    # Tick 4: 30 min in, body is exhausted, but model is finally starting to admit it
    print()
    print("TICK 4 — 30 min in, model finally admits fatigue")
    game.score = 1400; game.accuracy = 0.78; game.actions = 350; game.errors = 77
    game.reaction_time_ms = 320; game.duration_s = 1800
    obs4 = body(alpha=8000, beta=28000, theta=8000, hr=26000, gsr=30000,
                posture=24000, blink=2000)
    model4 = HumanModel(perc_focus=16000, self_focus=14000, self_calm=10000,
                        self_effort=28000, pred_will_win=18000, pred_duration=14000)
    t4 = pipe.tick_(obs4, model4, game)
    print(f"  Integrity: {t4.integrity_score:.2f}  Leaks: {len(t4.leaks)}")
    print(f"  {t4.overall_interpretation}")
    for k, v in t4.leaks.items():
        print(f"    [{k}] claimed {v.get('claimed')}, actual {v.get('actual')}, gap {v.get('gap')}")

    print()
    print("=" * 75)
    print("INTEGRITY TRAJECTORY")
    print("=" * 75)
    for t in pipe.ticks:
        bar = "█" * int(t.integrity_score * 30)
        print(f"  Tick {t.tick_id}: integrity={t.integrity_score:.2f}  leaks={len(t.leaks)}  {bar}")
    print()
    print("Reading: As the session progresses, integrity FALLS. The model is leaking")
    print("ever more out of sync with the body. By tick 4, the player is overdriven,")
    print("errors are climbing, and the model is finally starting to admit it — but")
    print("not because the model is honest, because the leaks are now too big to hide.")


# === Demonstration: a player in integrity the whole time ===
def demo_integrity_session():
    from human_model import HumanModel, BodyState, GameState

    pipe = NegativeSpacePipeline(BodyGraph(seed=42))
    game = GameState(score=0, accuracy=0.0, reaction_time_ms=0,
                     actions=0, errors=0, duration_s=0, win=False, game="tetris")

    def body(alpha, beta, theta, hr, gsr, posture, blink):
        return {
            "eeg_alpha": alpha, "eeg_beta": beta, "eeg_theta": theta,
            "heart_rate": hr, "gsr": gsr, "posture_tension": posture,
            "blink_rate": blink,
        }

    print()
    print("=" * 75)
    print("INTEGRITY SESSION — model, body, and game always agree")
    print("=" * 75)
    print()
    for t in range(4):
        game.actions = 30 + t * 50
        game.errors = 3 + t * 4
        game.score = 200 * (t + 1)
        game.accuracy = 0.9 - t * 0.03
        game.reaction_time_ms = 200 + t * 20
        game.duration_s = 300 * (t + 1)
        # body, model, game all aligned
        alpha = 22000 - t * 1000
        beta = 8000 + t * 2000
        hr = 12000 + t * 1000
        gsr = 8000 + t * 1000
        obs = body(alpha=alpha, beta=beta, theta=alpha-2000, hr=hr, gsr=gsr,
                   posture=8000+t*500, blink=12000-t*1000)
        # Model tracks the body
        model = HumanModel(
            perc_focus=int(0.7 * 32767 - t * 1000),
            self_focus=int(0.7 * 32767 - t * 1000),
            self_calm=int(0.7 * 32767 - t * 1000),
            self_effort=int(0.6 * 32767 + t * 500),
            pred_will_win=int(0.7 * 32767 - t * 1000),
            pred_duration=int(0.8 * 32767 - t * 500),
        )
        result = pipe.tick_(obs, model, game)
        print(f"  Tick {t+1}: integrity={result.integrity_score:.2f}  leaks={len(result.leaks)}")

    print(f"  Average integrity: {sum(t.integrity_score for t in pipe.ticks)/len(pipe.ticks):.2f}")
    print()
    print("  → High integrity throughout. The model and the body are aligned.")


if __name__ == "__main__":
    demo_game_session()
    demo_integrity_session()
