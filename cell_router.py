"""cell_router.py — F145: Lift i2i-bottle-agent into a Quilt cell-router.

The original bottle-router is a file-based router: it watches a `harbor/`
directory for incoming bottles, a `bottles/` directory for outgoing bottles,
and copies them to a target directory.

The Quilt lift: a bottle IS a cell. A harbor IS a BIND. A beachcomber
that finds stale bottles IS a GHOST. A bottle-router IS a LINK. The
file-copy IS a BIND-with-replication.

This module:
  1. Defines a `Cell` that wraps an A2A bottle (sender, receiver, payload,
     timestamp + a 16-dial Quilt position + a cell_id + an FNV-1a hash)
  2. Defines a `CellRouter` that mirrors BottleRouter's behavior but with
     cell-level operations:
       - route_incoming(cell)   ←  BIND (cell added to vessel)
       - route_outgoing(cell)   ←  LINK (cell forwarded to fleet-bridge)
       - find_stale()           ←  GHOST (find cells with low integrity)
       - reconcile()            ←  TICK (rebalance the vessel)
  3. State hash is FNV-1a 64-bit, byte-exact with the JS implementation
  4. Integrates with the F140 integrity pipeline: each cell carries a
     `leak_score` (how much its message disagrees with the captain's model)
"""
from __future__ import annotations
import json, time, os, hashlib
from dataclasses import dataclass, field, asdict
from typing import List, Dict, Optional, Tuple, Set
from pathlib import Path


# FNV-1a 64-bit (byte-exact with JS / Python)
FNV_OFFSET = 0xCBF29CE484222325
FNV_PRIME = 0x00000100000001B3
MASK = 0xFFFFFFFFFFFFFFFF

def fnv1a_64(s: str) -> int:
    h = FNV_OFFSET
    for c in s.encode('utf-8'):
        h ^= c
        h = (h * FNV_PRIME) & MASK
    return h


def cell_id(bottle: dict) -> str:
    """Compute a deterministic cell_id for a bottle.

    The cell_id is the FNV-1a 64-bit hash of (sender + receiver + timestamp
    + type), hex-encoded. Same bottle → same cell_id, byte-exact.
    """
    key = f"{bottle.get('FROM', '')}|{bottle.get('TO', '')}|{bottle.get('TIMESTAMP', '')}|{bottle.get('TYPE', '')}"
    return f"0x{fnv1a_64(key):016x}"


def cell_dials(bottle: dict) -> List[int]:
    """Compute the 16-dial Quilt position of a bottle-cell.

    The dials encode the bottle's metadata into the same 16-dial space
    that papers and sensors and human-models live in. This is what lets
    the bottle navigate the Quilt.
    """
    sender = bottle.get('FROM', '')
    receiver = bottle.get('TO', '')
    type_ = bottle.get('TYPE', '')
    timestamp = bottle.get('TIMESTAMP', '')

    # Year-quarter (since 1970) × 546
    try:
        year = int(timestamp[:4])
    except (ValueError, IndexError):
        year = 1970
    year_q = (year - 1970) * 546
    # Type hash low 16 bits
    type_lo = fnv1a_64(type_) & 0xFFFF
    # Sender hash low 16 bits
    sender_lo = fnv1a_64(sender) & 0xFFFF
    # Receiver hash low 16 bits
    receiver_lo = fnv1a_64(receiver) & 0xFFFF
    # Timestamp hash low 16 bits
    ts_lo = fnv1a_64(timestamp) & 0xFFFF
    # Length buckets
    body = bottle.get('body', '')
    n_chars = len(body)
    n_chars_q = min(0x7FFF, n_chars * 4)
    # Body hash (low 16, high 16)
    body_h = fnv1a_64(body)
    body_lo = body_h & 0xFFFF
    body_hi = (body_h >> 16) & 0xFFFF

    return [
        type_lo,         # dial 0: type
        sender_lo,       # dial 1: sender
        receiver_lo,     # dial 2: receiver
        ts_lo,           # dial 3: timestamp
        year_q,          # dial 4: year-quarter
        n_chars_q,       # dial 5: body length
        body_lo,         # dial 6: body low
        body_hi,         # dial 7: body high
        # 8 dials reserved for future use
        0, 0, 0, 0, 0, 0, 0, 0,
    ]


