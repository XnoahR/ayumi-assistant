# SPDX-License-Identifier: AGPL-3.0-or-later
"""Tests for Ayumi-Assistant.

Run with:  python3 tests/test_ayumi.py

No pytest, no network, no Anki. `config.py` imports `aqt`, which only exists
inside Anki, so the pure helpers are lifted out of it with `ast`. Transport is
exercised against a local HTTP server that speaks both SSE dialects.
"""

from __future__ import annotations

import ast
import json
import os
import pathlib
import re
import sys
import tempfile
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from typing import Any

ADDON = pathlib.Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ADDON))

import markdown_lite  # noqa: E402
import providers  # noqa: E402

# --------------------------------------------------------------------------- #
# Load the aqt-free parts of config.py
# --------------------------------------------------------------------------- #

_WANTED = {
    "DEFAULT_PERSONA", "DEFAULT_SYSTEM_PROMPT", "LANGUAGE_PRESETS",
    "GENERIC_PRESET", "EXPLANATION_LANGUAGES", "PROVIDER_FIELDS", "KIND_DEFAULTS",
    "DEFAULT_PROVIDERS", "DEFAULTS", "KeyLookupError", "normalize_provider",
    "resolve_api_key", "_migrate_legacy", "build_system_prompt", "language_names",
    "explanation_language_names",
}
_keep = []
for _node in ast.parse((ADDON / "config.py").read_text()).body:
    _name = (getattr(_node, "name", None)
             or getattr(getattr(_node, "target", None), "id", None)
             or getattr(getattr(_node, "targets", [None])[0], "id", None))
    if _name in _WANTED:
        _keep.append(_node)
cfg_mod: dict[str, Any] = {
    "Any": Any, "copy": __import__("copy"), "json": json, "os": os,
    "pathlib": pathlib,
}
exec(compile(ast.Module(_keep, []), "<config>", "exec"), cfg_mod)

normalize_provider = cfg_mod["normalize_provider"]
resolve_api_key = cfg_mod["resolve_api_key"]
KeyLookupError = cfg_mod["KeyLookupError"]
migrate_legacy = cfg_mod["_migrate_legacy"]
build_system_prompt = cfg_mod["build_system_prompt"]
language_names = cfg_mod["language_names"]
explanation_language_names = cfg_mod["explanation_language_names"]
DEFAULTS = cfg_mod["DEFAULTS"]

failures: list[str] = []
CAPTURED: dict[str, Any] = {}


def check(name: str, got: Any, want: Any) -> None:
    ok = got == want
    print(f"{'PASS' if ok else 'FAIL'}  {name}")
    if not ok:
        print(f"        got:  {got!r}\n        want: {want!r}")
        failures.append(name)


def section(title: str) -> None:
    print(f"\n--- {title} ---")


# --------------------------------------------------------------------------- #
# Fake API server
# --------------------------------------------------------------------------- #

def _sse(*events: dict[str, Any]) -> bytes:
    return "".join(
        f"event: {e.get('type', 'message')}\ndata: {json.dumps(e)}\n\n" for e in events
    ).encode()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silence
        pass

    def do_POST(self):  # noqa: N802
        n = int(self.headers.get("content-length", 0))
        CAPTURED["path"] = self.path
        CAPTURED["headers"] = {k.lower(): v for k, v in self.headers.items()}
        CAPTURED["body"] = json.loads(self.rfile.read(n))

        if self.path.endswith("/v1/messages"):
            if CAPTURED["body"].get("model") == "boom":
                self.send_response(401)
                self.send_header("content-type", "application/json")
                self.end_headers()
                self.wfile.write(
                    json.dumps({"error": {"message": "invalid x-api-key"}}).encode())
                return
            payload = _sse(
                {"type": "content_block_start", "index": 0,
                 "content_block": {"type": "thinking"}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "text_delta", "text": "友達 "}},
                {"type": "content_block_delta", "index": 1,
                 "delta": {"type": "text_delta", "text": "(ともだち)"}},
                {"type": "message_delta", "delta": {"stop_reason": "end_turn"}},
            )
        elif self.path.endswith("/chat/completions"):
            payload = (b'data: {"choices":[{"delta":{"content":"hello "}}]}\n\n'
                       b'data: {"choices":[{"delta":{"content":"world"}}]}\n\n'
                       b"data: [DONE]\n\n")
        else:
            self.send_response(404)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("content-type", "text/event-stream")
        self.end_headers()
        self.wfile.write(payload)


server = HTTPServer(("127.0.0.1", 0), Handler)
BASE = f"http://127.0.0.1:{server.server_address[1]}"
threading.Thread(target=server.serve_forever, daemon=True).start()


