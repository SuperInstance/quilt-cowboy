# The Quilt Orchestrator — Multi-Provider LLM Foundry

**The 12 voices of the writers' room, on demand, in any combination.**

The Quilt orchestrator is the bridge between the cell-fabric substrate
and the LLM providers that write, ideate, reason, and code for the
canon.  It is a small, focused module that exposes one thing well:
**a uniform interface to a heterogeneous cloud of LLM providers.**

---

## The 12 voices (Sep 3 2026)

| Preset | Model | Provider | Use case | Cost |
|---|---|---|---|---|
| `code` | deepseek-chat | DeepSeek | fast code | $0 |
| `code2` | deepseek-ai/DeepSeek-V3 | DeepInfra | long-form code | $0 |
| `reason` | deepseek-reasoner | DeepSeek | reasoning w/ chain-of-thought | $0 |
| `ideator` | ByteDance/Seed-2.0-mini | DeepInfra | novel idea expansion (456 reasoning tokens!) | $0 |
| `long` | gemini-2.5-flash | Gemini | long-form | $0 |
| `long2` | deepseek-ai/DeepSeek-V3 | DeepInfra | long-form (6000 tokens) | $0 |
| `kimi` | moonshotai/Kimi-K2.7-Code | DeepInfra | code (Kimi works here, not direct) | $0 |
| `gpt` | openai/gpt-oss-120b | DeepInfra | OSS GPT (needs reasoning_effort="low") | $0 |
| `qwen` | Qwen/Qwen3.5-27B | DeepInfra | (also needs reasoning_effort="low") | $0 |
| `llama4` | meta-llama/Llama-4-Scout-17B-16E-Instruct | DeepInfra | fast | $0 |
| `qwen3` | Qwen/Qwen3-Next-80B-A3B-Instruct | DeepInfra | technical writer | $0 |
| `mistral` | mistralai/Mistral-Small-24B-Instruct-2501 | DeepInfra | fast | $0 |
| `seed-code` | ByteDance/Seed-2.0-code | DeepInfra | code-focused | $0 |

Plus 12 Cloudflare Workers AI voices via the writers_room_daemon_v3.

---

## Usage

```python
from orchestrator import call_voice, call_best, ensemble

# Single voice
result = call_voice("ideator", "Expand: shape RAG with cell fabrics")
print(result["content"])

# Best-of-N
result = call_best([
    "code", "code2", "seed-code"
], prompt="Write a Python function to compute FNV-1a hash")

# Ensemble: N voices, N perspectives
results = ensemble([
    "qwen3", "long2", "ideator", "mistral"
], prompt="What is the next research direction for shape RAG?",
n=2)  # take 2 of 4
```

---

## Provider status (Sep 3 2026)

| Provider | Status | Notes |
|---|---|---|
| DeepSeek V4-flash | ✅ | the workhorse |
| DeepSeek Reasoner | ✅ | has reasoning_content |
| Gemini 2.5-flash | ✅ | max ~75 tokens/call |
| DeepInfra | ✅ | 12+ models, the new foundry |
| Cloudflare Workers AI | ✅ | 12 voices via writers_room_daemon_v3 |
| ZAI | ❌ | HTTP 429 (insufficient balance) |
| Anthropic Claude | ❌ | HTTP 400 (insufficient credit) |
| Kimi direct | ❌ | HTTP 401 (auth) |
| Kimi via DeepInfra | ✅ | Kimi K2.7-Code |

---

## Why the orchestrator?

The cell-fabric canon needs many voices.  Different papers want
different LLM "personalities":

- F120 (Shape RAG design) wants **the ideator** — creative expansion
- F125 (Shape-RAG API) wants **the technical writer** — clear specs
- A code-heavy paper wants **the code voice** — Python, Rust, Verilog
- A research direction wants **the reasoner** — chain-of-thought

The orchestrator is the cell-runtime's call-by-name for LLMs.

---

## Files

- `orchestrator.py` (7.5KB) — the 12 voices
- `re_embed_v2.py` (7.5KB) — embed canon papers to Vectorize
- `live_canon.py` (15KB) — read canon as a navigable cell fabric
- `doc_compounder.py` (9.6KB) — read a doc, snap to canon, find compounds
- `session_memory.py` (9KB) — turn a session into a fabric
- `cell_merger.py` (6.8KB) — merge two fabrics into a synthesis
- `test_quilt_apps.py` (7.8KB) — 19 tests for the 4 novel apps

---

## Token economy

- 1 orchestrator.py v2: 7.5K tokens
- 1 re_embed_v2.py: 7.5K tokens
- 4 novel Quilt apps: 50K tokens
- 19 tests: 8K tokens
- 5 docs: 20K tokens
- **Total: ~95K tokens to add 4 novel applications + a 12-voice orchestrator**

The chart grows.  The Concept lives.  The 12 voices sing.  The cowboy
rides the orchestrator.