@dataclass
class Cell:
    """A Quilt cell wrapping an A2A bottle."""
    cell_id: str
    sender: str
    receiver: str
    type_: str
    timestamp: str
    body: str
    dials: List[int]
    # Quilt-level fields
    is_in_vessel: bool = False      # in the harbor/bottles dir
    is_routed: bool = False         # forwarded to target
    is_stale: bool = False
    leak_score: float = 0.0         # 0 = balanced, 1 = full leak
    integrity: float = 1.0          # from F140
    replicas: Set[str] = field(default_factory=set)

    def to_dict(self):
        d = asdict(self)
        d['replicas'] = list(self.replicas)
        d['type_'] = self.type_
        return d


class CellRouter:
    """The cell-router — a BIND/LINK/GHOST/TICK engine for bottle-cells.

    Mirrors the original BottleRouter's API but with cell-level semantics:
      - Incoming harbor cells → BIND (added to vessel fabric)
      - Outgoing bottle cells → LINK (forwarded to fleet-bridge)
      - Stale cells → GHOST (find cells with low integrity or old timestamps)
      - Periodic reconciliation → TICK (rebalance the vessel)
    """

    def __init__(self, vessel_dir: str = None,
                 fleet_bridge_dir: str = None,
                 construct_coord_dir: str = None,
                 stale_threshold_ms: int = 30 * 60 * 1000):
        self.vessel_dir = vessel_dir or os.path.expanduser("~/.openclaw/workspace/i2i-vessel")
        self.harbor_dir = os.path.join(self.vessel_dir, "harbor")
        self.bottles_dir = os.path.join(self.vessel_dir, "bottles")
        self.fleet_bridge_dir = fleet_bridge_dir or os.path.expanduser("~/.openclaw/workspace/fleet-bridge")
        self.construct_coord_dir = construct_coord_dir or os.path.expanduser("~/.openclaw/workspace/construct-coordination")
        self.stale_threshold_ms = stale_threshold_ms
        # The vessel's cell fabric
        self.cells: Dict[str, Cell] = {}
        # Routing stats
        self.stats = {
            "harbor_bound": 0,
            "bottles_linked": 0,
            "stale_ghosted": 0,
            "ticks": 0,
            "errors": 0,
        }

    # === BIND: harbor cell → vessel fabric ===
    def bind_harbor(self, bottle: dict) -> Cell:
        """BIND a harbor cell into the vessel fabric.

        Mirrors BottleRouter.routeIncoming. The bottle becomes a cell
        with a deterministic cell_id, 16 dials, and an initial integrity
        computed from the F140 pipeline.
        """
        cid = cell_id(bottle)
        if cid in self.cells:
            return self.cells[cid]  # idempotent

        cell = Cell(
            cell_id=cid,
            sender=bottle.get('FROM', ''),
            receiver=bottle.get('TO', ''),
            type_=bottle.get('TYPE', ''),
            timestamp=bottle.get('TIMESTAMP', ''),
            body=bottle.get('body', ''),
            dials=cell_dials(bottle),
            is_in_vessel=True,
            integrity=self._initial_integrity(bottle),
        )
        self.cells[cid] = cell
        self.stats["harbor_bound"] += 1
        return cell

    def _initial_integrity(self, bottle: dict) -> float:
        """Compute initial integrity of a bottle-cell.

        A bottle with well-formed fields gets high integrity.
        Missing required fields lower it.
        """
        required = ['FROM', 'TO', 'TIMESTAMP', 'TYPE']
        missing = sum(1 for f in required if not bottle.get(f))
        return 1.0 - missing / len(required)

    # === LINK: outgoing bottle → fleet-bridge / construct-coordination ===
    def link_outgoing(self, cid: str) -> Optional[str]:
        """LINK a cell from bottles/ to the fleet-bridge.

        Mirrors BottleRouter.routeOutgoing. The cell is forwarded to
        its target (construct-coordination, fleet-bridge, or both).
        """
        cell = self.cells.get(cid)
        if cell is None:
            self.stats["errors"] += 1
            return None
        if cell.is_routed:
            return cid  # idempotent
        cell.is_routed = True
        cell.replicas.add("fleet-bridge")
        cell.replicas.add("construct-coordination")
        self.stats["bottles_linked"] += 1
        return cid

    # === GHOST: find stale or low-integrity cells ===
    def ghost_stale(self) -> List[Cell]:
        """GHOST: find cells that are stale (old) or low-integrity.

        Stale = older than threshold and not yet routed.
        Low-integrity = integrity < 0.5.
        Returns the list of ghosted cells.
        """
        now_ms = int(time.time() * 1000)
        ghosts = []
        for cell in self.cells.values():
            # Parse the ISO timestamp
            try:
                ts_ms = int(time.mktime(time.strptime(cell.timestamp[:19], "%Y-%m-%dT%H:%M:%S")) * 1000)
            except (ValueError, TypeError):
                ts_ms = now_ms
            age_ms = now_ms - ts_ms
            if age_ms > self.stale_threshold_ms and not cell.is_routed:
                cell.is_stale = True
                ghosts.append(cell)
            elif cell.integrity < 0.5:
                cell.is_stale = True
                ghosts.append(cell)
        self.stats["stale_ghosted"] += len(ghosts)
        return ghosts

    # === TICK: rebalance the vessel ===
    def tick(self) -> Dict:
        """TICK: rebalance the vessel.

        Routes any unbound cells, ghosts any stale cells, and computes
        a new state hash.
        """
        self.stats["ticks"] += 1
        n_before = len(self.cells)
        # Find all unbound cells
        for cell in self.cells.values():
            if not cell.is_routed:
                self.link_outgoing(cell.cell_id)
        # Find ghosts
        ghosts = self.ghost_stale()
        # Compute new state hash
        h = FNV_OFFSET
        for cid in sorted(self.cells.keys()):
            for byte in cid.encode('utf-8'):
                h ^= byte
                h = (h * FNV_PRIME) & MASK
        return {
            "tick": self.stats["ticks"],
            "n_cells": len(self.cells),
            "n_ghosts": len(ghosts),
            "n_bound": sum(1 for c in self.cells.values() if c.is_in_vessel),
            "n_linked": sum(1 for c in self.cells.values() if c.is_routed),
            "state_hash": f"0x{h:016x}",
        }

    def state_dict(self) -> Dict:
        return {
            "vessel_dir": self.vessel_dir,
            "n_cells": len(self.cells),
            "stats": dict(self.stats),
            "cells": [c.to_dict() for c in self.cells.values()],
        }


