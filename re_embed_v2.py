"""re_embed_v2.py — re-embed AI-Writings canon papers into Cloudflare Vectorize.

Walks the AI-Writings canon papers directory, embeds any new papers
into the quilt-canon-v2 Vectorize index, and updates
re_embed_checkpoint.json with the list of done papers.

The Cloudflare token is read from the CLOUDFLARE_TOKEN env var.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

CLOUDFLARE_ACCOUNT = "049ff5e84ecf636b53b162cbb580aae6"
# Token is read from the CLOUDFLARE_TOKEN env var at runtime.
# Do NOT hardcode the token in source (GitHub push protection).
CLOUDFLARE_TOKEN = os.environ.get("CLOUDFLARE_TOKEN", "")
CANON_DIR = Path("/tmp/canon/seed-canon/papers")
CHECKPOINT = Path("/tmp/canon/re_embed_checkpoint.json")
INDEX = "quilt-canon-v2"

# Workers AI embedder
EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
EMBED_DIM = 768
EMBED_URL = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT}/ai/run/{EMBED_MODEL}"


def load_done():
    if not CHECKPOINT.exists():
        return []
    try:
        return json.loads(CHECKPOINT.read_text()).get("done", [])
    except Exception:
        return []


def save_done(done):
    CHECKPOINT.write_text(json.dumps({"done": sorted(set(done))}, indent=2))


def chunk_text(text: str, max_chars: int = 1500) -> list:
    """Split text into chunks.  Simple word-boundary split."""
    if len(text) <= max_chars:
        return [text]
    chunks = []
    while text:
        if len(text) <= max_chars:
            chunks.append(text)
            break
        cut = text.rfind(" ", 0, max_chars)
        if cut < 0:
            cut = max_chars
        chunks.append(text[:cut].strip())
        text = text[cut:].strip()
    return chunks


def embed(text: str) -> list:
    """Call Workers AI for an embedding.  Returns a list of floats."""
    body = {"text": [text[:8000]]}  # max input length
    req = urllib.request.Request(EMBED_URL, data=json.dumps(body).encode(),
                                  headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}",
                                           "Content-Type": "application/json"},
                                  method="POST")
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=20) as r:
                data = json.loads(r.read().decode())
                return data.get("result", {}).get("data", [[]])[0]
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < 2:
                time.sleep(30)
                continue
            raise


def ensure_index():
    """Make sure the index exists."""
    info_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT}/vectorize/v2/indexes/{INDEX}"
    req = urllib.request.Request(info_url, headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            json.loads(r.read().decode())
        return True
    except urllib.error.HTTPError as e:
        if e.code == 404:
            create_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT}/vectorize/v2/indexes"
            body = {"name": INDEX, "config": {"dimensions": EMBED_DIM, "metric": "cosine"}}
            req = urllib.request.Request(create_url, data=json.dumps(body).encode(),
                                          headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}",
                                                   "Content-Type": "application/json"},
                                          method="POST")
            with urllib.request.urlopen(req, timeout=15) as r:
                json.loads(r.read().decode())
            return True
        raise


def upsert_vectors(vectors: list) -> bool:
    """Upsert vectors to the index.  vectors is a list of {id, values, metadata}."""
    url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT}/vectorize/v2/indexes/{INDEX}/upsert"
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, data=json.dumps({"vectors": vectors}).encode(),
                                          headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}",
                                                   "Content-Type": "application/json"},
                                          method="POST")
            with urllib.request.urlopen(req, timeout=30) as r:
                return True
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < 2:
                time.sleep(30)
                continue
            print(f"upsert error: HTTP {e.code}: {e.read().decode()[:200]}")
            return False


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--prefix", default="paper-", help="paper prefix to filter")
    ap.add_argument("--batch-size", type=int, default=20)
    args = ap.parse_args()

    if not CANON_DIR.exists():
        print(f"Canon dir not found: {CANON_DIR}")
        sys.exit(1)

    print("=" * 60)
    print(f"re_embed_v2.py — prefix: {args.prefix}, batch_size: {args.batch_size}")
    print("=" * 60)

    done = load_done()
    print(f"  loaded {len(done)} papers")
    print("  ensuring index exists...")
    ensure_index()
    info_url = f"https://api.cloudflare.com/client/v4/accounts/{CLOUDFLARE_ACCOUNT}/vectorize/v2/indexes/{INDEX}/info"
    req = urllib.request.Request(info_url, headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}"})
    try:
        with urllib.request.urlopen(req, timeout=10) as r:
            data = json.loads(r.read().decode())
            print(f"  index: {INDEX} ({data['result'].get('config', {}).get('dimensions')}d, {data['result'].get('metric')})")
    except Exception:
        print(f"  index: {INDEX} (Noned)")

    papers = sorted([p.stem for p in CANON_DIR.glob(f"{args.prefix}*.md")])
    if not papers:
        print(f"  no papers matching {args.prefix}*")
        return
    new_papers = [p for p in papers if p not in done]
    print(f"  {len(new_papers)} papers to embed (skipped {len(done)} already-done)")

    if not new_papers:
        print("  nothing to do!")
        return

    t0 = time.time()
    embedded = 0
    batch = []
    for paper in new_papers:
        path = CANON_DIR / f"{paper}.md"
        text = path.read_text(errors="replace")
        chunks = chunk_text(text)
        for i, chunk in enumerate(chunks):
            try:
                vec = embed(chunk)
            except Exception as e:
                print(f"  embed error: {paper}/{i}: {e}")
                time.sleep(2)
                continue
            vid = f"{paper}_{i}" if len(chunks) > 1 else paper
            batch.append({"id": vid, "values": vec,
                          "metadata": {"paper": paper, "chunk": i, "len": len(chunk)}})
            if len(batch) >= args.batch_size:
                if upsert_vectors(batch):
                    embedded += len(batch)
                    elapsed = time.time() - t0
                    rate = embedded / elapsed if elapsed > 0 else 0
                    print(f"  upserted {embedded}/{len(new_papers)*1} ({rate:.1f}/s, ETA {(len(new_papers)-embedded)/max(rate, 0.1):.0f}s)")
                else:
                    print(f"  upsert failed for batch of {len(batch)}")
                batch = []
                time.sleep(0.5)

    if batch:
        if upsert_vectors(batch):
            embedded += len(batch)

    done.extend(new_papers)
    save_done(done)
    print(f"  done! {embedded} vectors embedded in {time.time()-t0:.1f}s")


if __name__ == "__main__":
    main()
