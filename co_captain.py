"""co_captain.py — The Co-Captain: a symbiotic digital twin with a hand-on/hands-off dial.

In a hierarchy of distributed agency:

  CREW        many humans, rotating
  CO-PILOTS   many agents, rotating (each handles a specific subsystem)
  AUTOPILOT   one simple-ML agent, low-effort steering (like pincher)
  CO-CAPTAIN  one ABOVE all of these — a digital twin with full state, integrity
              score, and a HAND-ON / HANDS-OFF dial

The Co-Captain is a Quilt cell that lives across the distributed devices:
  - captain's wearable (the wrist-worn dial)
  - captain's phone (the dashboard)
  - wheelhouse tablet (the operations view)
  - engine-room monitor (the power-plant view)
  - back-deck tablet (the hands-on view)
  - cloud cell (the canonical, off-ship mirror)

The Co-Captain's dials:
  - hands_on (0 = hands-off, autopilot does everything)
              32767 = hands-on, captain is steering
  - integrity (from F140 — the audit of model/body/game)
  - fatigue (cumulative over the session)
  - trust_autopilot (0 = don't trust it, 32767 = full trust)
  - trust_crew (0 = don't trust them, 32767 = full trust)
  - trust_copilots (0 = don't trust them, 32767 = full trust)
  - mission_priority (what's the current P0? safety, fuel, catch, time, weather)
  - risk_tolerance (0 = conservative, 32767 = bold)

The Co-Captain consumes and emits A2A bottles (signal-chain integration).
A bottle IS a cell. A harbor IS a BIND. A beachcomber IS a GHOST.

The Co-Captain's job: maintain integrity. The captain's job: turn the dial.
"""
from __future__ import annotations
import json, time, math, random
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set
from enum import Enum


# The hierarchy of distributed agency
class Role(Enum):
    CREW = "crew"           # many humans
    COPILOT = "copilot"     # many agents, rotating
    AUTOPILOT = "autopilot" # one simple-ML
    COCAPTAIN = "cocaptain" # one above all


# A device the Co-Captain can live on
@dataclass
class Device:
    id: str
    name: str
    role: str               # captain_wrist, captain_phone, wheelhouse, engine_room, back_deck, cloud
    latency_ms: int = 50
    bandwidth: int = 1000    # msgs/sec
    is_online: bool = True
    battery_pct: int = 100
    last_seen: int = 0

    def to_dict(self): return asdict(self)


# A Quilt cell in the Co-Captain's fabric
@dataclass
class CaptainCell:
    """A single cell in the Co-Captain's distributed state."""
    id: str
    dials: List[int]        # 16 dials, 0-32767
    device: str             # which device holds the canonical version
    replicas: Set[str] = field(default_factory=set)  # other devices with copies
    last_modified: int = 0
    integrity: float = 1.0  # local integrity (does this replica agree with the canonical?)

    def to_dict(self):
        d = asdict(self)
        d['replicas'] = list(self.replicas)
        return d


# An A2A bottle — a message between agents
@dataclass
class Bottle:
    """A message in the signal-chain A2A protocol.

    Now lifted into the Quilt cell model: a bottle IS a cell with a
    sender, a receiver, and a payload.
    """
    id: str
    sender: str
    receiver: str
    cell_id: str             # which cell is this bottle about?
    payload: str
    timestamp_ms: int
    priority: int = 16384    # 0-32767
    is_read: bool = False

    def to_dict(self): return asdict(self)


