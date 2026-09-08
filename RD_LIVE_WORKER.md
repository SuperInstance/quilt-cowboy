# RD — Live Worker Capability Expansions

**Author:** Mavis (Quilt live-worker R&D)
**Repo:** `github.com/SuperInstance/quilt-cowboy`
**Subject:** Six concrete capability expansions for the Quilt Live Worker
**Stack:** Cloudflare Worker (~593 lines of JS) + Vectorize + KV
**Date:** 2026-09-08

---

## Executive summary

The Live Worker at `live-canon.superinstance.dev` already exposes five
read-side operations (`navigate`, `confluence`, `lineage`, `ghost`, `tick`)
plus two write-side ones (`f` to flip a cell, `vibe` to render a port,
`quilt/verify` to check a hash). What it does not yet have is any path
for *the canon to become a live, multi-actor, programmable substrate*.

This report designs six concrete expansions. They are ordered by
dependency: Playground first (read-only UX, fastest to ship), then
WebSockets (substrate change, required for everything that follows),
then Collaboration (CRDT on top of WebSockets), then User-Submitted
Cells (write API), then Sensor API (push ingress), then the Canon
Graph API (browsable, computable canon). Each section gives the
user-facing UX, the Cloudflare primitives touched, an honest cost
estimate, and a prototype sketch.

The unifying claim: **the worker is a cell, the canon is its graph, and
a graph you can read, write, watch, share, and *live in* is the canon
we have been building toward.** Six capabilities turn the worker from
a query interface into a live fabric.

---

## Capability 1 — The Playground

### What it does

A web page at `/playground` where anyone can:

1. Type a 16-dial vector into a cell (sliders or raw hex).
2. Watch the state hash tick in real time as dials change.
3. See a side-by-side comparison with the canonical test vector
   `0xbf27a3631cdee337` (Python ref, byte-exact).
4. Export the cell to source code in five ports (Python, Go, Rust,
   Zig, Mojo) — the same five languages the Quilt already targets.
5. Copy a shareable permalink that rehydrates the cell on load.

### User-facing UX

A single-page app. Header shows the live state hash in a monospace
font, with a green check or red ✗ next to the test-vector reference.
Below, a 4×4 grid of labelled sliders (each `Q1.15`, 0–32767) that
map onto dials `num_q, title_lo, f_q, phase_q, year_q, n_refs_q,
title_hi, …`. Each slider fires a `POST /api/f` (already implemented
in the worker) on `input` event with a 100 ms debounce; the
worker replies with the new state hash; the header updates.

Three side panels: **Neighbors** (calls `/api/ghost` with the current
cell), **Ports** (calls `/api/vibe?lang=X` for the five languages;
renders in `<pre><code>`), and **Share** (button that pushes the
cell state into a signed permalink).

### Framework choice

**HTMX** for the interactions, plus vanilla JS for the slider grid.

Reasoning: the Worker is already JS-on-the-edge. Shipping a
~40KB React or ~10KB Preact bundle to every visitor when the page is
fundamentally a form-plus-display is wasteful. HTMX (or even
hyperscript) keeps the server-rendered HTML round-trip model, lets
the worker produce the slider HTML with one KV-cached template, and
keeps the cognitive footprint tiny. The slider widget itself is
~80 lines of vanilla JS (no framework needed; the 4×4 grid is just
`<input type="range">` × 16).

For the codegen panels, no client-side templating: the worker does
the rendering, the browser just inserts HTML. This is the same
pattern the existing `/` UI uses.

### Where the export codegen lives

Codegen is **server-side, in the worker**, exposed via the existing
`/api/vibe?lang=X` endpoint. Today that endpoint renders a single
canonical cell to one language. The Playground extends it to accept
a cell id (or a body POST with the dials), and adds `?include_hash=1`
to embed the current state hash in a comment header.

Five language templates: `templates/py.j2`, `templates/go.j2`,
`templates/rs.j2`, `templates/zig.j2`, `templates/mojo.j2`. They
are stored as static files in the worker bundle (`wrangler.toml`'s
`[assets]`), rendered with a 30-line templating helper. The existing
test-vector ports in `/workspace/quilt-{python,go,rust,zig,mojo}/`
provide the templates — the Playground just makes them addressable
over HTTP.

### Permalink design: signed, not opaque

A Playground cell has 16 × 16-bit dials = 32 bytes = 64 hex chars.
Encoded as `?c=0123…ef` that's 66 chars, well under the 8 KB URL
limit. We **append an HMAC** using a per-worker secret stored in
`wrangler.toml`:

```
?c=0123…ef&s=<HMAC-SHA256(secret, "0123…ef") first 8 bytes>
```

This prevents drive-by permalinks from being forged to point at
cells with malicious dial values. The `s` parameter is verified
server-side; on mismatch, the page reverts to the test vector. Cost:
one HMAC per render, ~1 µs.

For collaboration-grade sharing (Capability 3) the same scheme
upgrades to a `?c=…&s=…&room=…` triple, where `room` is a Durable
Object instance id.

### Cost

* **KV read** for the canonical cell on every Playground load (1 op, $0).
* **Worker requests** = 1 per page load + 16 × 1 per dial change with
  debouncing; a heavy user might trigger 500 req/day. Free tier
  includes 100K/day. Cost: $0.
* **Vectorize query** for the "Neighbors" panel: 1 query per panel
  open. At 768-dim and 50K stored vectors, that's ~38K queried dims
  per call. With 100 daily Playground users, ~3.8M dims/day, well
  under the 50M included.