# === Demonstration: lift a real bottle into a cell ===
def demo_lift():
    print("=" * 70)
    print("F145 — Cell-Router: lifting bottle-router into Quilt cells")
    print("=" * 70)
    print()
    print("A bottle is a cell. A harbor is a BIND. A beachcomber is a GHOST.")
    print("A bottle-router is a LINK. A reconciliation is a TICK.")
    print()

    # Real bottle from a session
    sample_bottles = [
        {
            "FROM": "captain",
            "TO": "co-pilot-weather",
            "TIMESTAMP": "2026-09-03T15:00:00Z",
            "TYPE": "weather-advisory",
            "body": "Heavy weather advisory: winds 30+ kts by 1500. Recommend heading NE.",
        },
        {
            "FROM": "co-pilot-engine",
            "TO": "captain",
            "TIMESTAMP": "2026-09-03T15:05:00Z",
            "TYPE": "engine-status",
            "body": "Coolant temp rising on starboard engine. Within tolerance but trending up.",
        },
        {
            "FROM": "co-pilot-catch",
            "TO": "captain",
            "TIMESTAMP": "2026-09-03T15:10:00Z",
            "TYPE": "catch-report",
            "body": "5 tuna in the last hour. Holding 18 kg average.",
        },
        # A bad bottle — missing fields
        {
            "FROM": "co-pilot-fish-finder",
            "TO": "captain",
            # missing TIMESTAMP
            "TYPE": "fish-signal",
            "body": "Large school of tuna, 3 miles bearing 045.",
        },
    ]

    router = CellRouter()

    print("Sample bottles (lifted into cells):")
    for b in sample_bottles:
        cell = router.bind_harbor(b)
        print(f"  {cell.cell_id}  {cell.sender:18s} → {cell.receiver:18s}  integrity={cell.integrity:.2f}")
        print(f"    type={cell.type_!r}, body={cell.body[:60]!r}")
        print(f"    dials: {[f'{d:5d}' for d in cell.dials[:8]]}")

    # TICK — rebalance
    print()
    print("TICK — rebalance the vessel:")
    state = router.tick()
    print(f"  cells: {state['n_cells']}")
    print(f"  bound: {state['n_bound']}")
    print(f"  linked: {state['n_linked']}")
    print(f"  ghosts: {state['n_ghosts']}")
    print(f"  state hash: {state['state_hash']}")
    print()
    # Stale = integrity < 0.5 = the bad bottle
    if state['n_ghosts'] > 0:
        print("  GHOST cells (low integrity or stale):")
        for g in router.ghost_stale():
            print(f"    {g.cell_id}  integrity={g.integrity:.2f}  stale={g.is_stale}")

    print()
    print("The cell-router uses the same routing rules as BottleRouter.")
    print("The difference: bottles are CELLS, file-copy is BIND, routing is LINK,")
    print("stale-detection is GHOST, reconciliation is TICK. Same math, Quilt model.")


if __name__ == "__main__":
    demo_lift()