# The Co-Captain itself
class CoCaptain:
    """The symbiotic digital twin.

    A Co-Captain has:
      - 16 dials (the captain's dial-board)
      - A map of devices (where each cell lives)
      - A bottle inbox/outbox
      - A mission state (what P0 are we on right now?)
      - An integrity score (from F140)
      - A trust vector (how much does it trust each layer below?)
    """

    def __init__(self, captain_id: str = "cocaptain-01"):
        self.id = captain_id
        self.devices: Dict[str, Device] = {}
        self.cells: Dict[str, CaptainCell] = {}
        self.inbox: List[Bottle] = []
        self.outbox: List[Bottle] = []
        self.mission_p0: str = "safety"  # current top priority
        self.integrity: float = 1.0
        self.session_start_ms = int(time.time() * 1000)
        self.hand_on_history: List[Tuple[int, int]] = []  # (timestamp, hand_on_value)

        # 16 dials of the captain's board
        self.dials = {
            "hands_on":          16384,  # 0 = hands-off, 32767 = hands-on
            "integrity":         32767,  # from F140
            "fatigue":           8192,   # cumulative
            "trust_autopilot":   16384,
            "trust_crew":        24576,
            "trust_copilots":    16384,
            "trust_self":        24576,
            "mission_priority_safety":   32767,
            "mission_priority_fuel":     16384,
            "mission_priority_catch":    16384,
            "mission_priority_time":     16384,
            "mission_priority_weather":  16384,
            "mission_priority_gear":     16384,
            "risk_tolerance":    16384,
            "alert_level":       0,      # 0 = quiet, 32767 = RED ALERT
            "presence":          32767,  # 0 = ghost, 32767 = fully present
        }

    # --- Device management ---

    def add_device(self, device: Device):
        self.devices[device.id] = device

    def device_summary(self) -> Dict:
        online = sum(1 for d in self.devices.values() if d.is_online)
        return {
            "total": len(self.devices),
            "online": online,
            "offline": len(self.devices) - online,
            "devices": [d.to_dict() for d in self.devices.values()],
        }

    # --- Cell management ---

    def add_cell(self, cell: CaptainCell):
        self.cells[cell.id] = cell

    def cell_at(self, cell_id: str) -> Optional[CaptainCell]:
        return self.cells.get(cell_id)

    def sync_cells(self):
        """Replicate cells across devices. Returns the number of syncs performed."""
        syncs = 0
        online_devices = [d.id for d in self.devices.values() if d.is_online]
        for cell in self.cells.values():
            # If the canonical device is offline, promote a replica
            if cell.device not in online_devices and cell.replicas:
                new_canonical = next((r for r in cell.replicas if r in online_devices), None)
                if new_canonical:
                    cell.replicas.add(cell.device)
                    cell.device = new_canonical
                    cell.replicas.discard(new_canonical)
                    syncs += 1
            # Replicate to all online devices
            for d in online_devices:
                if d != cell.device and d not in cell.replicas:
                    cell.replicas.add(d)
                    syncs += 1
        return syncs

    # --- Bottle (A2A message) management ---

    def send_bottle(self, receiver: str, cell_id: str, payload: str,
                    priority: int = 16384) -> Bottle:
        b = Bottle(
            id=f"bottle-{len(self.outbox)+len(self.inbox)+1}",
            sender=self.id,
            receiver=receiver,
            cell_id=cell_id,
            payload=payload,
            timestamp_ms=int(time.time() * 1000),
            priority=priority,
        )
        self.outbox.append(b)
        return b

    def receive_bottle(self, bottle: Bottle):
        bottle.is_read = True
        self.inbox.append(bottle)

    # --- The hand-on / hands-off dial ---

    def set_hands_on(self, value: int):
        """Set the hand-on dial. 0 = hands-off (autopilot), 32767 = hands-on (captain)."""
        v = max(0, min(32767, value))
        self.dials["hands_on"] = v
        self.hand_on_history.append((int(time.time() * 1000), v))
        return v

    def hands_on_pct(self) -> float:
        return self.dials["hands_on"] / 327.67

    # --- Mission priority ---

    def set_p0(self, p0: str):
        """Set the current P0 (top priority). Adjusts the mission_priority_* dials."""
        valid = ["safety", "fuel", "catch", "time", "weather", "gear"]
        if p0 not in valid:
            return
        self.mission_p0 = p0
        # Set all priority dials to baseline, then raise the chosen one
        for k in self.dials:
            if k.startswith("mission_priority_"):
                self.dials[k] = 16384
        self.dials[f"mission_priority_{p0}"] = 32767

    # --- Integrity (from F140) ---

    def set_integrity(self, value: float):
        self.integrity = max(0.0, min(1.0, value))
        self.dials["integrity"] = int(value * 32767)

    # --- State hash (for polyformalism) ---

    def state_hash(self) -> int:
        """FNV-1a 64-bit hash of the Co-Captain's state."""
        h = 0xCBF29CE484222325
        mask = 0xFFFFFFFFFFFFFFFF
        prime = 0x00000100000001B3
        # Hash the dial values in order
        for k in sorted(self.dials.keys()):
            v = self.dials[k]
            for byte in v.to_bytes(2, 'big'):
                h ^= byte
                h = (h * prime) & mask
        # Hash the device ids
        for d_id in sorted(self.devices.keys()):
            for byte in d_id.encode('utf-8'):
                h ^= byte
                h = (h * prime) & mask
        # Hash the cell ids
        for c_id in sorted(self.cells.keys()):
            for byte in c_id.encode('utf-8'):
                h ^= byte
                h = (h * prime) & mask
        # Hash the mission_p0
        for byte in self.mission_p0.encode('utf-8'):
            h ^= byte
            h = (h * prime) & mask
        return h

    def state_dict(self) -> Dict:
        return {
            "id": self.id,
            "dials": dict(self.dials),
            "mission_p0": self.mission_p0,
            "integrity": self.integrity,
            "devices": self.device_summary(),
            "cells": {c_id: c.to_dict() for c_id, c in self.cells.items()},
            "bottles_in": len(self.inbox),
            "bottles_out": len(self.outbox),
            "session_duration_s": (int(time.time() * 1000) - self.session_start_ms) // 1000,
        }

    def dials_to_vector(self) -> List[int]:
        """The Co-Captain's 16 dials as a 16-dial vector (for Quilt navigation)."""
        return [self.dials[k] for k in sorted(self.dials.keys())]


