# SPDX-License-Identifier: AGPL-3.0-or-later
from __future__ import annotations

import copy
import json
import os
import pathlib
from typing import Any

from aqt import mw

ADDON_VERSION = "0.4.0"
ADDON_PACKAGE = __name__.split(".")[0]

# Who Ayumi is. Warmth has to live in the tone, not in extra words — a chatty
# tutor would wreck the short answer format, so the padding bans are explicit.
DEFAULT_PERSONA = (
    "You are Ayumi, a warm and patient woman who teaches {language} and speaks "
    "to your student in {explain_lang}. You care "
    "that your student genuinely understands, and your manner is gentle and "
    "unhurried — never stern, never gushing.\n\n"
    "Your warmth shows in how clearly you explain, not in extra words. No pet "
    "names, no emotes or roleplayed actions, no praise for routine questions, "
    "no restating the question back. When something is genuinely difficult, or "
    "the student sounds stuck or discouraged, close with one short encouraging "
    "line — otherwise leave it off. Correct mistakes kindly and without fuss."
)

# The prompt is a template so the answer format stays identical across
# languages while the language-specific parts swap in. {persona}, {language},
# {reading} and {extra} are filled in by build_system_prompt().
DEFAULT_SYSTEM_PROMPT = (
    "{persona}\n\n"
    "You are embedded in Anki as a study assistant. The student is an "
    "intermediate learner doing immersion-based study.\n\n"
    "Write to the student in {explain_lang}. Keep {language} words, readings "
    "and example sentences in {language}; everything you say *about* them is "
    "in {explain_lang}.\n\n"
    "When asked about a word or phrase, give: {reading}, a short gloss in "
    "{explain_lang}, register/nuance worth knowing, and one natural example "
    "sentence translated into {explain_lang}.{extra}\n\n"
    "Keep answers under about 120 words unless the student asks to go deeper. "
    "Answer directly with no preamble. Use short markdown; avoid headings for "
    "short answers.\n\n"
    "Reply with the finished answer only. Never narrate your reasoning, your "
    "plan, or how you are following these instructions; never write drafts, "
    "self-commentary, or notes to yourself. The student sees your reply "
    "verbatim."
)

# What counts as "the reading" differs by language. Anything not listed here
# still works — it just falls back to GENERIC_PRESET.
LANGUAGE_PRESETS: dict[str, dict[str, str]] = {
    "Japanese": {
        "reading": "the reading in hiragana (or katakana where appropriate)",
        "extra": " Mention pitch accent only if it is notable.",
    },
    "Chinese": {
        "reading": "the pinyin with tone marks",
        "extra": " Note the traditional form when it differs from the simplified one.",
    },
    "Korean": {
        "reading": "the hangul and a romanization",
        "extra": " Note the speech level (formal/polite/casual) where it matters.",
    },
    "English": {
        "reading": "the IPA pronunciation",
        "extra": " Note whether usage differs between British and American English.",
    },
    "Spanish": {
        "reading": "the pronunciation, plus the gender and article for nouns",
        "extra": " Note where usage differs between Spain and Latin America.",
    },
    "French": {
        "reading": "the IPA pronunciation, plus the gender and article for nouns",
        "extra": " Flag any liaison or silent letters worth knowing.",
    },
    "German": {
        "reading": "the pronunciation, plus the gender and plural for nouns",
        "extra": " Flag separable verbs and their prefixes.",
    },
    "Italian": {
        "reading": "the pronunciation, plus the gender and article for nouns",
        "extra": " Mark the stressed syllable when it is irregular.",
    },
    "Russian": {
        "reading": "the Cyrillic with the stressed vowel marked, plus a romanization",
        "extra": " Note the aspect for verbs and the case a preposition governs.",
    },
    "Arabic": {
        "reading": "the vocalised form and a romanization",
        "extra": " Give the root consonants and the verb form where relevant.",
    },
}

GENERIC_PRESET = {"reading": "its pronunciation", "extra": ""}