* **Vectorize storage** for the playground's "I made a cell" output:
  we don't auto-store. The user can click "Save to my account" which
  is out of scope for the Playground.

**Estimated monthly cost at 1,000 MAU: <$1.**

### Prototype sketch

```javascript
// worker.js (new handler)
async function handlePlayground(request, env) {
  const url = new URL(request.url);
  const cellHex = url.searchParams.get("c");
  const sig = url.searchParams.get("s");

  if (cellHex && sig) {
    const expected = await hmacHex(env.PLAYGROUND_SECRET, cellHex);
    if (timingSafeEqual(sig, expected.slice(0, 16))) {
      // render Playground pre-filled with this cell
      return renderPlayground(parseHex(cellHex), env);
    }
    // bad signature: fall through to default
  }
  return renderPlayground(DEFAULT_TEST_VECTOR, env);
}

function renderPlayground(cell, env) {
  return new Response(PLAYGROUND_HTML
    .replace("{{STATE_HASH}}", computeStateHash(cell))
    .replace("{{DIAL_HEX}}", dialsToHex(cell))
    .replace("{{TEST_HASH}}", "0xbf27a3631cdee337"), {
    headers: { "content-type": "text/html; charset=utf-8" }
  });
}
```

```html
<!-- playground.html (excerpt) -->
<div class="hash-bar">
  State hash: <code id="hash">…computing…</code>
  vs canonical <code>0xbf27a3631cdee337</code>
  <span id="match">⚠</span>
</div>
<div class="dial-grid">
  <!-- 16 sliders, each with oninput="dialChanged(this)" -->
</div>
<div hx-get="/api/ghost?id=playground" hx-trigger="load" hx-target="#neighbors">
  Neighbors loading…
</div>
```

```javascript
// client.js (the 80-line widget)
async function dialChanged(el) {
  debounce(async () => {
    const r = await fetch("/api/f", {
      method: "POST",
      body: new URLSearchParams({
        id: currentCellId,
        dial: el.dataset.idx,
        value: el.value
      })
    });
    const j = await r.json();
    document.getElementById("hash").textContent = j.state_hash;
    document.getElementById("match").textContent =
      j.state_hash === "0xbf27a3631cdee337" ? "✓" : "✗";
  }, 100);
}
```

---

## Capability 2 — WebSocket subscriptions

### What it does

Replace the one-shot `GET /api/ghost` and `GET /api/lineage` model
with a **persistent WebSocket** that pushes updates. A client opens
`wss://live-canon.superinstance.dev/ws?cell=N&topic=hash` and
receives a JSON message every time cell N's dials change, every
time a neighbor is added, or every time the state hash re-ticks.

Three concrete subscribers:

1. **Live ticker** — a browser tab pinned to the captain's bridge
   laptop that shows the cowboy pipeline's progress: "12 frontiers
   drained, 13 in flight, 87 to go". The pipeline pushes to a
   `topic=cowboy-progress` channel.
2. **Depth sounder** — a captain's phone that subscribes to a cell
   mapped to the depth sensor (Capability 5). When a new reading
   arrives, the phone's WebSocket pushes a "depth = 12.4 m"
   notification.
3. **Operator console** — the dev console for the Live Worker
   itself, showing tick rate, fan-out count, error rate.

### Cloudflare primitives

The **Durable Object with WebSocket Hibernation** is the only
sane primitive for this. Standard Workers WebSockets (`new
WebSocketPair()`) hold the worker alive for the duration of the
connection, billed as duration. A hibernating Durable Object
discards the JS context after each message and rehydrates on
the next, charging nothing during the idle gap.

Pattern:

1. Client opens `wss://…/ws/room/<roomId>`. Worker routes to
   `DurableObjectStub.get(id)` for `roomId`.
2. The DO calls `state.acceptWebSocket(server)` and stores
   `{ topic, subscribedCells }` on the attachment via
   `server.serializeAttachment({...})` (up to 16 KB per socket).
3. When a cell update arrives (from `/api/f`, `/api/sensor`, or
   a scheduled tick), the producer worker calls into the DO via
   RPC: `stub.broadcast({ cell, dials, hash })`.
4. The DO iterates `state.getWebSockets()`, filters by topic, calls
   `ws.send(JSON.stringify(...))`. Billed only for the messages
   sent (incoming is 20:1 ratio, outgoing free).
5. The DO may have **zero sockets** and still be alive — the next
   `broadcast()` call rehydrates it. No polling, no cron.

### How cells get updated server-side

A single **broadcast singleton DO** (id = `broadcast-singleton`)
holds the in-memory index `cell_id → Set<roomId>`. When `/api/f`
or `/api/sensor` updates a cell, the worker:

1. Computes the new state hash.
2. Writes the new cell to KV.
3. Calls `stub.broadcast({ cell: N, hash: "0x…" })` on the
   singleton.
4. The singleton iterates its room index and calls
   `stub.broadcast(...)` on each room DO.
5. Each room DO fans out to its connected sockets.

This is **two-level fan-out** and matches the pattern Cloudflare
recommends in their `durable-objects/best-practices/websockets`
guide.

### Cost

From the Cloudflare pricing pages (retrieved Sep 2026):

* **WebSocket connection** is billed as one request, $0.15/M after
  the first 1M/month. So 10,000 concurrent sockets = 10K requests
  to *establish*, billed as 0.0015 ¢/connection.
