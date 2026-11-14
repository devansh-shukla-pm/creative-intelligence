"""OpenRouter client. Ports the retry and timeout behaviour of the creative extraction dashboard:
 - exponential backoff on 429/5xx/network errors
 - a hard wall-clock deadline per attempt (a stuck request is abandoned, then retried)
 - 'regenerate' loop when the call succeeds but the JSON is malformed
"""
from __future__ import annotations
import json, re, time, concurrent.futures
import requests
from . import config

RETRYABLE = {429, 500, 502, 503, 504}
API_RETRIES = 3
BACKOFF_S = 2.0
PARSE_RETRIES = 3

class LLMError(Exception):
    def __init__(self, msg, status=None):
        super().__init__(msg); self.status = status

_deadline_pool = concurrent.futures.ThreadPoolExecutor(max_workers=64)

def _with_deadline(fn, seconds):
    fut = _deadline_pool.submit(fn)
    try:
        return fut.result(timeout=seconds)
    except concurrent.futures.TimeoutError:
        raise LLMError(f"Request timed out after {seconds}s")

def parse_json(text: str) -> dict:
    """Accepts plain JSON, ```json fences, or JSON surrounded by chatter."""
    cleaned = re.sub(r"```json\n?|```\n?", "", text or "").strip()
    a, b = cleaned.find("{"), cleaned.rfind("}")
    if a != -1 and b > a:
        cleaned = cleaned[a:b + 1]
    return json.loads(cleaned)

class LLM:
    def __init__(self, api_key=None):
        self.key = api_key or config.OPENROUTER_API_KEY
        if not self.key:
            raise LLMError("OPENROUTER_API_KEY is not set")

    def _post(self, body, timeout_s):
        def go():
            r = requests.post(config.OPENROUTER_URL, json=body, timeout=(10, timeout_s),
                              headers={"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"})
            if r.status_code != 200:
                raise LLMError(f"OpenRouter {r.status_code}: {r.text[:300]}", r.status_code)
            return r.json()
        return _with_deadline(go, timeout_s)

    def chat(self, model, content, max_tokens=4096, timeout_s=None, system=None) -> str:
        """content: str or list of OpenAI-style parts. Returns the model's text."""
        parts = [{"type": "text", "text": content}] if isinstance(content, str) else content
        messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": parts}]
        body = {"model": model, "messages": messages, "temperature": 0.1, "max_tokens": max_tokens,
                "response_format": {"type": "json_object"}}
        timeout_s = timeout_s or config.LLM_TIMEOUT_S
        last = None
        for attempt in range(API_RETRIES):
            try:
                data = self._post(body, timeout_s)
                return (data.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
            except LLMError as e:
                last = e
                retry = e.status is None or e.status in RETRYABLE      # timeouts and network errors have no status
                if not retry or attempt == API_RETRIES - 1:
                    raise
                time.sleep(BACKOFF_S * (2 ** attempt))
            except requests.RequestException as e:
                last = LLMError(f"network error: {e}")
                if attempt == API_RETRIES - 1:
                    raise last
                time.sleep(BACKOFF_S * (2 ** attempt))
        raise last

    def chat_json(self, model, content, max_tokens=4096, label="", timeout_s=None, system=None) -> dict:
        last = None
        for _ in range(PARSE_RETRIES):
            text = self.chat(model, content, max_tokens, timeout_s, system)
            try:
                return parse_json(text)
            except json.JSONDecodeError as e:     # 200 OK but malformed: regenerate
                last = e
        raise LLMError(f"{label or 'call'}: malformed JSON after {PARSE_RETRIES} attempts ({last})")

def get_llm():
    if config.MOCK_LLM:
        from .mock import MockLLM
        return MockLLM()
    return LLM()
