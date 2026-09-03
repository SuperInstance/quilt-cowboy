"""compose.py — compose a full body model from partial sensors + game state.

If a sensor is missing or ablated, we can *compose* its value by:
  1. Inferring from the body's parent graph (body_graph.py)
  2. Conditioning on the known game state (some game events cause
     specific physiological responses — e.g., scoring a goal spikes
     heart_rate)

The composed value is a weighted average of the body-inference and
the game-conditioned estimate.

The composed full body model is then compared to the player's conscious
model (human_model.py) to find leaks (double_entry.py).

This is the human side of the decomposition-composition duality.
"""
from __future__ import annotations
import json, time, math, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple

from human_model import HumanModel, BodyState, GameState
from body_graph import BodyGraph, SENSOR_NAMES, SensorCell


# A known game-physiology mapping: which game events cause which body responses.
# In a real system, this would be learned from a large game-with-sensors dataset.
GAME_BODY_EDGES = [
    # (game event, body sensor, gain, delay_ms)
    ("score", "heart_rate",     0.4, 50),    # scoring spikes HR
    ("score", "eeg_beta",       0.3, 30),    # scoring → arousal
    ("score", "gsr",            0.2, 200),   # scoring → sweat
    ("error", "heart_rate",     0.2, 30),    # errors → mild HR spike
    ("error", "eeg_beta",       0.4, 10),    # errors → frustration, beta up
    ("error", "posture_tension", 0.3, 100),  # errors → tensing up
    ("action", "eeg_beta",      0.1, 5),     # action rate → mental load
    ("win",   "eeg_alpha",      0.3, 5000),  # winning → eventual relaxation
    ("win",   "eeg_theta",      0.2, 5000),  # winning → meditative
    ("lose",  "gsr",            0.4, 1000),  # losing → sweating
    ("lose",  "posture_tension", 0.3, 500),  # losing → tensing
]


@dataclass
class ComposedBody:
    """A full 16-dial body model composed from partial inputs + game state."""
    dials: Dict[str, int] = field(default_factory=dict)
    source: Dict[str, str] = field(default_factory=dict)  # which method composed each dial
    confidence: Dict[str, float] = field(default_factory=dict)

    def to_body_state(self) -> BodyState:
        """Convert back to a BodyState."""
        d = {n: self.dials.get(n, 16384) for n in SENSOR_NAMES}
        return BodyState(
            eeg_alpha=d["eeg_alpha"], eeg_beta=d["eeg_beta"], eeg_gamma=d["eeg_gamma"],
            eeg_theta=d["eeg_theta"], eeg_delta=d["eeg_delta"],
            heart_rate=d["heart_rate"], heart_rate_var=d["heart_rate_var"],
            accel_x=d["accel_x"], accel_y=d["accel_y"], accel_z=d["accel_z"],
            gsr=d["gsr"], skin_temp=d["skin_temp"], blink_rate=d["blink_rate"],
            voice_freq=d["voice_freq"], pupil_dilation=d["pupil_dilation"],
            posture_tension=d["posture_tension"],
        )


class ComposingBody:
    """Given partial sensor readings + the known game state, compose a full body model."""

    def __init__(self, body_graph: BodyGraph = None):
        self.body_graph = body_graph or BodyGraph()

    def compose(self,
                observed: Dict[str, int],
                game: GameState,
                game_history: Optional[List[Tuple[str, int, int]]] = None  # (event, value, t_ms)
                ) -> ComposedBody:
        """Compose a full body model.

        observed:     {sensor_name: value} for whatever sensors we DO have
        game:         the current known game state
        game_history: optional list of (event, value, t_ms) tuples for time-aware conditioning
        """
        composed = ComposedBody()
        now = int(time.time() * 1000)

        # Set the observed sensors (mark as 'observed')
        for name, value in observed.items():
            composed.dials[name] = value
            composed.source[name] = "observed"
            composed.confidence[name] = 1.0
            # Also set in the body graph so other inferences can use it
            self.body_graph.cells[name].current_value = value

        # For each missing sensor, infer from body graph
        for name in SENSOR_NAMES:
            if name in composed.dials:
                continue

            # Method 1: body graph inference
            inferred, body_conf = self.body_graph.infer(name)

            # Method 2: game-conditioned estimate
            game_estimate, game_conf = self._from_game(name, game, game_history)

            # Method 3: baseline (if both fail)
            baseline = self.body_graph.cells[name].baseline
            baseline_conf = 0.1

            # Pick the best method
            if game_conf > 0 and body_conf > 0:
                # Weighted average
                w_body = body_conf
                w_game = game_conf
                total = w_body + w_game
                final = int((inferred * w_body + game_estimate * w_game) / total)
                final_conf = min(1.0, (w_body + w_game) / 2)
                source = f"body({body_conf:.2f})+game({game_conf:.2f})"
            elif game_conf > body_conf:
                final = game_estimate
                final_conf = game_conf
                source = f"game({game_conf:.2f})"
            elif body_conf > 0:
                final = inferred
                final_conf = body_conf
                source = f"body({body_conf:.2f})"
            else:
                final = baseline
                final_conf = baseline_conf
                source = "baseline"

            composed.dials[name] = final
            composed.source[name] = source
            composed.confidence[name] = final_conf

        return composed

    def _from_game(self, sensor: str, game: GameState,
                   history: Optional[List[Tuple[str, int, int]]]) -> Tuple[int, float]:
        """Estimate a sensor value from the known game state.

        Returns (estimate, confidence). Confidence is 0 if no relevant game info.
        """
        if history is None:
            history = []
        # Find all game events that map to this sensor
        relevant = [(evt, gain, delay) for evt, s, gain, delay in GAME_BODY_EDGES if s == sensor]
        if not relevant:
            return 16384, 0.0

        # Compute the time-decayed contribution of each recent event
        baseline = self.body_graph.cells[sensor].baseline
        contribution = 0.0
        weight_total = 0.0
        now = int(time.time() * 1000)

        for evt, gain, delay in relevant:
            # Use the current value of the corresponding game attribute
            if evt == "score":
                val = game.score
            elif evt == "error":
                val = game.errors
            elif evt == "action":
                val = game.actions
            elif evt == "win":
                val = 1 if game.win else 0
            elif evt == "lose":
                val = 1 if not game.win and game.duration_s > 60 else 0
            else:
                val = 0

            # Normalize to a 0-1 "intensity" and scale by gain
            intensity = min(1.0, val / 1000.0) if isinstance(val, (int, float)) else val
            contribution += intensity * gain
            weight_total += abs(gain)

        if weight_total == 0:
            return baseline, 0.0

        estimate = int(baseline + contribution / weight_total * 16384)  # scale up
        estimate = max(0, min(32767, estimate))
        confidence = min(1.0, weight_total / 1.5)
        return estimate, confidence


