"""quilt_cowboy — The cowboy: reflection loop, morning ritual, and real-time reactor.

The cowboy is the human (or the agent acting as human) who keeps the
Quilt in shape. The cowboy is not the AI. The cowboy is the rider.

The cowboy has three components:
1. **Cowboy** — the persistent reflection loop. Reads witness, runs
   nightcycle, refines Wilson profiles, writes the morning report.
2. **CowboyMemory** — append-only, hash-chained JSONL on disk.
3. **CowboyReactor** — real-time reactions via the bus. Subscribes
   to cast.observed, auto-retires on consecutive failures.

The cowboy is a self-contained concern. It can be used with or
without the substrate, the plugin, the bus, or the witness.
"""
from .cowboy import (
    Cowboy, CowboyAction, CowboyMemory, MorningReport, fnv1a64, main,
)
from .cowboy_reactor import CowboyReactor

__version__ = "1.0.0"
__all__ = [
    "Cowboy", "CowboyAction", "CowboyMemory", "MorningReport", "fnv1a64",
    "CowboyReactor", "main",
]
