"""double_entry.py — back-trading double-entry relational bookkeeping.

Every entry in this ledger MUST have a counterpart. The double-entry
accounting invariant: the sum of debits equals the sum of credits.

For the human-model system:
  - A score increase in the game MUST have a corresponding physiological
    correlate (heart rate spike, focus dip, etc.)
  - A physiological spike MUST have a corresponding behavioral correlate
    (action, error, pause, etc.)
  - A self-reported "I am focused" MUST correspond to an actual focus
    signal, OR be recorded as a "leak" — the player is reporting focus
    they don't have

The ledger finds LEAKS: places where the three streams don't match.
The leaks ARE the negative space.
"""
from __future__ import annotations
import json, time, math
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple
from human_model import HumanModel, BodyState, GameState, LedgerEntry


class DoubleEntryLedger:
    """The accounting ledger for the model-body-game triad."""

    def __init__(self):
        self.entries: List[LedgerEntry] = []
        self._next_id = 0

    def add(self, source: str, account: str, debit: int = 0, credit: int = 0,
            description: str = "", ts_ms: int = None) -> int:
        """Add a single entry. Returns the entry id."""
        if ts_ms is None:
            ts_ms = int(time.time() * 1000)
        e = LedgerEntry(
            timestamp_ms=ts_ms,
            source=source,
            account=account,
            debit=debit,
            credit=credit,
            description=description,
        )
        self.entries.append(e)
        eid = self._next_id
        self._next_id += 1
        return eid

    def pair(self, source_a: str, account_a: str, source_b: str, account_b: str,
             amount: int, description: str = "") -> Tuple[int, int]:
        """Add a paired entry (credit in one, debit in the other)."""
        ts = int(time.time() * 1000)
        id_a = self.add(source_a, account_a, credit=amount, description=description, ts_ms=ts)
        id_b = self.add(source_b, account_b, debit=amount, description=description, ts_ms=ts)
        # Link them
        self.entries[id_a].related_entry_id = id_b
        self.entries[id_b].related_entry_id = id_a
        return (id_a, id_b)

    def balance(self) -> Dict:
        """Compute the balance per account. Should be ~0 for a healthy system."""
        balance = {}
        for e in self.entries:
            if e.account not in balance:
                balance[e.account] = 0
            balance[e.account] += e.credit - e.debit
        return balance

    def leaks(self, threshold: int = 5000) -> List[Dict]:
        """Find accounts that are out of balance beyond the threshold.

        A leak is an account that has accumulated credits or debits
        without a corresponding counterpart. The leak is the negative
        space — the gap between the streams.
        """
        b = self.balance()
        out = []
        for account, balance in b.items():
            if abs(balance) > threshold:
                # Find which sources contributed
                credits = sum(e.credit for e in self.entries if e.account == account)
                debits = sum(e.debit for e in self.entries if e.account == account)
                out.append({
                    "account": account,
                    "balance": balance,
                    "credits": credits,
                    "debits": debits,
                    "leak_direction": "credit" if balance > 0 else "debit",
                })
        return sorted(out, key=lambda x: -abs(x["balance"]))

    def as_dict(self) -> List[Dict]:
        return [e.to_dict() for e in self.entries]


