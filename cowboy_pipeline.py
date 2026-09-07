"""cowboy_pipeline.py — auto-promote cowboy papers to canon + re-embed.

Watches /workspace/quilt-cowboy/cowboy_papers/ for new files. When a new
file appears:
  1. Push it to AI-Writings as paper-{latest+1}.md
  2. Embed it into Cloudflare Vectorize (quilt-canon-v2)
  3. Log the run

The daemon and the pipeline run side-by-side. The daemon writes papers,
this script promotes them to canon and the index.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CLOUDFLARE_TOKEN = os.environ.get("CLOUDFLARE_TOKEN", "")
CF_ACCOUNT = "049ff5e84ecf636b53b162cbb580aae6"
CANON_REPO = "SuperInstance/AI-Writings"
BRANCH = "main"
VECTORIZE_INDEX = "quilt-canon-v2"
EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
EMBED_DIM = 768

PAPERS_DIR = Path("/workspace/quilt-cowboy/cowboy_papers")
LOG = Path("/workspace/quilt-cowboy/cowboy_pipeline.log")
EMBED_CP = Path("/tmp/canon/re_embed_checkpoint.json")
PUSHED_LOG = Path("/workspace/quilt-cowboy/pushed_cowboy_papers.json")


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG, "a") as f:
        f.write(line + "\n")


def get_latest_paper_num():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/contents/seed-canon/papers",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        d = json.load(r)
    nums = []
    for e in d:
        m = re.match(r"^paper-(\d+)\.md$", e.get("name", ""))
        if m:
            nums.append(int(m.group(1)))
    return max(nums) if nums else 0


def get_main_sha():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/refs/heads/{BRANCH}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["object"]["sha"]


def get_base_tree(sha):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/commits/{sha}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["tree"]["sha"]


def upload_blob(content):
    b64 = base64.b64encode(content).decode("ascii")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/blobs",
        data=json.dumps({"content": b64, "encoding": "base64"}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["sha"]


def create_tree(base, entries):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/trees",
        data=json.dumps({"base_tree": base, "tree": entries}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["sha"]


def create_commit(sha, tree, msg):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/commits",
        data=json.dumps({"message": msg, "tree": tree, "parents": [sha]}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["sha"]


def update_ref(sha, commit):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/refs/heads/{BRANCH}",
        data=json.dumps({"sha": commit, "force": True}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="PATCH",
    )
    return urllib.request.urlopen(req).status


def embed_text(text: str) -> list:
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/ai/run/{EMBED_MODEL}"
    body = {"text": [text[:8000]]}
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    return data.get("result", {}).get("data", [[]])[0]


def upsert_vectors(vectors):
    url = f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT}/vectorize/v2/indexes/{VECTORIZE_INDEX}/upsert"
    for attempt in range(3):
        try:
            req = urllib.request.Request(
                url, data=json.dumps({"vectors": vectors}).encode(),
                headers={"Authorization": f"Bearer {CLOUDFLARE_TOKEN}", "Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=30) as r:
                return True
        except urllib.error.HTTPError as e:
            if e.code == 503 and attempt < 2:
                time.sleep(15)
                continue
            log(f"  upsert HTTP {e.code}: {e.read().decode()[:100]}")
            return False


def get_pushed_set():
    if not PUSHED_LOG.exists():
        return set()
    return set(json.loads(PUSHED_LOG.read_text()).get("pushed", []))


def save_pushed(s):
    PUSHED_LOG.write_text(json.dumps({"pushed": sorted(s)}, indent=2))


def promote(paper_path: Path, paper_num: int) -> int:
    """Push + embed a single cowboy paper. Returns the new paper number, or 0 on fail."""
    if not GITHUB_TOKEN or not CLOUDFLARE_TOKEN:
        log("missing tokens")
        return 0

    text = paper_path.read_text(errors="replace")
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end > 0:
            text = text[end + 5:]

    m = re.search(r"^# (.+)$", text, re.MULTILINE)
    title = m.group(1).strip() if m else "Cowboy Paper"
    if m:
        text = re.sub(r"^# .+\n\n", "", text, count=1)

    new_num = paper_num
    new_path = f"seed-canon/papers/paper-{new_num}.md"
    new_content = f"# {title}\n\n{text.strip()}\n"

    main_sha = get_main_sha()
    base_tree = get_base_tree(main_sha)
    blob_sha = upload_blob(new_content.encode("utf-8"))
    new_tree = create_tree(base_tree, [{"path": new_path, "mode": "100644",
                                       "type": "blob", "sha": blob_sha}])
    msg = f"canon: paper-{new_num} — {title[:60]}"
    new_commit = create_commit(main_sha, new_tree, msg)
    status = update_ref(main_sha, new_commit)
    log(f"  pushed {paper_path.name} -> paper-{new_num} (commit {new_commit[:12]}, status {status})")

    # Embed
    words = new_content.split()
    chunk_size = 200
    chunks = []
    for i in range(0, len(words), chunk_size):
        chunks.append(" ".join(words[i:i+chunk_size]))

    batch = []
    for i, chunk in enumerate(chunks):
        try:
            vec = embed_text(chunk)
            batch.append({"id": f"paper-{new_num}_{i}" if len(chunks) > 1 else f"paper-{new_num}",
                          "values": vec,
                          "metadata": {"paper": f"paper-{new_num}", "chunk": i, "len": len(chunk)}})
        except Exception as e:
            log(f"  embed error paper-{new_num}/{i}: {e}")
    if batch and upsert_vectors(batch):
        log(f"  embedded {len(batch)} vectors for paper-{new_num}")
        # Update checkpoint
        done = set()
        if EMBED_CP.exists():
            done = set(json.loads(EMBED_CP.read_text()).get("done", []))
        done.add(f"paper-{new_num}")
        EMBED_CP.parent.mkdir(parents=True, exist_ok=True)
        EMBED_CP.write_text(json.dumps({"done": sorted(done)}, indent=2))

    return new_num


def watch_loop(sleep_s: int = 20):
    log(f"=== cowboy_pipeline starting (watching {PAPERS_DIR}) ===")
    seen = set()
    while True:
        try:
            current = set(PAPERS_DIR.glob("paper-cowboy-*.md"))
            new = current - seen
            pushed = get_pushed_set()
            # Use a stable per-file mapping: {file: paper_num} persisted to disk
            # so we never push the same file twice and never overwrite a previous file.
            mapping = load_mapping()
            # Recompute next available from repo + 1
            next_num = get_latest_paper_num() + 1
            for p in sorted(new):
                if str(p) in pushed:
                    seen.add(p)
                    continue
                # If this file has been mapped before, use that number; otherwise
                # allocate the next available and record it.
                if str(p) in mapping:
                    paper_num = mapping[str(p)]
                else:
                    # Make sure next_num is not already used by an existing mapping
                    while next_num in mapping.values():
                        next_num += 1
                    paper_num = next_num
                    mapping[str(p)] = paper_num
                    save_mapping(mapping)
                log(f"new paper detected: {p.name} -> paper-{paper_num}")
                n = promote(p, paper_num)
                if n > 0:
                    pushed.add(str(p))
                    save_pushed(pushed)
                    seen.add(p)
                    next_num = n + 1
                else:
                    log(f"  promote failed for {p.name}, will retry")
                    time.sleep(5)
                    break
        except Exception as e:
            log(f"watch error: {e}")
        time.sleep(sleep_s)


MAPPING_FILE = Path("/workspace/quilt-cowboy/cowboy_paper_mapping.json")


def load_mapping():
    if not MAPPING_FILE.exists():
        return {}
    try:
        return json.loads(MAPPING_FILE.read_text()).get("mapping", {})
    except Exception:
        return {}


def save_mapping(m):
    MAPPING_FILE.write_text(json.dumps({"mapping": m}, indent=2))


def main():
    """Process all currently-existing papers once, then watch."""
    log("=== cowboy_pipeline: processing existing papers first ===")
    pushed = get_pushed_set()
    mapping = load_mapping()
    next_num = get_latest_paper_num() + 1
    for p in sorted(PAPERS_DIR.glob("paper-cowboy-*.md")):
        if str(p) in pushed:
            continue
        if str(p) in mapping:
            paper_num = mapping[str(p)]
        else:
            # Allocate fresh
            while next_num in mapping.values():
                next_num += 1
            paper_num = next_num
            mapping[str(p)] = paper_num
            save_mapping(mapping)
        log(f"processing existing: {p.name} -> paper-{paper_num}")
        n = promote(p, paper_num)
        if n > 0:
            pushed.add(str(p))
            save_pushed(pushed)
            next_num = n + 1
    log("=== existing papers processed, entering watch mode ===")
    watch_loop()


if __name__ == "__main__":
    main()
