#!/usr/bin/env python3
"""Live status page generator for the cowboy pipeline."""
import json
import os
import time
from pathlib import Path
import re
import urllib.request

W = Path("/workspace")
CC = W / "quilt-cowboy"
PAPER_DIR = CC / "cowboy_papers"
WORKLOG = CC / "cowboy_worklog.jsonl"
OUT = CC / "cowboy_status" / "index.html"
OUT.parent.mkdir(exist_ok=True)

def get_canon_state():
    try:
        req = urllib.request.Request(
            "https://api.github.com/repos/SuperInstance/AI-Writings/git/trees/main?recursive=1",
            headers={"Authorization": f"Bearer {os.environ.get('GITHUB_TOKEN', '')}"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.load(r)
        nums = [int(re.match(r'^seed-canon/papers/paper-(\d+)', e['path']).group(1))
                for e in d.get('tree', []) if re.match(r'^seed-canon/papers/paper-(\d+)', e['path'])]
        return len(nums), max(nums) if nums else 0
    except Exception as e:
        return 0, 0

today = time.strftime("%Y%m%d")
today_papers = sorted([p for p in PAPER_DIR.glob(f"paper-cowboy-{today}*.md")])

worklog_n = 0
last_topics = []
if WORKLOG.exists():
    for line in WORKLOG.read_text().splitlines()[-200:]:
        if line.strip():
            worklog_n += 1
            try:
                e = json.loads(line)
                t = e.get('topic', e.get('name', ''))
                if t: last_topics.append(t)
            except Exception:
                pass

daemon_state = "unknown"
log_file = Path("/tmp/cowboy_daemon_v3.log")
if log_file.exists():
    text = log_file.read_text()
    if "saved:" in text:
        last_save = text.split("saved:")[-1].split("\n")[0].strip()
        daemon_state = f"draining aviation frontier, last saved: {last_save[-80:]}"
    elif "starting" in text:
        daemon_state = "starting up"
    else:
        daemon_state = text[-100:].strip()

def get_live_status():
    try:
        req = urllib.request.Request("https://live-canon.superinstance.dev/api/ports",
                                     headers={"User-Agent": "Quilt-Cowboy-Status/1.0"})
        with urllib.request.urlopen(req, timeout=5) as r:
            d = json.load(r)
        return d.get('n_ports', 0), d.get('sigma', 0), d.get('test_hash', '?')
    except Exception:
        return 0, 0, "?"

canon_count, canon_max = get_canon_state()
n_ports, sigma, test_hash = get_live_status()

html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Cowboy Live Status — Quilt</title>
<meta http-equiv="refresh" content="60">
<style>
body {{ font: 16px/1.5 system-ui, sans-serif; background: #0a0e14; color: #d8d8d8; max-width: 1200px; margin: 2em auto; padding: 0 1em; }}
h1 {{ color: #7ecfff; border-bottom: 1px solid #2a3340; padding-bottom: 0.5em; }}
h2 {{ color: #d0b070; margin-top: 1.5em; }}
.kpi-grid {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(200px, 1fr)); gap: 1em; margin: 1em 0; }}
.kpi {{ background: #1a2128; border: 1px solid #2a3340; border-radius: 6px; padding: 1em; }}
.kpi-label {{ font-size: 0.85em; color: #88a; text-transform: uppercase; letter-spacing: 0.05em; }}
.kpi-value {{ font-size: 2em; color: #7ecfff; font-weight: bold; margin-top: 0.2em; }}
.kpi-sub {{ font-size: 0.85em; color: #aab; margin-top: 0.3em; }}
.topic-list {{ list-style: none; padding: 0; }}
.topic-list li {{ padding: 0.4em 0.8em; border-left: 3px solid #d0b070; background: #1a2128; margin: 0.3em 0; font-family: monospace; font-size: 0.92em; }}
.footer {{ color: #556; font-size: 0.85em; margin-top: 2em; border-top: 1px solid #2a3340; padding-top: 1em; }}
a {{ color: #7ecfff; }}
pre {{ background: #1a2128; padding: 0.5em; border-radius: 3px; overflow-x: auto; }}
</style>
</head>
<body>
<h1>Cowboy Live Status</h1>
<p><em>Quilt polyformalism: from cell to canon, from one cowboy to many.</em></p>
<p>Last refresh: <strong>{time.strftime('%Y-%m-%d %H:%M:%S UTC', time.gmtime())}</strong></p>

<h2>KPIs</h2>
<div class="kpi-grid">
<div class="kpi"><div class="kpi-label">Canon Papers</div><div class="kpi-value">{canon_count}</div><div class="kpi-sub">max paper #{canon_max}</div></div>
<div class="kpi"><div class="kpi-label">Live Ports</div><div class="kpi-value">{n_ports}</div><div class="kpi-sub">{sigma}-sigma polyformalism</div></div>
<div class="kpi"><div class="kpi-label">Test Hash</div><div class="kpi-value" style="font-size:1.1em; font-family:monospace;">{test_hash}</div><div class="kpi-sub">byte-exact</div></div>
<div class="kpi"><div class="kpi-label">Today</div><div class="kpi-value">{len(today_papers)}</div><div class="kpi-sub">cowboy papers</div></div>
<div class="kpi"><div class="kpi-label">Worklog</div><div class="kpi-value">{worklog_n}</div><div class="kpi-sub">entries</div></div>
</div>

<h2>Pipeline State</h2>
<pre>{daemon_state}</pre>

<h2>Today's Papers ({len(today_papers)})</h2>
<ul class="topic-list">
{chr(10).join(f'<li>{p.name.split("-", 3)[3].replace(".md", "").replace("---", " - ")}</li>' for p in today_papers[-15:])}
</ul>

<h2>Live Endpoints</h2>
<ul>
<li><a href="https://live-canon.superinstance.dev/api/ports">/api/ports</a> - 14 ports, 5-sigma</li>
<li><a href="https://live-canon.superinstance.dev/api/canon/random">/api/canon/random</a> - random cell</li>
<li><a href="https://live-canon.superinstance.dev/api/canon/cell/425">/api/canon/cell/425</a> - full cell</li>
<li><a href="https://live-canon.superinstance.dev/api/canon/lineage?from=425&to=440">/api/canon/lineage</a> - graph traversal</li>
<li><a href="https://live-canon.superinstance.dev/api/canon/similar?id=425">/api/canon/similar</a> - semantic neighbors</li>
<li><a href="https://live-canon.superinstance.dev/playground">/playground</a> - interactive 4x4 dials</li>
<li><a href="https://live-canon.superinstance.dev/api/sensors">/api/sensors</a> - 16 boat sensors</li>
<li><a href="https://live-canon.superinstance.dev/api/boat/9900">/api/boat/9900</a> - boat cell (after sensors)</li>
</ul>

<h2>Substrate Map</h2>
<pre>
Python     C99      Rust     Verilog   VHDL
JS         TS       Go       Zig       Mojo
Forth      Haskell  Lua      J

5 language families. 14 ports. 1 hash.
</pre>

<div class="footer">
Sources: <a href="https://github.com/SuperInstance/quilt-cowboy">github.com/SuperInstance/quilt-cowboy</a> - <a href="https://github.com/SuperInstance/AI-Writings">AI-Writings</a> - <a href="https://github.com/SuperInstance/quilt-live-canon">quilt-live-canon</a><br>
The cowboy rides the canon. The canon rides the cell. The cell rides the byte.
</div>
</body>
</html>"""

OUT.write_text(html)
print(f"wrote {OUT}, {len(html)} bytes, canon: {canon_count}/{canon_max}, ports: {n_ports}, sigma: {sigma}")