def negative_space(model: HumanModel, body: BodyState, game: GameState) -> Dict:
    """Compute the negative space — the gaps between model, body, and game.

    Returns a structured report of where the streams don't match.
    """
    leaks = {}

    # 1. "I am focused" (model) vs actual alpha/beta ratio (body)
    perceived_focus = model.perc_focus / 327.67  # 0-100
    actual_focus_proxy = (body.eeg_beta / 327.67 * 0.6 + body.eeg_alpha / 327.67 * 0.4)
    focus_gap = perceived_focus - actual_focus_proxy
    if abs(focus_gap) > 10:  # more than 10% gap
        leaks["focus"] = {
            "claimed": f"{perceived_focus:.0f}%",
            "actual": f"{actual_focus_proxy:.0f}%",
            "gap": f"{focus_gap:+.0f}%",
            "interpretation": "OVER-CLAIM: thinking you're more focused than you are" if focus_gap > 0
                            else "UNDER-CLAIM: thinking you're less focused than you are",
        }

    # 2. "I am calm" (model) vs heart rate / GSR (body)
    perceived_calm = model.self_calm / 327.67
    actual_calm_proxy = 100 - (body.heart_rate / 327.67 * 0.5 + body.gsr / 327.67 * 0.5)
    calm_gap = perceived_calm - actual_calm_proxy
    if abs(calm_gap) > 10:
        leaks["calm"] = {
            "claimed": f"{perceived_calm:.0f}%",
            "actual": f"{actual_calm_proxy:.0f}%",
            "gap": f"{calm_gap:+.0f}%",
            "interpretation": "OVER-CLAIM: thinking you're calmer than you are" if calm_gap > 0
                            else "UNDER-CLAIM: thinking you're less calm than you are",
        }

    # 3. "I will win" (model) vs game score (game)
    pred_win = model.pred_will_win / 327.67
    # For demo: use accuracy as a proxy for actual win likelihood
    actual_win_proxy = game.accuracy * 100 if game.actions > 0 else 0
    win_gap = pred_win - actual_win_proxy
    if abs(win_gap) > 15:
        leaks["winning"] = {
            "claimed": f"{pred_win:.0f}%",
            "actual": f"{actual_win_proxy:.0f}% (accuracy)",
            "gap": f"{win_gap:+.0f}%",
            "interpretation": "OVER-CONFIDENT: predicting you'll win more than the game suggests" if win_gap > 0
                            else "UNDER-CONFIDENT: predicting you'll win less than the game suggests",
        }

    # 4. "I can keep this up" (model duration prediction) vs fatigue (body + game)
    # pred_duration: 0-32767 maps to 0-120 minutes (a reasonable game session)
    # Correct: pred_duration / 32767 * 120 (not / 327.67!)
    pred_duration_min = model.pred_duration / 32767 * 120
    # Fatigue model: 0-100 scale, where 100 = exhausted
    # Component 1: sympathetic arousal (HR + GSR) → 0-40
    arousal = min(40, (body.heart_rate / 32767) * 20 + (body.gsr / 32767) * 20)
    # Component 2: time on task → 0-30 (capped at 60 min = full)
    time_load = min(30, (game.duration_s / 60) * 0.5)
    # Component 3: error rate → 0-30
    error_rate = (game.errors / max(1, game.actions)) * 100
    error_load = min(30, error_rate)
    fatigue = arousal + time_load + error_load
    # Fatigue > 100 = exhausted. 100 fatigue = 0 remaining
    remaining_min = max(0, 100 - fatigue)
    duration_gap = pred_duration_min - remaining_min
    if abs(duration_gap) > 5:
        leaks["sustainability"] = {
            "claimed": f"{pred_duration_min:.0f} more min",
            "actual": f"~{remaining_min:.0f} more min (fatigue {fatigue:.0f}/100)",
            "gap": f"{duration_gap:+.0f} min",
            "interpretation": "OVER-ESTIMATE: thinking you can sustain longer than physiology suggests" if duration_gap > 0
                            else "UNDER-ESTIMATE: you're being more conservative than you need to be",
        }

    # 5. Hidden: effort (model) vs reaction_time (game)
    effort = model.self_effort / 327.67
    if game.reaction_time_ms > 0 and game.actions > 5:
        # 200ms = baseline, 500ms = slow, 1000ms = exhausted
        if game.reaction_time_ms > 600 and effort > 70:
            leaks["effort_vs_reaction"] = {
                "claimed": f"{effort:.0f}% effort",
                "actual": f"reaction time {game.reaction_time_ms}ms (slow)",
                "gap": "claimed high effort, but reactions are slow",
                "interpretation": "EFFORT WITHOUT YIELD: trying hard but not converting effort into speed",
            }

    return {
        "leaks": leaks,
        "n_leaks": len(leaks),
        "interpretation": _overall_interpretation(leaks),
    }


def _overall_interpretation(leaks: Dict) -> str:
    """One-sentence overall read of the leaks."""
    if not leaks:
        return "The model and the body are aligned. The player is in integrity."

    overclaims = sum(1 for v in leaks.values()
                     if v.get("interpretation", "").startswith("OVER-"))
    underclaims = sum(1 for v in leaks.values()
                      if v.get("interpretation", "").startswith("UNDER-"))

    if overclaims >= 2 and overclaims > underclaims:
        return "The player is over-claiming. Body and game say one thing; the conscious model says another. Burnout risk."
    if underclaims >= 2 and underclaims > overclaims:
        return "The player is under-claiming. The model is more conservative than the body and game suggest. False modesty or hidden capacity."
    if leaks.get("effort_vs_reaction"):
        return "Effort without yield. The player is trying but the conversion to performance is breaking down."
    return f"Mixed signals — {len(leaks)} gaps between model, body, and game. The player is not in integrity."


