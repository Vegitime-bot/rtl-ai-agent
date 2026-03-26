from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import requests
import yaml


# ── LLM 대화 로깅 ────────────────────────────────
# yaml에 llm_log: "logs/llm.jsonl" 설정 시 활성화
# 각 요청/응답을 JSONL 형식으로 append

def _log_llm(cfg: dict, entry: dict) -> None:
    """cfg에 llm_log 경로가 있으면 JSONL로 append."""
    log_path = cfg.get("llm_log")
    if not log_path:
        return
    path = Path(log_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


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
    import time

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
    url = cfg["endpoint"].rstrip("/") + "/chat/completions"

    # 429 Rate Limit 자동 재시도 (최대 5회, 지수 backoff)
    max_rate_retries = cfg.get("rate_limit_retries", 5)
    rate_retry_base = cfg.get("rate_limit_retry_base", 60)  # 기본 대기 60초

    for attempt in range(max_rate_retries + 1):
        resp = requests.post(url, json=payload, headers=headers, timeout=timeout, stream=use_stream)
        if resp.status_code == 429:
            if attempt < max_rate_retries:
                # Retry-After 헤더가 있으면 우선 사용, 없으면 지수 backoff
                retry_after = resp.headers.get("Retry-After")
                wait = int(retry_after) if retry_after and retry_after.isdigit() else rate_retry_base * (2 ** attempt)
                print(f"[llm] 429 Rate Limit — {wait}초 후 재시도 ({attempt + 1}/{max_rate_retries})...")
                time.sleep(wait)
                continue
        break  # 429 아니면 루프 탈출

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
        content = choice["message"]["content"] or ""
        _log_llm(cfg, {
            "ts": datetime.utcnow().isoformat(),
            "provider": "openai",
            "model": cfg.get("model"),
            "prompt_tokens": usage.get("prompt_tokens"),
            "completion_tokens": usage.get("completion_tokens"),
            "finish_reason": finish_reason,
            "max_tokens_requested": max_tokens,
            "prompt": prompt[:500],   # 앞 500자만 기록 (로그 크기 제한)
            "response": content[:500],
        })
        return content

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
        content = ""
        for block in data.get("content", []):
            if block.get("type") == "text":
                content = block.get("text", "")
                break
        usage = data.get("usage", {})
        _log_llm(cfg, {
            "ts": datetime.utcnow().isoformat(),
            "provider": "claude",
            "model": cfg.get("model"),
            "prompt_tokens": usage.get("input_tokens"),
            "completion_tokens": usage.get("output_tokens"),
            "finish_reason": data.get("stop_reason"),
            "max_tokens_requested": max_tokens,
            "prompt": prompt[:500],
            "response": content[:500],
        })
        return content

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


def _hard_trim_prompt(prompt: str, max_input_tokens: int) -> str:
    """
    프롬프트가 max_input_tokens를 초과하면 뒷부분을 잘라 반드시 맞춤.
    Requirements 섹션은 보존하기 위해 앞부분(RTL/algo)을 우선 자름.
    """
    char_limit = max_input_tokens * 4  # 4자 ≈ 1토큰
    if len(prompt) <= char_limit:
        return prompt

    # Requirements 섹션 보존: 마지막 === Requirements === 이후를 분리
    req_marker = "=== Requirements ==="
    req_idx = prompt.rfind(req_marker)
    if req_idx != -1:
        body = prompt[:req_idx]
        tail = prompt[req_idx:]
        tail_chars = len(tail)
        body_limit = char_limit - tail_chars - 100  # 여유 100자
        if body_limit > 0:
            trimmed_body = body[:body_limit] + "\n... [prompt trimmed to fit context window]\n"
            result = trimmed_body + tail
            trimmed_tokens = (len(prompt) - len(result)) // 4
            import warnings
            warnings.warn(
                f"[llm] ⚠️  prompt hard-trimmed: {trimmed_tokens} tokens removed to fit context window",
                stacklevel=4,
            )
            return result

    # fallback: 단순 앞부분 유지
    import warnings
    warnings.warn(
        f"[llm] ⚠️  prompt hard-trimmed (simple): {(len(prompt) - char_limit) // 4} tokens removed",
        stacklevel=4,
    )
    return prompt[:char_limit]


def call_llm(
    prompt: str,
    cfg: dict,
    system_prompt: str = "You are an RTL design assistant.",
    max_tokens: int | None = None,
) -> str:
    effective_max_tokens = max_tokens if max_tokens is not None else cfg.get("max_tokens", 1024)

    # 하드 가드: context_window 설정 있으면 반드시 맞춤
    context_window = cfg.get("context_window")
    if context_window:
        max_input = context_window - effective_max_tokens - 500  # 500토큰 안전 마진
        prompt = _hard_trim_prompt(prompt, max_input)

    provider = cfg.get("provider", "openai").lower()
    if provider == "claude":
        return _call_claude(prompt, cfg, system_prompt, effective_max_tokens)
    return _call_openai(prompt, cfg, system_prompt, effective_max_tokens)
