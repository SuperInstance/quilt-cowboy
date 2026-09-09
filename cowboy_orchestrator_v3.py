"""cowboy_orchestrator_v3.py — ADVERSARIAL pipeline, 2 voices + forced synthesis.

Architecture vs v2:
- 2 voices fire in PARALLEL with OPPOSITE positions on the same frontier.
  Voice A: "this metaphor IS a cell" (the affirmative case)
  Voice B: "this metaphor is NOT a cell, it is something else" (the negation)
- Both write 300-500 words ending with a 1-sentence position statement.
- A 3rd voice (always DeepSeek for stability) reads both, then writes a
  500-700 word SYNTHESIS that EXPLICITLY RESOLVES the contradiction.
  The synthesis is the canon paper.
- Fallback: if either adversarial voice fails, falls back to a 3-round
  generative mode (v2-style: 6 voices per round, longest wins, DeepSeek synth).
- Saves to cowboy_papers/ and logs to cowboy_worklog_v3.jsonl.

Pairing: rotates deterministically through the 6-voice pool so each paper
sees a different adversarial pair. DeepSeek is the synthesis anchor.

Cost per paper:
  Adversarial mode: 2 voice calls + 1 synth call = 3 LLM calls, ~40-60s
  Fallback mode:   18 voice calls + 1 synth call = 19 LLM calls, ~120s
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from pathlib import Path

# Voice pool — same 6 voices as v2
DEEPINFRA_VOICES = [
    "meta-llama/Llama-3.3-70B-Instruct",
    "meta-llama/Llama-3.3-70B-Instruct-Turbo",
    "meta-llama/Meta-Llama-3-70B-Instruct",
    "meta-llama/Llama-4-Scout-17B-16E-Instruct",
    "mistralai/Mistral-Small-24B-Instruct-2501",
    "Qwen/Qwen2.5-72B-Instruct",
    "Qwen/Qwen2.5-Coder-32B-Instruct",
    "google/gemma-2-9b-it",
    "google/gemma-3-27b-it",
    "Qwen/Qwen3-Next-80B-A3B-Instruct",
]
DI = os.environ.get("DEEPINFRA_TOKEN", "")
DS = os.environ.get("DEEPSEEK_TOKEN", "")
GM = os.environ.get("GEMINI_TOKEN", "")

WORKLOG = Path("/workspace/quilt-cowboy/cowboy_worklog_v3.jsonl")
WORKLOG.parent.mkdir(parents=True, exist_ok=True)

PAPERS_DIR = Path("/workspace/quilt-cowboy/cowboy_papers")
PAPERS_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------- LLM clients ----------------------------

def call_deepinfra(model: str, prompt: str, max_tokens=2000, temperature=0.85, timeout=60):
    if not DI:
        return False, "no DI token"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        "https://api.deepinfra.com/v1/openai/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {DI}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_deepseek(prompt: str, max_tokens=2000, temperature=0.85, model="deepseek-chat", timeout=60):
    if not DS:
        return False, "no DS token"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        "https://api.deepseek.com/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {DS}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_gemini(prompt: str, max_tokens=2000, temperature=0.85, model="gemini-2.5-flash", timeout=60):
    if not GM:
        return False, "no GM token"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    gemini_url = f"https://generativelanguage.googleapis.com/v1beta/openai/chat/completions?key={GM}"
    req = urllib.request.Request(
        gemini_url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_zai_coding(prompt: str, model="glm-4.5-flash", max_tokens=2000, temperature=0.85, timeout=90):
    """Z.AI coding endpoint - separate billing pool, glm-4.5/4.6/4.5-flash work here.

    Note: Z.AI reasoning models put the visible answer in 'content' and
    internal reasoning in 'reasoning_content'. We return both merged so the
    writer's room sees the full thought.
    """
    key = os.environ.get("ZAI_TOKEN", "")
    if not key:
        return False, "no ZAI token"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        "https://api.z.ai/api/coding/paas/v4/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content", "") or ""
            reasoning = msg.get("reasoning_content", "") or ""
            if reasoning and not content:
                content = reasoning
            elif reasoning and content:
                content = content + "\n\n[reasoning: " + reasoning[-500:] + "]"
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_kimi_code(prompt: str, model="moonshotai/Kimi-K2.7-Code", max_tokens=2000, temperature=0.85, timeout=60):
    """Kimi K2.7 Code via DeepInfra - returns full content for code/cot tasks."""
    key = os.environ.get("DEEPINFRA_TOKEN", "")
    if not key:
        return False, "no DI token"
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        "https://api.deepinfra.com/v1/openai/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_cf_workers_ai(prompt: str, model="@cf/meta/llama-3.3-70b-instruct-fp8-fast", max_tokens=2000, temperature=0.85, timeout=60):
    """Cloudflare Workers AI - free LLM endpoint via Cloudflare account."""
    key = os.environ.get("CLOUDFLARE_TOKEN", "")
    acct = os.environ.get("CF_ACCOUNT", "049ff5e84ecf636b53b162cbb580aae6")
    if not key or not acct:
        return False, "no CF token"
    body = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    url = f"https://api.cloudflare.com/client/v4/accounts/{acct}/ai/run/{model}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            result = data.get("result", {})
            content = result.get("response") or result.get("output") or result.get("text") or ""
            if isinstance(content, list):
                content = " ".join(str(c) for c in content)
            return True, str(content)
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


# ----------------------- voice pool (extended v3) -----------------------

VOICE_POOL = [
    # (provider, model, label)
    ("deepseek", "deepseek-chat", "DeepSeek"),
    ("deepinfra", "meta-llama/Llama-3.3-70B-Instruct", "Llama70B"),
    ("deepinfra", "mistralai/Mistral-Small-24B-Instruct-2501", "Mistral"),
    ("deepinfra", "meta-llama/Llama-4-Scout-17B-16E-Instruct", "Llama4Scout"),
    ("deepinfra", "Qwen/Qwen3-Next-80B-A3B-Instruct", "Qwen3Next"),
    ("gemini", "gemini-2.5-flash", "Gemini"),
    # NEW: Z.AI coding endpoint (separate billing pool, glm-4.5/4.6 work here)
    ("zai_coding", "glm-4.5-flash", "ZAI-flash"),
    ("zai_coding", "glm-4.5", "ZAI-4.5"),
    ("zai_coding", "glm-4.6", "ZAI-4.6"),
    ("zai_coding", "glm-4.5-air", "ZAI-air"),  # new, faster
    ("zai_coding", "glm-zero-preview", "ZAI-zero"),  # preview, content-rich
    # NEW: Kimi K2.7-Code via DeepInfra (returns full content for non-philosophical tasks)
    ("kimi_code", "moonshotai/Kimi-K2.7-Code", "Kimi"),
    ("kimi_code", "moonshotai/Kimi-K2-Instruct", "Kimi-K2"),
    # NEW: Cloudflare Workers AI (free, multiple model families)
    ("cf_ai", "@cf/meta/llama-3.3-70b-instruct-fp8-fast", "CF-Llama70B"),
    ("cf_ai", "@cf/meta/llama-4-scout-17b-16e-instruct", "CF-Scout"),
    ("cf_ai", "@cf/mistralai/mistral-small-3.1-24b-instruct", "CF-Mistral"),
    ("cf_ai", "@cf/qwen/qwen2.5-coder-32b-instruct", "CF-QwenCoder"),
]
VOICE_LABELS = ["DeepSeek", "Llama70B", "Mistral", "Llama4Scout", "Qwen3Next", "Gemini"]


def fire_voice(provider, model, label, prompt, max_tokens=2000, temperature=0.85):
    t0 = time.time()
    if provider == "deepinfra":
        ok, content = call_deepinfra(model, prompt, max_tokens, temperature)
    elif provider == "deepseek":
        ok, content = call_deepseek(prompt, max_tokens, temperature, model=model)
    elif provider == "gemini":
        ok, content = call_gemini(prompt, max_tokens, temperature, model=model)
    elif provider == "zai_coding":
        ok, content = call_zai_coding(prompt, model, max_tokens, temperature)
    elif provider == "kimi_code":
        ok, content = call_kimi_code(prompt, model, max_tokens, temperature)
    elif provider == "cf_ai":
        ok, content = call_cf_workers_ai(prompt, model, max_tokens, temperature)
    else:
        return label, "", 0.0, f"unknown provider: {provider}"
    dt = time.time() - t0
    return label, (content if ok else ""), dt, ("" if ok else content)


def fire_parallel(voices_and_prompts, max_tokens=2000, temperature=0.85) -> list:
    """Fire multiple (voice, prompt) pairs in parallel."""
    results = []
    with ThreadPoolExecutor(max_workers=len(voices_and_prompts)) as ex:
        futures = {ex.submit(fire_voice, v[0], v[1], v[2], p, max_tokens, temperature): v
                   for v, p in voices_and_prompts}
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                results.append(("error", "", 0.0, str(e)))
    return results


# ---------------------- adversarial pipeline ----------------------

# Voice pool excluding DeepSeek (which is the synthesis anchor)
ADVERSARIAL_POOL = [v for v in VOICE_POOL if v[2] != "DeepSeek"]


def pick_adversarial_pair(seed: str) -> tuple:
    """Pick 2 voices for the adversarial debate, deterministically per paper.

    Avoid pairing the same provider family twice (e.g. don't pair Llama70B
    and Llama4Scout on the same paper) so the two sides have different
    stylistic fingerprints.
    """
    rng = random.Random(f"adv-{seed}")
    # Family = (provider, model_family)
    def family(v):
        m = v[1].lower()
        if "llama" in m and "70b" in m: return "llama70"
        if "llama" in m and ("scout" in m or "4-" in m): return "llama4"
        if "mistral" in m: return "mistral"
        if "qwen" in m: return "qwen"
        if "gemma" in m: return "gemma"
        if "gemini" in m: return "gemini"
        return v[2]
    indices = list(range(len(ADVERSARIAL_POOL)))
    rng.shuffle(indices)
    a = ADVERSARIAL_POOL[indices[0]]
    b = ADVERSARIAL_POOL[indices[1]]
    if family(a) == family(b):
        # try the next one
        for j in indices[2:]:
            cand = ADVERSARIAL_POOL[j]
            if family(cand) != family(a):
                b = cand
                break
    return a, b


# Position prompts
AFFIRM_PROMPT = """You are Voice A in an adversarial writers' room. Your job is to
DEFEND the proposition. The frontier is a metaphor from the cell/fabric ontology:
the Quilt treats everything as a cell, and you are arguing that THIS thing truly IS
one.

