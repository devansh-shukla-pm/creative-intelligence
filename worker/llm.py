"""OpenRouter client. Ports the retry and timeout behaviour of the creative extraction dashboard:
 - exponential backoff on 429/5xx/network errors
 - a hard wall-clock deadline per attempt (a stuck request is abandoned, then retried)
 - 'regenerate' loop when the call succeeds but the JSON is malformed
"""
from __future__ import annotations
import json, re, threading, time, concurrent.futures
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
    """One or more OpenRouter keys. Calls are spread round-robin; a key that is rate limited rests for a while and a key that is
    rejected (invalid, out of credit) is dropped while others remain."""
    COOLDOWN_S = 20.0

    def __init__(self, api_key=None):
        keys = [api_key] if api_key else list(config.OPENROUTER_API_KEYS)
        if not keys:
            raise LLMError("OPENROUTER_API_KEY is not set")
        self.keys = keys
        self._rest = {}                   # key -> time it may be used again
        self._dead = set()
        self._i = 0
        self._lock = threading.Lock()

    @property
    def n_keys(self):
        return max(1, len(self.keys) - len(self._dead))

    def _take_key(self):
        with self._lock:
            live = [k for k in self.keys if k not in self._dead] or list(self.keys)
            now = time.time()
            for _ in range(len(live)):
                k = live[self._i % len(live)]; self._i += 1
                if self._rest.get(k, 0) <= now: return k
            return min(live, key=lambda k: self._rest.get(k, 0))      # all resting: take the one that rests least

    def _report_key(self, key, status):
        with self._lock:
            if status == 429: self._rest[key] = time.time() + self.COOLDOWN_S
            elif status in (401, 402, 403) and len([k for k in self.keys if k not in self._dead]) > 1:
                self._dead.add(key); print(f"[llm] key ...{key[-4:]} rejected ({status}); using the others", flush=True)

    def _post(self, body, timeout_s):
        key = self._take_key()
        def go():
            r = requests.post(config.OPENROUTER_URL, json=body, timeout=(10, timeout_s),
                              headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
            if r.status_code != 200:
                raise LLMError(f"OpenRouter {r.status_code}: {r.text[:300]}", r.status_code)
            return r.json()
        try:
            return _with_deadline(go, timeout_s)
        except LLMError as e:
            if e.status: self._report_key(key, e.status)
            raise

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
                retry = e.status is None or e.status in RETRYABLE or (e.status in (401, 402, 403) and self.n_keys > 0 and len(self.keys) > 1)   # timeouts have no status; a rejected key is retried on another
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
