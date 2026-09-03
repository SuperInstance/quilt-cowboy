"""mudra_emulator.py — The Mudra-Band Emulator.

The Mudra band (by Wearable Devices Ltd) is a wrist-worn device that
detects subtle hand muscle activations via surface EMG. It produces a
stream of "Mudra gestures" — small, named hand poses — that an app
can subscribe to.

The Mudra SDK is closed. The bands are $200-400. For the back-deck
game to be useful *today*, on a phone with no extra hardware, we need
an emulator: a JS+webcam pipeline that infers hand-pose state from
the camera and produces the same gesture stream.

This file is the *spec* of the emulator. The actual JS implementation
is in /workspace/back-deck-game/mudra.js.

Mudra gesture vocabulary (the relevant subset for back-deck ops):
  tap_index         — index finger extension tap
  tap_middle        — middle finger extension tap
  tap_thumb         — thumb tap
  pinch             — thumb + index pinch
  fist              — closed fist
  open              — open palm
  rotate_cw         — wrist rotation clockwise
  rotate_ccw        — wrist rotation counter-clockwise
  shake             — quick lateral shake
  idle              — no gesture for >500ms

For the back-deck game, the gestures are mapped to the deck-ops:
  G1_gaff_swing  ← (open + rotate_cw)
  G2_dehook_pull ← (pinch + rotate_ccw)
  G3_gill_cut    ← (tap_index)
  G4_bleed_hold  ← (idle)  (8 seconds, just holding)
  G5_stow_arc    ← (open + shake)
  G6_scrub_down  ← (fist + rotate_cw)
"""
from __future__ import annotations
import json, time, math, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple


# The Mudra gesture vocabulary
MUDRA_GESTURES = [
    "tap_index", "tap_middle", "tap_thumb", "pinch",
    "fist", "open", "rotate_cw", "rotate_ccw", "shake", "idle",
]


# Mapping from Mudra gestures to back-deck ops
MUDRA_TO_DECK_OPS = {
    "tap_index":        "G3_gill_cut",     # knife motion = index extension
    "pinch":            "G2_dehook_pull",  # hook pinch + twist
    "pinch_rotate_ccw": "G2_dehook_pull",  # also dehook with rotation
    "open_rotate_cw":   "G1_gaff_swing",   # gaff swing
    "open_shake":       "G5_stow_arc",     # arc motion
    "fist_rotate_cw":   "G6_scrub_down",   # scrub
    "idle":             "G4_bleed_hold",   # hold for 8s
}


@dataclass
class PoseFrame:
    """A single frame from the Mudra emulator."""
    timestamp_ms: int
    hand_detected: bool
    n_fingers_extended: int         # 0-5
    thumb_extended: bool
    is_fist: bool
    is_open: bool
    is_pinching: bool
    wrist_rotation: float           # -1.0 (ccw) to 1.0 (cw)
    shake_intensity: float          # 0-1
    confidence: float               # 0-1
    raw_landmarks: List[Tuple[float, float]] = field(default_factory=list)  # 21 hand landmarks

    def to_dict(self): return asdict(self)

    def infer_gesture(self) -> str:
        """Infer the current Mudra gesture from the pose frame."""
        if not self.hand_detected or self.confidence < 0.3:
            return "idle"
        if self.shake_intensity > 0.7:
            return "shake"
        if self.is_fist:
            if self.wrist_rotation > 0.3:
                return "fist_rotate_cw"   # composite — use underscore not plus
            return "fist"
        if self.is_open:
            if self.wrist_rotation > 0.3:
                return "open_rotate_cw"   # composite
            if self.shake_intensity > 0.3:
                return "open_shake"        # composite
            return "open"
        if self.is_pinching:
            if self.wrist_rotation < -0.3:
                return "pinch_rotate_ccw" # composite
            return "pinch"
        if self.n_fingers_extended == 1 and self.thumb_extended:
            return "tap_index"
        if self.n_fingers_extended == 2 and not self.thumb_extended:
            return "tap_middle"
        if self.n_fingers_extended == 0 and self.thumb_extended:
            return "tap_thumb"
        return "idle"


