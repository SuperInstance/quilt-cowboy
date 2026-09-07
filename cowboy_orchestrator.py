"""cowboy_orchestrator.py — long-running competing-ensemble writers' room.

The cowboy's lever: spawn N parallel voices per topic, let them compete,
pick the gold. The parent session just steers via --topic and --rounds.

Usage:
  python3 cowboy_orchestrator.py --topic "the in-between frontier" --rounds 4
  python3 cowboy_orchestrator.py --daemon                  # run continuously
  python3 cowboy_orchestrator.py --queue file.jsonl        # drain a queue
  python3 cowboy_orchestrator.py --status                   # show recent runs

Design:
  4 voices per round (DeepSeek + DeepInfra trio + Gemini).
  Each voice writes 200-500 tokens per round.
  Cowboy picks the gold (longest + most concrete) or synthesizes.
  After 4 rounds, output is canonized as a paper (markdown).
"""
from __future__ import annotations

import argparse
import json
import os
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
    "ByteDance/Seed-OSS-36B-Instruct",
]
DI = os.environ.get("DEEPINFRA_TOKEN", "")
DS = os.environ.get("DEEPSEEK_TOKEN", "")
GM = os.environ.get("GEMINI_TOKEN", "")

WORKLOG = Path("/workspace/quilt-cowboy/cowboy_worklog.jsonl")
WORKLOG.parent.mkdir(parents=True, exist_ok=True)


def call_deepinfra(model: str, prompt: str, max_tokens=2000, temperature=0.7, timeout=60):
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
            reasoning = data.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")
            if not content and reasoning:
                return True, reasoning
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_deepseek(prompt: str, max_tokens=2000, temperature=0.7, model="deepseek-chat", timeout=60):
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
            reasoning = data.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")
            if not content and reasoning:
                return True, reasoning
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_gemini(prompt: str, max_tokens=2000, temperature=0.7, model="gemini-2.5-flash", timeout=60):
    if not GM:
        return False, "no GM token"
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent?key={GM}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return True, text
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


# --- 4 voices for the writers' room ---
# Different perspectives compete. Each one writes ~200-500 tokens.
VOICES_4 = [
    ("deepinfra", "meta-llama/Llama-3.3-70B-Instruct-Turbo", "Llama70B"),
    ("deepseek", "deepseek-chat", "DeepSeek"),
    ("deepinfra", "mistralai/Mistral-Small-24B-Instruct-2501", "Mistral"),
    ("gemini", "gemini-2.5-flash", "Gemini"),
]

VOICES_8 = VOICES_4 + [
    ("deepinfra", "Qwen/Qwen2.5-72B-Instruct", "Qwen72B"),
    ("deepinfra", "google/gemma-3-27b-it", "Gemma3"),
    ("deepinfra", "Qwen/Qwen3-Next-80B-A3B-Instruct", "Qwen3Next"),
    ("deepinfra", "meta-llama/Llama-4-Scout-17B-16E-Instruct", "Llama4Scout"),
]


def fire_voice(provider, model, label, prompt, max_tokens=2000, temperature=0.7):
    """Fire one voice. Returns (label, content, time, error)."""
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


def fire_round(prompt: str, voices=None, max_tokens=2000, temperature=0.7) -> list:
    """Fire all voices in parallel. Returns list of (label, content, time, error)."""
    if voices is None:
        voices = VOICES_4
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


def writers_room(topic: str, rounds: int = 4, voice_count: int = 4, max_tokens: int = 2000,
                 temperature: float = 0.85, log_to: Path = WORKLOG) -> dict:
    """Run N rounds of N-voice writers' room. Returns dict with all rounds + synthesis."""
    voices = VOICES_4 if voice_count == 4 else VOICES_8
    t_start = time.time()
    rounds_log = []
    prev_synthesis = ""

    for r in range(1, rounds + 1):
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

Your job: take the strongest idea from round 1 and push it further. Find the
gold that's *under* the surface — the deeper mechanism, the missing step, the
concrete test. Don't repeat.

Topic: {topic}

