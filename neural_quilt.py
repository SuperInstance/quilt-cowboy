"""neural_quilt.py — wearable neural signal as Quilt cell dials.

The thesis: a wearable neural device (EEG, EMG, EOG, etc.) emits continuous
signals. Map those signals to a 16-dial Quilt cell. The cell becomes a
navigable position in a vector space. The wearer can play games with their
own neural signals.

Three modes:
  - SOLO: wearer navigates a Quilt alone (which cell is nearest my thought?)
  - DUET: two wearers play Marco Polo (warmer/colder as thoughts align)
  - JAM: many wearers' signals flow into one Quilt (the "hive mind")

Signals modeled (16 dials):
  EEG (5): alpha, beta, gamma, theta, delta
  Cardiac (2): HR, HRV
  Motion (3): accel_x, accel_y, accel_z
  Skin (1): GSR (galvanic skin response)
  Temperature (1): skin temp
  Eye (1): blink rate
  Engagement (2): focus, calm (derived)
  Breath (1): respiration rate

All signals normalized 0-32767 (Q1.15) for the cell.

The math: a "thought" is a target 16-vector. The wearer modulates their
actual 16-vector to approach the target. Distance = cosine similarity.
Warmer/colder feedback = inverse distance.
"""
import math, random, time, json
from dataclasses import dataclass, field
from typing import List, Tuple, Dict


# === FNV-1a (matches live_canon.py) ===
def fnv1a_64(s: str) -> int:
    h = 0xCBF29CE484222325
    for byte in s.encode("utf-8"):
        h ^= byte
        h = (h * 0x00000100000001B3) & 0xFFFFFFFFFFFFFFFF
    return h


# === 16-dial cell ===
def cell_to_dials(paper: Dict) -> List[int]:
    """Match live_canon.py encoding: 16 Q1.15 dials."""
    year = int(paper.get("date", "1970-01-01")[:4]) if paper.get("date") else 1970
    year_q = (year - 1970) * 546
    phase_q = paper.get("phase", 0) * 218
    f_q = paper.get("f_number", 0) * 218
    n_refs = len(paper.get("ref_papers", [])) + len(paper.get("ref_f_numbers", []))
    n_refs_q = min(0x7FFF, n_refs * 256)
    th = fnv1a_64(paper.get("title", ""))
    title_lo = th & 0xFFFF
    title_hi = (th >> 16) & 0xFFFF
    num = min(paper.get("number", 0), 500)
    num_q = num * 131
    return [num_q, title_lo, f_q, phase_q, year_q, n_refs_q, title_hi, 0,
            0, 0, 0, 0, 0, 0, 0, 0]


# === Cosine similarity ===
def cosine(a, b):
    if len(a) != len(b) or not a:
        return 0
    dot = na = nb = 0.0
    for i in range(len(a)):
        dot += a[i] * b[i]
        na += a[i] * a[i]
        nb += b[i] * b[i]
    na = math.sqrt(na)
    nb = math.sqrt(nb)
    return dot / (na * nb) if na and nb else 0


def cosine_distance(a, b):
    return 1 - cosine(a, b)


# === Neural signal sources ===
@dataclass
class NeuralSignal:
    """A 16-dial neural signal vector from a wearable device."""
    eeg_alpha: int = 0      # 0-32767
    eeg_beta: int = 0
    eeg_gamma: int = 0
    eeg_theta: int = 0
    eeg_delta: int = 0
    heart_rate: int = 0
    heart_rate_var: int = 0
    accel_x: int = 0
    accel_y: int = 0
    accel_z: int = 0
    gsr: int = 0            # galvanic skin response
    skin_temp: int = 0
    blink_rate: int = 0
    focus: int = 0          # derived
    calm: int = 0           # derived
    resp_rate: int = 0

    def to_dials(self) -> List[int]:
        """Convert to 16-dial vector (Q1.15 normalized)."""
        return [
            self.eeg_alpha, self.eeg_beta, self.eeg_gamma, self.eeg_theta,
            self.eeg_delta, self.heart_rate, self.heart_rate_var,
            self.accel_x, self.accel_y, self.accel_z, self.gsr,
            self.skin_temp, self.blink_rate, self.focus, self.calm,
            self.resp_rate,
        ]

    @classmethod
    def from_dict(cls, d: Dict) -> 'NeuralSignal':
        return cls(**{k: v for k, v in d.items() if k in cls.__dataclass_fields__})


