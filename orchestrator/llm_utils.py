from __future__ import annotations

import os
from pathlib import Path

import requests
import yaml


def load_model_config(path: Path | None) -> dict | None:
    if not path:
        return None
    data = yaml.safe_load(path.read_text())
    api_key = data.get("api_key") or os.getenv("MODEL_API_KEY", "")
    data["api_key"] = api_key
    data.setdefault("provider", "openai")
    data.setdefault("max_tokens", 1024)
    data.setdefault("temperature", 0.2)
    if data.get("anthropic_version"):
        data["anthropic_version"] = str(data["anthropic_version"])
    return data


def _call_openai(prompt: str, cfg: dict, system_prompt: str) -> str:
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": cfg.get("temperature", 0.2),
        "max_tokens": cfg.get("max_tokens", 1024),
    }
    resp = requests.post(
        cfg["endpoint"].rstrip("/") + "/chat/completions",
        json=payload,
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["choices"][0]["message"]["content"]


def _call_claude(prompt: str, cfg: dict, system_prompt: str) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg.get("api_key", ""),
        "anthropic-version": cfg.get("anthropic_version", "2023-06-01"),
    }
    payload = {
        "model": cfg["model"],
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
        "max_tokens": cfg.get("max_tokens", 1024),
        "temperature": cfg.get("temperature", 0.2),
    }
    resp = requests.post(
        cfg["endpoint"].rstrip("/") + "/v1/messages",
        json=payload,
        headers=headers,
        timeout=60,
    )
    resp.raise_for_status()
    data = resp.json()
    # Claude responses are arrays of content blocks; pick first text block
    for block in data.get("content", []):
        if block.get("type") == "text":
            return block.get("text", "")
    return ""


def call_llm(prompt: str, cfg: dict, system_prompt: str = "You are an RTL design assistant.") -> str:
    provider = cfg.get("provider", "openai").lower()
    if provider == "claude":
        return _call_claude(prompt, cfg, system_prompt)
    return _call_openai(prompt, cfg, system_prompt)