Style: cowboy, marine metaphor OK, no padding. 200-400 words. Be specific.
One or two concrete claims you can defend."""

        print(f"  [round {r}/{rounds}] firing {len(voices)} voices on {topic[:60]!r}...", file=sys.stderr)
        t_round = time.time()
        results = fire_round(prompt, voices=voices, max_tokens=max_tokens, temperature=temperature)
        dt_round = time.time() - t_round

        # Pick the longest concrete content (the gold)
        gold = max((r for r in results if r[1]), key=lambda r: len(r[1]), default=None)
        rounds_log.append({
            "round": r,
            "prompt_kind": "first" if r == 1 else "next",
            "voices": [{"label": l, "len": len(c), "time": round(t, 1), "err": e[:80] if e else ""}
                        for l, c, t, e in results],
            "gold_label": gold[0] if gold else None,
            "gold_len": len(gold[1]) if gold else 0,
            "gold": gold[1] if gold else "",
            "all_responses": [{"label": l, "content": c, "time": round(t, 1), "err": e[:120] if e else ""}
                              for l, c, t, e in results],
            "round_time_s": round(dt_round, 1),
        })
        prev_synthesis = gold[1] if gold else prev_synthesis
        print(f"  [round {r}] gold={gold[0] if gold else 'NONE'} ({len(gold[1]) if gold else 0} chars, {dt_round:.1f}s)",
              file=sys.stderr)

    # Final synthesis: 1 voice, asked to write the canon paper
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
    ok, paper = call_deepseek(synth_prompt, max_tokens=4000, temperature=0.6)
    if not ok or len(paper or "") < 200:
        synth_provider = "gemini"
        ok, paper = call_gemini(synth_prompt, max_tokens=4000, temperature=0.6)
    if not ok or len(paper or "") < 200:
        synth_provider = "deepinfra-llama70b"
        ok, paper = call_deepinfra("meta-llama/Llama-3.3-70B-Instruct",
                                    synth_prompt, max_tokens=4000, temperature=0.6)
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

    # Log
    with open(log_to, "a") as f:
        # Don't log all_responses (too long); just the metadata
        log_entry = {k: v for k, v in out.items() if k != "rounds"}
        log_entry["rounds"] = [{"round": r["round"], "gold_label": r["gold_label"],
                                 "gold_len": r["gold_len"], "round_time_s": r["round_time_s"]}
                                for r in rounds_log]
        f.write(json.dumps(log_entry) + "\n")

    return out


def save_paper(out: dict, out_dir: str = "/workspace/quilt-cowboy/cowboy_papers") -> Path:
    """Save the synthesis as a paper file with frontmatter."""
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
generated_by: cowboy_orchestrator.py
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


def daemon_loop(sleep_s: int = 30, frontier_file: str = "/workspace/quilt-cowboy/frontier_queue.jsonl"):
    """Run continuously. Drain frontier queue, write papers to disk."""
    print(f"=== cowboy daemon: draining {frontier_file} ===", file=sys.stderr)
    queue = Path(frontier_file)
    queue.parent.mkdir(parents=True, exist_ok=True)
    if not queue.exists():
        # Seed the queue with a few starter frontiers if it doesn't exist
        seed = [
            "the inverse of a fabric — a sub-fabric, a hole that is also a cell",
            "the canoe: a vessel small enough that the captain and the boat are the same agent",
            "the kelp forest: an ecosystem whose cells are not pinned to a substrate but to a current",
            "the watch as a server: how the oscillation becomes an API",
            "the gift economy: cells that give to survive, not cells that compete to extract",
            "the captain's child: a cell that grows up to be a captain",
        ]
        with open(queue, "w") as f:
            for s in seed:
                f.write(json.dumps({"topic": s, "rounds": 4}) + "\n")
        print(f"  seeded queue with {len(seed)} starter frontiers", file=sys.stderr)

    with open(queue) as f:
        frontiers = [json.loads(line) for line in f if line.strip()]

    print(f"  {len(frontiers)} frontiers queued", file=sys.stderr)
    while frontiers:
        item = frontiers.pop(0)
        topic = item["topic"]
        rounds = item.get("rounds", 4)
        print(f"\n=== frontier: {topic} ===", file=sys.stderr)
        try:
            out = writers_room(topic, rounds=rounds)
            p = save_paper(out)
            print(f"  saved: {p}", file=sys.stderr)
        except Exception as e:
            print(f"  ERROR: {e}", file=sys.stderr)
        # Persist the remaining queue
        with open(queue, "w") as f:
            for fr in frontiers:
                f.write(json.dumps(fr) + "\n")
        print(f"  {len(frontiers)} frontiers remaining; sleeping {sleep_s}s", file=sys.stderr)
        time.sleep(sleep_s)
    print("=== queue empty, daemon done ===", file=sys.stderr)


def show_status():
    if not WORKLOG.exists():
        print("no worklog yet")
        return
    n = 0
    with open(WORKLOG) as f:
        for line in f:
            try:
                e = json.loads(line)
                n += 1
                print(f"  {e.get('timestamp','?')[:19]}  {e.get('topic','?')[:50]:<50} "
                      f"rounds={len(e.get('rounds',[]))} time={e.get('total_time_s','?')}s "
                      f"synth={e.get('synth_len','?')}c")
            except Exception:
                pass
    print(f"\n  total runs: {n}")


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--topic", help="single topic")
    p.add_argument("--rounds", type=int, default=4)
    p.add_argument("--voices", type=int, default=4, choices=[4, 8])
    p.add_argument("--max-tokens", type=int, default=2000)
    p.add_argument("--temperature", type=float, default=0.85)
    p.add_argument("--daemon", action="store_true", help="drain frontier queue continuously")
    p.add_argument("--queue", help="path to frontier queue JSONL")
    p.add_argument("--status", action="store_true")
    p.add_argument("--out-dir", default="/workspace/quilt-cowboy/cowboy_papers")
    args = p.parse_args()

    if args.status:
        show_status()
        return
    if args.daemon:
        daemon_loop()
        return
    if not args.topic:
        p.error("need --topic or --daemon or --status")

    out = writers_room(args.topic, rounds=args.rounds, voice_count=args.voices,
                       max_tokens=args.max_tokens, temperature=args.temperature)
    p = save_paper(out, out_dir=args.out_dir)
    print(f"\n=== PAPER ===\nFile: {p}\n")
    print(out["synthesis"])


if __name__ == "__main__":
    main()
