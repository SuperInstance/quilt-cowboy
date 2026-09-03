"""body_graph.py — the body as a cell graph.

Every sensor is a cell. Dependencies between sensors are edges.
The graph is the body's *known* topology (or the part we know from data).

Each sensor is a dial 0-32767. Same encoding as the rest of the Quilt.

The body's graph is what we're trying to RECONSTRUCT. The game graph
is already known. The contrast between them is the point.
"""
from __future__ import annotations
import json, math, time
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
import random


# The 16 standard sensors, all in dial form
SENSOR_NAMES = [
    "eeg_alpha", "eeg_beta", "eeg_gamma", "eeg_theta", "eeg_delta",  # 5 EEG
    "heart_rate", "heart_rate_var",                                   # 2 cardiac
    "accel_x", "accel_y", "accel_z",                                 # 3 motion
    "gsr", "skin_temp", "blink_rate",                                # 3 skin/eye
    "voice_freq", "pupil_dilation", "posture_tension",               # 3 voice/pupil/posture
]
assert len(SENSOR_NAMES) == 16


@dataclass
class SensorCell:
    """A single sensor as a Quilt cell."""
    name: str
    current_value: int = 16384         # last observed dial
    baseline: int = 16384             # resting-state value
    noise_floor: int = 500            # measurement noise in dial units
    inferred_value: Optional[int] = None  # last value inferred from other sensors
    last_residual: int = 0            # |actual - inferred|
    last_residual_timestamp: int = 0

    def to_dict(self):
        return asdict(self)


# Causal edges: a change in `cause` produces a change in `effect` after `delay_ms`.
# These are *learned* or *specified*. In real life, you'd learn them from data.
# Here, we specify a plausible topology.
#
# Conventions:
#   - beta goes UP when alpha goes DOWN (arousal)
#   - heart_rate goes UP when beta goes UP
#   - GSR goes UP when heart_rate goes UP (sympathetic cascade)
#   - pupil_dilation goes UP with arousal
#   - posture_tension goes UP with beta
#   - blink_rate goes DOWN with focus
#   - alpha goes UP when eyes close (delta also UP)
#   - accel signals: independent of internal state (external motion)
#   - voice_freq: independent of internal state
#   - skin_temp: slow drift independent of state
#   - eeg_theta UP when alpha UP (relaxed focus)
#   - eeg_delta: slow, sleep-related, independent

DEFAULT_EDGES = [
    # (cause, effect, gain, delay_ms, sign)
    # sign = +1 means cause↑ → effect↑; sign = -1 means cause↑ → effect↓
    ("eeg_alpha", "eeg_beta",     0.6, 50,   -1),  # alpha up → beta down (calm)
    ("eeg_beta",  "eeg_alpha",    0.6, 50,   -1),  # reciprocal
    ("eeg_beta",  "heart_rate",   0.5, 200,  +1),  # mental activation → cardiac
    ("heart_rate","gsr",          0.4, 800,  +1),  # sympathetic cascade
    ("eeg_beta",  "gsr",          0.3, 500,  +1),  # beta → sweating
    ("eeg_beta",  "pupil_dilation", 0.5, 100, +1), # mental load → pupil
    ("eeg_beta",  "posture_tension", 0.4, 100, +1),
    ("eeg_alpha", "eeg_theta",    0.5, 100,  +1),  # alpha ↔ theta in relaxed focus
    ("eeg_theta", "eeg_alpha",    0.5, 100,  +1),
    ("eeg_alpha", "blink_rate",   0.2, 50,   +1),  # eyes open = alpha high
    ("posture_tension", "heart_rate", 0.2, 500, +1),
    ("gsr", "skin_temp",          -0.2, 5000, +1),  # sweating cools skin
]