# === Demonstration: a player who's performing well but burning out ===
def demo_burnout():
    """The classic case: 95% accuracy, but the body is in overdrive."""
    model = HumanModel(
        perc_focus=28000,      # "I'm 85% focused"
        self_focus=30000,      # "I am very focused"
        self_calm=25000,       # "I am calm"
        self_effort=28000,     # "I'm trying hard"
        pred_will_win=22000,   # "67% chance of winning"
        pred_duration=24000,   # "I can do this for 44 min"
    )
    body = BodyState(
        eeg_alpha=8192,        # LOW alpha = anxious, not calm
        eeg_beta=25000,        # HIGH beta = mentally overdriven
        eeg_gamma=18000,
        eeg_theta=12000,       # LOW theta = not meditative
        eeg_delta=4096,
        heart_rate=22000,      # HIGH HR = physiologically aroused
        heart_rate_var=8000,   # HRV spiking
        gsr=28000,             # HIGH GSR = sweating, stressed
        pupil_dilation=30000,  # HIGH pupil = aroused
        posture_tension=22000, # tense posture
    )
    game = GameState(
        score=950,
        accuracy=0.95,
        reaction_time_ms=180,
        actions=240,
        errors=12,
        duration_s=1800,       # 30 min in
    )

    print("=" * 70)
    print("DEMO: Player performing 95% but body is in overdrive")
    print("=" * 70)
    print()
    print("MODEL (conscious):")
    print(f"  'I am {model.self_focus/327:.0f}% focused and {model.self_calm/327:.0f}% calm'")
    print(f"  'I will win {model.pred_will_win/327:.0f}%'")
    print(f"  'I can sustain {model.pred_duration/327*60:.0f} minutes'")
    print()
    print("BODY (actual):")
    print(f"  alpha={body.eeg_alpha/327:.0f}% (low = ANXIOUS)")
    print(f"  beta={body.eeg_beta/327:.0f}% (high = OVERDRIVEN)")
    print(f"  HR={body.heart_rate/327:.0f}% (high = AROUSED)")
    print(f"  GSR={body.gsr/327:.0f}% (high = STRESSED)")
    print(f"  pupil={body.pupil_dilation/327:.0f}% (dilated = AROUSED)")
    print()
    print("GAME (ground truth):")
    print(f"  accuracy={game.accuracy*100:.0f}%, score={game.score}, RT={game.reaction_time_ms}ms")
    print()
    print("=" * 70)
    print("NEGATIVE SPACE — the leaks")
    print("=" * 70)

    ns = negative_space(model, body, game)
    for k, v in ns["leaks"].items():
        print(f"\n  [{k}]")
        for kk, vv in v.items():
            print(f"    {kk}: {vv}")
    print()
    print(f"  N leaks: {ns['n_leaks']}")
    print(f"  Overall: {ns['interpretation']}")


# === Demonstration: a player who's performing badly but is calm and capable ===
def demo_underconfident():
    """A player who's fine but thinks they're failing."""
    model = HumanModel(
        perc_focus=10000,      # "I'm 30% focused"
        self_focus=8000,       # "I am unfocused"
        self_calm=8000,        # "I am anxious"
        self_effort=12000,     # "I'm not trying"
        pred_will_win=4000,    # "12% chance of winning"
        pred_duration=8000,    # "I can do this for 15 min"
    )
    body = BodyState(
        eeg_alpha=22000,       # HIGH alpha = CALM
        eeg_beta=12000,        # low beta = not overdriven
        eeg_gamma=10000,
        eeg_theta=20000,       # HIGH theta = meditative, focused
        eeg_delta=8000,
        heart_rate=14000,      # normal-ish
        heart_rate_var=4000,
        gsr=8000,              # low GSR = calm
        pupil_dilation=14000,  # normal
        posture_tension=10000, # relaxed
    )
    game = GameState(
        score=420,
        accuracy=0.84,
        reaction_time_ms=220,
        actions=180,
        errors=28,
        duration_s=900,        # 15 min in
    )

    print()
    print("=" * 70)
    print("DEMO: Player performing 84% but model says 'I am failing'")
    print("=" * 70)
    print()
    print("MODEL (conscious):")
    print(f"  'I am {model.self_focus/327:.0f}% focused and {model.self_calm/327:.0f}% calm'")
    print(f"  'I will win {model.pred_will_win/327:.0f}%'")
    print()
    print("BODY (actual):")
    print(f"  alpha={body.eeg_alpha/327:.0f}% (HIGH = CALM, FOCUSED)")
    print(f"  theta={body.eeg_theta/327:.0f}% (HIGH = MEDITATIVE)")
    print()
    print("GAME (ground truth):")
    print(f"  accuracy={game.accuracy*100:.0f}%, score={game.score}")
    print()

    ns = negative_space(model, body, game)
    print("NEGATIVE SPACE:")
    for k, v in ns["leaks"].items():
        print(f"\n  [{k}]")
        for kk, vv in v.items():
            print(f"    {kk}: {vv}")
    print(f"\n  Overall: {ns['interpretation']}")


# === Demonstration: integrity ===
def demo_integrity():
    """A player whose model, body, and game all agree."""
    model = HumanModel(
        perc_focus=20000, self_focus=20000, self_calm=20000, self_effort=20000,
        pred_will_win=16000, pred_duration=20000,
    )
    body = BodyState(
        eeg_alpha=20000, eeg_beta=20000, eeg_gamma=14000, eeg_theta=16000,
        eeg_delta=8000, heart_rate=14000, heart_rate_var=4000,
        gsr=12000, skin_temp=24000, blink_rate=8000,
        voice_freq=16000, pupil_dilation=18000, posture_tension=12000,
    )
    game = GameState(
        score=500, accuracy=0.88, reaction_time_ms=220, actions=200, errors=24, duration_s=900,
    )
    print()
    print("=" * 70)
    print("DEMO: Player in integrity — model, body, game all agree")
    print("=" * 70)
    ns = negative_space(model, body, game)
    print(f"  N leaks: {ns['n_leaks']}")
    print(f"  Overall: {ns['interpretation']}")


if __name__ == "__main__":
    demo_burnout()
    demo_underconfident()
    demo_integrity()