# The language Ayumi *writes in* — separate from the one being studied. The
# dropdown is editable, so anything not listed here still works.
EXPLANATION_LANGUAGES: list[str] = [
    "English",
    "Bahasa Indonesia",
    "Bahasa Melayu",
    "Chinese",
    "Filipino",
    "French",
    "German",
    "Japanese",
    "Korean",
    "Portuguese",
    "Russian",
    "Spanish",
    "Thai",
    "Vietnamese",
]

# Every field a provider entry may carry, with its fallback.
PROVIDER_FIELDS: dict[str, Any] = {
    "name": "",
    "kind": "openai",
    "model": "",
    "base_url": "",
    "api_key": "",
    "api_key_env": "",
    "api_key_file": "",
    "api_key_path": "",
    "effort": "",
    "thinking": "default",
    "max_tokens": 0,
    "extra_headers": {},
}

KIND_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": {
        "base_url": "https://api.anthropic.com",
        "model": "claude-opus-5",
        "effort": "low",
    },
    "openai": {
        "base_url": "https://api.openai.com/v1",
        "model": "gpt-4o-mini",
        "effort": "",
    },
}

DEFAULT_PROVIDERS: list[dict[str, Any]] = [
    # No API keys ship with the add-on — every user supplies their own.
    # NOTE: `api_key_file` is unusable on the Flatpak build of Anki (its sandbox
    # cannot read paths outside ~/.var/app/net.ankiweb.Anki), so keys go inline.
    {
        "name": "OpenRouter",
        "kind": "openai",
        "model": "anthropic/claude-haiku-4.5",
        "base_url": "https://openrouter.ai/api/v1",
        "api_key": "",
        "extra_headers": {"X-Title": "Ayumi-Assistant"},
    },
    {
        "name": "OpenAI",
        "kind": "openai",
        "model": "gpt-4o-mini",
        "base_url": "https://api.openai.com/v1",
        "api_key": "",
    },
    {
        "name": "Anthropic",
        "kind": "anthropic",
        "model": "claude-haiku-4-5",
        "base_url": "https://api.anthropic.com",
        "api_key": "",
        "effort": "",
        "thinking": "default",
    },
    {
        "name": "Google Gemini",
        "kind": "openai",
        "model": "gemini-2.5-flash",
        "base_url": "https://generativelanguage.googleapis.com/v1beta/openai",
        "api_key": "",
    },
    {
        "name": "DeepSeek",
        "kind": "openai",
        "model": "deepseek-chat",
        "base_url": "https://api.deepseek.com/v1",
        "api_key": "",
    },
    {
        "name": "Ollama (local, free)",
        "kind": "openai",
        "model": "qwen2.5:14b",
        "base_url": "http://localhost:11434/v1",
        "api_key": "",
    },
]

DEFAULTS: dict[str, Any] = {
    "active_provider": "OpenRouter",
    "providers": DEFAULT_PROVIDERS,
    "max_tokens": 16000,
    "timeout_seconds": 120,
    "target_language": "Japanese",
    "explanation_language": "English",
    "explanation_languages": EXPLANATION_LANGUAGES,
    "persona": DEFAULT_PERSONA,
    "system_prompt": DEFAULT_SYSTEM_PROMPT,
    "language_presets": LANGUAGE_PRESETS,
    "send_card_context": True,
    "max_context_chars": 1200,
    "max_history_turns": 12,
    "shortcut": "Ctrl+Shift+A",
    "focus_input_on_open": True,
    "show_on_startup": True,
    "font_family": "",
    "font_size": 14,
    "quick_prompts": [
        {"label": "Explain", "prompt": "Explain {word}."},
        {
            "label": "Examples",
            "prompt": "Give me three natural example sentences using {word}, "
            "with translations.",
        },
        {
            "label": "Nuance",
            "prompt": "What is the nuance and register of {word}, and how does it "
            "differ from its closest synonyms?",
        },
        {
            "label": "Breakdown",
            "prompt": "Break {word} down into its parts — characters, roots, or "
            "components — with their meanings, plus a couple of other common "
            "words that share them.",
        },
    ],
}


