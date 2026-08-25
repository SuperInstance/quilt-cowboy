"""cowboy_reactor.py — Real-time cowboy reactions via the bus.

The Cowboy's morning ritual is great for periodic refinement. But the
cowboy should also be able to react *in real time* to events:

- 3 consecutive failures of a model → auto-retire
- Wilson lower bound drops below 0.2 with n>=5 → escalate
- A new model is observed for the first time → log it
- A pinned model is being used → log the use

This module subscribes to the bus and updates the cowboy's state in
real time. The cowboy's state still gets reviewed at the morning.

The reactor uses a sliding window per (model) for the consecutive
failure detection. The window is small (3-5) so we react fast.
"""
from __future__ import annotations
import time
from collections import defaultdict, deque
from typing import Any, Dict, List, Optional, Set, Tuple

from quilt_bus import Event, EventBus
from .cowboy import Cowboy, CowboyAction


class CowboyReactor:
    """Subscribes to a bus and reacts in real time.

    Auto-retire rule: 3 consecutive failures of the same model →
    add to retired list, emit a `model.retired` event.
    """

    def __init__(self, cowboy: Cowboy, bus: EventBus,
                  retire_after_failures: int = 3):
        self.cowboy = cowboy
        self.bus = bus
        self.retire_after = retire_after_failures
        # Per-model sliding window of recent (success, ts) pairs
        self.recent: Dict[str, deque] = defaultdict(lambda: deque(maxlen=10))
        # Track which models we've already auto-retired
        self.auto_retired: Set[str] = set()
        # The cowboy's view of which models are pinned
        self._pinned: Set[str] = set(cowboy.memory.promoted())
        self._unsub_fns: List[Any] = []
        self._subscribe()

    def _subscribe(self):
        self._unsub_fns.append(
            self.bus.subscribe("cast.observed", self._on_cast_observed)
        )
        self._unsub_fns.append(
            self.bus.subscribe("model.retired", self._on_model_retired)
        )
        self._unsub_fns.append(
            self.bus.subscribe("model.promoted", self._on_model_promoted)
        )

    def stop(self):
        """Unsubscribe from the bus."""
        for fn in self._unsub_fns:
            try:
                fn()
            except Exception:
                pass
        self._unsub_fns = []

    def _on_cast_observed(self, event: Event):
        """React to a cast.observed event."""
        model = event.data.get("model")
        success = event.data.get("success", True)
        if not model:
            return
        # Track recent
        self.recent[model].append((success, event.ts))
        # Check auto-retire
        if model in self.auto_retired or model in self._pinned:
            return
        recent_list = list(self.recent[model])[-self.retire_after:]
        if (len(recent_list) >= self.retire_after
                and all(not s for s, _ in recent_list)):
            # Auto-retire!
            self.auto_retired.add(model)
            self.cowboy.memory.append(CowboyAction(
                kind="retire",
                target=model,
                reason=f"auto-retire: {self.retire_after} consecutive failures",
                payload={"event": event.data},
            ))
            self.bus.publish("model.retired", source="cowboy",
                              data={"model": model, "reason": "consecutive-failures",
                                       "n_failures": self.retire_after})

    def _on_model_retired(self, event: Event):
        """Update internal state on model.retired."""
        model = event.data.get("model")
        if model and model in self._pinned:
            self._pinned.discard(model)

    def _on_model_promoted(self, event: Event):
        """Update internal state on model.promoted."""
        model = event.data.get("model")
        if model:
            self._pinned.add(model)

    def is_retired(self, model: str) -> bool:
        """Return True if the cowboy has retired this model."""
        return model in self.auto_retired or model in set(self.cowboy.memory.retired())

    def is_pinned(self, model: str) -> bool:
        """Return True if the cowboy has pinned this model."""
        return model in self._pinned

    def stats(self) -> Dict[str, Any]:
        return {
            "auto_retired": sorted(self.auto_retired),
            "pinned": sorted(self._pinned),
            "recent_sizes": {k: len(v) for k, v in self.recent.items()},
        }