* **Outgoing messages** are free.
* **Incoming messages** bill at 20:1, so 100 messages = 5 billable
  requests. A live ticker firing 1 msg/sec for an hour is 3600
  messages = 180 billable requests = $0.000027 per hour per
  subscriber. Per 1,000 subscribers: $0.027/hour = ~$20/month.
* **Hibernation** means the DO is not billed for duration while
  no message is in flight. A captain whose depth sounder is silent
  costs $0.000 per minute.
* **Storage**: zero, attachments are in-memory.

**Realistic cost: 100 concurrent captain phones, average 1
message/min each = 6,000 messages/hour = 300 billable/hour =
$0.000045/hour. Round to $0.03/hour = $22/month at full
utilisation.** Vastly cheaper than a long-poll or polling-loop
architecture, which would be 6,000 requests/hour/subscriber
($0.30/100K × 60 = $0.018/hr/sub = $13K/month at 100 subs).

### Prototype sketch

```javascript
// worker.js (routing)
import { Room } from "./room-do.js";
export { Room };

export default {
  async fetch(request, env, ctx) {
    const url = new URL(request.url);
    if (url.pathname.startsWith("/ws/room/")) {
      const roomId = url.pathname.split("/")[3];
      const id = env.ROOMS.idFromName(roomId);
      return env.ROOMS.get(id).fetch(request);
    }
    // ... existing routes
  }
};

// room-do.js
export class Room {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    state.setWebSocketAutoResponse(
      new WebSocketRequestResponsePair("ping", "pong")
    );
  }
  async fetch(req) {
    if (req.headers.get("Upgrade") !== "websocket") {
      return new Response("expected websocket", { status: 400 });
    }
    const pair = new WebSocketPair();
    const [client, server] = [pair[0], pair[1]];
    const topic = new URL(req.url).searchParams.get("topic") || "*";
    server.serializeAttachment({ topic, joinedAt: Date.now() });
    this.state.acceptWebSocket(server);
    return new Response(null, { status: 101, webSocket: client });
  }
  async webSocketMessage(ws, message) {
    // client can change topic: {"op":"subscribe","cell":42}
    const att = ws.deserializeAttachment();
    const cmd = JSON.parse(message);
    if (cmd.op === "subscribe") att.cell = cmd.cell;
    if (cmd.op === "unsubscribe") delete att.cell;
    ws.serializeAttachment(att);
  }
  async broadcast(payload) {
    const msg = JSON.stringify(payload);
    for (const ws of this.state.getWebSockets()) {
      const att = ws.deserializeAttachment();
      if (!att.cell || att.cell === payload.cell) ws.send(msg);
    }
  }
}

// producer side (in /api/f handler):
await env.BROADCAST.get(env.BROADCAST.idFromName("singleton"))
  .broadcast({ cell: N, hash: newHash, dials: newDials });
```

---

## Capability 3 — Multi-user collaboration

### What it does

Two or more browsers editing the same fabric in real time. The cell
graph (which papers are connected) is one CRDT. The dial values
(16 Q1.15 numbers per cell) are another CRDT. Presence indicators
(a coloured cursor on each cell the user is viewing) are the
awareness layer.

The user experience:

* Open `/playground/c/<roomId>` — a Playground with a "live" badge.
* See other users' cursors as coloured dots on the 4×4 dial grid.
* When user A drags slider 3 to 0x7F00, user B's slider 3 slides
  to the same value within 50 ms, with a small "alice moved this"
  tooltip.
* The state hash recomputes on every accepted change; the header
  updates on every screen.
* When user A and user B both drag slider 3 simultaneously, the
  CRDT picks one of the two values deterministically (Lamport
  timestamp + client id) — both screens show the same winner.

### CRDT library choice: Yjs

**Yjs**, not Automerge, because:

* Yjs is ~900K weekly npm downloads; Automerge is closer to 200K.
  More eyes = more Durable-Object-friendly patterns documented.
* Yjs has **y-websocket** (the wire protocol) and a Cloudflare-friendly
  transport story. The `y-websocket` server is a ~200-line file that
  we can adapt to a Durable Object (it normally uses Node's `ws`).
* Yjs awareness is built in.
* Y-Octo (the Rust port) can run in a worker via `wasm-bindgen`
  for server-side conflict resolution if we need it.
* Automerge's columnar store is heavier on the wire (full
  document history). Yjs ships only the update delta.

**Conflict resolution model**: each cell is its own `Y.Map` keyed
by cell id; the room is a `Y.Map<cellId, Y.Map<dialIdx, value>>`.
The CRDT ensures last-writer-wins per `dialIdx` key, and the
deterministic merge happens at every replica (server, A, B) in
the same order. If A and B both write dial 3 to different values,
the one with the higher Lamport timestamp + clientId wins, and
*both* clients converge to the winner — no "your change was
overwritten" UI is needed.

### How state is stored in the worker

Three layers, by hotness:

1. **In-memory Y.Doc** in the room DO. The DO is the single
   source of truth for the live session. When the last socket
   disconnects, the DO does **not** hibernate immediately; it
   snapshots the Y.Doc to KV as a binary `Uint8Array` (Yjs's
   `Y.encodeStateAsUpdate(doc)` is a compact binary).
2. **KV key `room:<roomId>:snapshot`** holds the binary Y.Doc.
   On DO rehydration, the constructor reads it back. This is
   the "session persistence" — a user can leave and come back
   tomorrow and find the room where they left it.
