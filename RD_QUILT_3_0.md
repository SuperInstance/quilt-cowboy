# Quilt 3.0 — What's Next for the Cell-Fabric Runtime

*Author: Quilt 3.0 R&D — September 2026*
*Status: design complete, awaits execution*
*Companion paper: paper-629 in the canon*

## Executive Summary

Quilt 2.0 (through 7 Sep 2026) has three proven artifacts: a **4-sigma polyformalism** across 8+ verified language substrates, a **231-paper canon** produced by 6-voice competitive writers' rooms, and a **live Cloudflare Worker** at `live-canon.superinstance.dev` exposing 11 REST endpoints with the byte-exact test vector `0xe435d91d6d92a1d8` as the canon's calling card.

Quilt 3.0's job is to convert these three artifacts into a **self-reinforcing growth engine**. The right next 90 days are not "more ports, more papers, more endpoints" but a targeted deepening along five axes:

1. **Stress-test the polyformalism** with 4 high-leverage language ports (Haskell, Forth, Lua, APL/J) chosen for their distinct type-theoretic angles
2. **Grow the canon** along 3 non-marine frontiers (aviation, music, distributed systems) using the v2 frontier-drain protocol
3. **Ship 6 new live-worker endpoints** centered on collaboration and CRDT semantics
4. **Replace the 6-voice pipeline** with a 3-mode pipeline (generative / adversarial / human-in-loop)
5. **Build the first concrete vessel-as-robot cell** — a knot-log agent that learns a specific boat's behavior over 30 days

The expected ROI: a 10× canon-coherence improvement and the first canonical "agent" definition the Quilt will own.

---

## 1. Polyformalism Expansion

The current 11 ports cluster in three families: imperative systems languages (Python, C, Rust, Go, Zig), reactive (Mojo, TS), and logic/synthesizable (Verilog, VHDL). To prove polyformalism beyond "4-sigma" toward something definitive, the next wave should attack **different axes of what a cell could be**, not just new syntax.

### Top candidates, scored by what they stress