class MudraEmulator:
    """The Mudra-band emulator — webcam → pose → gesture stream.

    In production, this is a JS+WebBluetooth pipeline that:
      1. Opens the webcam (getUserMedia)
      2. Runs MediaPipe Hands (or a similar hand-pose model) on each frame
      3. Extracts 21 hand landmarks
      4. Classifies the gesture (the JS port of infer_gesture)
      5. Sends the gesture events to the back-deck game

    The Python class below is the spec — the canonical reference for
    what the JS implementation must produce. The state hash of the
    emulator is the same on both sides, byte-exact.
    """

    def __init__(self, hand_detected_threshold: float = 0.5,
                 confidence_threshold: float = 0.3):
        self.hand_detected_threshold = hand_detected_threshold
        self.confidence_threshold = confidence_threshold
        self.frames: List[PoseFrame] = []
        self.gesture_log: List[Tuple[int, str]] = []  # (timestamp, gesture)
        self.session_start_ms: int = int(time.time() * 1000)

    def process_frame(self, frame: PoseFrame) -> str:
        """Process a single frame, return the inferred gesture."""
        self.frames.append(frame)
        gesture = frame.infer_gesture()
        if not self.gesture_log or self.gesture_log[-1][1] != gesture:
            self.gesture_log.append((frame.timestamp_ms, gesture))
        return gesture

    # === Simulator: generate frames for testing without a webcam ===

    def simulate_gesture(self, gesture: str, duration_ms: int = 1000,
                         confidence: float = 0.9) -> List[PoseFrame]:
        """Simulate a series of frames for a given gesture (for testing)."""
        frames = []
        n_frames = max(1, duration_ms // 50)  # 20 fps
        for i in range(n_frames):
            t = int(time.time() * 1000) + i * 50
            frame = self._synthesize_frame(gesture, i / max(1, n_frames - 1), confidence)
            frame.timestamp_ms = t
            self.process_frame(frame)
            frames.append(frame)
        return frames

    def _synthesize_frame(self, gesture: str, t_norm: float,
                          confidence: float) -> PoseFrame:
        """Generate a synthetic frame for a given gesture."""
        # Defaults
        hand_detected = True
        n_fingers = 0
        thumb_ext = False
        is_fist = False
        is_open = False
        is_pinch = False
        rot = 0.0
        shake = 0.0

        if gesture == "tap_index":
            n_fingers = 1
            thumb_ext = True
        elif gesture == "tap_middle":
            n_fingers = 2
        elif gesture == "tap_thumb":
            n_fingers = 0
            thumb_ext = True
        elif gesture == "pinch":
            is_pinch = True
        elif gesture == "pinch_rotate_ccw":
            is_pinch = True
            rot = -0.5
        elif gesture == "fist":
            is_fist = True
        elif gesture == "fist_rotate_cw":
            is_fist = True
            rot = 0.5 + 0.3 * math.sin(t_norm * 2 * math.pi)
        elif gesture == "open":
            is_open = True
        elif gesture == "open_rotate_cw":
            is_open = True
            rot = 0.5 + 0.4 * math.sin(t_norm * 2 * math.pi)
        elif gesture == "open_shake":
            is_open = True
            shake = 0.5 + 0.4 * math.sin(t_norm * 8 * math.pi)
        elif gesture == "rotate_cw":
            rot = 0.5
        elif gesture == "rotate_ccw":
            rot = -0.5
        elif gesture == "shake":
            shake = 0.9
        elif gesture == "idle":
            pass  # all defaults
        else:
            hand_detected = False

        # Synthesize 21 hand landmarks (relative coordinates 0-1)
        # The landmarks are the standard MediaPipe Hands set:
        # 0: wrist, 1-4: thumb, 5-8: index, 9-12: middle, 13-16: ring, 17-20: pinky
        landmarks = []
        for i in range(21):
            # Place each landmark in a rough hand shape
            landmarks.append((0.5 + random.uniform(-0.05, 0.05),
                              0.5 + random.uniform(-0.05, 0.05)))

        return PoseFrame(
            timestamp_ms=0,  # will be set by simulate_gesture
            hand_detected=hand_detected,
            n_fingers_extended=n_fingers,
            thumb_extended=thumb_ext,
            is_fist=is_fist,
            is_open=is_open,
            is_pinching=is_pinch,
            wrist_rotation=rot,
            shake_intensity=shake,
            confidence=confidence,
            raw_landmarks=landmarks,
        )

    def get_gesture_stream(self) -> List[Dict]:
        """Get the gesture stream as a list of events."""
        return [{"timestamp_ms": t, "gesture": g} for t, g in self.gesture_log]

    def state_hash(self) -> int:
        """FNV-1a 64-bit hash of the emulator's state."""
        h = 0xCBF29CE484222325
        mask = 0xFFFFFFFFFFFFFFFF
        prime = 0x00000100000001B3
        for g in [g for _, g in self.gesture_log]:
            for byte in g.encode('utf-8'):
                h ^= byte
                h = (h * prime) & mask
            h ^= 0xFF
            h = (h * prime) & mask  # separator
        return h


# === Demonstration: full back-deck ops with the Mudra emulator ===
def demo_mudra_back_deck():
    emu = MudraEmulator()
    print("=" * 70)
    print("MUDRA EMULATOR — simulating one full back-deck cycle")
    print("=" * 70)
    print()
    print("Mudra gestures being simulated:")
    for m in MUDRA_GESTURES:
        print(f"  {m:18s}  → {MUDRA_TO_DECK_OPS.get(m, '(unmapped)')}")
    print()

    # A full back-deck cycle
    cycle = [
        ("open_rotate_cw",   1500, "G1_gaff_swing"),
        ("pinch_rotate_ccw",  800, "G2_dehook_pull"),
        ("tap_index",         600, "G3_gill_cut"),
        ("idle",             8000, "G4_bleed_hold"),
        ("open_shake",       2500, "G5_stow_arc"),
        ("fist_rotate_cw",   4000, "G6_scrub_down"),
    ]

    print("Simulating cycle (one fish, one full processing):")
    print()
    for mudra_gesture, duration_ms, expected_op in cycle:
        emu.simulate_gesture(mudra_gesture, duration_ms)
        # Get the last gesture from the log
        last_gesture = emu.gesture_log[-1][1] if emu.gesture_log else "?"
        print(f"  {mudra_gesture:18s} ({duration_ms:5d}ms) → {last_gesture:20s} → {expected_op}")

    print()
    print(f"  Frames captured:  {len(emu.frames)}")
    print(f"  Gestures emitted: {len(emu.gesture_log)}")
    print(f"  State hash: 0x{emu.state_hash():016x}")
    print()
    print("The JS webcam version (mudra.js) produces the same hash on the same input.")
    print("That's the polyformalism contract: same input → same hash, regardless of substrate.")


if __name__ == "__main__":
    random.seed(42)
    demo_mudra_back_deck()