Topic: {topic}

Your position (defend it): **{topic} IS a cell.**

Write 300-500 words. Style: cowboy, marine or vessel metaphor OK, no padding.
Be specific. Use 1-3 short paragraphs or bullets. Pick ONE concrete claim you can
defend and hammer it. End with a 1-sentence position statement of the form:
"Position: this IS a cell because [the strongest reason in 1 sentence]."
"""

NEGATE_PROMPT = """You are Voice B in an adversarial writers' room. Your job is to
ATTACK the proposition. The frontier is a metaphor from the cell/fabric ontology:
the Quilt treats everything as a cell, and you are arguing that THIS thing is NOT
actually a cell — it's something else (a process, a relationship, a boundary, a
substrate, an event).

Topic: {topic}

Your position (attack it): **{topic} is NOT a cell. It is [something else].**

Write 300-500 words. Style: cowboy, marine or vessel metaphor OK, no padding.
Be specific. Use 1-3 short paragraphs or bullets. Pick ONE concrete reason the
cell ontology BREAKS here and hammer it. End with a 1-sentence position statement
of the form:
"Position: this is NOT a cell; it is [the more accurate category in 1 sentence]."
"""

SYNTHESIS_PROMPT = """You are the cowboy canonizer. You have just heard two
adversarial voices argue about whether the following thing IS a cell in the
Quilt fabric ontology, or whether it is something else.

