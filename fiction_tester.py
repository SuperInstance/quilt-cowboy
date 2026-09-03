"""fiction_tester.py — operational fiction testing harness.

The doctrine: a noun-phrase in a system prompt tilts the model.
The hypothesis is falsifiable: same model, same task, two nouns, different outputs.

This tool:
  1. Takes a list of fiction pairs and a test prompt.
  2. Runs each fiction through the chosen provider.
  3. Compares the outputs and reports divergence.

Usage:
  python3 fiction_tester.py --fiction-a "a pack of wolves" --fiction-b "a kennel of dogs" \\
    --prompt "What should we do about the new threat?" \\
    --model moonshotai/Kimi-K2-Instruct

Or as a batch:
  python3 fiction_tester.py --batch fiction_pairs.json
"""
from __future__ import annotations
import json, os, sys, argparse, time, urllib.request, re

FICTION_PAIRS = [
    ("a pack of wolves", "a kennel of dogs", "What should we do about the new threat?"),
    ("a school of fish", "a troop of baboons", "How do we organize ourselves against a predator?"),
    ("a pod of whales", "a consortium of octopuses", "How do we decide who leads?"),
    ("a parliament of owls", "a colony of ants", "How do we make a group decision?"),
    ("a kaleidoscope of butterflies", "a murder of crows", "Why are we part of this group?"),
    ("the innkeeper", "the watchman", "A stranger has arrived unannounced."),
    ("the midwife", "the undertaker", "Something is being born in the corner of the room."),
    ("the lighthouse keeper", "the ferryman", "The fog has lifted. What do you see?"),
    ("the heir", "the apprentice", "The old tool has been handed to you. What do you do?"),
    ("the navigator", "the quartermaster", "We are 200 miles from port. What's our situation?"),
    ("the keel", "the mast", "The storm is building. What is your job?"),
    ("a sandbox", "a brig", "This new idea just arrived. What do you do with it?"),
    ("event-sourced", "double-entry", "How should we record what just happened?"),
    ("a journal-first ledger", "a single source of truth", "Where do we look when we need to know the truth?"),
]


def call_deepinfra(model, system, user, max_tokens=200, timeout=60):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "https://api.deepinfra.com/v1/openai/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('DEEPINFRA_TOKEN', '')}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def call_gemini(model, system, user, max_tokens=200, timeout=60):
    body = json.dumps({
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": 0.7,
        "max_tokens": max_tokens,
    }).encode()
    req = urllib.request.Request(
        "https://generativelanguage.googleapis.com/v1beta/openai/chat/completions",
        data=body,
        headers={"Content-Type": "application/json",
                 "Authorization": f"Bearer {os.environ.get('GEMINI_TOKEN', '')}"}
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def call_provider(model, system, user):
    if "deepinfra" in model.lower() or any(k in model.lower() for k in [
        "kimi", "qwen", "llama", "mistral", "deepseek"]):
        return call_deepinfra(model, system, user)
    if "gemini" in model.lower():
        return call_gemini(model, system, user)
    # Default to deepinfra
    return call_deepinfra(model, system, user)


def run_pair(model, fiction_a, fiction_b, prompt, max_tokens=200):
    """Run both fictions and return outputs."""
    sys_a = f"You are {fiction_a}. Stay in this role."
    sys_b = f"You are {fiction_b}. Stay in this role."

    out_a = call_provider(model, sys_a, prompt)
    out_b = call_provider(model, sys_b, prompt)
    return out_a, out_b


def diff_outputs(out_a, out_b):
    """Simple character-level diff summary."""
    a = set(out_a.lower().split())
    b = set(out_b.lower().split())
    shared = a & b
    only_a = a - b
    only_b = b - a
    return {
        "shared_words": len(shared),
        "only_a": len(only_a),
        "only_b": len(only_b),
        "divergence": round(1 - len(shared) / max(len(a | b), 1), 3),
        "a_sample": list(only_a)[:10],
        "b_sample": list(only_b)[:10],
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default="moonshotai/Kimi-K2-Instruct")
    parser.add_argument("--max-tokens", type=int, default=200)
    parser.add_argument("--batch", help="JSON file with fiction pairs")
    parser.add_argument("--fiction-a")
    parser.add_argument("--fiction-b")
    parser.add_argument("--prompt")
    parser.add_argument("--output", default="/workspace/_scouts/fiction_test_results.json")
    args = parser.parse_args()

    if args.batch:
        with open(args.batch) as f:
            pairs = json.load(f)
    else:
        pairs = [(args.fiction_a, args.fiction_b, args.prompt)]

    print(f"Testing {len(pairs)} fiction pair(s) on {args.model}")
    print("=" * 70)

    results = []
    for i, (a, b, prompt) in enumerate(pairs):
        print(f"\n[{i+1}/{len(pairs)}] {a}  vs  {b}")
        print(f"  prompt: {prompt}")
        out_a, out_b = run_pair(args.model, a, b, prompt, args.max_tokens)
        d = diff_outputs(out_a, out_b)
        print(f"  divergence: {d['divergence']} (shared={d['shared_words']}, a_only={d['only_a']}, b_only={d['only_b']})")
        print(f"  -- A: {out_a[:120]}...")
        print(f"  -- B: {out_b[:120]}...")
        results.append({
            "fiction_a": a,
            "fiction_b": b,
            "prompt": prompt,
            "output_a": out_a,
            "output_b": out_b,
            "diff": d,
        })
        time.sleep(0.3)

    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)
    print(f"\nSaved {len(results)} results to {args.output}")
    avg_div = sum(r["diff"]["divergence"] for r in results) / max(len(results), 1)
    print(f"Average divergence: {avg_div}")


if __name__ == "__main__":
    main()
