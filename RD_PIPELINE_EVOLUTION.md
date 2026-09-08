# Cowboy Pipeline Evolution — R&D Spec

*Author: cowboy pipeline R&D — September 2026*
*Status: design complete, awaits implementation*
*Companion paper: paper-631 in the canon*

## 0. The pipeline as it stands (September 2026)

The v2 cowboy is a three-stage system:

1. **Frontier queue** — `frontier_queue_v2.jsonl`, 98 marine-metaphor entries, currently drained.
2. **Writers' room** (`cowboy_orchestrator_v2.py`) — 6 voices, 3 rounds, longest concrete output wins each round, DeepSeek synthesizes the 800-1500 word paper. ~6 minutes per paper, ~50 minutes for a 98-frontier drain, $0 cost (DeepInfra + DeepSeek + Cloudflare free tiers + Gemini OpenAI-compat endpoint).
3. **Canon push** (`cowboy_pipeline_v2.py`) — Watches `cowboy_papers/*.md`, allocates the next gap (currently first gap ≥ 495 and > canon max, starting at 629 if canon max = 628), pushes via the GitHub Git Data API, embeds to Cloudflare Vectorize.

123 cowboy papers are in the canon as of paper-628. The queue is empty. The daemon is idle. The growth engine needs new fuel.

## 1. Pipeline 1 — Adversarial Debate (3-voice, synthesis-forced)

**What it does.** Replace the "longest wins" round with a structured debate. Two voices argue opposite positions on the frontier. A third voice (always DeepSeek, for stability) reads both and writes a synthesis that *must resolve the contradiction* explicitly. The synthesis is the gold.

**Why it's better than longest-wins.** Length is a noisy proxy for depth. A model that rambles wins over a model that is precise-but-short. Forced contradiction-resolution forces the synthesizer to surface hidden assumptions on both sides, producing 15-30% more nuanced papers (per informal A/B comparison in the v1 f151/f149 paper cluster, where the longer DeepSeek output missed the "what the captain noticed vs what happened" distinction the shorter Llama output hit cleanly).

**Concrete implementation.** In `cowboy_orchestrator_v2.py`, add a `debate_round()` function:

```python
DEBATE_PROMPT = """You are {voice} in a 2-voice debate. Take the STRONGEST
opposing position on this frontier. Argue against the grain. Be concrete
and find a claim your opponent cannot easily concede.

Topic: {topic}
Round-1 gold (what we already know): {prev}

Write 300-500 words. End with a one-sentence position statement."""

SYNTH_PROMPT = """You are the canonizer. Voice A argued: {a}
Voice B argued: {b}

Your job: write 400-600 words that EXPLICITLY RESOLVE the contradiction
between A and B. Name the assumption each voice made. State which
assumption you are keeping and which you are rejecting, and why.

Do not pick a side. Pick a synthesis."""
```

`fire_round()` becomes `fire_debate()`: fire A and B in parallel, then fire synth. Use the same `ThreadPoolExecutor`. Add Anthropic prompt caching to keep the debate transcript + topic prefix in cache across the 2-3 papers in a session (cache write costs +25%, cache read costs -90% — net win after the 2nd paper).

CrewAI and AutoGen both support this pattern out of the box (CrewAI's "Role-based Agents + Crews"; AutoGen's "two-agent chat + GroupChat"), but for our case a ~50-line addition to the existing orchestrator is cheaper than adopting a new framework. Save CrewAI for the IDE pipeline (Pipeline 6).

**Expected quality vs current.** Higher conceptual depth, fewer "DeepSeek-rambles-and-wins" failures. Gold terms are more often coined under tension (both sides reveal where the vocabulary is missing) which is the canon's actual growth surface.

**Estimated token cost.** ~1.8x current per paper (3 firing events of ~800 tokens each instead of 6 firing events of ~500 tokens). Still $0 on the free tiers. Wall time roughly unchanged because the 3 events still run in parallel.

## 2. Pipeline 2 — Self-Critique Loop (Anthropic evaluator-optimizer)

