"""back_deck_game.py — The Back-Deck Game.

A gamified simulator of the back deck of a commercial fishing boat.

The back deck is where fish are landed, gaffed, dehooked, bled, and cleaned.
A skilled deckhand's hand choreography is:
  1. Sight the fish
  2. Gaff (the hook-and-pole motion to bring the fish aboard)
  3. Dehook (remove the hook from the fish's mouth)
  4. Bleed (cut the gills so the fish bleeds out cleanly)
  5. Move to the cleaning station
  6. Clean (gut, descale, fillet)
  7. Ice and stow

A HUMAN hand is limited: 5 fingers, 1 wrist orientation, 1 grip strength.
A ROBOT arm could be:
  - gaff + dehooker + bleed-cutter built in
  - net-bleed (a mesh net that holds and bleeds simultaneously)
  - cleaning station with knife + spoon + water-hose attachment
  - dehooking with a thick hook (no fine-motor needed)

The GAME captures this:

  SCORE  = (safety * 0.4) + (quality * 0.3) + (time * 0.2) + (efficiency * 0.1)
  P0     = safety (always — injuries on deck are catastrophic)
  HAND-SKILL = a sequence of gestures read by the camera (Mudra bands or webcam)

The MOTION LIBRARY is the gold standard. The robot's motions are the reference.
A new crew member trains to match the robot's reference, not the human's.

  Gesture vocabulary (deck-ops):
    G1: gaff-swing     (full arm swing, gaff tip traces a J)
    G2: dehook-pull    (twist + pull, hook releases from jaw)
    G3: gill-cut       (knife to gills, slice)
    G4: bleed-hold     (hold fish over the deck scupper, 8 sec)
    G5: stow-arc       (carry the fish to the hold, arc motion)
    G6: scrub-down     (clean the deck of blood, hose + brush)
    G7: idle           (no action, scored as time-loss)

The simulator runs in the browser (webcam + JS), scores each gesture in
real-time, and gives a level-up tree for the crew.
"""
from __future__ import annotations
import json, time, math, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple


# The deck-ops gesture vocabulary
DECK_GESTURES = {
    "G1_gaff_swing":  {"duration_ms": 1500, "safety_risk": 0.7,  "skill_points": 10},
    "G2_dehook_pull": {"duration_ms": 800,  "safety_risk": 0.5,  "skill_points": 8},
    "G3_gill_cut":    {"duration_ms": 600,  "safety_risk": 0.6,  "skill_points": 6},
    "G4_bleed_hold":  {"duration_ms": 8000, "safety_risk": 0.2,  "skill_points": 4},
    "G5_stow_arc":    {"duration_ms": 2500, "safety_risk": 0.4,  "skill_points": 7},
    "G6_scrub_down":  {"duration_ms": 4000, "safety_risk": 0.3,  "skill_points": 5},
    "G7_idle":        {"duration_ms": 1000, "safety_risk": 0.0,  "skill_points": 0},
}


# The robot's gold-standard motion (the reference crew train to)
GOLD_STANDARD = {
    "G1_gaff_swing":  {"smoothness": 0.95, "precision": 0.98, "speed": 0.85},
    "G2_dehook_pull": {"smoothness": 0.92, "precision": 0.97, "speed": 0.88},
    "G3_gill_cut":    {"smoothness": 0.98, "precision": 0.99, "speed": 0.80},
    "G4_bleed_hold":  {"smoothness": 1.00, "precision": 1.00, "speed": 0.95},
    "G5_stow_arc":    {"smoothness": 0.94, "precision": 0.95, "speed": 0.90},
    "G6_scrub_down":  {"smoothness": 0.93, "precision": 0.96, "speed": 0.85},
}


@dataclass
class Fish:
    """A fish on the deck — being processed."""
    id: int
    species: str            # "tuna", "halibut", "rockfish"
    weight_kg: float
    quality: float          # 0-1, higher = better
    state: str = "in_water"  # in_water, gaffed, dehooked, bled, cleaned, stowed
    bleeding_done: bool = False
    gill_cut_done: bool = False
    started_ms: int = 0

    def to_dict(self): return asdict(self)