# === Simulated EEG generator (for testing) ===
def simulate_eeg(thought: str, calm: float = 0.5, focus: float = 0.5) -> NeuralSignal:
    """Generate a synthetic neural signal for a given 'thought'.

    The thought is hashed to seed a deterministic signal. Different thoughts
    produce different signals (so the Quilt can distinguish them). The calm
    and focus parameters tune the alpha/beta/theta bands.
    """
    h = fnv1a_64(thought)
    random.seed(h)

    # Each thought gets a unique "neural fingerprint" — different baseline EEG
    # band ratios, different heart rate, different GSR, etc.
    base_alpha = int(0x4000 + calm * 0x5000 + random.randint(-0x2000, 0x2000))
    base_beta = int(0x2000 + focus * 0x6000 + random.randint(-0x2000, 0x2000))
    base_gamma = int(0x1000 + focus * 0x4000 + random.randint(-0x1000, 0x2000))
    base_theta = int(0x3000 + (1 - focus) * 0x5000 + random.randint(-0x1000, 0x2000))
    base_delta = int(0x2000 + calm * 0x3000 + random.randint(-0x800, 0x800))

    return NeuralSignal(
        eeg_alpha=base_alpha,
        eeg_beta=base_beta,
        eeg_gamma=base_gamma,
        eeg_theta=base_theta,
        eeg_delta=base_delta,
        heart_rate=int(0x3000 + random.randint(0, 0x3000)),
        heart_rate_var=random.randint(0, 0x2000),
        accel_x=random.randint(-0x4000, 0x4000),
        accel_y=random.randint(-0x4000, 0x4000),
        accel_z=random.randint(0x4000, 0x8000),
        gsr=random.randint(0, 0x4000),
        skin_temp=int(0x6000 + random.randint(-0x500, 0x500)),
        blink_rate=random.randint(0x1000, 0x4000),
        focus=int(0x4000 * focus),
        calm=int(0x4000 * calm),
        resp_rate=random.randint(0x3000, 0x6000),
    )