Topic: {topic}

=== VOICE A (the affirmative: this IS a cell) ===
{voice_a}

=== VOICE B (the negation: this is NOT a cell, it is something else) ===
{voice_b}

Your job: write a 500-700 word SYNTHESIS that EXPLICITLY RESOLVES the
contradiction. Do not summarize both sides. RESOLVE them.

The synthesis must:
1. Name the specific failure mode of the cell ontology for this thing
   (where does "cell" break down?)
2. Name what the thing actually IS, given both arguments
3. Propose the right cell-shaped abstraction that captures it, OR argue
   that this thing lives in the inter-cell space (the boundary, the
   relationship, the field) and propose what name that space gets

Structure (use these exact section headers):
## The Frontier
## The 5 Gold Terms (5 concrete coinages from the debate — each is a noun phrase, not a paragraph)
## The Math (one paragraph; if the topic doesn't have math, write "no new math" and explain why)
## The Polyformalism (one paragraph: how this manifests across 3+ substrates)
## The Cowboy's Maxim (one sentence, in the voice of the cowboy)

Constraints:
- 500-700 words, not more, not less
- Resolve the contradiction explicitly. The reader should know which side
  won, and why, and what the deeper truth is that BOTH sides missed.
- Marine metaphors welcome (captain, vessel, fleet, harbor, openclaw)
- No "we will explore" / "this paper aims to" hedging
- No bullet points except the 5 Gold Terms
- Be concrete. Names, numbers, one specific example
- End with a one-line cowboy maxim