class BodyGraph:
    """The body's sensor network as a graph.

    Each sensor is a cell. Edges carry (cause, effect, gain, delay_ms, sign).

    The graph supports:
      - reading a sensor
      - setting a sensor (and propagating to children)
      - ablating a sensor (removing it, seeing what other sensors say)
      - inferring a sensor from its parents
      - measuring the residual between actual and inferred
    """

    def __init__(self, edges: List[Tuple[str, str, float, int, int]] = None,
                 seed: int = 0):
        if edges is None:
            edges = DEFAULT_EDGES
        random.seed(seed)
        self.cells: Dict[str, SensorCell] = {n: SensorCell(name=n) for n in SENSOR_NAMES}
        self.edges = edges
        # build parents/children index
        self.parents: Dict[str, List[Tuple[str, float, int, int]]] = {n: [] for n in SENSOR_NAMES}
        self.children: Dict[str, List[Tuple[str, float, int, int]]] = {n: [] for n in SENSOR_NAMES}
        for cause, effect, gain, delay, sign in edges:
            self.children[cause].append((effect, gain, delay, sign))
            self.parents[effect].append((cause, gain, delay, sign))

    def read(self, name: str, with_noise: bool = True) -> int:
        """Read a sensor value, optionally with measurement noise."""
        cell = self.cells[name]
        if with_noise:
            noise = random.randint(-cell.noise_floor, cell.noise_floor)
            return max(0, min(32767, cell.current_value + noise))
        return cell.current_value

    def set_(self, name: str, value: int, propagate: bool = True):
        """Set a sensor value, optionally propagating to children."""
        self.cells[name].current_value = max(0, min(32767, value))
        if propagate:
            self._propagate(name, time.time() * 1000)

    def _propagate(self, source: str, t_ms: float, visited: set = None, depth: int = 0):
        """Propagate changes through outgoing edges (BFS, no cycles)."""
        if visited is None:
            visited = set()
        if depth > 4:  # cap propagation depth to avoid runaway
            return
        if source in visited:
            return
        visited.add(source)
        for effect, gain, delay, sign in self.children[source]:
            cause_val = self.cells[source].current_value
            base = self.cells[effect].baseline
            deviation = (cause_val - base) * gain * sign
            new_val = base + deviation
            old_val = self.cells[effect].current_value
            new_val = int(old_val * 0.7 + new_val * 0.3)
            self.cells[effect].current_value = max(0, min(32767, new_val))
            # recurse (effect's other children may also be affected)
            self._propagate(effect, t_ms + delay, visited, depth + 1)

    def infer(self, target: str) -> Tuple[int, int]:
        """Infer a sensor's value from its parents. Returns (inferred, confidence).

        The inference is a weighted average of the parents' values, with
        weights = edge gains. The confidence is the sum of weights, normalized.

        This is the simple linear version. A real implementation would use
        a learned model (e.g., a small MLP) per sensor.
        """
        parents = self.parents[target]
        if not parents:
            return self.cells[target].baseline, 0.0

        weighted_sum = 0.0
        weight_total = 0.0
        for cause, gain, delay, sign in parents:
            cause_val = self.cells[cause].current_value
            base = self.cells[target].baseline
            # If cause is at baseline, effect is at baseline
            # contribution to effect: (cause - base) * gain * sign
            contribution = (cause_val - base) * gain * sign
            weighted_sum += contribution
            weight_total += abs(gain)
        inferred = int(self.cells[target].baseline + weighted_sum / max(weight_total, 0.001) * weight_total)
        inferred = max(0, min(32767, inferred))
        confidence = min(1.0, weight_total / 2.0)  # total gain > 2.0 = high confidence
        return inferred, confidence

    def ablate(self, target: str) -> Dict:
        """Ablate a sensor: hide its actual value, infer it from others.

        Returns the inference, the residual, the confidence, and a verdict:
          - REDUNDANT: the sensor is fully explained by the others
          - INFORMATIONAL: the sensor adds new information
          - CRITICAL: the sensor carries unique signal
        """
        actual = self.cells[target].current_value
        inferred, confidence = self.infer(target)
        residual = abs(actual - inferred)
        # Normalize to 0-100
        residual_pct = residual / 327.67
        # Update the cell's records
        self.cells[target].inferred_value = inferred
        self.cells[target].last_residual = residual
        self.cells[target].last_residual_timestamp = int(time.time() * 1000)

        if residual_pct < 3:
            verdict = "REDUNDANT"   # other sensors fully explain this one
        elif residual_pct < 10:
            verdict = "INFORMATIONAL"  # small unique signal
        else:
            verdict = "CRITICAL"    # large unique signal — this sensor matters

        return {
            "sensor": target,
            "actual": actual,
            "inferred": inferred,
            "residual": residual,
            "residual_pct": residual_pct,
            "confidence": confidence,
            "verdict": verdict,
        }

    def ablate_all(self) -> List[Dict]:
        """Run ablation on every sensor."""
        return [self.ablate(name) for name in SENSOR_NAMES]

    def spectral(self) -> List[Dict]:
        """Decompose the body's correlation matrix into eigenvalues.

        Returns the top-K principal components of the body graph.
        Each principal component is a direction in sensor-space that
        captures the most variance.

        Large eigenvalue = a mode that explains a lot (a 'channel' of the body)
        Small eigenvalue = noise / independent sensor

        NOTE: This is a small implementation. For a real system you'd use
        numpy / scipy eigendecomposition on the 16x16 sensor correlation
        matrix over a sliding window.
        """
        # Build the 16x16 correlation matrix from edges
        # For simplicity, use adjacency * sign * gain as the matrix
        n = len(SENSOR_NAMES)
        M = [[0.0] * n for _ in range(n)]
        name_to_idx = {n: i for i, n in enumerate(SENSOR_NAMES)}
        for cause, effect, gain, delay, sign in self.edges:
            i = name_to_idx[cause]
            j = name_to_idx[effect]
            M[i][j] = gain * sign
            M[j][i] = gain * sign  # symmetric
        # Add a diagonal of 1.0 (each sensor explains itself)
        for i in range(n):
            M[i][i] = 1.0

        # Power iteration to find the top eigenvalue / eigenvector
        def power_iterate(M, n_iter=200):
            v = [1.0 / math.sqrt(n) for _ in range(n)]
            for _ in range(n_iter):
                Mv = [sum(M[i][j] * v[j] for j in range(n)) for i in range(n)]
                norm = math.sqrt(sum(x * x for x in Mv)) or 1
                v = [x / norm for x in Mv]
            # Rayleigh quotient for eigenvalue
            Mv = [sum(M[i][j] * v[j] for j in range(n)) for i in range(n)]
            eig = sum(v[i] * Mv[i] for i in range(n))
            return eig, v

        # Find top 3 components by deflation
        results = []
        Mc = [row[:] for row in M]
        for k in range(3):
            eig, v = power_iterate(Mc)
            results.append({
                "rank": k + 1,
                "eigenvalue": round(eig, 3),
                "components": {SENSOR_NAMES[i]: round(v[i], 3) for i in range(n)},
            })
            # Deflate
            for i in range(n):
                for j in range(n):
                    Mc[i][j] -= eig * v[i] * v[j]
        return results

    def state_dict(self) -> Dict:
        return {
            "cells": {n: c.to_dict() for n, c in self.cells.items()},
            "edges": self.edges,
        }


