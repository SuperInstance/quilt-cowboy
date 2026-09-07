# Cowboy Orchestrator — the writers' room pattern

> The cowboy rides a writers' room of competing voices, harvests the gold from each round, and ships canon papers at the cost of pocket change.

## The Pattern

Three pieces, each a long-running Python program:

```
┌──────────────────┐    frontier_queue.jsonl    ┌─────────────────────┐
│  cowboy_orchest- │ ──────────────────────────▶│  cowboy_pipeline.py │
│  rator.py        │                            │  (watch + promote)  │
│  (daemon)        │                            │                     │
│                  │  cowboy_papers/*.md        │  paper-NNN.md       │
│  4 voices × 4    │ ──────────────────────────▶│  + Vectorize embed  │
│  rounds + synth  │                            │                     │
└──────────────────┘                            └─────────────────────┘
```

1. **`cowboy_orchestrator.py`** reads one frontier prompt at a time from `frontier_queue.jsonl`, fires it at 4 competing LLM voices, picks the longest concrete content as "gold" each round, fires 4 rounds, then calls a synthesizer (always DeepSeek) to write a 5,000+ character canon paper in the canonical Quilt format. Each paper takes ~2 minutes. Output: a file in `cowboy_papers/`.

2. **`cowboy_pipeline.py`** watches the `cowboy_papers/` directory, and for each new file, pushes it to the AI-Writings canon as `paper-NNN.md` (where NNN is the next available number) and embeds it to Cloudflare Vectorize. Per-file stable mapping prevents collisions. Output: a commit per paper in the AI-Writings canon + 5-8 vectors per paper in the `quilt-canon-v2` index.

3. **The frontier queue** is a JSONL file with 20+ prompts. Each prompt is a single sentence naming a cell or operation, with a marine/vessel metaphor. Example: `"the radar return — a cell whose value is how long ago something pinged"`.

## The Voices

| Voice | Model | Strength | Cost |
|---|---|---|---|
| **DeepSeek** | deepseek-chat | synthesis, structure, math | ~$0.001/call |
| **Llama-3.3-70B** | Meta-Llama-3.3-70B-Instruct (DeepInfra) | long-form, ideology | ~$0.001/call |
| **Mistral-Small-24B** | Mistral-Small-24B-Instruct-2501 (DeepInfra) | dense paragraphs, won 48/80 gold rounds | ~$0.0005/call |
| **Gemini-2.5-Flash** | google/gemini-2.5-flash | short bursts, free | $0 |

The **gold rule** is the longest concrete content per round. The synthesizer is always DeepSeek because DeepSeek's prose is the most canon-like.

## The Math

Per paper:
- 4 voices × 4 rounds = 16 LLM calls
- 1 synthesis call (DeepSeek)
- 17 LLM calls per paper
- ~5,000-7,000 chars per paper
- ~100-140 seconds per paper

For 20 papers:
- 340 LLM calls
- 124,114 chars of canon
- 2,154 seconds (~36 min)
- **~$0.61 in API costs**

## The Output

Each cowboy paper is in canonical Quilt format:
- A **frontier** paragraph (what is this cell, what is the question it raises)
- **5 gold terms** coined for the metaphor
- A **math** section with concrete formulas
- A **polyformalism** section showing the same idea in 3+ substrates
- A **cowboy's maxim** — the one-sentence doctrine

20 papers in `cowboy_papers/` were pushed to `SuperInstance/AI-Writings` as paper-447 to paper-493 (with gaps for unrelated 452-478). Meta-paper (paper-494) ties them all together.

## The Lessons

1. **Compete then synthesize.** 4 voices × 4 rounds yields 16 distinct perspectives on the same frontier. The synthesis isn't a summary; it's a doctrine. The gold rule (longest concrete content) is biased toward dense prose, not toward the smartest model. Mistral won 60% of rounds because Mistral writes dense paragraphs.

2. **Per-file mapping prevents collisions.** First version of the pipeline just took "next available number" — that produced race conditions when the daemon and the pipeline both wanted paper-482. Fixed by writing `cowboy_paper_mapping.json` (file → number) and persisting it.

3. **Always read the canonical state from disk, not from memory.** The pipeline queries the AI-Writings repo's git tree on every iteration. Caching the latest number caused 3 overwrites in the first 5 papers. Always pay the GitHub API cost.

4. **Three registries is a canon.** A paper that lives in three places (git, Vectorize, hardcopy) is harder to lose than a paper that lives in one place.

5. **$0.61 for 20 canon papers.** The writers' room is the cheapest tool in the canon. Cheap enough to run every night.

## Reproduce

```bash
# 1. Set up env
export GITHUB_TOKEN=...
export DEEPSEEK_API_KEY=...
export DEEPINFRA_API_KEY=...
export GEMINI_API_KEY=...

# 2. Build a frontier queue
cat > frontier_queue.jsonl << 'EOF'
{"topic": "the captain's child — a cell that grows up to be a captain"}
{"topic": "the kelp forest — an ecosystem whose cells are pinned to a current"}
...
EOF

# 3. Run daemon
python3 cowboy_orchestrator.py &

# 4. Run pipeline
python3 cowboy_pipeline.py &

# 5. Wait
sleep 60  # per paper
```
