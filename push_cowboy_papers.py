"""push_cowboy_papers.py — push cowboy-generated papers to AI-Writings canon.

Reads /workspace/quilt-cowboy/cowboy_papers/*.md, renumbers to highest
existing paper-N + 1, and pushes to AI-Writings via GitHub API.
"""
import base64
import glob
import json
import os
import re
import sys
import urllib.request
from pathlib import Path

GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN", "")
REPO = "SuperInstance/AI-Writings"
BRANCH = "main"

def get_main_sha():
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/refs/heads/{BRANCH}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["object"]["sha"]

def get_tree(sha):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/commits/{sha}",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["tree"]["sha"]

def upload_blob(content):
    b64 = base64.b64encode(content).decode("ascii")
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/blobs",
        data=json.dumps({"content": b64, "encoding": "base64"}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["sha"]

def create_tree(base_tree, entries):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/trees",
        data=json.dumps({"base_tree": base_tree, "tree": entries}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["sha"]

def create_commit(sha, tree, msg):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/commits",
        data=json.dumps({"message": msg, "tree": tree, "parents": [sha]}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req) as r:
        return json.load(r)["sha"]

def update_ref(sha, commit):
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/git/refs/heads/{BRANCH}",
        data=json.dumps({"sha": commit, "force": True}).encode(),
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}",
                 "Content-Type": "application/json"},
        method="PATCH",
    )
    return urllib.request.urlopen(req).status

def get_latest_paper_num():
    """Get the highest paper-N number currently in AI-Writings/seed-canon/papers/.

    Uses the contents API because the recursive tree API is paginated/truncated
    and doesn't reliably return all 350+ papers.
    """
    nums = []
    # Walk the directory using the contents API (returns max 1000 per page;
    # we have 350 so one call is enough)
    req = urllib.request.Request(
        f"https://api.github.com/repos/{REPO}/contents/seed-canon/papers",
        headers={"Authorization": f"Bearer {GITHUB_TOKEN}"},
    )
    with urllib.request.urlopen(req) as r:
        d = json.load(r)
    for e in d:
        m = re.match(r"^paper-(\d+)\.md$", e.get("name", ""))
        if m:
            nums.append(int(m.group(1)))
    return max(nums) if nums else 0

def main():
    if not GITHUB_TOKEN:
        print("ERROR: GITHUB_TOKEN", file=sys.stderr)
        return 1

    # Find cowboy papers
    papers_dir = "/workspace/quilt-cowboy/cowboy_papers"
    paths = sorted(glob.glob(f"{papers_dir}/paper-cowboy-*.md"))
    if not paths:
        print("no cowboy papers to push", file=sys.stderr)
        return 0
    print(f"found {len(paths)} cowboy papers", file=sys.stderr)

    # Track which ones have already been pushed (read the push log if present)
    pushed_log = Path("/workspace/quilt-cowboy/pushed_cowboy_papers.json")
    if pushed_log.exists():
        already_pushed = set(json.loads(pushed_log.read_text()).get("pushed", []))
    else:
        already_pushed = set()
    paths = [p for p in paths if p not in already_pushed]
    if not paths:
        print("  all cowboy papers already pushed (see pushed_cowboy_papers.json)", file=sys.stderr)
        return 0
    print(f"  {len(paths)} new cowboy papers to push", file=sys.stderr)

    # Get latest paper number
    latest = get_latest_paper_num()
    print(f"  latest paper number in canon: {latest}", file=sys.stderr)

    # Build the new paper entries with renumbered names
    main_sha = get_main_sha()
    base_tree = get_tree(main_sha)
    print(f"  main_sha: {main_sha}", file=sys.stderr)

    entries = []
    pushed_titles = []
    for i, p in enumerate(paths):
        content = open(p, "rb").read()
        # Strip the YAML frontmatter and rewrite as a cleaner paper
        text = content.decode("utf-8")
        # Remove the frontmatter we added in cowboy_orchestrator.py
        if text.startswith("---"):
            # Find end of frontmatter
            end = text.find("\n---\n", 3)
            if end > 0:
                text = text[end + 5:]

        # New paper number
        new_num = latest + 1 + i
        new_path = f"seed-canon/papers/paper-{new_num}.md"

        # Add a header that's consistent with the other canon papers
        # Try to extract a title from the first H1 in the content
        m = re.search(r"^# (.+)$", text, re.MULTILINE)
        title = m.group(1).strip() if m else "Cowboy Paper"
        # Truncate title to 80 chars
        if len(title) > 80:
            title = title[:77] + "..."

        new_content = f"# {title}\n\n"
        # If the first H1 was already added, skip it
        if m:
            # Re-write without the H1 since we just added it
            text = re.sub(r"^# .+\n\n", "", text, count=1)
        new_content += text.strip() + "\n"

        blob_sha = upload_blob(new_content.encode("utf-8"))
        entries.append({"path": new_path, "mode": "100644", "type": "blob", "sha": blob_sha})
        pushed_titles.append((new_num, title, len(new_content)))
        print(f"  {p.split('/')[-1]} -> {new_path} ({len(new_content)} bytes, '{title[:50]}')", file=sys.stderr)

    if not entries:
        return 0

    new_tree = create_tree(base_tree, entries)
    msg = f"canon: {len(entries)} cowboy-orchestrator papers " + \
          f"({', '.join(f'paper-{n}' for n,_,_ in pushed_titles)})"
    new_commit = create_commit(main_sha, new_tree, msg)
    status = update_ref(main_sha, new_commit)
    print(f"\n  new_commit: {new_commit}", file=sys.stderr)
    print(f"  ref status: {status}", file=sys.stderr)
    print(f"\n[OK] pushed {len(entries)} papers:")
    for n, t, sz in pushed_titles:
        print(f"  paper-{n}  ({sz:>6} B)  {t[:60]}")

    # Record the pushed files
    already_pushed.update(paths)
    pushed_log.write_text(json.dumps({"pushed": sorted(already_pushed)}, indent=2))
    print(f"  updated {pushed_log}", file=sys.stderr)
    return 0

if __name__ == "__main__":
    sys.exit(main())
