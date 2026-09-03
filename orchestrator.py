"""orchestrator.py — multi-provider LLM orchestrator for the writers' room.

Working providers (Sep 2026):
  - DeepSeek V4-flash     fast, $0
  - DeepSeek Reasoner     reasoning
  - Gemini 2.5-flash      long-form
  - DeepInfra             12+ models (Seed-2.0-mini, DeepSeek V3, Kimi K2.7, etc.)

Not working (no credit / auth):
  - ZAI (HTTP 429)
  - Anthropic Claude (HTTP 400)
  - Kimi direct (HTTP 401)

Cloudflare Workers AI is also available via writers_room_daemon_v3.run_voice.
"""
from __future__ import annotations

import json
import os
import sys
import time
import urllib.error
import urllib.request
from typing import Optional, Tuple

DEEPSEEK_URL = "https://api.deepseek.com/v1/chat/completions"
GEMINI_URL_TEMPLATE = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
DEEPINFRA_URL = "https://api.deepinfra.com/v1/openai/chat/completions"


def call_deepseek(prompt, system="", model="deepseek-chat", max_tokens=4096, temperature=0.7, timeout=60):
    body = {
        "model": model,
        "messages": [
            *([{"role": "system", "content": system}] if system else []),
            {"role": "user", "content": prompt},
        ],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    req = urllib.request.Request(
        DEEPSEEK_URL,
        data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['DEEPSEEK_TOKEN']}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            content = data.get("choices", [{}])[0].get("message", {}).get("content", "")
            reasoning = data.get("choices", [{}])[0].get("message", {}).get("reasoning_content", "")
            if reasoning and not content:
                return True, reasoning
            return True, content or reasoning
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_gemini(prompt, model="gemini-2.5-flash", max_tokens=4096, temperature=0.7, timeout=60):
    url = GEMINI_URL_TEMPLATE.format(model=model) + f"?key={os.environ['GEMINI_TOKEN']}"
    body = {
        "contents": [{"parts": [{"text": prompt}]}],
        "generationConfig": {"maxOutputTokens": max_tokens, "temperature": temperature},
    }
    req = urllib.request.Request(
        url, data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            text = data.get("candidates", [{}])[0].get("content", {}).get("parts", [{}])[0].get("text", "")
            return True, text
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


def call_deepinfra(prompt, model="ByteDance/Seed-2.0-mini", max_tokens=4096, temperature=0.7,
                   reasoning_effort=None, timeout=60):
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": temperature,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    req = urllib.request.Request(
        DEEPINFRA_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {os.environ['DEEPINFRA_TOKEN']}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
            msg = data.get("choices", [{}])[0].get("message", {})
            content = msg.get("content", "")
            reasoning = msg.get("reasoning_content", "")
            if not content and reasoning:
                return True, reasoning
            return True, content
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code}: {e.read().decode()[:200]}"
    except Exception as e:
        return False, f"ERR: {e}"


VOICES = {
    "code":     ("deepseek",  {"model": "deepseek-chat"}),
    "code2":    ("deepinfra", {"model": "deepseek-ai/DeepSeek-V3", "max_tokens": 4000}),
    "reason":   ("deepseek",  {"model": "deepseek-reasoner"}),
    "ideator":  ("deepinfra", {"model": "ByteDance/Seed-2.0-mini", "max_tokens": 4000}),
    "long":     ("gemini",    {"model": "gemini-2.5-flash"}),
    "long2":    ("deepinfra", {"model": "deepseek-ai/DeepSeek-V3", "max_tokens": 6000}),
    "kimi":     ("deepinfra", {"model": "moonshotai/Kimi-K2.7-Code", "max_tokens": 4000}),
    "gpt":      ("deepinfra", {"model": "openai/gpt-oss-120b", "max_tokens": 4000, "reasoning_effort": "low"}),
    "qwen":     ("deepinfra", {"model": "Qwen/Qwen3.5-27B", "max_tokens": 4000, "reasoning_effort": "low"}),
    "llama4":   ("deepinfra", {"model": "meta-llama/Llama-4-Scout-17B-16E-Instruct", "max_tokens": 4000}),
    "qwen3":    ("deepinfra", {"model": "Qwen/Qwen3-Next-80B-A3B-Instruct", "max_tokens": 4000}),
    "mistral":  ("deepinfra", {"model": "mistralai/Mistral-Small-24B-Instruct-2501", "max_tokens": 4000}),
    "seed-code": ("deepinfra", {"model": "ByteDance/Seed-2.0-code", "max_tokens": 4000}),
}


def call_voice(voice, prompt, max_tokens=4096):
    if voice not in VOICES:
        return "unknown", f"unknown voice: {voice}; available: {list(VOICES)}"
    provider, kwargs = VOICES[voice]
    kwargs = dict(kwargs)
    kwargs["max_tokens"] = max_tokens
    if provider == "deepseek":
        ok, content = call_deepseek(prompt, **kwargs)
    elif provider == "gemini":
        ok, content = call_gemini(prompt, **kwargs)
    elif provider == "deepinfra":
        ok, content = call_deepinfra(prompt, **kwargs)
    else:
        return "unknown", f"unknown provider: {provider}"
    if ok and content:
        return f"{provider}:{kwargs.get('model', voice)}", content
    return f"{provider}:{kwargs.get('model', voice)}:FAIL", content or ""


def call_best(prompt, role="long", max_tokens=4096):
    if role in VOICES:
        prov, content = call_voice(role, prompt, max_tokens=max_tokens)
        if not prov.endswith(":FAIL"):
            return prov, content
    for fallback in ["code2", "long2", "code", "long", "ideator"]:
        if fallback == role:
            continue
        prov, content = call_voice(fallback, prompt, max_tokens=max_tokens)
        if not prov.endswith(":FAIL"):
            return prov, content
    return "none", "all providers failed"


def ensemble(prompt, voices=None, max_tokens=2000):
    if voices is None:
        voices = ["ideator", "code2", "llama4", "qwen3"]
    results = []
    for v in voices:
        t0 = time.time()
        prov, content = call_voice(v, prompt, max_tokens=max_tokens)
        results.append((prov, content, time.time() - t0))
    return results


if __name__ == "__main__":
    print("Orchestrator v2 — multi-provider + DeepInfra + 12 voices")
    print()
    print("Quick smoke test:")
    for role in ["code", "ideator", "kimi", "qwen", "llama4", "qwen3", "mistral", "seed-code"]:
        prov, content = call_voice(role, "Reply with: ok", max_tokens=20)
        status = "OK" if not prov.endswith(":FAIL") else "X"
        print(f"  [{status}] {role:12s} {prov:60s} {content[:30]!r}")