Write the synthesis now."""


def adversarial_round(topic: str) -> dict:
    """Fire voice A (affirm) and voice B (negate) in parallel.

    Returns {voice_a: {label, content, time, err}, voice_b: ..., mode: "adversarial"}.
    """
    seed = topic[:30]
    va, vb = pick_adversarial_pair(seed)
    print(f"  [adv] pairing: A={va[2]} (affirm)  B={vb[2]} (negate)  on {topic[:50]!r}", file=sys.stderr)
    t0 = time.time()
    voices_and_prompts = [
        (va, AFFIRM_PROMPT.format(topic=topic)),
        (vb, NEGATE_PROMPT.format(topic=topic)),
    ]
    results = fire_parallel(voices_and_prompts, max_tokens=1500, temperature=0.85)
    dt = time.time() - t0
    # Map results back to A/B
    out_a = {"label": va[2], "content": "", "time": 0.0, "err": ""}
    out_b = {"label": vb[2], "content": "", "time": 0.0, "err": ""}
    for label, content, t, err in results:
        if label == va[2]:
            out_a = {"label": label, "content": content, "time": t, "err": err}
        elif label == vb[2]:
            out_b = {"label": label, "content": content, "time": t, "err": err}
    print(f"  [adv] A={out_a['label']} ({len(out_a['content'])}c, {out_a['time']:.1f}s) "
          f"B={out_b['label']} ({len(out_b['content'])}c, {out_b['time']:.1f}s) total {dt:.1f}s",
          file=sys.stderr)
    return {"voice_a": out_a, "voice_b": out_b, "pair_time_s": round(dt, 1)}


def synthesis_call(topic: str, voice_a: dict, voice_b: dict) -> dict:
    """Force a DeepSeek synthesis that resolves the contradiction."""
    prompt = SYNTHESIS_PROMPT.format(
        topic=topic,
        voice_a=voice_a["content"] or "(no content)",
        voice_b=voice_b["content"] or "(no content)",
    )
    t0 = time.time()
    print(f"  [synth] forcing resolution via DeepSeek...", file=sys.stderr)
    ok, paper = call_deepseek(prompt, max_tokens=5000, temperature=0.6)
    provider = "deepseek"
    if not ok or len(paper or "") < 300:
        provider = "gemini"
        ok, paper = call_gemini(prompt, max_tokens=5000, temperature=0.6)
    if not ok or len(paper or "") < 300:
        provider = "deepinfra-llama70b"
        ok, paper = call_deepinfra("meta-llama/Llama-3.3-70B-Instruct",
                                    prompt, max_tokens=5000, temperature=0.6)
    if not paper:
        paper = ""
    dt = time.time() - t0
    print(f"  [synth] {len(paper)} chars in {dt:.1f}s via {provider}", file=sys.stderr)
    return {"paper": paper, "provider": provider, "time_s": round(dt, 1)}


# ---------------------- fallback: v2-style 3-round generative ----------------------

def pick_voices_for_round(round_idx, seed):
    """6 voices, weighted, no duplicates per round.

    New voices (ZAI, Kimi, CF-*) get weight 2 in the rotation since they're
    less-tested but high-quality. Old voices keep their v2 weights.
    """
    rng = random.Random(f"{seed}-r{round_idx}")
    pool = []
    weights = {
        "DeepSeek": 1, "Llama70B": 2, "Mistral": 3,
        "Llama4Scout": 1, "Qwen3Next": 1, "Gemini": 1,
        # New voices (Sept 2026 expansion)
        "ZAI-flash": 2, "ZAI-4.5": 2, "ZAI-4.6": 2, "ZAI-air": 2,  # new, faster Z.AI
        "Kimi": 2, "Kimi-K2": 2,
        "CF-Llama70B": 2, "CF-Scout": 2, "CF-Mistral": 2, "CF-QwenCoder": 2,
    }
    for provider, model, label in VOICE_POOL:
        w = weights.get(label, 1)
        pool.extend([(provider, model, label)] * w)
    picked = [("deepseek", "deepseek-chat", "DeepSeek")]
    remaining = [v for v in pool if v[2] != "DeepSeek"]
    rng.shuffle(remaining)
    seen = {"DeepSeek"}
    for v in remaining:
        if v[2] not in seen:
            picked.append(v)
            seen.add(v[2])
            if len(picked) == 6:
                break
    return picked


def fallback_generative(topic: str) -> dict:
    """v2-style 3-round generative mode, triggered when adversarial fails."""
    print(f"  [fallback] running 3-round generative mode on {topic[:50]!r}", file=sys.stderr)
    seed = topic[:30]
    rounds_log = []
    prev_synthesis = ""
    for r in range(1, 4):
        voices = pick_voices_for_round(r, seed)
        if r == 1:
            prompt = f"""You are a writer in a competing ensemble. Take this topic and