def run(provider, key="k", system="sys", messages=None):
    out, status = [], []
    providers.stream_completion(
        provider, key, system, messages or [{"role": "user", "content": "hi"}],
        max_tokens=16000, timeout=10,
        on_text=out.append, on_status=status.append, should_stop=lambda: False,
    )
    return "".join(out), status


# --------------------------------------------------------------------------- #

section("provider normalization")
p = normalize_provider({"name": "X", "kind": "anthropic"})
check("anthropic base_url default", p["base_url"], "https://api.anthropic.com")
check("anthropic effort default", p["effort"], "low")
check("openai base_url default",
      normalize_provider({"kind": "openai"})["base_url"], "https://api.openai.com/v1")
check("unknown kind falls back to openai",
      normalize_provider({"kind": "zzz"})["kind"], "openai")
check("blank name gets placeholder", normalize_provider({}, 2)["name"], "Provider 3")
check("junk max_tokens coerced",
      normalize_provider({"max_tokens": "abc"})["max_tokens"], 0)
check("non-dict extra_headers dropped",
      normalize_provider({"extra_headers": 5})["extra_headers"], {})
check("unknown fields ignored", "wat" in normalize_provider({"wat": 1}), False)

section("key resolution")
check("literal key wins", resolve_api_key({"name": "a", "api_key": "lit"}), "lit")
os.environ["AYUMI_TEST_KEY"] = "from-env"
check("env var",
      resolve_api_key({"name": "a", "api_key_env": "AYUMI_TEST_KEY"}), "from-env")
try:
    resolve_api_key({"name": "a", "api_key_env": "AYUMI_MISSING"})
    check("missing env raises", False, True)
except KeyLookupError as e:
    check("missing env -> clear error", "is not set" in str(e), True)

with tempfile.TemporaryDirectory() as td:
    auth = pathlib.Path(td, "auth.json")
    auth.write_text(json.dumps({"openrouter": {"type": "api", "key": "sk-or-xyz"}}))
    base = {"name": "OR", "api_key_file": str(auth), "api_key_path": "openrouter.key"}
    check("dotted path into JSON file", resolve_api_key(base), "sk-or-xyz")
    try:
        resolve_api_key(dict(base, api_key_path="openrouter.nope"))
        check("bad path raises", False, True)
    except KeyLookupError as e:
        check("bad path lists available keys",
              "key" in str(e) and "Available at that level" in str(e), True)
    try:
        resolve_api_key({"name": "Z", "api_key_file": "/nope.json", "api_key_path": "a"})
        check("missing file raises", False, True)
    except KeyLookupError as e:
        check("missing file -> clear error", "not found" in str(e), True)
check("no key configured -> empty", resolve_api_key({"name": "a"}), "")

section("legacy config migration")
mig = migrate_legacy({
    "provider": "openai",
    "anthropic": {"api_key": "sk-ant", "model": "claude-opus-5"},
    "openai": {"api_key": "sk-oai"},
    "font_size": 20,
})
check("migrates to providers list", len(mig["providers"]), 2)
check("preserves keys", mig["providers"][0]["api_key"], "sk-ant")
check("assigns kinds", [q["kind"] for q in mig["providers"]], ["anthropic", "openai"])
check("keeps unrelated settings", mig["font_size"], 20)
check("old keys removed", "provider" in mig or "anthropic" in mig, False)
_new = {"providers": [{"name": "A"}], "active_provider": "A"}
check("new-style config untouched", migrate_legacy(_new), _new)

section("anthropic transport")
anth = normalize_provider({"name": "Anthropic", "kind": "anthropic", "base_url": BASE})
text, status = run(anth, key="sk-test")
check("streams text deltas", text, "友達 (ともだち)")
check("thinking surfaces as status", "Thinking…" in status, True)
body = CAPTURED["body"]
check("anthropic-version header",
      CAPTURED["headers"].get("anthropic-version"), "2023-06-01")
check("x-api-key header", CAPTURED["headers"].get("x-api-key"), "sk-test")
check("system hoisted to top level", body.get("system"), "sys")
check("effort sent", body.get("output_config"), {"effort": "low"})
check("no temperature (rejected by current models)", "temperature" in body, False)
check("no top_p/top_k", ("top_p" in body or "top_k" in body), False)
run(normalize_provider({"name": "a", "kind": "anthropic",
                        "base_url": BASE, "thinking": "off"}))
check("thinking:off -> disabled", CAPTURED["body"].get("thinking"), {"type": "disabled"})
run(normalize_provider({"name": "h", "kind": "anthropic", "base_url": BASE,
                        "model": "claude-haiku-4-5"}))
check("effort skipped for haiku", "output_config" in CAPTURED["body"], False)
run(normalize_provider({"name": "m", "kind": "anthropic", "base_url": BASE,
                        "max_tokens": 512}))