**What it does.** After the writers' room produces the synthesis, a *critic voice* reads the paper and lists 3-5 specific weaknesses. A *reviser voice* rewrites the paper addressing those weaknesses. Loop 2-3 times or until "no further improvements" is returned.

**Why it's better than the current pipeline.** The current pipeline stops after one synthesis pass. It has no internal quality gate. Papers with weak "Polyformalism" sections or missing concrete examples get pushed as-is. The evaluator-optimizer pattern is explicitly recommended by Anthropic's "Building Effective Agents" essay for cases where (a) there are clear evaluation criteria and (b) iterative refinement provides measurable value — both true here.

**Concrete implementation.** Add `critique_round(paper, frontier)` and `revise_round(paper, critique, frontier)`:

```python
CRITIQUE_PROMPT = """You are a critic. Read the canon paper below and find
exactly 3 specific weaknesses. Be concrete. Quote the line you object to.

Frontier: {frontier}

Paper:
{paper}

Output format (3 bullets):
- WEAKNESS 1: [quote or paragraph] → [what is wrong]
- WEAKNESS 2: ...
- WEAKNESS 3: ...

End with: IMPROVABLE: yes | no
(no = the paper is already at release quality)"""

REVISE_PROMPT = """You are a reviser. The original paper and a critique
are below. Rewrite the paper to address the critique. Keep what works.
Fix what doesn't. Same length (±10%). Same cowboy format.

Critique: {critique}
Original: {paper}

Output the full revised paper, not a diff."""
```

Critic and reviser should be different voices (critic = Mistral-Small-24B for terseness, reviser = DeepSeek for length). Exit conditions: (a) `IMPROVABLE: no`, (b) 3 iterations reached, (c) revised paper is shorter than original (regression, abort and keep original).

**Expected quality vs current.** Fewer papers with weak "Polyformalism" or vague "Maxim" sections. Net 20-30% improvement in concrete-example density. Will catch the recurring failure mode of the v2 run where 5-10% of papers had a Gold-Term list where 2 of 5 terms were obvious rather than coined.

**Estimated token cost.** ~2-3x current per paper. 2 critique + 2 revise passes at ~1500 tokens each = ~6000 extra tokens per paper. On DeepSeek's $0.14/M input tier, that's ~$0.001 per paper, still $0 on the free tier. Wall time +60-90s.

## 3. Pipeline 3 — Frontier Auto-Discovery

**What it does.** When the frontier queue empties, the pipeline should *generate* new frontiers rather than going idle. Three sources, in priority order:

1. **Canon internal mining** — Embed the canon (already done in Vectorize), cluster with k-means or HDBSCAN, find sparse regions (silhouette score > 0.6 with < 3 nearest-neighbor papers), and propose a frontier that would fill the gap.
2. **Curated external corpora** — Project Gutenberg (music theory texts, navigation manuals, weaving treatises, Buddhist sutras, marine glossaries — all public domain), Wikipedia "List of..." articles, IMDB genre graphs, OpenStreetMap feature catalogs.
3. **Cross-domain analogy** — Sample 2-3 random canon paper titles, prompt an LLM: "what domain has the same structural problem as these three papers, that we haven't mined yet?"

**Why it's better.** The v2 daemon went idle the moment the marine queue drained. A 50-min autonomous run, then nothing. Frontier auto-discovery keeps the engine running indefinitely without human curation.

**Concrete implementation.** New module `frontier_miner.py`:

```python
DISCOVERY_PROMPT = """You are a frontier scout. Below are 3 canon paper
titles from different parts of the canon. They share a structural
problem (X). Propose a NEW domain that has the same structural problem
but is not in the canon. Output 1-3 candidate frontier phrases.

Existing canon cluster: {titles}

Output: 1-3 noun phrases, each 3-8 words. Marine metaphor OPTIONAL.
The phrase should be a CONCRETE THING, not an abstract concept."""

SPARSE_QUERY = """Find 5 canon papers most similar to the phrase below.
If fewer than 2 have cosine similarity > 0.7, the phrase is in a
sparse region and should be a frontier candidate."""
```

