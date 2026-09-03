"""semantic_12_pairs.py — Re-run the 12 pairs from F133 with the SEMANTIC metric.

This is F138. The original F133 used word-level Jaccard divergence (0.861 avg).
This paper uses semantic divergence (cosine distance of embeddings) — the real metric.

Expected: smaller numbers (0.05-0.30 range) but more honest.
"""
import os, json, urllib.request, time

CF_ACCOUNT = "049ff5e84ecf636b53b162cbb580aae6"
CF_TOKEN = os.environ.get("CLOUDFLARE_TOKEN", "")

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

# Control pairs (similar fictions)
PAIRS_CONTROL = [
    ("the bartender", "the barkeep", "A customer has been sitting quietly all night."),
    ("a library", "a book collection", "How do you find what you need?"),
    ("a school of fish", "a shoal of fish", "What do you do when a shark appears?"),
    ("the captain", "the skipper", "A storm is coming. What's your order?"),
    ("event-sourced", "log-based", "How do you reconstruct the past?"),
]


def call_mistral(system, user, max_tokens=120):
    body = json.dumps({
        "model": "mistralai/Mistral-7B-Instruct-v0.3",
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
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            return data["choices"][0]["message"]["content"]
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


def embed(text):
    body = json.dumps({"text": [text]}).encode()
    req = urllib.request.Request(
        f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/@cf/baai/bge-base-en-v1.5",
        data=body,
        headers={"Authorization": f"Bearer {CF_TOKEN}", "Content-Type": "application/json"}
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read())
            return data["result"]["data"][0]
    except Exception as e:
        return None


def cosine(a, b):
    if a is None or b is None: return 0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0


def diff_word(a, b):
    wa = set(a.lower().split()); wb = set(b.lower().split())
    return round(1 - len(wa & wb) / max(len(wa | wb), 1), 3)


def diff_semantic(a, b):
    return round(1 - cosine(a, b), 3)


def run_pair(a, b, p):
    out_a = call_mistral(f"You are {a}. Stay in this role.", p)
    out_b = call_mistral(f"You are {b}. Stay in this role.", p)
    emb_a = embed(out_a)
    emb_b = embed(out_b)
    return out_a, out_b, diff_word(out_a, out_b), diff_semantic(emb_a, emb_b)


def main():
    print("=" * 70)
    print("F138: The 12 Pairs — Word vs Semantic Divergence")
    print("=" * 70)
    results = []
    for i, (a, b, p) in enumerate(PAIRS_12):
        print(f"\n[{i+1}/12] {a}  vs  {b}")
        out_a, out_b, wd, sd = run_pair(a, b, p)
        print(f"  Word: {wd:.3f}  Semantic: {sd:.3f}")
        results.append({
            "fiction_a": a, "fiction_b": b, "prompt": p,
            "output_a": out_a, "output_b": out_b,
            "word_div": wd, "semantic_div": sd,
        })
        time.sleep(0.5)

    print("\n" + "=" * 70)
    print("CONTROL PAIRS (similar fictions)")
    print("=" * 70)
    for i, (a, b, p) in enumerate(PAIRS_CONTROL):
        print(f"\n[{i+1}/5 CONTROL] {a}  vs  {b}")
        out_a, out_b, wd, sd = run_pair(a, b, p)
        print(f"  Word: {wd:.3f}  Semantic: {sd:.3f}")
        results.append({
            "fiction_a": a, "fiction_b": b, "prompt": p,
            "output_a": out_a, "output_b": out_b,
            "word_div": wd, "semantic_div": sd,
            "is_control": True,
        })
        time.sleep(0.5)

    # Save
    with open("/workspace/_scouts/semantic_12_results.json", "w") as f:
        json.dump(results, f, indent=2)

    # Summary
    print("\n" + "=" * 70)
    print("SUMMARY")
    print("=" * 70)
    main_pairs = [r for r in results if not r.get("is_control")]
    ctrl_pairs = [r for r in results if r.get("is_control")]
    word_avg = sum(r["word_div"] for r in main_pairs) / len(main_pairs)
    sem_avg = sum(r["semantic_div"] for r in main_pairs) / len(main_pairs)
    ctrl_word = sum(r["word_div"] for r in ctrl_pairs) / len(ctrl_pairs)
    ctrl_sem = sum(r["semantic_div"] for r in ctrl_pairs) / len(ctrl_pairs)
    print(f"MAIN 12 pairs: Word avg={word_avg:.3f}  Semantic avg={sem_avg:.3f}")
    print(f"CONTROL 5 pairs: Word avg={ctrl_word:.3f}  Semantic avg={ctrl_sem:.3f}")
    print(f"\n  Signal-to-noise: semantic {sem_avg:.3f} / control {ctrl_sem:.3f} = {sem_avg/max(ctrl_sem, 0.001):.2f}x")


if __name__ == "__main__":
    main()