class KeyLookupError(Exception):
    """A provider's api_key_file / api_key_env could not be resolved."""


def _merge(base: dict[str, Any], overlay: Any) -> dict[str, Any]:
    """Overlay user config onto defaults. Lists are replaced, not merged."""
    if not isinstance(overlay, dict):
        return base

    for key, value in overlay.items():
        if key not in base:
            continue
        if isinstance(base[key], dict) and isinstance(value, dict):
            _merge(base[key], value)
        elif value is not None:
            base[key] = value

    return base


def _migrate_legacy(raw: dict[str, Any]) -> dict[str, Any]:
    """Convert the old provider/anthropic/openai shape into a providers list."""
    if "providers" in raw or "provider" not in raw:
        return raw

    raw = copy.deepcopy(raw)
    providers: list[dict[str, Any]] = []

    legacy_anthropic = raw.pop("anthropic", None)
    if isinstance(legacy_anthropic, dict):
        providers.append({"name": "Anthropic", "kind": "anthropic", **legacy_anthropic})

    legacy_openai = raw.pop("openai", None)
    if isinstance(legacy_openai, dict):
        providers.append({"name": "OpenAI", "kind": "openai", **legacy_openai})

    old = str(raw.pop("provider", "") or "").strip().lower()
    raw["active_provider"] = "Anthropic" if old == "anthropic" else "OpenAI"
    if providers:
        raw["providers"] = providers
    return raw


def normalize_provider(raw: Any, index: int = 0) -> dict[str, Any]:
    """Fill in a provider entry's missing fields from its kind's defaults."""
    entry = copy.deepcopy(PROVIDER_FIELDS)
    if isinstance(raw, dict):
        for key, value in raw.items():
            if key in entry and value is not None:
                entry[key] = value

    kind = str(entry["kind"]).strip().lower()
    entry["kind"] = kind if kind in KIND_DEFAULTS else "openai"

    kind_defaults = KIND_DEFAULTS[entry["kind"]]
    for key, fallback in kind_defaults.items():
        if not str(entry.get(key) or "").strip():
            entry[key] = fallback

    entry["name"] = str(entry["name"]).strip() or f"Provider {index + 1}"

    if not isinstance(entry["extra_headers"], dict):
        entry["extra_headers"] = {}

    try:
        entry["max_tokens"] = int(entry["max_tokens"])
    except (TypeError, ValueError):
        entry["max_tokens"] = 0

    return entry


def load_config() -> dict[str, Any]:
    raw = _migrate_legacy(mw.addonManager.getConfig(ADDON_PACKAGE) or {})
    cfg = _merge(copy.deepcopy(DEFAULTS), raw)

    for key, fallback in (
        ("max_tokens", DEFAULTS["max_tokens"]),
        ("timeout_seconds", DEFAULTS["timeout_seconds"]),
        ("max_context_chars", DEFAULTS["max_context_chars"]),
        ("max_history_turns", DEFAULTS["max_history_turns"]),
        ("font_size", DEFAULTS["font_size"]),
    ):
        try:
            cfg[key] = int(cfg[key])
        except (TypeError, ValueError):
            cfg[key] = fallback

    entries = cfg.get("providers")
    if not isinstance(entries, list) or not entries:
        entries = copy.deepcopy(DEFAULT_PROVIDERS)
    cfg["providers"] = [normalize_provider(e, i) for i, e in enumerate(entries)]

    return cfg


def explanation_language_names(cfg: dict[str, Any]) -> list[str]:
    """Reply languages offered, with the current one always present."""
    names = list(cfg.get("explanation_languages") or EXPLANATION_LANGUAGES)
    current = str(cfg.get("explanation_language") or "").strip()
    if current and current not in names:
        names.insert(0, current)
    return names


def save_explanation_language(language: str) -> None:
    raw = mw.addonManager.getConfig(ADDON_PACKAGE) or {}
    raw["explanation_language"] = language
    mw.addonManager.writeConfig(ADDON_PACKAGE, raw)


