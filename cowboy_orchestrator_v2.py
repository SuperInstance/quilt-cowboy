"""cowboy_orchestrator_v2.py — 6-voice writers' room, 4 rounds, 6 minutes per paper.

Differences from v1:
- 6 voices per round (rotating pool of 12) instead of 4
- 3 rounds instead of 4 (saves ~25% time per paper)
- Frontier queue v2 (98 new marine metaphors) drained continuously
- Per-round voice rotation so each paper sees a different mix
- Cheaper voice weight (3× Mistral, 2× Llama, 1× DeepSeek) for cost
- Synthesis: always DeepSeek, max 5000 chars (longer than v1's 4000)
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

# Voice pool — verified working Sep 2026
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

WORKLOG = Path("/workspace/quilt-cowboy/cowboy_worklog.jsonl")
WORKLOG.parent.mkdir(parents=True, exist_ok=True)


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
    # Use OpenAI-compatible endpoint for Gemini
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    # Try via the standard Gemini API URL
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


# 6-voice rotation pool — different mix per round
VOICE_POOL = [
    # Provider, Model, Label, Weight
    ("deepseek", "deepseek-chat", "DeepSeek", 1),
    ("deepinfra", "meta-llama/Llama-3.3-70B-Instruct", "Llama70B", 2),
    ("deepinfra", "mistralai/Mistral-Small-24B-Instruct-2501", "Mistral", 3),
    ("deepinfra", "meta-llama/Llama-4-Scout-17B-16E-Instruct", "Llama4Scout", 1),
    ("deepinfra", "Qwen/Qwen3-Next-80B-A3B-Instruct", "Qwen3Next", 1),
    ("gemini", "gemini-2.5-flash", "Gemini", 1),
]


def pick_voices_for_round(round_idx, seed):
    """Pick 6 voices weighted by weight, deterministically per (round, seed)."""
    rng = random.Random(f"{seed}-r{round_idx}")
    pool = []
    for provider, model, label, w in VOICE_POOL:
        pool.extend([(provider, model, label)] * w)
    # Always include DeepSeek for stability
    picked = [("deepseek", "deepseek-chat", "DeepSeek")]
    # Add 5 more from pool, no duplicates
    remaining = [v for v in pool if v[2] != "DeepSeek"]
    rng.shuffle(remaining)
    seen = set(["DeepSeek"])
    for v in remaining:
        if v[2] not in seen:
            picked.append(v)
            seen.add(v[2])
            if len(picked) == 6:
                break
    return picked


def fire_voice(provider, model, label, prompt, max_tokens=2000, temperature=0.85):
    t0 = time.time()
    if provider == "deepinfra":
        ok, content = call_deepinfra(model, prompt, max_tokens, temperature)
    elif provider == "deepseek":
        ok, content = call_deepseek(prompt, max_tokens, temperature, model=model)
    elif provider == "gemini":
        ok, content = call_gemini(prompt, max_tokens, temperature, model=model)
    else:
        return label, "", 0.0, f"unknown provider: {provider}"
    dt = time.time() - t0
    return label, (content if ok else ""), dt, ("" if ok else content)


def fire_round(prompt: str, voices, max_tokens=2000, temperature=0.85) -> list:
    results = []
    with ThreadPoolExecutor(max_workers=len(voices)) as ex:
        futures = {ex.submit(fire_voice, p, m, l, prompt, max_tokens, temperature): (p, m, l)
                   for (p, m, l) in voices}
        for f in as_completed(futures):
            try:
                results.append(f.result())
            except Exception as e:
                results.append(("error", "", 0.0, str(e)))
    return results


def writers_room(topic: str, rounds: int = 3, max_tokens: int = 1500,
                 temperature: float = 0.85, log_to: Path = WORKLOG) -> dict:
    t_start = time.time()
    rounds_log = []
    prev_synthesis = ""
    seed = topic[:30]

    for r in range(1, rounds + 1):
        voices = pick_voices_for_round(r, seed)
        if r == 1:
            prompt = f"""You are a writer in a competing ensemble. Your job: take this topic and
