# quilt-cowboy

The cowboy: reflection loop, morning ritual, and real-time reactor.

The cowboy is the human (or the agent acting as human) who keeps the
Quilt in shape. The cowboy is not the AI. The cowboy is the rider.

This is one of the small, focused repos that compose the Quilt.
It was extracted from `quilt-substrate` as part of the v4.0 split.

## What this provides

- `Cowboy` — the persistent reflection loop
- `CowboyMemory` — append-only, hash-chained JSONL on disk
- `CowboyAction` — the unit of cowboy memory
- `MorningReport` — the cowboy's daily report
- `fnv1a64` — the hash function (same as saddle's TypeScript)
- `CowboyReactor` — real-time reactions via the bus
- `main()` — the CLI entry point

## CLI

```
cowboy run                  # Run the morning (read witness, refine, write report)
cowboy watch                # Watch the bus in real time
cowboy watch --bus-log F    # Replay a bus log file
cowboy report               # Print the last morning report
cowboy state                # Print cowboy state (memory, retired, promoted)
cowboy note "text"          # Append a free-form note
cowboy retire MODEL         # Manually retire an alignment
```

## Cowboy memory

The cowboy's memory is JSONL, hash-chained with FNV-1a64 (same as
saddle's TypeScript implementation). Each action references the
action before it. The chain can be verified with `verify_chain()`.

Action kinds:
- `morning` — the cowboy ran the morning
- `retire` — the cowboy retired an alignment
- `promote` — the cowboy promoted an alignment
- `note` — the cowboy wrote a free-form note

## Cowboy's morning

The morning ritual:
1. Read the witness log
2. Read the ledger
3. Aggregate per-(alignment) success/failure counts
4. Apply earned-keep rule: `wilson_lb >= 0.5 AND n >= 5`
5. Apply retire rule: `wilson_lb < 0.3 AND n >= 3`
6. Apply escalation rule: `wilson_lb < 0.2 AND n >= 2`
7. Write the morning report (markdown)
8. Append the morning to the cowboy's memory
9. Apply the refinements to the substrate

## Cowboy's reactor

The reactor subscribes to the bus. The reactor watches
`cast.observed`. When N consecutive failures arrive for a model,
the reactor auto-retires it. The reactor is fast. The reactor
never sleeps.

The morning is slow. The morning is careful. The morning is the
cowboy's head.

The reactor without the morning is a headless horse. The morning
without the reactor is a horseless head.

## Why split out as a separate repo?

The cowboy is a self-contained concern. It does not depend on
the substrate. It does not depend on the plugin. It can be used
with or without the bus, the witness, or the ledger.

The cowboy is also the cowboy's audit trail. The cowboy's memory
must be preserved across substrate rewrites. A separate repo
ensures the cowboy's history is never lost.

## Test count

27 tests (17 cowboy + 10 reactor), all passing.

## Version

1.0.0 — extracted from quilt-substrate v4.0-cowboy-loop.