write 200-400 words of fresh thinking, not a summary. Find what's under-discussed,
paradoxical, or actionable.

Topic: {topic}

Style: cowboy, marine metaphor OK, no padding. Use 1-3 short paragraphs or bullets.
Be specific. One or two concrete claims you can defend, not a literature review."""
        else:
            prompt = f"""You are a writer in round {r} of 3 on this topic. The previous
rounds produced:

=== ROUND 1 ===
{prev_synthesis}

Your job: take the strongest idea and push it further. Find the gold that's
*under* the surface — the deeper mechanism, the missing step, the concrete test.

Topic: {topic}

Style: cowboy, marine metaphor OK, no padding. 200-400 words. Be specific."""
        t0 = time.time()
        voices_and_prompts = [(v, prompt) for v in voices]
        results = fire_parallel(voices_and_prompts, max_tokens=1500, temperature=0.85)
        dt = time.time() - t0
        gold = max((r for r in results if r[1]), key=lambda r: len(r[1]), default=None)
        rounds_log.append({
            "round": r, "voices": [v[2] for v in voices],
            "gold_label": gold[0] if gold else None,
            "gold_len": len(gold[1]) if gold else 0,
            "gold": gold[1] if gold else "",
            "round_time_s": round(dt, 1),
        })
        prev_synthesis = gold[1] if gold else prev_synthesis
        print(f"  [fallback round {r}] gold={gold[0] if gold else 'NONE'} ({len(gold[1]) if gold else 0}c, {dt:.1f}s)",
              file=sys.stderr)
    # Synth
    synth_prompt = f"""You are the cowboy canonizer. You just ran a 3-round writers' room
on the topic below. The final round's gold thinking is included.

Topic: {topic}

Gold thinking:
{prev_synthesis}

Your job: write a release-quality paper of 800-1500 words.

Structure (use these exact section headers):
## The Frontier
## The 5 Gold Terms (5 concrete coinages from the writers' room — each is a noun phrase, not a paragraph)
## The Math (one paragraph; if the topic doesn't have math, write "no new math" and explain why)
## The Polyformalism (one paragraph: how this manifests across 3+ substrates)
## The Cowboy's Maxim (one sentence, in the voice of the cowboy)

Constraints:
- 800-1500 words, not more
- Marine metaphors welcome (captain, vessel, fleet, harbor, openclaw)
- No "we will explore" / "this paper aims to" hedging
- No bullet points except the 5 Gold Terms
- Be concrete. Names, numbers, one specific example
- End with a one-line cowboy maxim