check("per-provider max_tokens override", CAPTURED["body"]["max_tokens"], 512)
try:
    run(anth, key="")
    check("missing key raises", False, True)
except providers.ProviderError as e:
    check("missing key names the provider", 'provider "Anthropic"' in str(e), True)
try:
    run(normalize_provider({"name": "b", "kind": "anthropic",
                            "base_url": BASE, "model": "boom"}))
    check("401 raises", False, True)
except providers.ProviderError as e:
    check("401 includes status", "HTTP 401" in str(e), True)
    check("401 includes API detail", "invalid x-api-key" in str(e), True)

section("openai-compatible transport")
oai = normalize_provider({"name": "OpenRouter", "kind": "openai", "base_url": BASE,
                          "extra_headers": {"X-Title": "Ayumi-Assistant"}})
text, _ = run(oai)
check("streams choices deltas", text, "hello world")
check("bearer auth", CAPTURED["headers"].get("authorization"), "Bearer k")
check("extra_headers sent", CAPTURED["headers"].get("x-title"), "Ayumi-Assistant")
check("system as message[0]", CAPTURED["body"]["messages"][0],
      {"role": "system", "content": "sys"})
try:
    run(normalize_provider({"name": "L", "kind": "openai",
                            "base_url": "http://localhost:1/v1"}), key="")
except providers.ProviderError as e:
    check("localhost needs no key", "No API key" not in str(e), True)

section("user-agent (Cloudflare 1010 regression)")
run(anth)
ua = CAPTURED["headers"].get("user-agent", "")
check("anthropic sends a real UA", ua.startswith("Ayumi-Assistant"), True)
check("UA is not urllib default", "Python-urllib" in ua, False)
run(oai)
check("openai sends a real UA",
      CAPTURED["headers"].get("user-agent", "").startswith("Ayumi-Assistant"), True)
run(normalize_provider({"name": "o", "kind": "openai", "base_url": BASE,
                        "extra_headers": {"User-Agent": "Custom/1.0"}}))
check("extra_headers can override UA", CAPTURED["headers"].get("user-agent"), "Custom/1.0")

section("cancellation")
out: list[str] = []
providers.stream_completion(anth, "k", "s", [{"role": "user", "content": "hi"}],
                            max_tokens=100, timeout=10, on_text=out.append,
                            on_status=lambda m: None, should_stop=lambda: True)
check("should_stop halts immediately", out, [])

section("prompt: language, persona, reply language")
JP_FORMAT = ("When asked about a word or phrase, give: the reading in hiragana "
             "(or katakana where appropriate), a short gloss in English, "
             "register/nuance worth knowing, and one natural example sentence "
             "translated into English. Mention pitch accent only if it is notable.")
jp = build_system_prompt(DEFAULTS)
check("Japanese answer-format clause unchanged", JP_FORMAT in jp, True)
check("length rules intact", "under about 120 words" in jp, True)
check("Spanish swaps in gender guidance",
      "gender and article" in
      build_system_prompt(dict(DEFAULTS, target_language="Spanish")), True)
check("Chinese swaps in pinyin",
      "pinyin" in build_system_prompt(dict(DEFAULTS, target_language="Chinese")), True)
check("unknown language falls back generically",
      "its pronunciation" in
      build_system_prompt(dict(DEFAULTS, target_language="Klingon")), True)
check("user prompt without placeholders passes through",
      build_system_prompt(dict(DEFAULTS, system_prompt="Just be terse.")),
      "Just be terse.")
check("bad placeholder does not crash",
      build_system_prompt(dict(DEFAULTS, system_prompt="Hi {nope}")), "Hi {nope}")

check("persona present by default", "Ayumi" in jp, True)
check("persona names the language", "teaches Japanese" in jp, True)
_off = build_system_prompt(dict(DEFAULTS, persona=""))
check("persona can be turned off", "Ayumi" not in _off, True)
check("no blank gap when persona off", _off[:1].strip() != "", True)
check("anti-narration guard present", "Never narrate your reasoning" in jp, True)
check("anti-narration guard survives persona off",
      "Never narrate your reasoning" in _off, True)

_id = build_system_prompt(dict(DEFAULTS, explanation_language="Bahasa Indonesia"))
check("reply language reaches the prompt", "in Bahasa Indonesia" in _id, True)
check("gloss uses the reply language", "gloss in Bahasa Indonesia" in _id, True)
check("persona speaks the reply language",
      "speaks to your student in Bahasa Indonesia" in _id, True)
check("target language unaffected", "teaches Japanese" in _id and "hiragana" in _id, True)
check("default reply language is English", "gloss in English" in jp, True)
_arts = [L for L in ("English", "Italian", "Arabic", "Indonesian")
         if re.search(rf"\ba {L}\b",
                      build_system_prompt(dict(DEFAULTS, explanation_language=L)))]
