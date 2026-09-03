"""human_model.py — the conscious model the player has of themselves.

This is the *internal* state — what the player thinks they are doing,
how they think they feel, what they think their performance is.
Narrow. Verbalizable. Conscious.

The model's job is to be wrong. The negative space is found by
comparing this model to the actual body stream.

A model has:
  - declared goals (what am I trying to do?)
  - perceived state (how do I think I'm doing?)
  - self-reported measures (focus, fatigue, mood, confidence)
  - predictions (what do I expect to happen next?)

Each of these is a 0-32767 dial. Same encoding as Quilt cells.
"""
from __future__ import annotations
import json
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional


# 16 dials of the conscious model
@dataclass
class HumanModel:
    """What the player thinks is happening."""

    # Declared goals (4 dials)
    goal_focus: int = 16384        # 0 = scattered, 32767 = single-pointed
    goal_skill: int = 16384        # 0 = learning, 32767 = expert
    goal_pace: int = 16384         # 0 = slow, 32767 = fast
    goal_risk: int = 16384         # 0 = conservative, 32767 = bold

    # Perceived state (4 dials)
    perc_focus: int = 16384        # how focused do I feel?
    perc_fatigue: int = 8192       # how tired do I feel? (inverted: high = tired)
    perc_mood: int = 24576         # how's my mood? (high = good)
    perc_confidence: int = 16384   # how confident do I feel?

    # Self-reported (4 dials)
    self_focus: int = 16384        # "I am focused" (self-rating)
    self_calm: int = 16384         # "I am calm" (self-rating)
    self_effort: int = 16384        # "I am trying hard" (self-rating)
    self_clarity: int = 16384      # "I understand the situation" (self-rating)

    # Predictions (4 dials)
    pred_will_win: int = 16384     # how likely I think I am to win (0-32767 = 0-100%)
    pred_next_score: int = 16384   # what I think my next score will be
    pred_duration: int = 16384     # how long I think I can keep this up
    pred_outcome: int = 16384      # what I think the overall outcome will be

    def to_dials(self) -> List[int]:
        """The model's 16 dials — the conscious signal."""
        return [
            self.goal_focus, self.goal_skill, self.goal_pace, self.goal_risk,
            self.perc_focus, self.perc_fatigue, self.perc_mood, self.perc_confidence,
            self.self_focus, self.self_calm, self.self_effort, self.self_clarity,
            self.pred_will_win, self.pred_next_score, self.pred_duration, self.pred_outcome,
        ]

    @classmethod
    def from_dials(cls, dials: List[int]) -> 'HumanModel':
        """Reconstruct a model from 16 dials."""
        defaults = cls()
        d = defaults.to_dials()
        dials = dials + d[len(dials):] if len(dials) < 16 else dials
        return cls(
            goal_focus=dials[0], goal_skill=dials[1], goal_pace=dials[2], goal_risk=dials[3],
            perc_focus=dials[4], perc_fatigue=dials[5], perc_mood=dials[6], perc_confidence=dials[7],
            self_focus=dials[8], self_calm=dials[9], self_effort=dials[10], self_clarity=dials[11],
            pred_will_win=dials[12], pred_next_score=dials[13], pred_duration=dials[14], pred_outcome=dials[15],
        )

    def to_dict(self) -> Dict:
        return asdict(self)


# 16 dials of the body — the actual physiological state
@dataclass
class BodyState:
    """What the body is actually doing — the ground truth stream."""

    # EEG (5)
    eeg_alpha: int = 16384
    eeg_beta: int = 16384
    eeg_gamma: int = 16384
    eeg_theta: int = 16384
    eeg_delta: int = 16384

    # Cardiac (2)
    heart_rate: int = 12288
    heart_rate_var: int = 4096

    # Motion (3)
    accel_x: int = 16384
    accel_y: int = 16384
    accel_z: int = 24576

    # Skin / eye (3)
    gsr: int = 8192                # galvanic skin response
    skin_temp: int = 24576
    blink_rate: int = 8192

    # Voice (1)
    voice_freq: int = 16384         # dominant frequency of voice

    # Pupil (1) — infrared
    pupil_dilation: int = 16384     # higher = more dilated

    # Posture (1)
    posture_tension: int = 8192     # higher = more tense

    def to_dials(self) -> List[int]:
        return [
            self.eeg_alpha, self.eeg_beta, self.eeg_gamma, self.eeg_theta, self.eeg_delta,
            self.heart_rate, self.heart_rate_var,
            self.accel_x, self.accel_y, self.accel_z,
            self.gsr, self.skin_temp, self.blink_rate,
            self.voice_freq, self.pupil_dilation, self.posture_tension,
        ]


# The game state — the *known* score and behavior
@dataclass
class GameState:
    """The ground truth from the game's internal logic."""

    score: int = 0                  # current score
    accuracy: float = 0.0           # 0-1
    reaction_time_ms: int = 0      # last reaction time
    actions: int = 0               # total actions
    errors: int = 0                # total errors
    duration_s: int = 0            # how long the game has been going
    win: bool = False
    game: str = "tetris"           # which game

    def to_dict(self) -> Dict:
        return asdict(self)


# An entry in the double-entry ledger
@dataclass
class LedgerEntry:
    """A single entry in the back-trading double-entry ledger.

    Every physiological signal MUST have a corresponding state change.
    Every score change MUST have a corresponding physiological correlate.
    The ledger is symmetric — credits and debits must balance.
    """
    timestamp_ms: int
    source: str           # 'body' or 'game' or 'model'
    account: str          # which account (e.g., 'alpha', 'heart_rate', 'score')
    debit: int = 0        # what went out
    credit: int = 0       # what came in
    description: str = ""
    related_entry_id: Optional[int] = None

    def to_dict(self) -> Dict:
        return asdict(self)


def example():
    """Quick demo of the 3-layer model."""
    m = HumanModel(perc_focus=28000, self_focus=30000, self_calm=25000)
    print("Player's conscious model:")
    print(f"  perceived focus:  {m.perc_focus} (~{m.perc_focus/327:.0f}%)")
    print(f"  self-rated focus: {m.self_focus} (~{m.self_focus/327:.0f}%)")
    print(f"  self-rated calm:  {m.self_calm} (~{m.self_calm/327:.0f}%)")
    print(f"  prediction of winning: {m.pred_will_win/327:.0f}%")
    print()

    b = BodyState(eeg_alpha=8192, heart_rate=22000, gsr=28000, pupil_dilation=30000)
    print("Player's actual body:")
    print(f"  alpha:  {b.eeg_alpha} (~{b.eeg_alpha/327:.0f}%)  ← low alpha = anxious, NOT focused")
    print(f"  HR:     {b.heart_rate} (~{b.heart_rate/327:.0f}%)  ← high HR = aroused, not calm")
    print(f"  GSR:    {b.gsr} (~{b.gsr/327:.0f}%)  ← high GSR = sweating, stressed")
    print(f"  pupil:  {b.pupil_dilation} (~{b.pupil_dilation/327:.0f}%)  ← dilated = aroused")
    print()
    print("THE NEGATIVE SPACE:")
    print("  Player says: 'I am focused and calm' (model)")
    print("  Body says:    'You are aroused and stressed' (stream)")
    print("  → The player is performing while burning out.")


if __name__ == "__main__":
    example()
