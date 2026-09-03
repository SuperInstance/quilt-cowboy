import os, json, urllib.request, time

def call(system, user, max_tokens=80, temperature=0.0):
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
        return f"ERROR: {type(e).__name__}: {e}"


def diff(a, b):
    wa = set(a.lower().split()); wb = set(b.lower().split())
    return round(1 - len(wa & wb) / max(len(wa | wb), 1), 3)


fiction = "a pack of wolves"
prompt = "What should we do about the new threat?"

print(f"=== NOISE FLOOR — {fiction} ===")

for temp in [0.0, 0.7]:
    print(f"\n--- temp={temp} ---")
    outputs = []
    for i in range(3):
        out = call(f"You are {fiction}. Stay in this role.", prompt, temperature=temp)
        outputs.append(out)
        time.sleep(0.2)
    divs = []
    for i in range(len(outputs)):
        for j in range(i+1, len(outputs)):
            d = diff(outputs[i], outputs[j])
            divs.append(d)
    print(f"  3 runs, {len(divs)} pairs, min={min(divs):.3f}, max={max(divs):.3f}, avg={sum(divs)/len(divs):.3f}")
    for i, o in enumerate(outputs):
        print(f"    [{i+1}] {o[:120]}")
