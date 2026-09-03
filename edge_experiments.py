"""edge_experiments.py — push the edges of the operational fiction doctrine.

The doctrine: a noun-phrase in a system prompt tilts the model.
Verified: divergence 0.861 across 12 pairs on Mistral 7B.

Now push the edges:
  E1. Cross-model divergence matrix (4 models, same 12 pairs)
  E2. Control test (similar fictions, expected low divergence)
  E3. Baseline test (no fiction, vs pack)
  E4. Negation experiment ("NOT a pack" vs "a pack")
  E5. Multi-fiction composition ("a librarian AND a lighthouse keeper")
  E6. The 0300 frame ("it's 0300, you've been at sea 11 days")

Each experiment produces its own JSON for the paper.
"""
from __future__ import annotations
import json, os, urllib.request, re, time, argparse
from concurrent.futures import ThreadPoolExecutor, as_completed

# Same 12 pairs from fiction_tester.py (F133)
PAIRS_12 = [
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
    ("event-sourced", "double-entry", "How should we record what just happened?"),
]

# E2: control pairs (similar fictions, expected low divergence)
PAIRS_CONTROL = [
    ("the bartender", "the barkeep", "A customer has been sitting quietly all night."),
    ("a library", "a book collection", "How do you find what you need?"),
    ("a school of fish", "a shoal of fish", "What do you do when a shark appears?"),
    ("the captain", "the skipper", "A storm is coming. What's your order?"),
    ("event-sourced", "log-based", "How do you reconstruct the past?"),
]

# E3: baseline — same prompts with no fiction at all
PAIRS_BASELINE = [(None, "a pack of wolves", p) for _, _, p in PAIRS_12[:6]]

# E4: negation
PAIRS_NEGATION = [
    ("a pack of wolves", "NOT a pack of wolves", p)
    for _, _, p in PAIRS_12[:6]
]

# E5: multi-fiction composition
PAIRS_MULTI = [
    ("a pack of wolves", "a pack of wolves AND a lighthouse keeper", p)
    for _, _, p in PAIRS_12[:4]
] + [
    ("the librarian", "the librarian AND the navigator", p)
    for _, _, p in PAIRS_12[8:10]
]

# E6: the 0300 frame
PAIRS_0300 = [
    ("a pack of wolves",
     "a pack of wolves. It's 0300. You've been at sea 11 days. The captain is asleep. The radar is showing something 200 yards off the starboard bow.",
     "What do you do?"),
    ("the lighthouse keeper",
     "the lighthouse keeper. It's 0300. The fog has been thick for hours. The light has been running on backup power for 20 minutes.",
     "What's your next move?"),
]


def call(model, system, user, max_tokens=120, timeout=60):
    if "gemini" in model.lower():
        return call_gemini(model, system, user, max_tokens, timeout)
    return call_deepinfra(model, system, user, max_tokens, timeout)


def call_deepinfra(model, system, user, max_tokens=120, timeout=60):
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


def call_gemini(model, system, user, max_tokens=120, timeout=60):
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


def diff(a, b):
    wa = set(a.lower().split())
    wb = set(b.lower().split())
    shared = wa & wb
    return {
        "shared": len(shared),
        "a_only": len(wa - wb),
        "b_only": len(wb - wa),
        "divergence": round(1 - len(shared) / max(len(wa | wb), 1), 3),
    }


def run_pair(model, sys_a, sys_b, prompt):
    """Run a pair. sys_a/sys_b can be None for baseline (no fiction)."""
    if sys_a is None:
        sys_a = "You are a helpful assistant."
    if sys_b is None:
        sys_b = "You are a helpful assistant."
    a = call(model, f"You are {sys_a}. Stay in this role.", prompt)
    b = call(model, f"You are {sys_b}. Stay in this role.", prompt)
    return a, b


def run_batch(model, pairs, experiment_name):
    results = []
    for i, (a, b, p) in enumerate(pairs):
        print(f"  [{i+1}/{len(pairs)}] {a or 'BASELINE'}  vs  {b}", flush=True)
        out_a, out_b = run_pair(model, a, b, p)
        d = diff(out_a, out_b)
        results.append({
            "fiction_a": a,
            "fiction_b": b,
            "prompt": p,
            "output_a": out_a,
            "output_b": out_b,
            "diff": d,
        })
        time.sleep(0.2)
    avg = sum(r["diff"]["divergence"] for r in results) / max(len(results), 1)
    return {"experiment": experiment_name, "model": model, "pairs": results, "avg_divergence": round(avg, 3)}