write 200-400 words of fresh thinking, not a summary. Find what's under-discussed,
paradoxical, or actionable.

Topic: {topic}

Style: cowboy, marine metaphor OK, no padding. Use 1-3 short paragraphs or bullets.
Be specific. One or two concrete claims you can defend, not a literature review."""
        else:
            prompt = f"""You are a writer in round {r} of {rounds} on this topic. The previous
rounds produced:

=== ROUND 1 ===
{prev_synthesis}

Your job: take the strongest idea from the previous round and push it further. Find the
gold that's *under* the surface — the deeper mechanism, the missing step, the
concrete test. Don't repeat.

Topic: {topic}

Style: cowboy, marine metaphor OK, no padding. 200-400 words. Be specific.
One or two concrete claims you can defend."""

        print(f"  [round {r}/{rounds}] firing {len(voices)} voices on {topic[:60]!r}...", file=sys.stderr)
        t_round = time.time()
        results = fire_round(prompt, voices, max_tokens, temperature)
        dt_round = time.time() - t_round

        gold = max((r for r in results if r[1]), key=lambda r: len(r[1]), default=None)
        rounds_log.append({
            "round": r,
            "voices": [l for p, m, l in voices],
            "gold_label": gold[0] if gold else None,
            "gold_len": len(gold[1]) if gold else 0,
            "gold": gold[1] if gold else "",
            "all": [{"label": l, "len": len(c), "time": round(t, 1), "err": e[:80] if e else ""}
                     for l, c, t, e in results],
            "round_time_s": round(dt_round, 1),
        })
        prev_synthesis = gold[1] if gold else prev_synthesis
        print(f"  [round {r}] gold={gold[0] if gold else 'NONE'} ({len(gold[1]) if gold else 0} chars, {dt_round:.1f}s)",
              file=sys.stderr)

    # Synthesis: always DeepSeek
    synth_prompt = f"""You are the cowboy canonizer. You just ran a {rounds}-round writers' room
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
    print(f"  [synth] writing paper...", file=sys.stderr)
    t_synth = time.time()
    synth_provider = "deepseek"
    ok, paper = call_deepseek(synth_prompt, max_tokens=5000, temperature=0.6)
    if not ok or len(paper or "") < 200:
        synth_provider = "gemini"
        ok, paper = call_gemini(synth_prompt, max_tokens=5000, temperature=0.6)
    if not ok or len(paper or "") < 200:
        synth_provider = "deepinfra-llama70b"
        ok, paper = call_deepinfra("meta-llama/Llama-3.3-70B-Instruct",
                                    synth_prompt, max_tokens=5000, temperature=0.6)
    if not paper:
        paper = ""
    dt_synth = time.time() - t_synth
    print(f"  [synth] {len(paper)} chars in {dt_synth:.1f}s via {synth_provider}", file=sys.stderr)

    out = {
        "topic": topic,
        "rounds": rounds_log,
        "synthesis": paper,
        "synthesis_len": len(paper),
        "synth_provider": synth_provider,
        "synth_time_s": round(dt_synth, 1),
        "total_time_s": round(time.time() - t_start, 1),
        "timestamp": datetime.utcnow().isoformat() + "Z",
    }

    with open(log_to, "a") as f:
        log_entry = {k: v for k, v in out.items() if k != "rounds"}
        log_entry["rounds"] = [{"round": r["round"], "gold_label": r["gold_label"],
                                 "gold_len": r["gold_len"], "round_time_s": r["round_time_s"]}
                                for r in rounds_log]
        f.write(json.dumps(log_entry) + "\n")

    return out