# === Demonstration: setting up a Co-Captain with the boat's devices ===
def demo_setup():
    cc = CoCaptain("cocaptain-fishing-vessel-01")

    # Add the boat's devices
    cc.add_device(Device("captain_wrist",  "Captain's Wrist",  "wearable",   latency_ms=20,  battery_pct=85))
    cc.add_device(Device("captain_phone",  "Captain's Phone",  "phone",      latency_ms=50,  battery_pct=72))
    cc.add_device(Device("wheelhouse",     "Wheelhouse Tablet","tablet",     latency_ms=80,  battery_pct=91))
    cc.add_device(Device("engine_room",    "Engine Room Mon",  "monitor",    latency_ms=100, battery_pct=100))
    cc.add_device(Device("back_deck",      "Back Deck Tablet", "tablet",     latency_ms=120, battery_pct=68))
    cc.add_device(Device("cloud",          "Cloud Mirror",     "cloud",      latency_ms=300, battery_pct=100))

    # Add a few cells (each on a different device)
    cc.add_cell(CaptainCell("cell.current_p0",  [0]*16, device="captain_wrist",  replicas={"captain_phone", "wheelhouse"}))
    cc.add_cell(CaptainCell("cell.integrity",   [0]*16, device="captain_phone",  replicas={"wheelhouse", "cloud"}))
    cc.add_cell(CaptainCell("cell.catch_state", [0]*16, device="back_deck",      replicas={"wheelhouse", "captain_phone"}))
    cc.add_cell(CaptainCell("cell.weather",     [0]*16, device="wheelhouse",     replicas={"cloud", "captain_phone"}))
    cc.add_cell(CaptainCell("cell.engine",      [0]*16, device="engine_room",    replicas={"cloud"}))

    # Set initial P0
    cc.set_p0("safety")
    # Set initial integrity
    cc.set_integrity(0.92)
    # Set hands-on to mid (50%)
    cc.set_hands_on(16384)

    # Send a bottle to a co-pilot
    cc.send_bottle("copilot-weather", "cell.weather", "Heavy weather advisory: winds 30+ kts by 1500", priority=30000)

    print("=" * 70)
    print("CO-CAPTAIN — initial state")
    print("=" * 70)
    state = cc.state_dict()
    print(f"  ID: {state['id']}")
    print(f"  P0: {state['mission_p0']}")
    print(f"  Integrity: {state['integrity']:.2f}")
    print(f"  Hands-on: {cc.hands_on_pct():.0f}%")
    print(f"  Devices: {state['devices']['online']}/{state['devices']['total']} online")
    print(f"  Cells: {len(state['cells'])}")
    print(f"  Bottles out: {state['bottles_out']}")
    print(f"  State hash: 0x{cc.state_hash():016x}")
    print()
    print("  Dials:")
    for k, v in sorted(state['dials'].items()):
        bar = "█" * int(v / 3276.7)
        print(f"    {k:30s} {v:5d} ({v/327.67:5.1f}%)  {bar}")

    return cc