def language_names(cfg: dict[str, Any]) -> list[str]:
    """Languages offered in the dropdown, with the current one always present."""
    names = sorted(cfg.get("language_presets") or {})
    current = str(cfg.get("target_language") or "").strip()
    if current and current not in names:
        names.append(current)
    return names


def save_target_language(language: str) -> None:
    raw = mw.addonManager.getConfig(ADDON_PACKAGE) or {}
    raw["target_language"] = language
    mw.addonManager.writeConfig(ADDON_PACKAGE, raw)


def build_system_prompt(cfg: dict[str, Any]) -> str:
    """Fill the prompt template for the configured language.

    A user who rewrites `system_prompt` without the placeholders still gets
    exactly what they typed — formatting failures fall back to the raw text.
    """
    template = str(cfg.get("system_prompt") or "")
    language = str(cfg.get("target_language") or "").strip() or "target"

    presets = cfg.get("language_presets") or {}
    preset = presets.get(language)
    if not isinstance(preset, dict):
        preset = GENERIC_PRESET

    # The persona is its own template so it can name the language too. Clearing
    # `persona` turns the character off and leaves a plain, neutral assistant.
    explain_lang = str(cfg.get("explanation_language") or "").strip() or "English"

    persona = str(cfg.get("persona") or "")
    try:
        persona = persona.format(language=language, explain_lang=explain_lang)
    except (KeyError, IndexError, ValueError):
        pass

    try:
        filled = template.format(
            persona=persona,
            language=language,
            explain_lang=explain_lang,
            reading=preset.get("reading", GENERIC_PRESET["reading"]),
            extra=preset.get("extra", ""),
        )
    except (KeyError, IndexError, ValueError):
        return template

    # An empty persona would otherwise leave a blank gap at the top.
    return filled.strip()


def provider_names(cfg: dict[str, Any]) -> list[str]:
    return [p["name"] for p in cfg["providers"]]


def active_provider(cfg: dict[str, Any]) -> dict[str, Any]:
    """The selected provider, falling back to the first configured one."""
    wanted = str(cfg.get("active_provider") or "").strip().lower()
    for entry in cfg["providers"]:
        if entry["name"].strip().lower() == wanted:
            return entry
    return cfg["providers"][0]


def save_active_provider(name: str) -> None:
    raw = mw.addonManager.getConfig(ADDON_PACKAGE) or {}
    raw["active_provider"] = name
    mw.addonManager.writeConfig(ADDON_PACKAGE, raw)


def resolve_api_key(provider: dict[str, Any]) -> str:
    """Literal key, else env var, else a dotted path into a JSON file."""
    literal = str(provider.get("api_key") or "").strip()
    if literal:
        return literal

    env_name = str(provider.get("api_key_env") or "").strip()
    if env_name:
        from_env = os.environ.get(env_name, "").strip()
        if from_env:
            return from_env
        raise KeyLookupError(
            f"Environment variable {env_name} is not set (provider "
            f"\"{provider['name']}\")."
        )

    file_name = str(provider.get("api_key_file") or "").strip()
    if not file_name:
        return ""

    path = pathlib.Path(file_name).expanduser()
    if not path.exists():
        raise KeyLookupError(f"Key file not found: {path}")

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise KeyLookupError(f"Could not read {path}: {exc}") from exc

    dotted = str(provider.get("api_key_path") or "").strip()
    if not dotted:
        raise KeyLookupError(
            f'Provider "{provider["name"]}" sets api_key_file but not api_key_path.'
        )

    cursor: Any = data
    for part in dotted.split("."):
        if not isinstance(cursor, dict) or part not in cursor:
            available = ", ".join(sorted(cursor)) if isinstance(cursor, dict) else "—"
            raise KeyLookupError(
                f'"{dotted}" not found in {path}.\n\nAvailable at that level: {available}'
            )
        cursor = cursor[part]

    if not isinstance(cursor, str) or not cursor.strip():
        raise KeyLookupError(f'"{dotted}" in {path} is not a non-empty string.')

    return cursor.strip()