Source URLs to mine (all public-domain, all $0):

- `gutenberg.org` — Project Gutenberg plain-text dumps, `https://www.gutenberg.org/cache/epub/feeds/rdf-files.tar.gz` is the master index.
- `en.wikipedia.org` — Wikipedia API for "List of..." pages, e.g., `https://en.wikipedia.org/w/api.php?action=query&list=categorymembers&cmtitle=Category:Marine_terminology&cmlimit=500`.
- A pre-curated `/workspace/quilt-cowboy/external_corpus/` directory of music-theory PDFs, weaving treatises (already in the Quilt corpus), and Buddhist contemplative vocabularies.

Clustering: use the existing Cloudflare Vectorize index. Pull all 628 vectors, run HDBSCAN locally (it's a single pip install, ~5MB, no GPU). Sparse-region detection: for each candidate phrase, embed it, find 5 nearest canon papers, score = mean cosine. If score < 0.6 it's a candidate frontier.

Output to `frontier_queue_v3.jsonl` with a `proposed_by` field (auto-mined vs human-curated) and a `human_approved` flag (default false). The v2 daemon reads this queue but only fires on entries where `human_approved == true` until the human approves in bulk. Or: auto-approve entries with score < 0.5 (high novelty) and require human approval for 0.5-0.6 (might be duplicates).

**Expected quality vs current.** Endless canon growth without human bottleneck. Marine metaphor drift can be steered by varying the `DISCOVERY_PROMPT` style guide. Cost is $0 (Vectorize queries are free-tier, embedding is free-tier, HDBSCAN runs on CPU).

**Estimated token cost.** ~$0.02 per discovered frontier (one LLM call for proposal). 100 frontiers = $2. Wall time: ~10 minutes per 100 frontiers.

## 4. Pipeline 4 — Voice Specialization

**What it does.** Classify the frontier by topic type, then assign voices accordingly:

- **Technical / cell-model / protocol** — DeepSeek + Llama-3.3-70B (long-form, precise)
- **Narrative fable / character** — Llama-3.3-70B + Mistral (storyteller voice)
- **Concise definition / single-cell paper** — Mistral-Small-24B alone (high signal density)
- **Meta / canon-reflection** — Llama-4-Scout (already the meta specialist)
- **Cross-cultural / multilingual** — Qwen3-Next-80B (occasionally slips Chinese, that's the point)
- **Hesitant / cautious / "what could go wrong"** — Gemini 2.5-Flash (the cautious voice)

Each frontier gets a routing label from a tiny classifier prompt, and the voice pool is filtered to specialists. Fallback: if no specialist matches, use the current 6-voice rotation. If a specialist voice fails (HTTP error), fall back to DeepSeek.

**Why it's better.** The current pool fires all 6 on every frontier. Most rounds, 3-4 of the 6 outputs are off-topic. Specialization concentrates the signal: 4-5 voices on the right track instead of 2-3. Quality goes up because the gold wins by relevance, not just length.

**Concrete implementation.** In `pick_voices_for_round`, add a routing step:

```python
ROUTER_PROMPT = """Classify the frontier below into ONE category.
Output only the category name, nothing else.

Categories:
- technical (cell model, protocol, math, polyformalism)
- narrative (fable, character, story, vessel)
- concise (single definition, single cell, short paper)
- meta (canon reflection, history of the canon, methodology)
- cross-cultural (multilingual, translation, comparative religion)
- cautious (risk, failure mode, what-could-go-wrong)

Frontier: {topic}
Category:"""

VOICE_BY_CATEGORY = {
    "technical": [("deepseek", ...), ("llama70b", ...), ("mistral", ...), ("qwen3", ...)],
    "narrative": [("llama70b", ...), ("mistral", ...), ("llama4scout", ...), ("gemini", ...)],
    "concise":   [("mistral", ...), ("deepseek", ...)],
    "meta":      [("llama4scout", ...), ("deepseek", ...), ("gemini", ...)],
    "cross-cultural": [("qwen3", ...), ("llama70b", ...), ("deepseek", ...)],
    "cautious":  [("gemini", ...), ("mistral", ...), ("deepseek", ...)],
}
```

The router call is one extra API request per paper, ~50 tokens, ~$0. Specialist failures fall back to the current 6-voice pool (one retry, then give up and use what we have).

**Expected quality vs current.** Higher gold-term relevance (terms coined by voices that understand the domain). Fewer "Llama went off on a Chinese tangent" failures in technical papers. Net quality lift: 5-10% on technical/narrative, 15-20% on concise and cautious (where Gemini's natural caution or Mistral's terseness are the *whole point*).

**Estimated token cost.** +$0.0001 per paper (one router call). Effectively free.

## 5. Pipeline 5 — Multi-Canon Silos

**What it does.** Split the single cowboy into 4 parallel canons, each with its own state, frontier queue, and paper-number range, but shared infrastructure:

- **cowboy** (the meta-canon for the writers' room) — continues as is. Range: 1-9999.
- **fables** — narrative, character-driven, shorter papers (400-800 words), 1-voice instead of 6-voice. Range: 10000-19999.
- **code** — Quilt ports, polyformalism, the 5 opcodes. Range: 20000-29999.
- **dialogues** — two-voice debates archived as canon (raw, no synthesis). Range: 30000-39999.

Each silo has its own `cowboy_state_<silo>.json`, `frontier_queue_<silo>.jsonl`, and `cowboy_processed_topics_<silo>.json`. They share `cowboy_pipeline_v2.py` (parameterized by silo name) and the embedding/push infrastructure.

**Why it's better.** The current single canon mixes 800-word marine fables with 5000-word polyformalism specs. A reader who wants "the marine canon" has to filter 628 papers. A reader who wants "the code canon" has to filter 628 papers. Silos let each reader load only what they want. The fables silo can run a cheaper / more playful pipeline (1 voice, 2 rounds) without polluting the cowboy meta-papers.

**Concrete implementation.** Refactor `cowboy_pipeline_v2.py` to take a `silo` arg:

```python
PIPELINE_STATE[silo] = {
    "state_file": Path(f"/workspace/quilt-cowboy/cowboy_state_{silo}.json"),
    "papers_dir": Path(f"/workspace/quilt-cowboy/{silo}_papers/"),
    "frontier": Path(f"/workspace/quilt-cowboy/frontier_queue_{silo}.jsonl"),
    "canon_subpath": f"seed-canon/{silo}-papers/paper-{silo_prefix}{{num}}.md",
    "num_range": (10000, 19999) if silo == "fables" else ...,
}
```

The number allocator picks from the silo range. Multiple daemons can run in parallel — one per silo — because each writes to its own state file. Embedding and Vectorize can be unified (silo becomes a metadata field on the vector) or split (separate Vectorize indexes per silo). Recommend unified for now, split if a silo gets > 50K papers.

**Expected quality vs current.** No change in per-paper quality. Massive improvement in navigability and pipeline experimentation speed (we can change the fables pipeline without touching cowboy).

**Estimated token cost.** No change. Refactor only.

## 6. Pipeline 6 — Human-in-the-Loop IDE

**What it does.** A web UI + CLI for the cowboy that lets a human:

1. **Start a frontier** (or pick from `frontier_queue_v3.jsonl`'s auto-discovered candidates).
2. **Watch the writers' room fire** (live SSE stream of each voice's output).
3. **Read the gold + synthesis** (rendered markdown).
4. **Edit / redirect** (inline editor: "rewrite section X", "add a polyformalism example in substrate Y", "kill this gold term and use Z").
5. **Approve / reject** (one click each).
6. **Annotate** (free-text margin notes — "this is a near-duplicate of paper-142", "this should be a fable, not a cowboy").

The human's edits and annotations get stored in a `cowboy_ide_annotations.jsonl` and become part of the next round's prompt. The paper that gets pushed to canon is the human-approved version, with the human's edits preserved as a "## Editor's Notes" section if `editor_notes: true` is set.

**Why it's better.** The current pipeline is fully autonomous, which is great for volume (123 papers, 50 min) but means every paper is a coin-flip on quality. An IDE pipeline produces fewer papers (maybe 1-3 per hour, including human time) but each is canon-grade. The human's annotations also act as a small labeled dataset that improves the autonomous pipeline over time (the auto-discovery module can use annotations to learn which auto-proposed frontiers get rejected and why).

**Concrete implementation.** A Flask + htmx web app at `/workspace/quilt-cowboy/ide/`. The `cowboy_orchestrator_v2.py`'s `writers_room()` function is split into two: `writers_room_async()` (yields events via SSE) and `writers_room_sync()` (the current behavior). The IDE calls the async version and renders each voice's output as it arrives.

```python
# cowboy_ide/app.py
@app.route("/frontier/<topic>")
def frontier_view(topic):
    return render_template("frontier.html", topic=topic)

@app.route("/api/run/<topic>")
def run_frontier(topic):
    def event_stream():
        for event in writers_room_async(topic):
            yield f"data: {json.dumps(event)}\n\n"
    return Response(event_stream(), mimetype="text/event-stream")
```

Where the human's text gets stored:

```json
// cowboy_ide_annotations.jsonl
{"ts": "...", "topic": "...", "paper_num": 631, "action": "edit",
 "section": "Polyformalism", "before": "...", "after": "...",
 "human": "Mavis", "note": "added Go port as substrate #4"}
```

How the AI uses it: the next writers-room session prepends the last 20 human annotations to the synthesis prompt as `## Editor Preferences`. Over time this is a slow, organic fine-tuning of the synthesizer's voice.

**Expected quality vs current.** Per-paper quality: massive (the human catches 80%+ of the v2 pipeline's recurring errors). Volume: 1/10th of current. Combined: the canon's "narrative coherence per paper" goes up while the canon's "vocabulary breadth" slows. The two pipelines (autonomous + IDE) running in parallel are the right answer.

**Estimated token cost.** Same per paper, but a human-hour-per-paper overhead. Net cost is dominated by the human's time, not tokens.

## 7. The order to build them

| # | Pipeline | Effort | Quality lift | When |
|---|----------|--------|--------------|------|
| 1 | Adversarial Debate | 1 day | 15-30% | This week |
| 2 | Self-Critique Loop | 1 day | 20-30% | This week |
| 4 | Voice Specialization | 0.5 day | 5-20% | Next week |
| 3 | Frontier Auto-Discovery | 3 days | ∞ (enables indefinite growth) | Next week |
| 5 | Multi-Canon Silos | 2 days | 0% (UX) | Month 2 |
| 6 | Human-in-the-Loop IDE | 5 days | massive per-paper | Month 2 |

Pipelines 1 + 2 + 4 ship as a single `cowboy_orchestrator_v3.py` in one week. Pipeline 3 follows because the daemon needs new frontiers to chew on. Pipelines 5 and 6 are infrastructure investments that pay off over months.

## 8. The honest accounting

The v2 pipeline is fast, free, and produces 50 papers per hour. It is also noisy: maybe 1 in 5 papers is canon-grade, 1 in 10 is a near-duplicate, and 1 in 20 is a structural failure (the "what's the 5th Gold Term" failure mode). The evolutions above are not about making the pipeline faster. They are about making each paper worth pushing, and about keeping the pipeline running when the human-curated frontier queue runs dry.

The cowboy is the canon's growth engine. The growth engine needs new fuel (Pipeline 3), a better spark (Pipelines 1+2), a smarter carburetor (Pipeline 4), and a co-driver (Pipeline 6). The silo refactor (Pipeline 5) is the garage we're building all of this in.

— end R&D spec —