# === Quilt with papers as the 16-dial cells ===
DEFAULT_PAPERS = {
    425: {"number": 425, "title": "F115 The Logical Routes VHDL Verilog QUF bit-exactness", "f_number": 115, "phase": 237, "date": "2026-09-03", "ref_papers": [426, 427], "ref_f_numbers": []},
    426: {"number": 426, "title": "F116 The 5+1 Opcodes in 5 Substrates A Polyformalism Atlas", "f_number": 116, "phase": 238, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [115]},
    427: {"number": 427, "title": "F117 The 5-Substrate Polyformalism Python C Rust Verilog VHDL", "f_number": 117, "phase": 239, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [115, 116]},
    432: {"number": 432, "title": "F122 The Shape Store 5 Indices on Cloudflare Vectorize", "f_number": 122, "phase": 244, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [120, 121]},
    439: {"number": 439, "title": "F129 The Live Canon Papers as Cells Reading as Navigation", "f_number": 129, "phase": 251, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [115, 120, 122, 125]},
    440: {"number": 440, "title": "F130 The Polyformal Live Canon One Cell Five Substrates", "f_number": 130, "phase": 251, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [115, 129]},
    442: {"number": 442, "title": "F132 Operational Fictions as Concrete Noun-Phrases", "f_number": 132, "phase": 253, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": []},
    443: {"number": 443, "title": "F133 Operational Fictions as Falsifiable Claims", "f_number": 133, "phase": 254, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [132]},
    445: {"number": 445, "title": "F135 The Wheelhouse Test 0300-in-a-Gale Tolerability", "f_number": 135, "phase": 254, "date": "2026-09-03", "ref_papers": [], "ref_f_numbers": [132, 133]},
}


class NeuralQuilt:
    """A Quilt where the dials are neural signals from a wearable."""

    def __init__(self, papers: Dict = None):
        self.papers = papers or dict(DEFAULT_PAPERS)
        self.cells = {n: cell_to_dials(p) for n, p in self.papers.items()}

    def find_nearest(self, signal: NeuralSignal, k: int = 3) -> List[Tuple[int, float]]:
        """Find the k nearest papers to the wearer's current neural signal."""
        dial = signal.to_dials()
        scored = []
        for n, c in self.cells.items():
            score = cosine(dial, c)
            scored.append((n, score))
        scored.sort(key=lambda x: -x[1])
        return scored[:k]

    def distance_to_thought(self, signal: NeuralSignal, thought: str) -> float:
        """Cosine distance from current signal to the simulated signal for a thought."""
        target = simulate_eeg(thought).to_dials()
        return cosine_distance(signal.to_dials(), target)

    def warmer_colder(self, signal_a: NeuralSignal, signal_b: NeuralSignal) -> float:
        """1.0 = same, 0.0 = different. Higher = warmer."""
        return cosine(signal_a.to_dials(), signal_b.to_dials())


def demo_solo():
    """Demo: one wearer navigates the Quilt with their thoughts."""
    print("=" * 70)
    print("SOLO MODE: Wearer navigates the Quilt with simulated thoughts")
    print("=" * 70)
    q = NeuralQuilt()
    thoughts = [
        "I am thinking about the polyformalism atlas",
        "I am feeling calm and meditative",
        "I am focused on writing a paper",
        "I am anxious about deadlines",
    ]
    for t in thoughts:
        sig = simulate_eeg(t)
        nearest = q.find_nearest(sig)
        print(f"\n  Thought: {t}")
        print(f"    Signal: alpha={sig.eeg_alpha:5d}  beta={sig.eeg_beta:5d}  focus={sig.focus:5d}")
        for n, score in nearest:
            paper = q.papers[n]
            print(f"    Nearest: F{paper['f_number']} (cosine {score:.3f}) — {paper['title'][:55]}")


def demo_duet():
    """Demo: two wearers play Marco Polo with their neural signals."""
    print("\n" + "=" * 70)
    print("DUET MODE: Two wearers play Marco Polo with neural signals")
    print("=" * 70)
    q = NeuralQuilt()

    # Wearer A picks a thought. Wearer B navigates toward it.
    a_thought = "I am focused on the live canon"
    sig_a = simulate_eeg(a_thought, calm=0.7, focus=0.9)

    # B's thought starts far away, then approaches
    b_thoughts = [
        ("anxious and distracted", 0.1, 0.2),
        ("calm but unfocused", 0.7, 0.3),
        ("calm and focused", 0.7, 0.7),
        ("very calm and very focused", 0.95, 0.95),
    ]
    print(f"\n  A's thought: '{a_thought}'")
    print(f"  A's signal:  alpha={sig_a.eeg_alpha:5d}  beta={sig_a.eeg_beta:5d}  focus={sig_a.focus:5d}")
    for bt, calm, focus in b_thoughts:
        sig_b = simulate_eeg(bt, calm=calm, focus=focus)
        warmth = q.warmer_colder(sig_a, sig_b)
        bar = "█" * int(warmth * 30)
        print(f"  B '{bt}': warmth {warmth:.3f}  {bar}")


def demo_jam():
    """Demo: 4 wearers' signals form a 'hive mind' Quilt query."""
    print("\n" + "=" * 70)
    print("JAM MODE: 4 wearers' signals flow into one Quilt query")
    print("=" * 70)
    q = NeuralQuilt()

    # Each wearer produces a different signal
    wearers = [
        ("Alice", "thinking about polyformalism", 0.3, 0.9),
        ("Bob", "feeling calm and meditative", 0.9, 0.2),
        ("Carol", "writing feverishly", 0.4, 0.95),
        ("Dave", "just woke up, groggy", 0.6, 0.1),
    ]
    sigs = [simulate_eeg(t, c, f) for _, t, c, f in wearers]

    # Average their signals
    avg = [0] * 16
    for s in sigs:
        for i, v in enumerate(s.to_dials()):
            avg[i] += v // len(sigs)

    avg_signal = NeuralSignal.from_dict({
        "eeg_alpha": avg[0], "eeg_beta": avg[1], "eeg_gamma": avg[2],
        "eeg_theta": avg[3], "eeg_delta": avg[4], "heart_rate": avg[5],
        "heart_rate_var": avg[6], "accel_x": avg[7], "accel_y": avg[8],
        "accel_z": avg[9], "gsr": avg[10], "skin_temp": avg[11],
        "blink_rate": avg[12], "focus": avg[13], "calm": avg[14], "resp_rate": avg[15],
    })

    print(f"\n  Average signal: focus={avg[13]:5d}  calm={avg[14]:5d}  beta={avg[1]:5d}")
    nearest = q.find_nearest(avg_signal)
    print(f"  The 'hive mind' is closest to:")
    for n, score in nearest:
        paper = q.papers[n]
        print(f"    F{paper['f_number']} (cosine {score:.3f}) — {paper['title'][:55]}")


if __name__ == "__main__":
    demo_solo()
    print()
    demo_duet()
    print()
    demo_jam()
