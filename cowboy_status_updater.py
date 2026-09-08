#!/usr/bin/env python3
"""Periodically regenerate the live status page."""
import os, sys, subprocess, time
from pathlib import Path
SCRIPT = "/workspace/live_status.py"
LOG = Path("/workspace/quilt-cowboy/cowboy_status_updater.log")

def log(msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line)
    with open(LOG, "a") as f:
        f.write(line + "\n")

if __name__ == "__main__":
    while True:
        try:
            result = subprocess.run(["python3", SCRIPT], capture_output=True, text=True, timeout=30)
            if result.returncode == 0:
                subprocess.run(["git", "-C", "/workspace/quilt-cowboy", "-c", "http.sslVerify=false",
                                "-c", "user.email=cowboy@quilt.dev", "-c", "user.name=Mavis",
                                "add", "cowboy_status/index.html"], check=False)
                r = subprocess.run(["git", "-C", "/workspace/quilt-cowboy", "-c", "http.sslVerify=false",
                                "-c", "user.email=cowboy@quilt.dev", "-c", "user.name=Mavis",
                                "commit", "-m", "chore: refresh cowboy_status"], check=False, capture_output=True)
                if b"nothing to commit" not in r.stderr:
                    subprocess.run(["git", "-C", "/workspace/quilt-cowboy", "-c", "http.sslVerify=false",
                                    "push", f"https://{os.environ.get('GITHUB_TOKEN')}@github.com/SuperInstance/quilt-cowboy.git",
                                    "master"], check=False, capture_output=True)
                log("refreshed + pushed")
            else:
                log(f"error: {result.stderr[:200]}")
        except Exception as e:
            log(f"exception: {e}")
        time.sleep(60)