@dataclass
class GestureAttempt:
    """A single gesture attempt by the crew member."""
    crew_id: str
    gesture: str             # G1, G2, G3, G4, G5, G6, G7
    timestamp_ms: int
    smoothness: float        # 0-1, vs gold standard
    precision: float         # 0-1, vs gold standard
    speed: float             # 0-1, vs gold standard
    safety_score: float      # 0-1, did they hurt themselves / the fish?
    points: int              # skill points earned

    def to_dict(self): return asdict(self)

    def score(self) -> float:
        """Composite score for this gesture (0-1, 1 = gold standard)."""
        gold = GOLD_STANDARD.get(self.gesture, {"smoothness": 1, "precision": 1, "speed": 1})
        s = (self.smoothness / gold["smoothness"]) * 0.4
        p = (self.precision / gold["precision"]) * 0.4
        sp = (self.speed / gold["speed"]) * 0.2
        return min(1.0, (s + p + sp) * self.safety_score)


@dataclass
class CrewMember:
    """A crew member with a skill tree."""
    id: str
    name: str
    level: int = 1
    xp: int = 0
    xp_to_next: int = 100
    skills: Dict[str, float] = field(default_factory=dict)  # G1, G2, ... → 0-1 mastery

    def to_dict(self): return asdict(self)

    def award_xp(self, points: int):
        self.xp += points
        leveled = False
        while self.xp >= self.xp_to_next:
            self.xp -= self.xp_to_next
            self.level += 1
            self.xp_to_next = int(self.xp_to_next * 1.5)
            leveled = True
        return leveled


@dataclass
class BackDeckGame:
    """The full back-deck game session."""
    crew: CrewMember
    fish: List[Fish] = field(default_factory=list)
    attempts: List[GestureAttempt] = field(default_factory=list)
    session_start_ms: int = field(default_factory=lambda: int(time.time() * 1000))

    # Scores
    safety_score: float = 1.0
    quality_score: float = 0.0
    time_score: float = 0.0
    efficiency_score: float = 0.0
    n_injuries: int = 0

    def to_dict(self):
        return {
            "crew": self.crew.to_dict(),
            "n_fish": len(self.fish),
            "n_attempts": len(self.attempts),
            "scores": {
                "safety": self.safety_score,
                "quality": self.quality_score,
                "time": self.time_score,
                "efficiency": self.efficiency_score,
            },
            "n_injuries": self.n_injuries,
        }

    def add_fish(self, fish: Fish):
        self.fish.append(fish)

    def attempt(self, gesture: str, smoothness: float, precision: float,
                speed: float, safety: float = 1.0) -> GestureAttempt:
        """Record a gesture attempt."""
        info = DECK_GESTURES.get(gesture, DECK_GESTURES["G7_idle"])
        points = int(info["skill_points"] * smoothness * precision * safety)
        a = GestureAttempt(
            crew_id=self.crew.id,
            gesture=gesture,
            timestamp_ms=int(time.time() * 1000),
            smoothness=smoothness,
            precision=precision,
            speed=speed,
            safety_score=safety,
            points=points,
        )
        self.attempts.append(a)
        # Update skills
        g = self.crew.skills.get(gesture, 0.5)
        self.crew.skills[gesture] = min(1.0, g * 0.9 + a.score() * 0.1)
        # Award XP
        leveled = self.crew.award_xp(points)
        # Update scores
        if safety < 0.7:
            self.n_injuries += 1
            self.safety_score = max(0, self.safety_score - 0.1)
        return a

    def compute_final_score(self) -> Dict:
        """Compute the final weighted score."""
        if not self.attempts:
            return {"score": 0, "weights": {}}
        n_fish = max(1, len(self.fish))
        n_attempts = max(1, len(self.attempts))
        self.time_score = min(1.0, n_fish / 5)  # 5+ fish in session = max time score
        self.quality_score = sum(a.score() for a in self.attempts) / n_attempts
        self.efficiency_score = self.quality_score * (1 - self.n_injuries * 0.1)
        composite = (
            self.safety_score * 0.4 +
            self.quality_score * 0.3 +
            self.time_score * 0.2 +
            self.efficiency_score * 0.1
        )
        return {
            "score": round(composite, 3),
            "weights": {
                "safety":     round(self.safety_score, 3),
                "quality":    round(self.quality_score, 3),
                "time":       round(self.time_score, 3),
                "efficiency": round(self.efficiency_score, 3),
            },
        }