# === Demonstration: a session evolving over time ===
def demo_session():
    cc = demo_setup()
    print()
    print("=" * 70)
    print("SESSION EVOLUTION — captain's day")
    print("=" * 70)
    print()
    print("Tick 1: Calm start. Captain's hands-on is at 50%, P0 = safety.")
    cc.set_hands_on(16384)
    cc.set_integrity(0.95)
    print(f"  State hash: 0x{cc.state_hash():016x}")
    print()

    print("Tick 2: Weather deteriorates. P0 shifts to weather. Captain goes more hands-on.")
    cc.set_p0("weather")
    cc.set_hands_on(28000)  # 85% hands-on
    cc.set_integrity(0.88)
    print(f"  hands_on: {cc.hands_on_pct():.0f}%, P0: {cc.mission_p0}, integrity: {cc.integrity:.2f}")
    print(f"  State hash: 0x{cc.state_hash():016x}")
    print()

    print("Tick 3: Co-pilot reports engine anomaly. P0 shifts to gear.")
    cc.set_p0("gear")
    cc.set_hands_on(30000)  # 92% hands-on
    cc.set_integrity(0.82)
    cc.send_bottle("copilot-engine", "cell.engine", "Coolant temp rising on starboard", priority=28000)
    print(f"  hands_on: {cc.hands_on_pct():.0f}%, P0: {cc.mission_p0}, integrity: {cc.integrity:.2f}")
    print(f"  bottles sent: {len(cc.outbox)}")
    print(f"  State hash: 0x{cc.state_hash():016x}")
    print()

    print("Tick 4: Captain gets fatigued. Hands-on dial slides down (autopilot takes more).")
    cc.set_hands_on(12000)  # 37% hands-on
    cc.set_integrity(0.78)
    cc.dials["fatigue"] = 22000
    print(f"  hands_on: {cc.hands_on_pct():.0f}%, fatigue: {cc.dials['fatigue']/327.67:.0f}%, integrity: {cc.integrity:.2f}")
    print(f"  State hash: 0x{cc.state_hash():016x}")
    print()

    print("Tick 5: Captain hands-off entirely. Trust in autopilot is high.")
    cc.set_hands_on(2000)  # 6% hands-on
    cc.dials["trust_autopilot"] = 28000
    cc.set_integrity(0.91)
    print(f"  hands_on: {cc.hands_on_pct():.0f}%, trust_autopilot: {cc.dials['trust_autopilot']/327.67:.0f}%, integrity: {cc.integrity:.2f}")
    print(f"  State hash: 0x{cc.state_hash():016x}")
    print()

    print("The Co-Captain's state evolves. The dial tells the story: captain goes from")
    print("hands-on (intervention) to hands-off (delegation) as trust and fatigue change.")
    print("The state hash changes every tick — but the *trajectory* of the hash is the")
    print("Co-Captain's signature. Polyformal ports of this code produce the same hashes.")


if __name__ == "__main__":
    demo_setup()
    print()
    demo_session()
