# cowboy_orchestrator_v3 — Runbook

## What's in this drop

- `cowboy_orchestrator_v3.py` — adversarial pipeline, 2 voices + forced synthesis, 685 lines.
- `frontier_queue_aviation.jsonl` — 52 aviation metaphors ready to drain.
- `cowboy_orchestrator_v2.py` — the previous pipeline, kept for fallback.

## Architecture

```
frontier_queue_aviation.jsonl
        │
        ▼
cowboy_orchestrator_v3.py  (adversarial mode)
   ┌─────────────────────┐
   │ Voice A (affirm)    │ ── "this IS a cell" (300-500 words)
   │ Voice B (negate)    │ ── "this is NOT a cell" (300-500 words)
   │ Both in PARALLEL    │
   └──────────┬──────────┘
              ▼
   DeepSeek synthesis    ── 500-700 words, FORCED to resolve
              ▼
cowboy_papers/paper-cowboy-*.md
```

If either adversarial voice fails or the synthesis comes back too short,
the orchestrator automatically falls back to a 3-round generative mode
(same shape as v2: 6 voices per round, longest wins, DeepSeek synth).

## Token contract

The orchestrator needs these env vars (same as v2):

```bash
export DEEPSEEK_TOKEN="..."    # for synthesis
export DEEPINFRA_TOKEN="..."   # for the 5 non-DeepSeek voices
export GEMINI_TOKEN="..."      # for the Gemini voice
export GITHUB_TOKEN="..."      # for pushing papers (handled by cowboy_pipeline_v2.py)
export CLOUDFLARE_TOKEN="..."  # for Vectorize embedding
export CF_ACCOUNT="049ff5e84ecf636b53b162cbb580aae6"
```

## Run it

```bash
cd /workspace/quilt-cowboy
python3 cowboy_orchestrator_v3.py --daemon --frontier frontier_queue_aviation.jsonl
```

In a second shell:

```bash
cd /workspace/quilt-cowboy
python3 cowboy_pipeline_v2.py    # watches cowboy_papers/, pushes to AI-Writings
```

## Expected behavior

- 52 aviation frontiers × ~50s per adversarial paper = ~45 minutes total
- ~156 LLM calls (3 per paper, all in adversarial mode)
- 52 new papers in `cowboy_papers/`, named `paper-cowboy-YYYYMMDD-HHMMSS-{slug}.md`
- Pushed to `SuperInstance/AI-Writings` as `paper-NNN.md` starting from N=633
- Embedded to Cloudflare Vectorize `quilt-canon-v2` index

## Adversarial pairing

Each paper gets a different adversarial pair (deterministic per topic seed).
Same-family pairs (e.g., Llama70B + Llama4Scout) are avoided to maximize
stylistic diversity. Pair examples seen in testing:
- altimeter → A=Gemini / B=Mistral
- autopilot → A=Gemini / B=Llama70B
- wing → A=Llama4Scout / B=Qwen3Next

## Adversarial mode vs fallback

The orchestrator prefers adversarial mode. It falls back to generative
mode when:
- Either voice returns < 200 chars (treated as failure)
- The synthesis returns < 300 chars (treated as failure)

In the current sandbox (no API tokens), the orchestrator runs but always
falls back, then fails to synthesize. Once real tokens are in env, the
adversarial path will be taken ~100% of the time.

## Validation

The pipeline was tested structurally with mocked API calls:

```python
# mock out call_deepseek, call_deepinfra, call_gemini with long-enough
# returns, then run adversarial_writers_room('the altimeter ...')
# Result: mode=adversarial, synth=deepseek, 566 chars, file saved
# OK.
```

## Files written by this drop

- `/workspace/quilt-cowboy/cowboy_orchestrator_v3.py` (new, 685 lines)
- `/workspace/quilt-cowboy/frontier_queue_aviation.jsonl` (new, 52 topics)
- `/workspace/quilt-cowboy/RUN_V3_AVIATION.md` (this file)
- `/workspace/quilt-cowboy/cowboy_worklog_v3.jsonl` (created on first run)
- `/workspace/quilt-cowboy/cowboy_processed_topics_v3.json` (created on first run)
