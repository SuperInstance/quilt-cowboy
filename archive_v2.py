"""archive_v2.py — automate the next MEMORY.md snapshot.

Reads the current MEMORY.md + all topic files, batches them into a single
git commit, pushes to github.com/SuperInstance/quilt-agent-memory-archive.

Usage:
  python3 archive_v2.py --label 2026-09-07-cleanup
  python3 archive_v2.py --label 2026-09-07-cleanup --dry-run
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "SuperInstance/quilt-agent-memory-archive"

# MEMORY.md is read from the system, not from a file. The system exposes it
# via memory_read(scope="agent"). This script reads the workspace snapshot
# if present, otherwise uses the file path the operator saved.
DEFAULT_MEMORY = Path("/workspace/memory_snapshot_2026-09-07.md")

# Topic files live in the agent's memory graph; the script reads them from
# a snapshot directory if present, else via memory_topic_read would require
# the agent. We pass them as arguments.
TOPIC_NAMES = ["quilt-ecosystem", "quilt-phases", "quilt-cowboy",
               "quilt-deployment", "quilt-llm-worker", "quilt-classroom"]


def get_main_sha():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/refs/heads/main",
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "archive-v2"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["object"]["sha"]


def get_base_tree(sha):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/commits/{sha}",
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "archive-v2"},
    )
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.load(r)["tree"]["sha"]


def upload_blob(content_bytes):
    b64 = base64.b64encode(content_bytes).decode("ascii")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/blobs",
        data=json.dumps({"content": b64, "encoding": "base64"}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "archive-v2",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["sha"]


def create_tree(base_tree, entries):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/trees",
        data=json.dumps({"base_tree": base_tree, "tree": entries}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "archive-v2",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["sha"]


def create_commit(sha, tree, msg):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/commits",
        data=json.dumps({"message": msg, "tree": tree, "parents": [sha]}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "archive-v2",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.load(r)["sha"]


def update_ref(sha, commit):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/refs/heads/main",
        data=json.dumps({"sha": commit, "force": True}).encode(),
        headers={"Authorization": f"Bearer {TOKEN}", "User-Agent": "archive-v2",
                 "Content-Type": "application/json"},
        method="PATCH",
    )
    return urllib.request.urlopen(req, timeout=15).status


def archive(label, memory_path: Path, topic_paths: dict, dry_run=False):
    if not TOKEN:
        print("ERROR: GITHUB_TOKEN not set", file=sys.stderr)
        return 1
    if not memory_path.exists():
        print(f"ERROR: {memory_path} not found", file=sys.stderr)
        return 1

    snap_dir = f"snapshots/{label}"
    files = [("MEMORY.md", memory_path)]
    for tname, tpath in topic_paths.items():
        if tpath and Path(tpath).exists():
            files.append((f"topics/{tname}.md", Path(tpath)))

    if dry_run:
        print(f"[dry-run] would archive {len(files)} files to {snap_dir}:")
        for relp, p in files:
            print(f"  {relp:<30} {p.stat().st_size:>10} B  {p}")
        return 0

    main_sha = get_main_sha()
    base_tree = get_base_tree(main_sha)
    print(f"  main_sha: {main_sha}", file=sys.stderr)
    print(f"  base_tree: {base_tree}", file=sys.stderr)

    entries = []
    total_bytes = 0
    for relp, p in files:
        blob_sha = upload_blob(p.read_bytes())
        entries.append({"path": f"{snap_dir}/{relp}", "mode": "100644",
                        "type": "blob", "sha": blob_sha})
        total_bytes += p.stat().st_size
        print(f"  blob {relp:<30} {p.stat().st_size:>10} B  {blob_sha[:12]}", file=sys.stderr)

    new_tree = create_tree(base_tree, entries)
    msg = f"archive: {label} — {len(files)} files ({total_bytes} bytes)"
    new_commit = create_commit(main_sha, new_tree, msg)
    status = update_ref(main_sha, new_commit)
    print(f"  new_commit: {new_commit}", file=sys.stderr)
    print(f"  ref update status: {status}", file=sys.stderr)
    print(f"\n[OK] archived {len(files)} files to https://github.com/{REPO}/tree/main/{snap_dir}")
    return 0


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--label", required=True, help="snapshot label, e.g. 2026-09-07-cleanup")
    p.add_argument("--memory", default=str(DEFAULT_MEMORY), help="path to MEMORY.md snapshot")
    p.add_argument("--topic-dir", default="/workspace",
                   help="directory containing topic_*.md files")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()

    topic_paths = {}
    topic_dir = Path(args.topic_dir)
    for t in TOPIC_NAMES:
        # The snapshot pattern is /workspace/topic_<name>.md
        p = topic_dir / f"topic_{t}.md"
        topic_paths[t] = p if p.exists() else None

    return archive(args.label, Path(args.memory), topic_paths, dry_run=args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
