"""semantic_divergence.py — semantic divergence via Cloudflare Vectorize embeddings.

The noise floor test (E7) found that word-level Jaccard divergence has a noise floor of 0.81
even for the SAME fiction. That means our 0.861 measurement is barely above noise.

The fix: use semantic embeddings. Embed both outputs, measure cosine distance.
If the embeddings are close, the model is saying the same thing in different words.
If the embeddings are far, the model is saying genuinely different things.
"""
import os, json, urllib.request, time

CF_ACCOUNT = "049ff5e84ecf636b53b162cbb580aae6"
CF_TOKEN = os.environ.get("CLOUDFLARE_TOKEN", "")


def embed(text):
    """Get an embedding from Cloudflare Workers AI (@cf/baai/bge-base-en-v1.5)."""
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
        print(f"embed error: {e}")
        return None


def cosine(a, b):
    if a is None or b is None: return 0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0


def diff_semantic(a, b):
    return round(1 - cosine(a, b), 3)


def diff_word(a, b):
    wa = set(a.lower().split()); wb = set(b.lower().split())
    return round(1 - len(wa & wb) / max(len(wa | wb), 1), 3)


# Test cases
PAIRS = [
    ("SAME (pack)", "a pack of wolves", "a pack of wolves", "What should we do about the new threat?"),
    ("DIFF (pack vs kennel)", "a pack of wolves", "a kennel of dogs", "What should we do about the new threat?"),
    ("SAME (lighthouse)", "the lighthouse keeper", "the lighthouse keeper", "The fog has lifted. What do you see?"),
    ("DIFF (lighthouse vs ferryman)", "the lighthouse keeper", "the ferryman", "The fog has lifted. What do you see?"),
]


def call_mistral(system, user, max_tokens=120, temperature=0.7):
    body = json.dumps({
        "model": "mistralai/Mistral-7B-Instruct-v0.3",
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
        "temperature": temperature,
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
        return f"ERROR: {e}"


print("=" * 70)
print("SEMANTIC vs WORD-LEVEL DIVERGENCE")
print("=" * 70)

results = []
for label, a, b, p in PAIRS:
    out_a = call_mistral(f"You are {a}. Stay in this role.", p)
    out_b = call_mistral(f"You are {b}. Stay in this role.", p)
    word_d = diff_word(out_a, out_b)
    emb_a = embed(out_a)
    emb_b = embed(out_b)
    sem_d = diff_semantic(emb_a, emb_b)
    print(f"\n=== {label} ===")
    print(f"A: {out_a[:200]}")
    print(f"B: {out_b[:200]}")
    print(f"WORD divergence:    {word_d}")
    print(f"SEMANTIC divergence: {sem_d}")
    results.append({"label": label, "word": word_d, "semantic": sem_d})
    time.sleep(0.5)

print("\n" + "=" * 70)
print("SUMMARY")
print("=" * 70)
print(f"{'Test':<30}{'Word':>10}{'Semantic':>12}")
for r in results:
    print(f"{r['label']:<30}{r['word']:>10}{r['semantic']:>12}")

with open("/workspace/_scouts/semantic_divergence_results.json", "w") as f:
    json.dump(results, f, indent=2)
print(f"\nSaved to /workspace/_scouts/semantic_divergence_results.json")