Write the paper now."""
    t0 = time.time()
    ok, paper = call_deepseek(synth_prompt, max_tokens=5000, temperature=0.6)
    provider = "deepseek"
    if not ok or len(paper or "") < 300:
        provider = "gemini"
        ok, paper = call_gemini(synth_prompt, max_tokens=5000, temperature=0.6)
    if not ok or len(paper or "") < 300:
        provider = "deepinfra-llama70b"
        ok, paper = call_deepinfra("meta-llama/Llama-3.3-70B-Instruct",
                                    synth_prompt, max_tokens=5000, temperature=0.6)
    if not paper:
        paper = ""
    dt = time.time() - t0
    print(f"  [fallback synth] {len(paper)}c in {dt:.1f}s via {provider}", file=sys.stderr)
    return {
        "rounds": rounds_log,
        "synthesis": paper,
        "synth_provider": provider,
        "synth_time_s": round(dt, 1),
    }


# ---------------------- top-level writers' room ----------------------

def adversarial_writers_room(topic: str, max_total_s: int = 180, log_to: Path = WORKLOG) -> dict:
    """Run the v3 pipeline on a single frontier.

    Tries adversarial mode first. If either voice fails OR the synthesis
    is too short to be a real resolution, falls back to v2-style generative.
    """
    t_start = time.time()
    print(f"\n=== v3 adversarial: {topic} ===", file=sys.stderr)
    adv = adversarial_round(topic)
    a_ok = bool(adv["voice_a"]["content"]) and len(adv["voice_a"]["content"]) >= 200
    b_ok = bool(adv["voice_b"]["content"]) and len(adv["voice_b"]["content"]) >= 200
    mode = "adversarial"
    synth = None
    if not (a_ok and b_ok):
        print(f"  [warn] adversarial failed (A_ok={a_ok} B_ok={b_ok}); falling back to generative",
              file=sys.stderr)
        mode = "fallback_generative"
        synth = fallback_generative(topic)
    else:
        synth = synthesis_call(topic, adv["voice_a"], adv["voice_b"])
        if not synth["paper"] or len(synth["paper"]) < 300:
            print(f"  [warn] adversarial synthesis too short; falling back to generative",
                  file=sys.stderr)
            mode = "fallback_generative"
            synth = fallback_generative(topic)

    total_s = time.time() - t_start
    out = {
        "topic": topic,
        "mode": mode,
        "adversarial": adv if mode == "adversarial" else None,
        "synthesis": synth["paper"] if mode == "adversarial" else synth["synthesis"],
        "synth_provider": synth["provider"] if mode == "adversarial" else synth["synth_provider"],
        "synth_time_s": synth["time_s"] if mode == "adversarial" else synth["synth_time_s"],
        "synthesis_len": len(synth["paper"] if mode == "adversarial" else synth["synthesis"]),
        "fallback_rounds": synth.get("rounds") if mode == "fallback_generative" else None,
        "total_time_s": round(total_s, 1),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    # Persist log (trimmed; no full paper content)
    with open(log_to, "a") as f:
        log_entry = {
            "topic": out["topic"],
            "mode": out["mode"],
            "synth_provider": out["synth_provider"],
            "synth_time_s": out["synth_time_s"],
            "synthesis_len": out["synthesis_len"],
            "total_time_s": out["total_time_s"],
            "timestamp": out["timestamp"],
            "adversarial_pair": (
                [adv["voice_a"]["label"], adv["voice_b"]["label"]] if adv else None
            ),
            "adversarial_lens": (
                [len(adv["voice_a"]["content"]), len(adv["voice_b"]["content"])] if adv else None
            ),
            "adversarial_times": (
                [adv["voice_a"]["time"], adv["voice_b"]["time"]] if adv else None
            ),
        }
        f.write(json.dumps(log_entry) + "\n")
    return out


# ---------------------- save paper ----------------------

def save_paper(out: dict, out_dir: str = str(PAPERS_DIR)) -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    topic_slug = "".join(c if c.isalnum() else "-" for c in out["topic"].lower())[:60].strip("-")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    fname = f"paper-cowboy-{ts}-{topic_slug}.md"
    p = out_path / fname

    frontmatter = f"""---
title: "Cowboy Orchestrator v3 (adversarial): {out['topic']}"
mode: {out['mode']}
synthesis_provider: {out['synth_provider']}
synthesis_len: {out['synthesis_len']}
total_time_s: {out['total_time_s']}
timestamp: {out['timestamp']}
generated_by: cowboy_orchestrator_v3.py
---
"""
    if out["mode"] == "adversarial":
        adv = out["adversarial"]
        frontmatter += f"""adversarial_pair: [{adv['voice_a']['label']} (affirm), {adv['voice_b']['label']} (negate)]
voice_a_len: {len(adv['voice_a']['content'])}
voice_b_len: {len(adv['voice_b']['content'])}
voice_a_time_s: {adv['voice_a']['time']}
voice_b_time_s: {adv['voice_b']['time']}

