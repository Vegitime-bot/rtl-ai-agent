from __future__ import annotations

import json
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


def _estimate_timeout(max_tokens: int, base: int = 60) -> int:
    """max_tokens 기반으로 timeout(초) 동적 계산. 토큰 10개당 약 1초 여유."""
    return max(base, base + max_tokens // 10)


def _call_openai(prompt: str, cfg: dict, system_prompt: str, max_tokens: int) -> str:
    headers = {"Content-Type": "application/json"}
    if cfg.get("api_key"):
        headers["Authorization"] = f"Bearer {cfg['api_key']}"
    # stream 기본값 False — 사내망/비표준 모델에서 SSE 파싱 실패로 조용히 끊기는 현상 방지
    use_stream = cfg.get("stream", False)
    payload = {
        "model": cfg["model"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ],
        "temperature": cfg.get("temperature", 0.2),
        "max_tokens": max_tokens,
        "stream": use_stream,
    }
    timeout = cfg.get("timeout", _estimate_timeout(max_tokens))
    resp = requests.post(
        cfg["endpoint"].rstrip("/") + "/chat/completions",
        json=payload,
        headers=headers,
        timeout=timeout,
        stream=use_stream,
    )
    resp.raise_for_status()
    if not use_stream:
        return resp.json()["choices"][0]["message"]["content"]

    chunks: list[str] = []
    for line in resp.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        if data_str == "[DONE]":
            break
        try:
            obj = json.loads(data_str)
            delta = obj["choices"][0].get("delta", {})
            content = delta.get("content")
            if content:
                chunks.append(content)
        except (KeyError, json.JSONDecodeError):
            pass
    return "".join(chunks)


def _call_claude(prompt: str, cfg: dict, system_prompt: str, max_tokens: int) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": cfg.get("api_key", ""),
        "anthropic-version": cfg.get("anthropic_version", "2023-06-01"),
    }
    use_stream = cfg.get("stream", False)
    payload = {
        "model": cfg["model"],
        "system": system_prompt,
        "messages": [
            {"role": "user", "content": [{"type": "text", "text": prompt}]},
        ],
        "max_tokens": max_tokens,
        "temperature": cfg.get("temperature", 0.2),
        "stream": use_stream,
    }
    timeout = cfg.get("timeout", _estimate_timeout(max_tokens))
    resp = requests.post(
        cfg["endpoint"].rstrip("/").removesuffix("/v1") + "/v1/messages",
        json=payload,
        headers=headers,
        timeout=timeout,
        stream=use_stream,
    )
    resp.raise_for_status()
    if not use_stream:
        data = resp.json()
        for block in data.get("content", []):
            if block.get("type") == "text":
                return block.get("text", "")
        return ""

    chunks: list[str] = []
    for line in resp.iter_lines():
        if not line:
            continue
        if isinstance(line, bytes):
            line = line.decode("utf-8")
        if not line.startswith("data:"):
            continue
        data_str = line[5:].strip()
        try:
            obj = json.loads(data_str)
            if obj.get("type") == "content_block_delta":
                delta = obj.get("delta", {})
                if delta.get("type") == "text_delta":
                    chunks.append(delta.get("text", ""))
        except json.JSONDecodeError:
            pass
    return "".join(chunks)


def call_llm(
    prompt: str,
    cfg: dict,
    system_prompt: str = "You are an RTL design assistant.",
    max_tokens: int | None = None,
) -> str:
    effective_max_tokens = max_tokens if max_tokens is not None else cfg.get("max_tokens", 1024)
    provider = cfg.get("provider", "openai").lower()
    if provider == "claude":
        return _call_claude(prompt, cfg, system_prompt, effective_max_tokens)
    return _call_openai(prompt, cfg, system_prompt, effective_max_tokens)