check("no 'a English' style article errors", _arts, [])

# A prompt saved before {explain_lang} existed must not silently swallow the
# reply-language setting — this bit a real user.
_legacy = "You are a concise {language}-language assistant.\n\nKeep answers short."
_leg = build_system_prompt(dict(DEFAULTS, system_prompt=_legacy,
                                explanation_language="Bahasa Indonesia"))
check("legacy prompt still honours reply language",
      "Write to the student in Bahasa Indonesia" in _leg, True)
check("legacy prompt keeps its own text", "Keep answers short." in _leg, True)
check("legacy prompt + English adds nothing",
      "Write to the student in English" in
      build_system_prompt(dict(DEFAULTS, system_prompt=_legacy,
                               explanation_language="English")), False)
check("modern prompt is not double-instructed",
      _id.count("Write to the student in Bahasa Indonesia"), 1)

check("language list sorted", language_names(DEFAULTS)[:2], ["Arabic", "Chinese"])
check("custom language appended",
      "Klingon" in language_names(dict(DEFAULTS, target_language="Klingon")), True)
check("Bahasa Indonesia offered",
      "Bahasa Indonesia" in explanation_language_names(DEFAULTS), True)
check("custom reply language kept",
      "Tagalog" in explanation_language_names(
          dict(DEFAULTS, explanation_language="Tagalog")), True)

section("markdown")
r = markdown_lite.render
check("html from model escaped", "<script>" not in r("<script>alert(1)</script>"), True)
check("bold", r("**hi**"), "<p><b>hi</b></p>")
check("inline code not re-parsed", r("`**x**`"), "<p><code>**x**</code></p>")
check("bullets", r("- a\n- b"), "<ul><li>a</li><li>b</li></ul>")
check("fenced code", r("```py\nx=1\n```"), '<pre class="code">x=1</pre>')
check("link", r("[a](https://x.dev)"), '<p><a href="https://x.dev">a</a></p>')
check("partial stream safe", r("**par"), "<p>**par</p>")
check("japanese preserved", r("友達（ともだち）"), "<p>友達（ともだち）</p>")
check("table renders as <table>", "<table" in r("| a |\n|---|\n| 1 |"), True)
check("no raw pipes left", "|" not in r("| a | b |\n|---|---|\n| 1 | 2 |"), True)
check("alignment :-: parsed", 'align="center"' in r("| a |\n|:-:|\n| 1 |"), True)
check("ragged row padded", r("| a | b |\n|---|---|\n| 1 |").count("<td"), 2)
check("html in cell escaped",
      "&lt;script&gt;" in r("| x |\n|---|\n| <script>bad</script> |"), True)
check("mid-stream header-only table valid", r("| a |\n|---|").endswith("</table>"), True)
check("HR after pipe line stays HR", "<hr>" in r("has | pipe\n---\ntext"), True)
check("prose pipes not a table", r("Use a | b here."), "<p>Use a | b here.</p>")

section("shipped config.json")
shipped = json.loads((ADDON / "config.json").read_text())
check("top-level keys match code defaults", set(shipped), set(DEFAULTS))
check("providers normalize cleanly",
      [normalize_provider(q, i)["name"] for i, q in enumerate(shipped["providers"])],
      ["OpenRouter", "OpenAI", "Anthropic", "Google Gemini", "DeepSeek",
       "Ollama (local, free)"])
# OPEN SOURCE: no key may ever ship.
check("NO api keys in shipped config",
      [q["name"] for q in shipped["providers"] if q.get("api_key")], [])
check("no key-ish string in config.json",
      bool(re.search(r"sk-[A-Za-z0-9_-]{20,}|nvapi-|gsk_[A-Za-z0-9]{20,}",
                     (ADDON / "config.json").read_text())), False)
check("no secrets in config.py",
      all(not q.get("api_key") for q in DEFAULTS["providers"]), True)
check("no shipped entry relies on api_key_file",
      any(q.get("api_key_file") for q in shipped["providers"]), False)
check("active_provider resolves",
      shipped["active_provider"] in [q["name"] for q in shipped["providers"]], True)
check("target_language default", shipped["target_language"], "Japanese")
check("explanation_language default", shipped["explanation_language"], "English")
check("persona shipped", "Ayumi" in shipped["persona"], True)
check("persona bans padding",
      all(x in shipped["persona"] for x in ("No pet names", "no emotes")), True)
check("quick prompts do not hardcode English",
      any("English" in q["prompt"] for q in shipped["quick_prompts"]), False)

server.shutdown()
print("\n" + "=" * 52)
print("FAILURES: " + ", ".join(failures) if failures else "ALL CHECKS PASSED")
sys.exit(1 if failures else 0)