def save_paper(out: dict, out_dir: str = "/workspace/quilt-cowboy/cowboy_papers") -> Path:
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    topic_slug = "".join(c if c.isalnum() else "-" for c in out["topic"].lower())[:60].strip("-")
    ts = datetime.utcnow().strftime("%Y%m%d-%H%M%S")
    fname = f"paper-cowboy-{ts}-{topic_slug}.md"
    p = out_path / fname

    frontmatter = f"""---
title: "Cowboy Orchestrator: {out['topic']}"
synthesis_provider: {out['synth_provider']}
rounds: {len(out['rounds'])}
total_time_s: {out['total_time_s']}
synth_len: {out['synthesis_len']}
timestamp: {out['timestamp']}
generated_by: cowboy_orchestrator_v2.py
---

# {out['topic']}

{out['synthesis']}

---

## Writers' Room Metadata

| Field | Value |
|---|---|
| Topic | {out['topic']} |
| Rounds | {len(out['rounds'])} |
| Total time | {out['total_time_s']}s |
| Synthesis | {out['synth_provider']} ({out['synthesis_len']} chars) |
| Timestamp | {out['timestamp']} |

### Per-round gold
"""
    for r in out["rounds"]:
        frontmatter += f"- Round {r['round']}: {r['gold_label']} ({r['gold_len']} chars, {r['round_time_s']}s)\n"

    p.write_text(frontmatter)
    return p


def daemon_loop(sleep_s: int = 5, frontier_file: str = "/workspace/quilt-cowboy/frontier_queue_v2.jsonl",
                rounds: int = 3):
    print(f"=== cowboy v2 daemon: draining {frontier_file} (rounds={rounds}) ===", file=sys.stderr)
    queue = Path(frontier_file)
    if not queue.exists():
        print(f"  ERROR: {frontier_file} not found", file=sys.stderr)
        return

    # Track which topics we've already processed (in case the daemon restarts and the queue persists)
    processed_topics = set()
    proc_file = Path("/workspace/quilt-cowboy/cowboy_processed_topics.json")
    if proc_file.exists():
        try:
            processed_topics = set(json.loads(proc_file.read_text()))
        except Exception:
            pass

    with open(queue) as f:
        frontiers = [json.loads(line) for line in f if line.strip()]

    # Filter out already-processed topics
    original_count = len(frontiers)
    frontiers = [f for f in frontiers if f["topic"] not in processed_topics]
    if original_count - len(frontiers) > 0:
        print(f"  skipped {original_count - len(frontiers)} already-processed topics")

    print(f"  {len(frontiers)} frontiers queued", file=sys.stderr)
    while frontiers:
        item = frontiers.pop(0)
        topic = item["topic"]
        item_rounds = item.get("rounds", rounds)
        # Double-check
        if topic in processed_topics:
            print(f"\n=== SKIPPING (already done): {topic} ===", file=sys.stderr)
            continue
        print(f"\n=== frontier: {topic} ===", file=sys.stderr)
        try:
            out = writers_room(topic, rounds=item_rounds)
            p = save_paper(out)
            print(f"  saved: {p}", file=sys.stderr)
            processed_topics.add(topic)
            proc_file.write_text(json.dumps(sorted(processed_topics), indent=2))
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
        with open(queue, "w") as f:
            for fr in frontiers:
                f.write(json.dumps(fr) + "\n")
        print(f"  {len(frontiers)} frontiers remaining; sleeping {sleep_s}s", file=sys.stderr)
        time.sleep(sleep_s)
    print("=== queue empty, daemon done ===", file=sys.stderr)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--daemon", action="store_true")
    p.add_argument("--rounds", type=int, default=3)
    p.add_argument("--frontier", default="/workspace/quilt-cowboy/frontier_queue_v2.jsonl")
    p.add_argument("--sleep", type=int, default=5)
    args = p.parse_args()

    if args.daemon:
        daemon_loop(sleep_s=args.sleep, frontier_file=args.frontier, rounds=args.rounds)
    else:
        print("use --daemon to drain frontier queue")


if __name__ == "__main__":
    main()
