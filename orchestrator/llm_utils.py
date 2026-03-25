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


def safe_input_token_budget(cfg: dict, safety_margin: int = 2000) -> int:
    """
    모델 context_window 내에서 안전하게 사용 가능한 입력 토큰 예산 반환.

    context_window (yaml 설정) - max_tokens (출력) - safety_margin = 입력 예산
    yaml에 context_window가 없으면 기본 32000 사용 (보수적).

    예) context_window=131072, max_tokens=65536 → 입력 예산 = 63536
    """
    context_window = cfg.get("context_window", 32000)
    max_tokens = cfg.get("max_tokens", 1024)
    budget = context_window - max_tokens - safety_margin
    return max(budget, 4000)  # 최소 4000은 보장


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
    if not resp.ok:
        try:
            err_body = resp.json()
        except Exception:
            err_body = resp.text
        raise RuntimeError(
            f"[llm] API {resp.status_code} | max_tokens={max_tokens} | body: {err_body}"
        )
    resp.raise_for_status()
    if not use_stream:
        data = resp.json()
        choice = data["choices"][0]
        finish_reason = choice.get("finish_reason", "unknown")
        usage = data.get("usage", {})
        print(
            f"[llm] finish_reason={finish_reason} | "
            f"prompt_tokens={usage.get('prompt_tokens','?')} "
            f"completion_tokens={usage.get('completion_tokens','?')} "
            f"total={usage.get('total_tokens','?')} | "
            f"max_tokens_requested={max_tokens}"
        )
        if finish_reason == "length":
            import warnings
            warnings.warn(
                f"[llm] ⚠️  finish_reason=length: 출력이 max_tokens({max_tokens})에서 잘림. "
                "yaml의 max_tokens 값을 높이거나 --output-max-tokens를 늘리세요.",
                stacklevel=3,
            )
        return choice["message"]["content"]

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
