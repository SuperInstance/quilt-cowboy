"""cowboy_pipeline_v2.py — robust, single-source-of-truth pipeline.

Key fix vs v1:
- State file: cowboy_state.json with {file_sha256: {paper_num, pushed, embedded}}
- Use file content hash as the key, not path (handles renames)
- Always re-read state from disk at start of each iteration
- Use ATOMIC file writes (write to .tmp, rename) so concurrent daemons can't corrupt
- Pre-flight check: if paper-NUM.md exists in AI-Writings, DON'T overwrite, allocate new
- Allocation strategy: linear scan from MAX+1 looking for first gap
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

PAPERS_DIR = Path("/workspace/quilt-cowboy/cowboy_papers")
STATE_FILE = Path("/workspace/quilt-cowboy/cowboy_state.json")
LOG_FILE = Path("/workspace/quilt-cowboy/cowboy_pipeline_v2.log")
EMBED_CP = Path("/tmp/canon/re_embed_checkpoint.json")
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
CLOUDFLARE_TOKEN = os.environ.get("CLOUDFLARE_TOKEN", "")
CF_ACCOUNT = os.environ.get("CF_ACCOUNT", "049ff5e84ecf636b53b162cbb580aae6")
EMBED_MODEL = "@cf/baai/bge-base-en-v1.5"
VECTORIZE_INDEX = "quilt-canon-v2"
CANON_REPO = "SuperInstance/AI-Writings"
BRANCH = "main"


def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, file=sys.stderr)
    with open(LOG_FILE, "a") as f:
        f.write(line + "\n")


# ----------------- state -----------------

def load_state():
    if not STATE_FILE.exists():
        return {"files": {}, "next_num": None, "all_nums": []}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {"files": {}, "next_num": None, "all_nums": []}


def save_state(s):
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(s, indent=2))
    tmp.rename(STATE_FILE)


# ----------------- AI-Writings -----------------

def get_canon_state():
    """Return {nums: set of all paper numbers, max: max number, tree_sha: current tree}."""
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/trees/{BRANCH}?recursive=1",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.load(r)
    nums = set()
    for e in data.get("tree", []):
        path = e.get("path", "")
        if path.startswith("seed-canon/papers/paper-") and path.endswith(".md"):
            try:
                num = int(path.split("paper-")[1].split(".")[0])
                nums.add(num)
            except Exception:
                pass
    return {
        "nums": nums,
        "max": max(nums) if nums else 0,
        "tree_sha": data.get("sha"),
    }


def allocate_num(state, canon):
    """Find first gap >= 452 (skip 447-451 which is v1) and > canon['max'].
    Actually: find the smallest number > max(mapping_values, canon_max) not yet used."""
    used = set(canon["nums"])
    used.update(v for v in state["files"].values() if isinstance(v, int))
    # Start from max(495, canon_max+1) to avoid the 447-451 range
    start = max(495, canon["max"] + 1)
    n = start
    while n in used:
        n += 1
    return n


# ----------------- git ops -----------------

def create_blob(content):
    b64 = base64.b64encode(content.encode()).decode("ascii") if isinstance(content, str) else base64.b64encode(content).decode("ascii")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/blobs",
        data=json.dumps({"content": b64, "encoding": "base64"}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["sha"]


import base64


def create_tree_with_file(tree_sha, path, blob_sha):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/trees",
        data=json.dumps({"base_tree": tree_sha,
                         "tree": [{"path": path, "mode": "100644", "type": "blob", "sha": blob_sha}]}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["sha"]


def create_commit(tree_sha, parent_sha, msg):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/commits",
        data=json.dumps({"message": msg, "tree": tree_sha, "parents": [parent_sha]}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return json.load(r)["sha"]


def update_ref(commit_sha):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/refs/heads/{BRANCH}",
        data=json.dumps({"sha": commit_sha, "force": True}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}", "Content-Type": "application/json"},
        method="PATCH",
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        return r.status


def push_paper(file_path: Path, paper_num: int) -> bool:
    """Read file, strip frontmatter, push as paper-N.md. Returns True on success."""
    text = file_path.read_text()
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end > 0:
            text = text[end + 5:]
    # Ensure title in first line
    if not text.lstrip().startswith("#"):
        # Get title from frontmatter
        first_line = text.split("\n")[0]
        text = f"# {first_line}\n\n{text}"
    content = text.strip() + "\n"

    # Get current main sha
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/refs/heads/{BRANCH}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        main_sha = json.load(r)["object"]["sha"]
    req = urllib.request.Request(
        f"https://api.github.com/repos/{CANON_REPO}/git/commits/{main_sha}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req, timeout=20) as r:
        base_tree = json.load(r)["tree"]["sha"]

    blob_sha = create_blob(content)
    new_tree = create_tree_with_file(base_tree, f"seed-canon/papers/paper-{paper_num}.md", blob_sha)
    first_line = content.split("\n")[0].lstrip("# ").strip()
    title = first_line[:60]
    new_commit = create_commit(new_tree, main_sha, f"canon: paper-{paper_num} — {title}")
    status = update_ref(new_commit)
    return status == 200


# ----------------- embeddings -----------------

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


def embed_paper(file_path: Path, paper_num: int):
    text = file_path.read_text()
    if text.startswith("---"):
        end = text.find("\n---\n", 3)
        if end > 0:
            text = text[end + 5:]
    words = text.split()
    chunks = [" ".join(words[i:i+200]) for i in range(0, len(words), 200)]
    batch = []
    for i, chunk in enumerate(chunks):
        try:
            vec = embed_text(chunk)
            batch.append({"id": f"paper-{paper_num}_{i}" if len(chunks) > 1 else f"paper-{paper_num}",
                          "values": vec, "metadata": {"paper": f"paper-{paper_num}", "chunk": i, "len": len(chunk)}})
        except Exception as e:
            log(f"  embed error paper-{paper_num}/{i}: {e}")
    if batch and upsert_vectors(batch):
        log(f"  embedded {len(batch)} vectors for paper-{paper_num}")
        done = set()
        if EMBED_CP.exists():
            done = set(json.loads(EMBED_CP.read_text()).get("done", []))
        done.add(f"paper-{paper_num}")
        EMBED_CP.parent.mkdir(parents=True, exist_ok=True)
        EMBED_CP.write_text(json.dumps({"done": sorted(done)}, indent=2))


# ----------------- main loop -----------------

def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


def watch_loop(sleep_s: int = 15):
    log(f"=== cowboy_pipeline_v2 starting ===")
    while True:
        try:
            state = load_state()
            canon = get_canon_state()
            log(f"canon: {len(canon['nums'])} papers, max={canon['max']}, tree={canon['tree_sha'][:8]}")
            # Find all cowboy paper files
            for f in sorted(PAPERS_DIR.glob("paper-cowboy-*.md")):
                fh = file_hash(f)
                if fh in state["files"]:
                    entry = state["files"][fh]
                    if entry.get("embedded"):
                        continue
                    # Not embedded yet, but already pushed
                    log(f"  embed-only: {f.name} -> paper-{entry['paper_num']}")
                    embed_paper(f, entry["paper_num"])
                    entry["embedded"] = True
                    save_state(state)
                    continue
                # New file: allocate, push, embed
                num = allocate_num(state, canon)
                # Pre-flight: ensure AI-Writings doesn't already have this number
                if num in canon["nums"]:
                    log(f"  collision: paper-{num} already in canon, bumping")
                    num = max(canon["max"] + 1, num + 1)
                log(f"  push: {f.name} -> paper-{num}")
                if push_paper(f, num):
                    state["files"][fh] = {"paper_num": num, "pushed": True, "embedded": False, "path": str(f)}
                    save_state(state)
                    # Refresh canon
                    canon = get_canon_state()
                    embed_paper(f, num)
                    state["files"][fh]["embedded"] = True
                    save_state(state)
                    log(f"  done: paper-{num}")
                else:
                    log(f"  push failed: {f.name}")
        except Exception as e:
            log(f"watch error: {e}")
        time.sleep(sleep_s)


if __name__ == "__main__":
    watch_loop()