# === Demonstration: a 5-fish session ===
def demo_session():
    crew = CrewMember("crew-01", "Dani the Deckhand")
    # Initialize skills
    for g in DECK_GESTURES:
        crew.skills[g] = 0.5

    game = BackDeckGame(crew)
    # Add 5 fish
    for i in range(5):
        game.add_fish(Fish(id=i+1, species="tuna", weight_kg=15.0+i*2, quality=0.85))

    print("=" * 70)
    print("BACK-DECK GAME — 5-fish session, 6 gestures per fish")
    print("=" * 70)
    print(f"\nCrew: {crew.name} (level {crew.level}, {crew.xp} XP)")
    print(f"Score weights: safety 40%, quality 30%, time 20%, efficiency 10%")
    print()

    # Simulate 5 fish × 6 gestures
    gesture_sequence = ["G1_gaff_swing", "G2_dehook_pull", "G3_gill_cut",
                        "G4_bleed_hold", "G5_stow_arc", "G6_scrub_down"]

    for fish_id in range(1, 6):
        print(f"FISH {fish_id}:")
        for g in gesture_sequence:
            # Simulate the gesture (with some natural noise)
            base = GOLD_STANDARD[g]
            sm = max(0, min(1, base["smoothness"] + random.uniform(-0.15, 0.10)))
            pr = max(0, min(1, base["precision"]  + random.uniform(-0.10, 0.05)))
            sp = max(0, min(1, base["speed"]      + random.uniform(-0.20, 0.05)))
            # Random safety events
            safety = 1.0 if random.random() > 0.05 else 0.6
            a = game.attempt(g, sm, pr, sp, safety)
            print(f"  {g:18s}  sm={sm:.2f} pr={pr:.2f} sp={sp:.2f} safety={safety:.1f}  +{a.points:2d} XP")

    # Final score
    final = game.compute_final_score()
    print()
    print("=" * 70)
    print("FINAL SCORES")
    print("=" * 70)
    print(f"  Score:    {final['score']:.3f}")
    for k, v in final['weights'].items():
        bar = "█" * int(v * 30)
        print(f"  {k:12s} {v:.3f}  {bar}")
    print()
    print(f"  Crew: {crew.name} → level {crew.level} ({crew.xp} / {crew.xp_to_next} XP)")
    print(f"  Skills: {', '.join(f'{k}={v:.2f}' for k, v in crew.skills.items())}")
    print(f"  Injuries: {game.n_injuries}")
    print()
    print("The robot's gold standard is the reference. The crew member's gestures")
    print("are scored against the gold standard on smoothness, precision, speed.")
    print("Safety events (knocked gaff, slipped knife) tank the safety score.")
    print("The whole thing runs in a browser with a webcam — no Mudra bands required.")


# === Demonstration: a session with intentional overdrive (the burnout pattern) ===
def demo_overdrive():
    print()
    print("=" * 70)
    print("OVERDRIVE — captain at the wheel, body overdriven, hands_on falling")
    print("=" * 70)
    print()
    crew = CrewMember("crew-02", "Overdrive Deckhand")
    for g in DECK_GESTURES:
        crew.skills[g] = 0.5
    game = BackDeckGame(crew)
    for i in range(8):
        game.add_fish(Fish(id=i+1, species="halibut", weight_kg=20+i*2, quality=0.85))

    gesture_sequence = ["G1_gaff_swing", "G2_dehook_pull", "G3_gill_cut",
                        "G4_bleed_hold", "G5_stow_arc", "G6_scrub_down"]

    # Tick 1-3: high precision
    # Tick 4-6: precision starts dropping (fatigue)
    # Tick 7-8: errors, safety events
    for fish_id in range(1, 9):
        fatigue = (fish_id - 1) / 7  # 0 → 1
        for g in gesture_sequence:
            base = GOLD_STANDARD[g]
            sm = max(0, base["smoothness"] - fatigue * 0.3)
            pr = max(0, base["precision"] - fatigue * 0.4)
            sp = max(0, base["speed"] - fatigue * 0.2)
            # Safety drops with fatigue
            safety = 1.0 if random.random() > 0.05 + fatigue * 0.3 else 0.5
            a = game.attempt(g, sm, pr, sp, safety)

    final = game.compute_final_score()
    print(f"  Score: {final['score']:.3f}")
    for k, v in final['weights'].items():
        bar = "█" * int(v * 30)
        print(f"  {k:12s} {v:.3f}  {bar}")
    print(f"  Crew: {crew.name} → level {crew.level} ({crew.xp} XP)")
    print(f"  Injuries: {game.n_injuries}")
    print()
    print("The fatigue-driven quality drop is the SAME signal as F140's burnout")
    print("pattern. The back-deck game is the same negative-space pipeline with")
    print("gestures instead of EEG, and a multi-dimensional score instead of integrity.")


if __name__ == "__main__":
    random.seed(42)
    demo_session()
    demo_overdrive()
