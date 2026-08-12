## Ayumi-Assistant

An LLM assistant docked beside the reviewer. Toggle it from **Tools →
Ayumi-Assistant** or with the keyboard shortcut. Pick which provider to use
from the dropdown at the top of the panel.

---

## `providers`

A list — add as many as you like. The dropdown in the panel switches between
them, and your choice is saved back here as `active_provider`.

No API keys ship with the add-on — you supply your own. See the README for a
step-by-step walkthrough if you have not set one up before.

| Entry | Endpoint | Notes |
| --- | --- | --- |
| `OpenRouter` *(default)* | `https://openrouter.ai/api/v1` | One key, many models — including free ones. Easiest starting point. |
| `OpenAI` | `https://api.openai.com/v1` | |
| `Anthropic` | `https://api.anthropic.com` | Native API (`kind: "anthropic"`). |
| `Google Gemini` | `…/v1beta/openai` | Gemini's OpenAI-compatible endpoint. |
| `DeepSeek` | `https://api.deepseek.com/v1` | Inexpensive. |
| `Ollama (local, free)` | `http://localhost:11434/v1` | No key, no cost, fully offline. |

> ⚠️ **Flatpak:** the Flatpak build of Anki is sandboxed and can only read paths
> under `~/.var/app/net.ankiweb.Anki`. `api_key_file` therefore **cannot** be
> used there — pointing it at `~/.config/…` fails with "Key file not found" even
> though the file plainly exists. Put the key inline in `api_key` instead.
> `api_key_file` still works on non-Flatpak installs.

### Changing the model

Edit the `model` field on that provider and save — it applies immediately, no
restart needed. Use whatever model IDs your provider publishes.

For free models on OpenRouter, use an ID ending in `:free`, e.g.
`google/gemma-4-31b-it:free`. Browse the current list at
<https://openrouter.ai/models?max_price=0>.

Some endpoints (particularly small proxies) buffer their replies, so the panel
waits and then shows the whole answer at once instead of typing it out. That is
the endpoint's behaviour, not a fault in the add-on.

Each entry:

| Field | Meaning |
| --- | --- |
| `name` | Label shown in the dropdown. Must be unique. |
| `kind` | `"anthropic"` for the native Messages API, or `"openai"` for **any** OpenAI-compatible endpoint. |
| `model` | Model ID, exactly as that service names it. |
| `base_url` | API root. For `openai` kind this is the part before `/chat/completions`. |
| `api_key` | The key. See below for ways to avoid pasting it here. |
| `effort` | `anthropic` only — `low`/`medium`/`high`/`xhigh`/`max`. Omitted automatically for Haiku models, which reject it. |
| `thinking` | `anthropic` only — `default` or `off`. |
| `max_tokens` | Optional per-provider override of the global setting. |
| `extra_headers` | Optional extra HTTP headers. |

`kind: "openai"` covers OpenAI, OpenRouter, NVIDIA NIM, Z.ai, Together,
Groq, DeepSeek, Ollama, LM Studio, llama.cpp, vLLM — anything exposing
`/chat/completions`.

### Supplying the key without pasting it

*(Not usable on the Flatpak build — see the warning above.)*

Instead of `api_key`, an entry may point at a key kept elsewhere. Resolution
order is `api_key` → `api_key_env` → `api_key_file`.

- **`api_key_env`** — read from an environment variable, e.g.
  `"api_key_env": "OPENROUTER_API_KEY"`. Note Anki must be launched with that
  variable set.
- **`api_key_file`** + **`api_key_path`** — read from a JSON file, so the key
  lives in one place instead of being copied around. `api_key_path` is a dotted
  path into that file:

  ```json
  "api_key_file": "~/keys.json",
  "api_key_path": "openrouter.key"
  ```

  …reads `{"openrouter": {"key": "sk-or-..."}}`. Any JSON file works. If the
  path is wrong, the error lists the keys actually available at that level, so
  it is easy to correct.

### Examples

```json
{
  "name": "Groq",
  "kind": "openai",
  "model": "llama-3.3-70b-versatile",
  "base_url": "https://api.groq.com/openai/v1",
  "api_key": "gsk_..."
}
```

```json
{
  "name": "LM Studio",
  "kind": "openai",
  "model": "local-model",
  "base_url": "http://localhost:1234/v1",
  "api_key": ""
}
```

Local endpoints (`localhost`, `127.0.0.1`) do not require a key.

---

## `active_provider`

The `name` of the provider currently in use. Changing the dropdown in the panel
rewrites this, so you rarely need to edit it by hand.

## Behaviour

- **`max_tokens`** — ceiling for a single reply. Covers reasoning as well as
  visible text, so keep it generous.
- **`timeout_seconds`** — per-network-read timeout.
- **`persona`** — who Ayumi is. By default she is a warm, patient teacher:
  gentle and unhurried, encouraging when something is genuinely hard and quiet
  about it when it is not. Her warmth is deliberately kept in the *tone* rather
  than in extra words, so answers stay short.
  Set it to `""` to switch the character off entirely and get a plain,
  neutral assistant, or replace it with any character you like. `{language}` and
  `{explain_lang}` are substituted here too.
- **`explanation_language`** — the language Ayumi *writes in*. Independent of
  what you are studying, so you can learn Japanese with explanations in Bahasa
  Indonesia. Also settable from the second dropdown in the panel, which accepts
  any language you type. Target-language words, readings and example sentences
  stay in the target language; only the explanation around them changes.
- **`explanation_languages`** — the list offered in that dropdown. Purely a
  convenience list; typing anything else works too.
- **`target_language`** — the language you are studying. Also settable from the
  dropdown at the top of the panel, which accepts any language you type.
- **`system_prompt`** — the assistant's standing instructions, used as a
  template. `{persona}` is filled from `persona`; `{language}`, `{reading}` and
  `{extra}` come from `target_language` and `language_presets`; `{explain_lang}`
  comes from `explanation_language`. Rewrite it freely
  to change the format, the length, or the language answers are written in — if
  you drop the placeholders, your text is used exactly as typed.
  It ends with an instruction not to narrate reasoning or drafts: keep that if
  you rewrite it, or some models will think out loud in the reply.
- **`language_presets`** — per-language guidance on what counts as "the
  reading": hiragana for Japanese, pinyin for Chinese, noun gender for German,
  and so on. Add your own entry for any language not listed; anything missing
  falls back to a generic format.
- **`send_card_context`** — when true, the fields of the card on screen are sent
  with your question so you can just ask "explain this".
- **`max_context_chars`** — cap on how much card text is sent.
- **`max_history_turns`** — how many previous messages stay in the conversation.
- **`shortcut`** — keyboard shortcut to toggle the panel. Takes effect after a
  restart.
- **`focus_input_on_open`** — put the cursor in the ask box when the panel opens.
- **`show_on_startup`** — whether the panel is visible when Anki launches.
- **`font_family`** / **`font_size`** — transcript typography. Leave
  `font_family` empty to use the bundled CJK-capable fallbacks.

## `quick_prompts`

The buttons above the transcript. Each entry has a `label` and a `prompt`.
Three placeholders are substituted before sending:

- `{word}` — the target word from the current card (or your selection)
- `{selection}` — text you have highlighted on the card
- `{card}` — all fields of the current card

Add, remove, or reword these freely; changes apply as soon as you save.

---

Note: `temperature` is deliberately not supported — current Anthropic models
reject it outright. Steer tone and length through `system_prompt` instead.