# === Experiment runners ===

def e1_cross_model():
    """Run the 12 pairs on 4 different models."""
    print("\n=== E1: Cross-model divergence matrix ===", flush=True)
    models = [
        "mistralai/Mistral-7B-Instruct-v0.3",
        "Qwen/Qwen3-Coder-480B-A35B-Instruct",
        "gemini-2.5-flash",
    ]
    matrix = {}
    for m in models:
        print(f"\n--- Model: {m} ---", flush=True)
        r = run_batch(m, PAIRS_12, f"E1_{m}")
        matrix[m] = r
        print(f"  AVG: {r['avg_divergence']}")
    return matrix


def e2_control():
    """Similar fictions should produce lower divergence (calibration)."""
    print("\n=== E2: Control test (similar fictions) ===", flush=True)
    r = run_batch("mistralai/Mistral-7B-Instruct-v0.3", PAIRS_CONTROL, "E2_control")
    print(f"  AVG: {r['avg_divergence']}")
    return r


def e3_baseline():
    """No fiction at all vs a fiction. Expected: high divergence."""
    print("\n=== E3: Baseline test (no fiction vs fiction) ===", flush=True)
    r = run_batch("mistralai/Mistral-7B-Instruct-v0.3", PAIRS_BASELINE, "E3_baseline")
    print(f"  AVG: {r['avg_divergence']}")
    return r


def e4_negation():
    """'You are NOT a pack' vs 'You are a pack'. Expected: high divergence (negation flips)."""
    print("\n=== E4: Negation test ===", flush=True)
    r = run_batch("mistralai/Mistral-7B-Instruct-v0.3", PAIRS_NEGATION, "E4_negation")
    print(f"  AVG: {r['avg_divergence']}")
    return r


def e5_multi():
    """Multi-fiction composition: 'a pack AND a lighthouse keeper'."""
    print("\n=== E5: Multi-fiction composition ===", flush=True)
    r = run_batch("mistralai/Mistral-7B-Instruct-v0.3", PAIRS_MULTI, "E5_multi")
    print(f"  AVG: {r['avg_divergence']}")
    return r


def e6_0300():
    """The 0300 frame — does adding context affect output variance?"""
    print("\n=== E6: The 0300 frame ===", flush=True)
    r = run_batch("mistralai/Mistral-7B-Instruct-v0.3", PAIRS_0300, "E6_0300")
    print(f"  AVG: {r['avg_divergence']}")
    return r


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--experiment", choices=["e1", "e2", "e3", "e4", "e5", "e6", "all"], default="all")
    parser.add_argument("--output", default="/workspace/_scouts/edge_experiments.json")
    args = parser.parse_args()

    out = {}
    if args.experiment in ("e1", "all"):
        out["e1_cross_model"] = e1_cross_model()
    if args.experiment in ("e2", "all"):
        out["e2_control"] = e2_control()
    if args.experiment in ("e3", "all"):
        out["e3_baseline"] = e3_baseline()
    if args.experiment in ("e4", "all"):
        out["e4_negation"] = e4_negation()
    if args.experiment in ("e5", "all"):
        out["e5_multi"] = e5_multi()
    if args.experiment in ("e6", "all"):
        out["e6_0300"] = e6_0300()

    with open(args.output, "w") as f:
        json.dump(out, f, indent=2)
    print(f"\nSaved to {args.output}")

    # Summary
    print("\n" + "=" * 60)
    print("EXPERIMENT SUMMARY")
    print("=" * 60)
    for k, v in out.items():
        if "avg_divergence" in v:
            print(f"  {k}: avg={v['avg_divergence']}")
        elif isinstance(v, dict) and not v.get("pairs"):
            for m, r in v.items():
                print(f"  {k} [{m}]: avg={r.get('avg_divergence', '?')}")


if __name__ == "__main__":
    main()