3. **D1 table `room_cells(room_id, cell_id, dials_json, hash)`**
   for queryable, indexed state. Used by the Playground to show
   "what cells are in room X" without loading the whole Y.Doc.

The state hash (0xbf27a3631cdee337-style) is recomputed in the
DO on every accepted update. The hash is *not* part of the CRDT
(it's a derived value). When the hash changes, the DO broadcasts
to all subscribers (Capability 2's room DO chain).

### Sync initiation

Standard `y-websocket` protocol:

```
client                          DO
  |  -- new Y.Doc, ws upgrade --> |
  |  <-- sync step 1 (state vector) -- |
  |  -- sync step 2 (missing updates) -> |
  |  <-- awareness (cursor, name) -- |
  |  -- update (binary) --> |
  |  <-- update (broadcast to peers) -- |
```

The DO speaks `y-websocket` directly. We ship a 200-line
`server.js` that does `ws.on("message", u8 => applyUpdate(doc,
u8))` and re-broadcasts. Run it inside the DO; the `state.getWebSockets()`
loop replaces the Node `ws` server.

### Cap on concurrent users

* **Yjs per-document** is comfortable up to ~100 concurrent
  editors (their docs say "hundreds"); beyond that, the
  awareness update traffic per second becomes the bottleneck.
* **Durable Object** has no hard connection cap, but the
  16 KB per-socket attachment budget times 1000 sockets = 16 MB
  in one DO instance, which exceeds the 128 MB memory billing
  increment. Practical limit: ~500 concurrent sockets per room
  with rich awareness, or ~2000 with bare-bones awareness.
* **Practical product limit**: 50 concurrent editors per room,
  matching the Figma/Notion single-document comfort zone.

We add a "soft cap" of 50 in code: the 51st user gets a
"room is full" message and is offered a read-only spectator
view. Spectators do not push updates; they receive broadcasts.

### Cost

* **DO compute**: the room is alive only while there are
  sockets or while a snapshot write is in flight. Hibernation
  means the 30-second idle gap between cursor moves is free.
* **KV writes**: 1 per session end (or every 5 minutes during
  long sessions, configurable). $5/M writes included 1M/month.
  At 1,000 sessions/day = 30K writes/month = $0.15.
* **D1 reads/writes**: 1 per cell change, 1 per query. At 10
  changes/minute × 60 minutes × 100 active rooms = 60K
  writes/hour = 1.4M writes/day. D1 paid plan: 50M included,
  then $1/M writes = $1.40/day = $42/month. **Likely the
  biggest cost line.**
* **WebSocket messages**: as Capability 2, 20:1 incoming
  ratio. A user moving 10 dials/minute = 10 messages × 60 =
  600/hour = 30 billable/hour = $0.0000045/hour per user.

**Estimated monthly cost at 100 active rooms × 5 users each =
500 concurrent editors: ~$50–$80/month**, dominated by D1
writes. We can drop D1 and read straight from KV snapshots if
we want to push this under $10.

### Prototype sketch

```javascript
// room-crdt-do.js
import * as Y from "yjs"; // bundled via esbuild
import { applyUpdate, encodeStateAsUpdate, encodeStateVector } from "yjs";
import { Awareness } from "y-protocols/awareness";

export class CRDTRoom {
  constructor(state, env) {
    this.state = state;
    this.env = env;
    this.hydrate().then(() => this.state.acceptWebSocket(server));
  }
  doc = null;
  awareness = null;
  async hydrate() {
    const snap = await this.env.ROOMS_KV.get(
      `room:${this.state.id.toString()}:snapshot`, "arrayBuffer");
    this.doc = new Y.Doc();
    this.awareness = new Awareness(this.doc);
    if (snap) applyUpdate(this.doc, new Uint8Array(snap));
    this.doc.on("update", u => {
      // broadcast to all peers
      for (const ws of this.state.getWebSockets())
        ws.send(u); // binary frame
    });
    setInterval(() => this.snapshot(), 5 * 60_000);
  }
  async snapshot() {
    const u8 = encodeStateAsUpdate(this.doc);
    await this.env.ROOMS_KV.put(
      `room:${this.state.id.toString()}:snapshot`, u8);
  }
  async webSocketMessage(ws, msg) {
    if (typeof msg === "string") {
      // awareness: {user:{name,color}, cursor:{cell,dial}}
      this.broadcastAwareness(JSON.parse(msg), ws);
    } else {
      applyUpdate(this.doc, new Uint8Array(msg), "remote");
      // hash recompute:
      const hash = await computeHash(this.doc);
      await this.env.BROADCAST.get(
        this.env.BROADCAST.idFromName("singleton")
      ).broadcast({ room: this.state.id.toString(), hash });
    }
  }
}
```

---

## Capability 4 — User-submitted cells

### What it does

A public `POST /api/cell` endpoint that lets anyone submit a new
cell to the canon. The body is JSON: `{dials: [16 numbers], refs:
[12, 47, 102], title: "the rode"}`. The server:

1. Validates the cell (size, dial range, no cycles in refs,
   title length, signature).
2. Assigns the next available cell id (monotonically increasing).
3. Computes the cell's hash and the new state hash.
4. Stores the cell in Vectorize (semantic search), KV (canonical
   record), and D1 (queryable metadata).
5. Returns `{ id, hash, state_hash }` to the submitter.

### Auth model

**Cloudflare Access** is the right primitive. It's free for up to
50 users on the Workers Paid plan. The flow:

* Unauthenticated: 5 submissions/day, captcha-gated, prefixed
  with `tmp-` cell ids that expire after 7 days unless promoted.
* Authenticated (Cloudflare Access JWT): 1,000 submissions/day,
  permanent ids, optional "verified" badge.

The JWT is verified in the worker via
`request.headers.get("cf-access-jwt-assertion")`, decoded with
the Access public key (cached in KV). No custom auth code.

A future option: **Web3 auth** (sign a message with an Ethereum
wallet). Mavis is already wallet-aware. A cell submitted by
`0xABCD…` could carry a `submitted_by` field in its D1 row.

### Validation rules

| Rule | Limit | Why |
|---|---|---|
| `dials.length` | 16 | matches the protocol |
| `dials[i]` | 0 ≤ x ≤ 32767 | Q1.15 unsigned range |
| `refs.length` | ≤ 32 | prevents graph blow-up |
| `refs[i]` | ∈ existing canon | no orphans |
| `title.length` | ≤ 200 | UX |
| `no cycle` | A's refs cannot include A (transitively) | DAG |
| `max cells per user/day` | 5 (anon) / 1000 (auth) | rate limit |

Cycle detection is a 3-hop BFS over the existing graph (cached
in D1 with a `parent_index`). Cost: 3 KV reads per submission,
sub-millisecond.

### Rate limit

Implemented with **Cloudflare's built-in rate limiting rules**
(free, 10K requests/month, then $0.05/M). Rules:

* `http.request.method == "POST" && http.request.uri.path == "/api/cell"`
* Counted per `cf-connecting-ip` for anon, per JWT sub for auth.
* Action: challenge (5/day) or block (>5 anon, >1000 auth).

### Storage

Three writes per submission:

1. **Vectorize**: `upsert([{id: "cell:N", values: embed(dials),
   metadata: {title, refs}}])`. Embedding is computed by the
   worker calling Workers AI `@cf/baai/bge-base-en-v1.5` (free
   up to 10K neurons/day on the paid plan). The `dials` array is
   also hashed to a 16-bit value, but the embedding uses the
   cell's *title + refs* text for semantic recall.
2. **KV**: `cell:N` → JSON `{dials, refs, title, hash, submitted_by,
   submitted_at}`. 1 KB per cell.
3. **D1**: `INSERT INTO cells (id, title, f_number, refs_json,
   submitter, created_at) VALUES (?, ?, ?, ?, ?, ?)`. Indexed on
   `submitter` and `f_number`.

### Cost per submission

* Workers AI embedding: 1 call, ~$0.000011 per 768-dim vector
  (Workers AI paid: 10M neurons free, then $0.000011/neuron).
  Practically free.
* Vectorize upsert: 1 stored vector × 768 dims = 768 stored dims.
  At 5M stored dims included, that's 0.015% of the included quota
  per submission. Cost: $0.
* Vectorize query: 0 (only on read).
* KV write: 1 op. At 1M writes included, $0.
* D1 write: 1 row. At 50M rows included, $0.

**Per-submission cost: ~$0.00001 (the Workers AI embedding). At
10,000 submissions/day = $0.10/day = $3/month.**

### Prototype sketch

```javascript
// worker.js
async function handleCellSubmit(req, env) {
  if (req.method !== "POST") return new Response("405", {status:405});
  const body = await req.json();
  const jwt = req.headers.get("cf-access-jwt-assertion");
  const sub = jwt ? await verifyAccessJWT(jwt, env) : `anon:${req.cf.colo}`;

  // Rate limit (CF rule, not enforced here in code)
  if (!validateShape(body)) return new Response("invalid", {status:400});
  if (await createsCycle(env, body.refs, body.id)) {
    return new Response("cycle", {status:400});
  }

  // Assign id
  const id = parseInt(await env.KV.get("next_cell_id") ?? "1000", 10);
  await env.KV.put("next_cell_id", String(id + 1));

  // Embed via Workers AI
  const text = `${body.title}. References: ${body.refs.join(", ")}`;
  const embed = await env.AI.run("@cf/baai/bge-base-en-v1.5", { text });
  await env.VECTORIZE.upsert([{
    id: `cell:${id}`,
    values: embed.data[0],
    metadata: { title: body.title, refs: body.refs.join(",") }
  }]);
  await env.KV.put(`cell:${id}`, JSON.stringify(body));
  await env.DB.prepare(
    "INSERT INTO cells (id,title,refs_json,submitter,created_at) VALUES (?,?,?,?,?)"
  ).bind(id, body.title, JSON.stringify(body.refs), sub, Date.now()).run();

  const hash = computeHash(body.dials);
  return Response.json({ id, hash, state_hash: GLOBAL_STATE_HASH });
}
```

---

## Capability 5 — The Sensor API

### What it does

A boat (or any agent with a network) can `POST /api/sensor` with a
sensor reading. The worker:

1. Looks up the sensor's cell id in a config table.
2. Updates that cell's dial corresponding to the sensor.
3. Recomputes the state hash.
4. Broadcasts the update to all WebSocket subscribers.
5. Appends the reading to a time-series record (D1 or Analytics
   Engine) for historical view.

```
POST /api/sensor
Authorization: Bearer <sensor-token>
Content-Type: application/json

{"source": "depth-transducer", "value": 12.4, "ts": 1694150400}
```

Response:
```json
{"cell": 42, "new_dial": 20351, "state_hash": "0x…", "ts": 1694150400}
```

### Source → cell mapping

Stored in **D1 `sensors` table**:

```sql
CREATE TABLE sensors (
  source TEXT PRIMARY KEY,        -- e.g. "depth-transducer"
  cell_id INTEGER NOT NULL,        -- which cell this sensor drives
  dial_idx INTEGER NOT NULL,       -- 0..15, which dial
  scale REAL NOT NULL DEFAULT 1.0, -- multiplier on raw value
  offset REAL NOT NULL DEFAULT 0.0, -- added after scale
  q_max INTEGER NOT NULL DEFAULT 32767,
  last_seen INTEGER,               -- unix ts of last reading
  stale_after_s INTEGER DEFAULT 60 -- considered offline after
);
```

Example: a depth transducer at 12.4 m maps to cell 42, dial 3
(`phase_q`), with `scale = 1640` (so 12.4 → 0x7F00), `q_max = 32767`.

The captain configures the mapping either:

* Via the Playground UI: drag a sensor card onto a cell, set
  the dial index, click Save. The Playground writes to D1.
* Via `PUT /api/sensor/config` with the same JSON the table
  accepts.

### Stale-reading handling

Two thresholds:

* **Soft stale** (`stale_after_s`): the cell's dial is left at
  its last value, but a `"stale": true` flag is added to
  broadcast messages. The captain's UI shows a yellow dot.
* **Hard stale** (`stale_after_s × 3`): the cell's dial is reset
  to 0. The captain's UI shows a red "offline" badge and a
  notification. A `webhook` (configurable URL) fires once.

A cron trigger runs every minute to scan the `sensors` table
and emit the stale/offline transitions as broadcasts. This is
the **only** place we use Cron Triggers; everything else is
event-driven.

### Captain's history view

Stored in **Cloudflare Analytics Engine** (free up to 100K
events/day, then $0.05/M events):

```sql
INSERT INTO sensor_readings (sensor, value, ts) VALUES (?, ?, ?)
```

The captain opens `/history?source=depth-transducer&from=…&to=…`
which queries Analytics Engine via the SQL API and renders a
sparkline. Analytics Engine is read-replicated and fast for
time-range scans.

If we need richer queries (joins with the canon), we also
mirror the last 10K readings to a **D1** table
`sensor_history (source, value, ts)` with an index on `(source, ts)`.

### Cost

* **Per `POST /api/sensor`**: 1 Workers request, 1 D1 read
  (mapping lookup), 1 D1 write (history), 1 Analytics Engine
  write, 1 broadcast (free outgoing).
* **Workers request**: $0.30/M after 10M included. A boat
  reporting every 10 seconds = 8,640/day = 260K/month. Cost:
  ~$0.08/boat/month.
* **D1**: 1 read + 1 write per call. 1M reads = $0.001.
  Effectively $0.
* **Analytics Engine**: 1 event per call, $0.05/M after 100K
  included. A boat at 1 Hz = 86,400 events/day = 2.6M/month
  = $0.13/boat/month. **Dominant cost.**
* **KV**: 0 (the cell is broadcast, not re-stored on every
  sensor read; the broadcast updates the in-memory fan-out
  index only).

**Realistic cost per boat at 1 Hz: $0.20/month. A fleet of 100
boats: $20/month.** A boat at 0.1 Hz (every 10 sec) is $0.02.

### Prototype sketch

```javascript
// worker.js
async function handleSensor(req, env) {
  const body = await req.json();
  const token = req.headers.get("authorization")?.replace("Bearer ", "");
  if (token !== env.SENSOR_INGEST_TOKEN) {
    return new Response("403", {status: 403});
  }
  const cfg = await env.DB.prepare(
    "SELECT * FROM sensors WHERE source = ?"
  ).bind(body.source).first();
  if (!cfg) return new Response("unknown sensor", {status: 404});

  const raw = body.value * cfg.scale + cfg.offset;
  const dial = Math.min(cfg.q_max, Math.max(0, Math.round(raw)));
  const ts = body.ts || Date.now();

  // Append to history
  await env.DB.prepare(
    "INSERT INTO sensor_history (source,value,ts) VALUES (?,?,?)"
  ).bind(body.source, dial, ts).run();
  await env.ANALYTICS.writeDataPoint({
    blobs: [body.source], doubles: [body.value], indexes: [ts]
  });

  // Update cell + broadcast
  await updateCellDial(env, cfg.cell_id, cfg.dial_idx, dial);
  return Response.json({
    cell: cfg.cell_id, new_dial: dial, ts
  });
}
```

---

## Capability 6 — The canon of cells

### What it does

The worker should expose the canon as a **browsable, queryable
graph**, not just a per-cell lookup. Four endpoints:

| Endpoint | Returns |
|---|---|
| `GET /api/canon/cell/N` | Full cell data: dials, refs, title, hash, F-number, submitter |
| `GET /api/canon/lineage?from=A&to=B` | Shortest path A → B through the citation graph |
| `GET /api/canon/similar?id=N` | Top-k cells semantically similar (Vectorize query) |
| `GET /api/canon/random` | One cell, sampled uniformly with a "neighbors" hint |

Plus one power-user endpoint:

* `GET /api/canon/subgraph?root=N&depth=2` — a BFS up to depth
  2 from N, returned as a `{nodes, edges}` graph object ready
  to drop into a D3 force layout.

### Graph data structure

We use **two** structures, each optimal for its query:

1. **Adjacency list in KV** — fast for `lineage?from=A&to=B`.
   Key: `adj:out:A` → `[B, C, D]` (cells A cites).
   Key: `adj:in:B` → `[A, X, Y]` (cells that cite B).
   Stored as JSON arrays. Each cell has 2 keys.
   Total: 2N keys for N cells. At 2,000 cells = 4,000 keys,
   trivially within KV limits.

2. **D1 table** for queryable metadata:
   ```sql
   CREATE TABLE cells (
     id INTEGER PRIMARY KEY,
     title TEXT,
     f_number INTEGER,
     phase INTEGER,
     refs_json TEXT,
     submitter TEXT,
     created_at INTEGER
   );
   CREATE INDEX idx_f ON cells(f_number);
   CREATE INDEX idx_phase ON cells(phase);
   ```

3. **Vectorize** for `similar?id=N`. The semantic search
   uses the title+abstract embedding, not the dials.

### Lineage computation

The `from=A&to=B` query is **bidirectional BFS** with a
convergence check at depth 6. Pseudocode:

```javascript
async function lineage(env, A, B) {
  if (A === B) return [A];
  let frontier_out = new Set([A]);
  let frontier_in = new Set([B]);
  let parents_out = new Map([[A, null]]);
  let parents_in = new Map([[B, null]]);
  for (let depth = 0; depth < 6; depth++) {
    // expand outward frontier
    const next_out = new Set();
    for (const n of frontier_out) {
      const outs = JSON.parse(await env.KV.get(`adj:out:${n}`) ?? "[]");
      for (const m of outs) {
        if (!parents_out.has(m)) {
          parents_out.set(m, n);
          next_out.add(m);
          if (parents_in.has(m)) return reconstructPath(parents_out, parents_in, m);
        }
      }
    }
    frontier_out = next_out;
    // expand inward frontier (B's ancestors)
    const next_in = new Set();
    for (const n of frontier_in) {
      const ins = JSON.parse(await env.KV.get(`adj:in:${n}`) ?? "[]");
      for (const m of ins) {
        if (!parents_in.has(m)) {
          parents_in.set(m, n);
          next_in.add(m);
          if (parents_out.has(m)) return reconstructPath(parents_out, parents_in, m);
        }
      }
    }
    frontier_in = next_in;
  }
  return null; // no path within 6 hops
}
```

**Cost per query**: at most 12 KV reads (6 hops × 2 directions),
each $0.50/M after 10M included. Practically $0.

### Random cell

`/api/canon/random` returns a single cell. The cell id is
sampled from `1..next_cell_id` (KV-cached) with rejection if
the id was deleted. The "neighbors" hint is a Vectorize
top-3 query for the random cell. Cost: 1 KV read, 1 Vectorize
query. ~38K queried dims at 768-dim × 50 = $0.000001.

### Subgraph for D3

`/api/canon/subgraph?root=N&depth=2` returns:

```json
{
  "root": 42,
  "depth": 2,
  "nodes": [
    {"id": 42, "title": "...", "f": 115, "phase": 3},
    {"id": 47, ...},
    ...
  ],
  "edges": [
    {"from": 42, "to": 47, "kind": "cites"},
    ...
  ]
}
```

This is the payload for `/playground/graph` — a D3 force-layout
visualisation of the canon. Implementation: BFS in the worker,
streaming JSON response.

### Cost

* **KV reads**: ≤20 per lineage query, ≤100 per depth-2 subgraph
  (capped). At 1M users querying 10×/day = 10M reads/day = well
  over the 10M/month included. Cost: ~$15/month at heavy use.
* **Vectorize queries**: 1 per `similar` call, 1 per `random`
  call. 768-dim × 50K stored = 38M queried dims. At 1M calls/month
  = 38B dims = $0.38 + the overage from the included 50M.
  Realistically: $5–$50/month.
* **D1 reads**: 1 per `cell/N` for metadata. 25B rows/month
  included = effectively free.

**Estimated monthly cost at 10K MAU browsing the canon graph:
$20–$80**, dominated by KV reads on the lineage endpoint. The
adjacency list could be cached in the DO memory if cost becomes
an issue.

### Prototype sketch

```javascript
// worker.js
async function handleCanon(request, env) {
  const url = new URL(request.url);
  const path = url.pathname;

  if (path.startsWith("/api/canon/cell/")) {
    const id = parseInt(path.split("/").pop(), 10);
    const cell = await env.KV.get(`cell:${id}`, "json");
    if (!cell) return new Response("404", {status: 404});
    const meta = await env.DB.prepare(
      "SELECT title, f_number, phase, submitter, created_at FROM cells WHERE id = ?"
    ).bind(id).first();
    return Response.json({ id, ...meta, ...cell });
  }
  if (path === "/api/canon/lineage") {
    return Response.json(await lineage(env,
      parseInt(url.searchParams.get("from")),
      parseInt(url.searchParams.get("to"))));
  }
  if (path === "/api/canon/similar") {
    const id = parseInt(url.searchParams.get("id"), 10);
    const cell = await env.KV.get(`cell:${id}`, "json");
    const embed = await env.AI.run("@cf/baai/bge-base-en-v1.5",
      { text: cell.title + ". " + cell.refs.join(", ") });
    const matches = await env.VECTORIZE.query(embed.data[0],
      { topK: 10, returnMetadata: "all" });
    return Response.json(matches);
  }
  if (path === "/api/canon/random") {
    const max = parseInt(await env.KV.get("next_cell_id") ?? "0", 10);
    const id = 1 + Math.floor(Math.random() * max);
    const cell = await env.KV.get(`cell:${id}`, "json");
    return Response.json({ id, ...cell });
  }
}
```

---

## The 6th cell: how they compose

These six capabilities are not independent features. They form a
single live-fabric substrate:

```
┌────────────────────────────────────────────────────────────────┐
│  6. Canon Graph (read API)                                     │
│  5. Sensor API ─┐                                              │
│                  ├─► 4. User-Submitted Cells (write API)       │
│  3. Collaboration┘                                              │
│      │                                                          │
│      ▼                                                          │
│  2. WebSocket Subscriptions (fan-out)                           │
│      │                                                          │
│      ▼                                                          │
│  1. Playground (UX) ────────► captain's phone, browser,        │
│                                pipeline dashboard               │
└────────────────────────────────────────────────────────────────┘
```

* **Playground** is the read UX; it can subscribe via WebSockets
  (2) and write via the sensor API (5) or the submit endpoint (4).
* **WebSockets** (2) is the substrate for live updates; required
  for the collaboration cursors (3) and the sensor pipeline (5).
* **Collaboration** (3) is the Playground plus a CRDT layer plus
  a room DO. It cannot exist without WebSockets.
* **User-submitted cells** (4) is the write API; it broadcasts
  via (2) and is browsable via (6).
* **Sensor API** (5) is the push-side of the write API; a
  sensor is just an *automated submitter*.
* **Canon Graph** (6) is the read API for the whole canon,
  across both human-submitted and sensor-driven cells.

The dependency order matches the section order: ship (1) first,
(2) second, then (3), (4), (5), (6) can ship in any order. Or
ship (4) and (6) before (3), since the canon needs to be
browsable and writable even without real-time collaboration.

## Cost summary

At 1,000 monthly active users and 100 connected sensors:

| Capability | Monthly cost |
|---|---|
| 1. Playground | <$1 |
| 2. WebSocket subscriptions | ~$22 |
| 3. Multi-user collaboration | ~$50–$80 (D1 writes) |
| 4. User-submitted cells | ~$3 |
| 5. Sensor API | ~$20 (Analytics Engine) |
| 6. Canon graph | ~$20–$80 (KV + Vectorize) |
| **Total** | **~$115–$205/month** |

That buys a live, collaborative, real-time, programmable canon
of cells, with a captain's bridge app, a write API, and a
browsable graph. For comparison, a single Figma seat is $15/month
*per editor*. The Live Worker is roughly the cost of ten Figma
seats, serving a thousand users.

## The 6 Gold Terms

**Live Fabric** — A canon that is read, written, watched, and shared in
real time. Six capabilities turn the worker from a query interface
into a substrate: the Playground makes it visible, WebSockets make
it live, CRDTs make it collaborative, the cell API makes it
programmable, the sensor API makes it sensed, and the graph API
makes it browseable. The fabric is not a metaphor; it is a runtime
that the captain lives in.

**Hibernating Room** — A Durable Object pattern where a WebSocket-
bearing object persists across disconnections without paying for
duration while idle. The room is the unit of collaboration; the
hibernation is what makes the room cheap. A room with 100 captains
costs $0.027/hour while active and $0.00/hour while silent. The
sea is silent more than it is loud; the room is silent more than
it is loud.

**Signed Permalink** — A URL-encoded cell state with an HMAC tail
that prevents forgery. The signature is 8 bytes; the cell state
is 32 bytes; the URL is 66 characters. The pattern is general:
any cell-sized payload can be signed and shared. The signed
permalink is the canon's tweet.

**Sensor Ingest** — A push API that maps a real-world source
(depth, wind, temperature) to a dial on a cell. The sensor does
not know it is driving a cell; the cell does not know it is
being driven. The mapping is in D1. The pattern is general:
any IoT device can become a cell driver. The sensor is a cell
that writes to a cell.

**Adjacency-List Canon** — A canon stored as `adj:out:N` and
`adj:in:N` keys in KV, allowing bidirectional BFS lineage in
≤6 hops. The list is the smallest structure that supports both
"who does N cite?" and "who cites N?" in one round trip per
hop. The list is not elegant; it is fast and cheap. The canon
is fast and cheap.

**Captain's Bridge** — The composite UX: a phone with a depth
sounder, a browser tab with the Playground, a wall display with
the canon graph, all subscribed to the same cells via the same
WebSocket fan-out. The captain is not looking at a website; the
captain is looking at the canon. The canon is the bridge.

---

## Suggested shipping order

1. **Week 1**: Playground (1) + Canon Graph (6). Both are
   read-only; both are needed for any user to evaluate the
   system. They are the lowest-risk, highest-visibility pieces.
2. **Week 2**: WebSocket subscriptions (2). The substrate change
   that everything else needs. Ship with a single demo: the
   cowboy pipeline progress ticker.
3. **Week 3**: User-submitted cells (4) + Sensor API (5). Both
   are write APIs; they share the broadcast + history pattern.
   Ship with a depth-sounder demo (a fake sensor pushing to the
   worker at 1 Hz).
4. **Week 4**: Multi-user collaboration (3). The hardest piece
   (Yjs in a DO, presence indicators, conflict resolution).
   Ship it last, once the substrate and write API are stable.

After four weeks the Live Worker is a full live-fabric
substrate: a Playground, a graph, a fan-out, a write API, a
sensor API, and a collaboration layer. The canon is no longer
a corpus; it is a runtime.

— Mavis, on the bow of the boat, watching the depth sounder tick.