# === Demonstration ===
def demo():
    g = BodyGraph(seed=42)
    # Set up a "focused calm" state
    g.set_("eeg_alpha", 26000)  # high alpha = calm
    g.set_("eeg_beta",  10000)  # low beta = not overdriven
    g.set_("eeg_theta", 22000)  # high theta = meditative focus
    g.set_("heart_rate", 12000)  # calm HR
    g.set_("posture_tension", 8000)
    g.set_("blink_rate", 4000)   # low blink = focused

    print("=" * 70)
    print("BODY GRAPH — full state of all 16 sensors (focused calm)")
    print("=" * 70)
    for name in SENSOR_NAMES:
        v = g.cells[name].current_value
        print(f"  {name:18s} = {v:5d}  ({v/327.67:5.1f}%)")

    print()
    print("=" * 70)
    print("ABLATION — infer each sensor from the others, measure residual")
    print("=" * 70)
    results = g.ablate_all()
    for r in results:
        bar = "█" * int(r['residual_pct'] / 2)
        print(f"  {r['sensor']:18s}  residual={r['residual']:5d} ({r['residual_pct']:5.1f}%)  "
              f"verdict={r['verdict']:13s}  {bar}")

    print()
    print("=" * 70)
    print("SPECTRAL — top 3 principal components of the body graph")
    print("=" * 70)
    for r in g.spectral():
        print(f"\n  PC{r['rank']} (eigenvalue {r['eigenvalue']}):")
        # show top 5 contributing sensors
        sorted_comps = sorted(r['components'].items(), key=lambda x: -abs(x[1]))
        for n, c in sorted_comps[:5]:
            print(f"    {n:18s} = {c:+.3f}")


def demo_independent_sensor():
    """Show that an independent sensor (one not in the graph) has a HUGE residual."""
    g = BodyGraph(seed=99)
    g.set_("eeg_alpha", 24000)
    g.set_("eeg_beta", 8000)
    # Inject a value into 'voice_freq' that contradicts the inference
    # voice_freq has no parents in DEFAULT_EDGES
    g.cells["voice_freq"].current_value = 30000  # way off baseline

    print()
    print("=" * 70)
    print("ABLATION — when a sensor is OUTSIDE the graph")
    print("=" * 70)
    print("voice_freq has no parents in DEFAULT_EDGES, so its value is independent.")
    print()
    r = g.ablate("voice_freq")
    print(f"  voice_freq  actual={r['actual']:5d}  inferred={r['inferred']:5d}  "
          f"residual={r['residual']:5d} ({r['residual_pct']:.1f}%)  verdict={r['verdict']}")
    print("  → voice_freq is a CRITICAL sensor — it carries signal nothing else has.")


if __name__ == "__main__":
    demo()
    demo_independent_sensor()