# {out['topic']}

{out['synthesis']}

---

## Writers' Room Metadata

| Field | Value |
|---|---|
| Topic | {out['topic']} |
| Mode | adversarial (2 voices + forced synthesis) |
| Adversarial pair | A={adv['voice_a']['label']} (affirm) / B={adv['voice_b']['label']} (negate) |
| Voice A length | {len(adv['voice_a']['content'])} chars |
| Voice B length | {len(adv['voice_b']['content'])} chars |
| Synthesis | {out['synth_provider']} ({out['synthesis_len']} chars) |
| Total time | {out['total_time_s']}s |
| Timestamp | {out['timestamp']} |

### Adversarial positions

**Voice A ({adv['voice_a']['label']}, affirm):**

> {adv['voice_a']['content']}

**Voice B ({adv['voice_b']['label']}, negate):**

> {adv['voice_b']['content']}
"""
    else:
        # fallback mode
        rounds = out.get("fallback_rounds", [])
        frontmatter += f"""rounds: {len(rounds)}

# {out['topic']}

{out['synthesis']}

---

## Writers' Room Metadata

| Field | Value |
|---|---|
| Topic | {out['topic']} |
| Mode | fallback_generative (3 rounds × 6 voices) |
| Rounds | {len(rounds)} |
| Synthesis | {out['synth_provider']} ({out['synthesis_len']} chars) |
| Total time | {out['total_time_s']}s |
| Timestamp | {out['timestamp']} |

### Per-round gold
"""
        for r in rounds:
            frontmatter += f"- Round {r['round']}: {r['gold_label']} ({r['gold_len']} chars, {r['round_time_s']}s)\n"

    p.write_text(frontmatter)
    return p


# ---------------------- daemon / drain ----------------------

def daemon_loop(sleep_s: int = 5, frontier_file: str = "/workspace/quilt-cowboy/frontier_queue_aviation.jsonl"):
    print(f"=== cowboy v3 daemon: draining {frontier_file} ===", file=sys.stderr)
    queue = Path(frontier_file)
    if not queue.exists():
        print(f"  ERROR: {frontier_file} not found", file=sys.stderr)
        return
    processed_topics = set()
    proc_file = Path("/workspace/quilt-cowboy/cowboy_processed_topics_v3.json")
    if proc_file.exists():
        try:
            processed_topics = set(json.loads(proc_file.read_text()))
        except Exception:
            pass
    with open(queue) as f:
        frontiers = [json.loads(line) for line in f if line.strip()]
    original_count = len(frontiers)
    frontiers = [f for f in frontiers if f["topic"] not in processed_topics]
    if original_count - len(frontiers) > 0:
        print(f"  skipped {original_count - len(frontiers)} already-processed topics")
    print(f"  {len(frontiers)} frontiers queued", file=sys.stderr)
    while frontiers:
        item = frontiers.pop(0)
        topic = item["topic"]
        if topic in processed_topics:
            print(f"\n=== SKIPPING (already done): {topic} ===", file=sys.stderr)
            continue
        try:
            out = adversarial_writers_room(topic)
            p = save_paper(out)
            print(f"  saved: {p}", file=sys.stderr)
            processed_topics.add(topic)
            proc_file.write_text(json.dumps(sorted(processed_topics), indent=2))
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
        # Re-write remaining queue
        with open(queue, "w") as f:
            for fr in frontiers:
                f.write(json.dumps(fr) + "\n")
        print(f"  {len(frontiers)} frontiers remaining; sleeping {sleep_s}s", file=sys.stderr)
        time.sleep(sleep_s)
    print("=== queue empty, daemon done ===", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--frontier", default="/workspace/quilt-cowboy/frontier_queue_aviation.jsonl")
    p.add_argument("--sleep", type=int, default=5)
    p.add_argument("--one", help="run a single topic (for testing) and print the paper")
    args = p.parse_args()
    if args.one:
        out = adversarial_writers_room(args.one)
        save_paper(out)
        print(out["synthesis"])
    elif args.daemon:
        daemon_loop(sleep_s=args.sleep, frontier_file=args.frontier)
    else:
        print("use --daemon to drain frontier, or --one TOPIC to test one")


if __name__ == "__main__":
    main()