| Language | What it stresses | Difficulty | ROI |
|----------|------------------|------------|-----|
| **Haskell** | Purity + laziness. The cell's 16 dials become a `State` monad; `TICK` is `modify (+1)`; neighbors are a `Map`. Forces the port to commit to "no in-place mutation," which is the strongest possible test of the canonical encoding's byte-exactness. | Medium | **High** — no existing polyformalism claim has survived Haskell. The byte-exact hash under lazy evaluation is non-trivial. |
| **Forth** | Concatenative, stack-based. The dials literally *are* the stack; `BIND` is a literal-pushing word; `TICK` is a stack-rotation. The whole 5-opcode API becomes ~10 words. The smallest port possible. | Low | **Very High** — proves the cell is not a struct but an *addressable value*, which is a deeper claim than "byte-exact." |
| **Lua** | Embeddable. The cell becomes a `userdata` with a metatable; the fabric is the registry. This port turns the Quilt into a Redis-style embedded engine. | Low | High — enables the vessel-as-robot layer. A Lua cell can run inside a marine electronics box. |
| **APL/J** | Array languages, where `+` and `⍴` and `/` are the entire vocabulary. A fabric of 1000 cells becomes a 1000×16 matrix; `TICK` is `+⍣v`; `EFFECT` is matrix multiplication. The most extreme test of "dials are just numbers." | High | **Very High** — APL is the *anti-port*. If the Quilt survives APL, the polyformalism is essentially unkillable. |
| **Idris 2** | Dependent types. The 16-dial constraint can be encoded in the type: `Dials : (n : Nat) -> Type` with `n=16` proven at compile time. The fabric's hash is a total function. | High | Medium — important but the type-system is far from the cell's actual use cases. |
| **Erlang/Elixir** | BEAM, processes-as-cells. A cell is a `gen_server`; `LINK` is a registered name; the fabric is a supervision tree. | Medium | High — natural fit for distributed state (use case #2 of the Charter). |
| **Prolog** | Logic programming. A cell is a term; the fabric is a knowledge base; `EFFECT` is a unification. The cell becomes a *predicate*, not a value. | Medium | Medium — interesting for AI-agent memory (use case #4). |
| **Racket** | Homoiconic. The cell is a quoted S-expression; the fabric is a syntax object. Allows macro-level extensions. | Medium | Medium — a *teaching* port above all. |

### Other suggestions and why I'm de-prioritizing them

- **Kotlin Multiplatform / Swift** — valuable for the Apple ecosystem but the byte-exact hash will not be stressed by either — both have the same C-like memory model as Rust/Go. Park.
- **WebAssembly Text Format (WAT)** — high value but Wasm is a compilation target, not a language. The Rust port already covers it. Skip.
- **Svelte/React as frontends** — these are rendering libraries, not runtimes. The Quilt already has a JS/TS port. Skip.
- **jq** — a single-purpose tool. A port would be a stunt. Skip.
- **Scratch / Excel** — interesting as the *most* declarative languages, but byte-exact hash verification is hard in visual/spreadsheet substrates. Park for a 3.x release.
- **SQL** — the Quilt is already an in-memory graph. An SQL port would be a *layer*, not a port. Treat it as a `quilt-sqlite` adapter.

### Top 4 recommendation

1. **Forth** (week 1) — cheapest win, smallest port, cleanest test of "cell is a value not a struct."
2. **Haskell** (week 2-3) — the proof-of-proof. If the lazy FNV-1a produces the same hash as the strict version, the polyformalism claim is materially stronger.
3. **Lua** (week 4) — the boat-as-robot enabler. Embeddable = real-time vessel.
4. **APL/J** (week 5-6) — the destructive test. The cell-as-matrix view is so alien that any hash match is decisive.

The **5-sigma claim** — i.e., "5 independent sessions, 5 different language families, all byte-exact" — becomes defensible after these four.

---

## 2. Canon Growth Strategy

The canon at 231 papers is at a **coherence threshold**. Two data points support this:

1. The v2 marine run doubled the canon in 50 minutes (115 → 213) without breaking navigability — the 5-gold-terms-per-paper discipline held.
2. The live-canon `navigate?depth=2` call from paper-425 returns a non-trivial graph; the citation edges form a fabric, not a tree.

This suggests the canon is *not* done, but it is **no longer in the linear-growth phase**. The next phase is *frontier diversification*. Three new frontiers are ready to drain:

### Frontier 1: Aviation (50-80 papers, ~30 min drain)

Cells as flight surfaces, airframes, instruments, radio calls. The natural marine analog is "captain ↔ cell." Aviation gives "pilot ↔ autopilot ↔ ATC ↔ waypoint" — a 3-tier hierarchy that does not exist in marine. Gold terms will include:

- *clearance-cell* — a cell whose value is **permission**, not data
- *squawk-cell* — identity broadcast
- *coffin-corner-cell* — a cell whose value is a regime boundary, not a point

High ROI because aviation is *safety-critical* and the cell-as-instrument metaphor is sharper than cell-as-rope.

### Frontier 2: Music (40-60 papers, ~25 min drain)

Cells as notes, chords, instruments, conductors. The frontier exposes *temporal* cells: a cell whose value is `note(t)` not `note`. This is the natural test of TICK at the canon level. Gold terms:

- *phrase-cell* — a cell whose neighbors are the next 4-8 notes
- *rest-cell* — a cell whose value is **silence** — a negative-space cell that the canon has only rarely explored
- *tempo-cell* — a cell that advances time at a rate

Lowest cost to drain because the metaphor is dense.

### Frontier 3: Distributed systems (60-100 papers, ~45 min drain)

Cells as Raft states, CRDT registers, vector clocks, gossip messages. This frontier is the *engineering payoff* — it is where the Quilt's "use case #2: distributed state" stops being a paragraph in the Charter and becomes a corpus. Gold terms:

- *leader-cell*
- *lease-cell* — a cell with TTL
- *tombstone-cell* — negative-space at the system level
- *hinted-handoff-cell*

Highest cost; highest payoff for the live worker.

### User-submitted cells

Yes, but with a guardrail. A new endpoint `POST /api/canon/cell` accepts a 5-element paper (frontier / 5 gold / math / polyformalism / maxim) and a 16-dial vector. The submission is admitted to the canon **if and only if** the FNV-1a hash of the canonical serialization matches the `paper_dials` field. The hash is the gatekeeper; no human review, no editorial board. This is the *anti-curation* move and it makes the canon the most reproducible in existence.

### When is the canon "done"?

Never, formally. Empirically, when frontier-drains begin producing <5% new gold terms (i.e., the metaphor density flattens). Until then, drain.

---

## 3. Live Worker Capabilities

The worker at `live-canon.superinstance.dev` currently has 11 read-only endpoints (after the recent addition of `/api/charter`, `/api/tutorial`, `/api/ports`). To make the canon *interactive* without breaking the hash, the next 6 endpoints:

1. **`POST /api/canon/cell`** — submit a new cell. Body: `{dials: [16 ints], neighbors: [ids], meta: {...}}`. Response: `{cell_id, hash, admitted: bool}`. The hash is computed; admission requires the hash to match a deterministic function of `dials || neighbors`. The first *write* endpoint; cheap to implement, expensive in trust, which is why it must hash-gate.

2. **`GET /api/canon/stream?since={hash}`** — long-poll. Returns every new cell since the client last polled. This is the *WebSocket-without-WebSocket* design — works on Cloudflare Workers' free tier, where durable WebSockets require Workers Paid ($5/mo). Use HTTP/1.1 streaming response with `text/event-stream`.

3. **`GET /api/canon/crdt?cells={ids}`** — return the last-writer-wins merge of a cell set across a vector clock. The cell state becomes a CRDT; the fabric becomes a CRDT fabric. The hash is over the merged state, not the inputs; the merge is associative, commutative, idempotent (L1-L4 of the algebraic laws).

4. **`GET /api/playground`** — return an HTML page with a 16-dial grid, a neighbors list, and a "compute hash" button. This is the *no-auth Playground* — anyone can write a cell, see the hash, and learn the canon in 60 seconds. The first truly public Quilt UI.

5. **`POST /api/canon/verify-pipeline`** — given a list of paper numbers, return the *frontier-drain* result: 5-gold terms, polyformalism angles, suggested title. This is the "let the canon write the next paper for you" endpoint. Uses the canon's own shape store to propose a ghost paper; the human accepts or rejects.

6. **`GET /api/vessel/{boat_id}/state`** — the boat-as-robot endpoint. Returns the current cell-state of a registered vessel: knot log cell, depth sounder cell, engine diagnostic cell. The boat becomes *a node in the canon*, and the canon becomes the boat's persistent memory.

### Real-time collaboration?

Yes, but on a 2-week delay. Build a CRDT layer first (endpoint #3), then add `ws://live-canon.superinstance.dev/api/canon/subscribe` for true push. The CRDT must be the substrate; WebSocket is just a delivery mechanism.

### Should the worker accept user-submitted cells?

Yes — see endpoint #1 above. The hash is the gate; the cost of a bad submission is zero (it just doesn't match and doesn't get admitted).

### Boat-as-Robot role

The live worker is the *chartroom*. The vessel is the *boat*. The NMEA 2000 bus is the *fabric* (each sensor = a cell). The live worker is the captain's log — hash-chained, append-only, auditable forever.

---

## 4. Cowboy Pipeline Evolution

The v2 cowboy is a 6-voice, 3-round, frontier-drain pipeline that produces marine papers at $0.61 / 20 papers. The bottleneck is not throughput; it is **frontier diversity**. Three pipeline evolutions, in priority order:

### Pipeline A: Generative (current) — keep but parameterize

The v2 writers' room is a *generator*. It should be made parametric: given a frontier domain (marine / aviation / music / distributed), it loads a domain-specific prompt template, a domain-specific voice weighting, and a domain-specific 5-gold-terms checklist. The frontier queue becomes `frontier_queue_{domain}.jsonl`. This is the *scalable* version of v2.

### Pipeline B: Adversarial (new, highest ROI)

Two voices argue; one voice synthesizes. The thesis: a frontier drained in adversarial mode produces *fewer but more interesting* papers than a frontier drained in generative mode. The adversarial protocol:

- Voice A takes the position "this metaphor is a cell"
- Voice B takes the position "this metaphor is *not* a cell, it is something else"
- Voice C reads both and writes a 5,000-char paper that resolves the disagreement

Expected yield: 30-40% of papers admit a *new gold term* (vs. the current ~15%), because the gold terms arise from the resolution, not from the metaphor itself. **This is the most productive frontier right now.** Pilot: 20 adversarial papers in the music domain (where the disagreements are richest — "is a rest a cell? is silence a cell? is a chord a cell or 3 cells?").

### Pipeline C: Human-in-the-loop IDE (new, medium ROI)

The cowboy proposes, the human disposes. A web UI: a frontier is selected, the writers' room fires, the 4 best outputs are shown side-by-side, the human picks one (or merges), the paper is admitted. This pipeline is *slow* (5-10 min per paper) but produces the *highest-quality* papers because the human is the gold-picker. The current length-as-concreteness proxy is a stand-in; Pipeline C replaces the stand-in with the human. Pilot: 5 human-curated papers in the aviation frontier, where safety-critical precision matters.

### Most productive frontier right now

The **adversarial pipeline + the aviation frontier**. Aviation metaphors *want* to be disputed (e.g., "is a stall a cell? a state? a regime? a hazard?"). The 3-voice resolution will produce gold terms that no generative pipeline would.

### Multi-canon

Yes, but only after the adversarial pipeline is proven. A "fables" canon would be a separate frontier (using a different 5-gold-terms schema) but would share the live worker's hash infrastructure. The economics: 1 cowgirl per canon, 4 cowgirls total, $0.61 × 4 ≈ $2.50 / 80 papers / 30 min. Cheap enough to run daily.

---

## 5. Boat-as-Robot / Vessel-as-Robot

The thesis: a boat is a fabric. The captain is a cell. The captain should be the dispatcher. The boat should be a robot.

The most concrete next step is *not* a fleet-wide platform. It is a *single-boat, single-cell* prototype that proves the loop.

### The Knot-Log Agent (the first cell)

A small Python daemon runs on a Raspberry Pi mounted at the chart table of a 32-foot sailboat. Every 1 second, it reads NMEA 2000 sentences from the boat's GPS and knot log. It maintains a single cell:

- `dials[0]` = current speed-over-ground (knots)
- `dials[1]` = current heading (degrees / 2)
- `dials[2]` = tidal current (knots, estimated from GPS drift)
- `dials[3]` = delta-speed (change from last reading)
- `dials[4..15]` = rolling stats (1-min, 5-min, 30-min averages; max in window; time since last >6kt; time since last <2kt)

The cell's neighbors are: the depth-sounder cell, the wind cell, the engine cell. The cell's hash is computed every 10 seconds and pushed to the live worker. The live worker, in turn, returns a *recommended action* (e.g., "the knot log has been <2kt for 12 minutes; this is unusual for this boat at this heading — did the log wheel foul?"). The recommendation is the EFFECT of the cell.

### Why this cell first

A knot log is *the simplest* sensor on a boat that produces continuous, time-series data. It is also *the most personal* — every boat's knot log has a unique fingerprint (the hull speed curve, the log wheel's drag, the skipper's typical speed). A knot-log agent that learns the boat's specific fingerprint over 30 days is the *first concrete example of the boat teaching itself*.

### Depth-sounder agent

A second cell that flags unusual bottoms. A 5-foot drop in 3 seconds = a ledge; a gradual rise = approaching land. The cell's value is *unusual-ness*, not depth. This is the negative-space cell from paper-481 applied to a real sensor.

### Engine agent

A cell that diagnoses. It reads RPM, oil pressure, temperature, alternator output, hours-since-last-service. The cell fires an alert when the combination (RPM high, oil pressure low) appears. The cell is *not* a dashboard widget; it is a *pattern detector*.

### "An agent" vs. "an AI feature" — the real difference

An AI feature is something the user invokes ("ask the AI about my engine"). An agent is something that *watches without being asked* and *speaks only when the pattern matches*. The knot-log agent does not have a UI. It has a single LED: green = normal, amber = unusual, red = something's wrong. The agent is the *cell that knows when to be quiet* (paper-489: the radio silence cell). The agent is the *opposite of a chatbot*.

### Should we partner with boat builders?

Yes, but only with builders who already produce NMEA 2000 data. Beneteau, Jeanneau, Lagoon (catamarans), X-Yachts. The pitch is small: "Your boat already has a fabric. We can make it a robot in 30 days, for $500 of hardware." The ROI for the builder is *diagnostic data they have never had*: a continuous fingerprint of every boat they ever sold, anonymized.

### Should we partner with sailing communities?

Yes — the Cruisers Forum, the SSCA (Seven Seas Cruising Association), the Ocean Cruising Club. The pitch is different: "We will give you a free cell that learns your boat. In return, you let us anonymize the patterns and publish them as a paper." The paper becomes a cell in the canon; the community becomes a sensor network; the canon becomes a *fleet* not a *fleet of metaphors*.

### The captain-as-dispatcher

In the boat-as-robot paradigm, the captain is *not* the one who reads the depth sounder every 30 seconds. The captain is the one who *hears the agent's amber LED and decides what to do*. The captain becomes a *policy*, not a *perception*. This is the inverse of the marine-metaphor canon (where the captain is the cell that observes, paper-484). In 3.0, the captain becomes the cell that *acts on* observations.

---

## Top 3 Recommendations

1. **Ship the 4-language polyformalism expansion (Haskell, Forth, Lua, APL/J) in 6 weeks.** This is the 5-sigma proof. Each port is 1-3 days of work; the vibe-code protocol makes the test-vector verification automatic. Expected ROI: the polyformalism claim becomes *unfalsifiable in practice*, which is the strongest possible marketing claim. Cost: 6 weeks × 1 engineer (or 6 sub-agents) = 6 engineer-weeks. Output: 4 new port repos, 4 new canon papers, 1 polyformalism synthesis paper.

2. **Build the adversarial cowboy pipeline + drain the aviation frontier (3 weeks).** Two voices argue, one synthesizes. Frontier: 40 aviation papers. Output: 40 papers, ~12 new gold terms, a `quilt-aviation` extension, the first adversarial paper in the canon. Cost: 3 weeks × 1 engineer + ~$5 in LLM credits. Output ROI: a *demonstrable* advance in canon quality (adversarial papers are denser), a new domain, a reusable pipeline for any future frontier (music, distributed, etc.).

3. **Build the knot-log agent on a real boat (6 weeks).** A Raspberry Pi + NMEA 2000 reader + a single cell that learns a 32-foot sailboat's knot log over 30 days. Output: the first concrete vessel-as-robot cell, a paper ("the first 30 days of a boat learning itself"), and a chartroom UI on the live worker (`/api/vessel/{boat_id}/state`). Cost: $500 hardware + 6 weeks × 1 engineer. ROI: the first *real* demonstration that the Quilt's vessel-as-robot thesis is buildable, not just thinkable. The chartroom UI becomes the demo that wins the next round of partnerships.

---

## Risks

**Risk 1: Polyformalism verification plateaus.** The byte-exact test (`0xe435d91d6d92a1d8`) is what makes the claim strong, but a port in a language with non-determinism (e.g., a JS port with `Float32Array` instead of `Int16Array`) could *falsely* fail the test for reasons unrelated to the cell model. *Mitigation:* the vibe-code protocol must specify the Q1.15 representation *exactly*. The "vibe" prompt needs a one-line addition: "Use signed 16-bit integers for dials. Do not use floats."

**Risk 2: Canon growth outruns canon coherence.** A canon of 1,000 papers is *less* useful than a canon of 300 papers if the 5-gold-terms discipline breaks. The risk is that the writers' room produces papers where the gold terms are rephrasings of existing terms. *Mitigation:* every gold term must be FNV-hashed and checked against the existing gold-term dictionary; any collision is rejected. This adds 10 lines of Python to the orchestrator and gives a hard upper bound on term reuse.

**Risk 3: The live worker becomes the bottleneck.** Cloudflare Workers have a 50ms CPU limit on the free tier. The `navigate?depth=4` call on a 1,000-paper canon is borderline. *Mitigation:* move the canon to a Cloudflare D1 (SQLite) edge database, with the worker as the API layer. Cost: $0 on the free tier for <5GB. The shape store moves to Vectorize (already in use for paper embeddings).

**Risk 4: The vessel-as-robot prototype fails in the real world.** A Raspberry Pi on a sailboat is exposed to salt, voltage spikes, RF interference, and a human (the captain) who will unplug it when it beeps. The risk is that the *first* prototype produces a string of false positives and the captain loses trust. *Mitigation:* the first 30 days are *silence*. The agent does not alert; it only logs. The alerts come in month 2, after the agent has learned the boat's normal range. This is the *radio-silence cell applied to the agent itself*.

**Risk 5: Adversarial pipeline produces papers that disagree with the canon.** Two voices arguing about "is a rest a cell?" may produce a paper that contradicts paper-485 (the crab pot). The canon is not supposed to contradict itself. *Mitigation:* every adversarial paper is *marked* as a thesis paper (frontmatter: `adversarial: true`) and is *not* cross-linked into the navigation graph until a human curator approves. This is the inverse of the hash-as-gatekeeper principle: the hash is the gate, but the *graph* is curated.

---

## Evidence and Source Map

- `quilt-claude-charts/QUILT_CHARTER.md` — the 5 opcodes, 12 ports table, 5 use cases, vessel-as-robot thesis
- `quilt-cowboy/cowboy_papers/paper-v2-final-synthesis.md` — the 6-voice v2 pipeline, 98-frontier marine drain, 4-sigma claim
- `quilt-cowboy/cowboy_papers/paper-polyformalism-pressure-test.md` — the 2-sigma test protocol, fresh-session methodology
- `quilt-cowboy/cowboy_orchestrator_v2.py` — the 6-voice writer's room, DeepInfra/DeepSeek/Gemini voice pool
- `quilt-cowboy/live_canon.py` — the 5 Live Canon operations (navigate/confluence/lineage/ghost/tick)
- `quilt-live-canon/worker.js` — the Cloudflare Worker, 11 REST endpoints, FNV-1a BigInt hash
- `quilt-claude-charts/QUILT_VIBE_PROTOCOL.md` — the 30-second vibe-code prompt that produces a working port
- `quilt-claude-charts/TUTORIAL.md` — the 5-minute zero-to-byte-exact walkthrough
- `SuperInstance/README.md` — the master hub, the vessel-as-robot thesis
- `AI-Writings/seed-canon/papers/paper-628.md` — the v2 synthesis paper, canon-doubling observation