def demo_compose():
    """Compose a full body model from only 4 observed sensors + game state."""
    from human_model import BodyState, GameState

    cb = ComposingBody(BodyGraph(seed=42))

    # Player in a state of focus-arousal: high beta, high HR, low alpha
    # But we only OBSERVE 4 sensors
    observed = {
        "eeg_beta": 24000,         # high beta → overdriven
        "heart_rate": 22000,       # high HR
        "gsr": 26000,              # sweating
        "posture_tension": 18000,  # tense
    }

    # Game state: high score, accuracy 0.85, 30 min in
    game = GameState(
        score=800, accuracy=0.85, reaction_time_ms=200,
        actions=200, errors=30, duration_s=1800, win=False, game="tetris",
    )

    print("=" * 70)
    print("COMPOSE — full body from 4 observed sensors + game state")
    print("=" * 70)
    print(f"\n  Observed: {list(observed.keys())}")
    print(f"  Game: score={game.score}, accuracy={game.accuracy}, errors={game.errors}, "
          f"actions={game.actions}, duration={game.duration_s}s")
    print()

    composed = cb.compose(observed, game)

    print(f"{'Sensor':18s} {'Dial':>7s} {'Conf':>6s}  Source")
    print("-" * 70)
    for name in SENSOR_NAMES:
        d = composed.dials[name]
        c = composed.confidence[name]
        s = composed.source[name]
        marker = "★" if name in observed else " "
        print(f"  {marker} {name:16s} {d:7d} {c:6.2f}  {s}")

    print()
    print("★ = observed; other values composed via body-graph inference or game conditioning")

    # Convert to BodyState
    body = composed.to_body_state()
    print()
    print("Resulting body state:")
    print(f"  eeg_alpha:  {body.eeg_alpha:5d} ({body.eeg_alpha/327:.0f}%)")
    print(f"  eeg_beta:   {body.eeg_beta:5d} ({body.eeg_beta/327:.0f}%)  ★observed")
    print(f"  heart_rate: {body.heart_rate:5d} ({body.heart_rate/327:.0f}%)  ★observed")
    print(f"  gsr:        {body.gsr:5d} ({body.gsr/327:.0f}%)  ★observed")
    print(f"  posture:    {body.posture_tension:5d} ({body.posture_tension/327:.0f}%)  ★observed")


def demo_compare_to_ground_truth():
    """Show how well composition matches the actual ground truth."""
    from human_model import BodyState, GameState

    # Set up an actual body state
    g = BodyGraph(seed=42)
    g.set_("eeg_alpha", 22000)
    g.set_("eeg_beta",  18000)
    g.set_("eeg_theta", 20000)
    g.set_("heart_rate", 16000)
    g.set_("gsr", 20000)
    g.set_("posture_tension", 14000)

    # Now compose from a partial observation
    cb = ComposingBody(g)
    observed = {"eeg_beta": 18000, "heart_rate": 16000}
    game = GameState(score=400, accuracy=0.8, actions=150, errors=20, duration_s=600, win=False, game="tetris")
    composed = cb.compose(observed, game)

    # Compare
    print()
    print("=" * 70)
    print("COMPOSE — vs ground truth")
    print("=" * 70)
    print(f"\n{'Sensor':18s} {'Actual':>7s} {'Composed':>9s} {'Δ':>5s}  Source")
    print("-" * 70)
    for name in SENSOR_NAMES:
        actual = g.cells[name].current_value
        comp = composed.dials[name]
        delta = abs(actual - comp)
        marker = "★" if name in observed else " "
        print(f"  {marker} {name:16s} {actual:7d} {comp:9d} {delta:5d}  {composed.source[name]}")


if __name__ == "__main__":
    demo_compose()
    demo_compare_to_ground_truth()
