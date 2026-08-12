# Ayumi-Assistant

An AI study assistant that lives **inside Anki**, docked next to your cards.

You're reviewing a card, you don't quite get a word — instead of switching to a
browser, you press one button and get the reading, the meaning, the nuance and
an example sentence, right there beside the card.

Your teacher is **Ayumi** — warm, patient, and unhurried. She explains clearly,
corrects kindly, and offers a word of encouragement when something is genuinely
hard rather than praising every answer. If you'd rather have a plain assistant,
her character can be switched off in one setting.

Works with any language you're studying. Japanese is the default; Chinese,
Korean, Spanish, French, German, Italian, Russian, Arabic and English have
tailored presets, and you can type in any other language.

---

## What it looks like

```
┌─ Anki ──────────────────┬─────────────────────────────┐
│                         │ 友達  Japanese ▾  OpenRouter ▾│
│         友達            │─────────────────────────────│
│      (ともだち)          │ [Explain][Examples][Nuance] │
│                         │─────────────────────────────│
│                         │ 友達（ともだち）— friend     │
│                         │                             │
│                         │ The everyday word for       │
│                         │ "friend". More casual than  │
│                         │ 友人（ゆうじん）...          │
│                         │─────────────────────────────│
│ Again  Hard  Good  Easy │ Ask anything…          [↵]  │
└─────────────────────────┴─────────────────────────────┘
```

---

## Installing

1. Download the latest `.ankiaddon` from the Releases page.
2. In Anki: **Tools → Add-ons → Install from file…** and pick it.
3. Restart Anki.

The panel appears on the right. Press **Ctrl+Shift+A** to show or hide it, or
use **Tools → Ayumi-Assistant**.

<details>
<summary>Installing from source instead</summary>

Copy this folder into your Anki add-ons directory, named `ayumi_assistant`:

| OS | Location |
| --- | --- |
| Windows | `%APPDATA%\Anki2\addons21\` |
| macOS | `~/Library/Application Support/Anki2/addons21/` |
| Linux | `~/.local/share/Anki2/addons21/` |
| Linux (Flatpak) | `~/.var/app/net.ankiweb.Anki/data/Anki2/addons21/` |

Then restart Anki.
</details>

---

## Setup — you need an API key

**New to this? Read this bit.** The add-on doesn't contain an AI itself. It
sends your question to an AI service over the internet and shows the reply. To
identify you, that service gives you an **API key** — a long password-like
string that also tracks your usage so you can be billed for it.

So there are two steps: get a key, paste it in.

### Step 1 — get a key

We recommend **OpenRouter**, because one key gives you access to models from
Anthropic, OpenAI, Google, DeepSeek and others, including free ones.

1. Go to **<https://openrouter.ai>** and create an account.
2. Open **<https://openrouter.ai/keys>**.
3. Click **Create Key**, give it any name, and copy the key that appears.
   It looks like `sk-or-v1-...`.
   **Copy it now — most services only show a key once.**

### Step 2 — paste it into Anki

1. **Tools → Add-ons**, select **Ayumi-Assistant**, click **Config**.
2. Find the `OpenRouter` block and put your key between the empty quotes:

   ```json
   {
     "name": "OpenRouter",
     "api_key": "sk-or-v1-paste-your-key-here"
   }
   ```

3. Click **Save**. That's it — no restart needed.

Open a card, press **Ctrl+Shift+A**, and click **Explain**.

### What does it cost?

You pay the AI service directly, per question. There is no charge for this
add-on and no subscription.

The default model (Claude Haiku 4.5) costs roughly **$0.002 per question** —
about 500 questions per dollar. Most services ask for a small minimum top-up
(commonly $5) to start.

**Want it free?** Two options:

- On OpenRouter, set `model` to one ending in `:free`, e.g.
  `"model": "google/gemma-4-31b-it:free"`. Browse them at
  <https://openrouter.ai/models?max_price=0>. Free models are rate-limited and
  come and go, so if one stops working, pick another.
- Run a model on your own computer with [Ollama](https://ollama.com) — no key,
  no cost, fully private. Install it, run `ollama pull qwen2.5:14b`, then pick
  **Ollama (local, free)** from the provider dropdown in the panel.

> ⚠️ **Keep your key private.** Anyone who has it can spend your money. It's
> stored in Anki's `meta.json` — don't paste that file into a bug report, and
> don't commit it if you fork this repo.

---

## Using it

| Action | How |
| --- | --- |
| Show/hide the panel | **Ctrl+Shift+A**, or Tools → Ayumi-Assistant |
| Ask about the current card | Click **Explain** |
| Ask about one word | Select it on the card first, then click a button |
| Ask anything | Type in the box, press **Enter** |
| New line instead of sending | **Shift+Enter** |
| Change language or provider | Dropdowns at the top of the panel |
| Start a fresh conversation | **Clear** |

The add-on automatically sends the fields of the card you're looking at, so
"explain this" works without typing the word out.

### Ayumi's character

By default the assistant answers as Ayumi, a gentle and caring teacher. She is
deliberately not chatty — no pet names, no roleplay, no praise for routine
questions — so answers stay as short as they would otherwise be.

To change or remove her, edit `persona` in the config. Setting it to `""` gives
you a neutral assistant with the same answer format.

### Choosing your language

Use the language dropdown at the top of the panel. It's editable — if your
language isn't listed, just type it in.

Listed languages get tailored guidance (Japanese gets hiragana readings and
pitch accent; Chinese gets pinyin with tone marks; German gets noun gender and
separable verbs; and so on). Anything else gets a sensible generic format.

---

## Configuration

Everything lives in **Tools → Add-ons → Ayumi-Assistant → Config**. The Config
window has its own documentation panel explaining every setting.

The most useful ones:

| Setting | What it does |
| --- | --- |
| `persona` | Ayumi's character. Set to `""` for a plain, neutral assistant, or write your own. |
| `target_language` | The language you're studying. |
| `system_prompt` | How answers are formatted. Rewrite this to change the style, the length, or the explanation language. |
| `providers` | The list of AI services. Add as many as you like. |
| `quick_prompts` | The buttons above the transcript. |
| `send_card_context` | Whether your card's fields are sent with the question. |

### Adding your own provider

Any service with an OpenAI-compatible API works — set `kind` to `"openai"` and
point `base_url` at it:

```json
{
  "name": "My Provider",
  "kind": "openai",
  "model": "some-model-name",
  "base_url": "https://api.example.com/v1",
  "api_key": "..."
}
```

Use `"kind": "anthropic"` for Anthropic's own API. Local servers
(`localhost`) don't need a key.

---

## Troubleshooting

| Message | What to do |
| --- | --- |
| *No API key for provider…* | You haven't pasted a key yet — see Setup above. |
| **HTTP 401** | The key is wrong, or was revoked. Copy it again. |
| **HTTP 402** | Out of credit. Top up, or switch to a free model. |
| **HTTP 404** | The `model` name is wrong for this provider. |
| **HTTP 429** | Too many requests too fast. Wait a moment. |
| *Key file not found* | `api_key_file` doesn't work on Flatpak Anki (see below). Paste the key inline instead. |
| Panel doesn't appear | Restart Anki, then Tools → Ayumi-Assistant. |

**Flatpak note:** the Flatpak build of Anki runs sandboxed and can only read
files under `~/.var/app/net.ankiweb.Anki`. The `api_key_file` option therefore
cannot reach a key stored anywhere else on your system — put the key directly in
`api_key` instead.

---

## Privacy

Your question, and the fields of the card you're viewing, are sent to whichever
provider you configure. Nothing is sent anywhere else — there is no telemetry
and no server belonging to this add-on.

If you'd rather nothing left your machine, use the **Ollama (local, free)**
provider.

Set `"send_card_context": false` to stop card fields being included.

---

## Requirements

- Anki 25.x or newer (Qt6)
- An internet connection, unless you're running a local model
- No Python packages to install — the add-on uses only the standard library

---

## Contributing

Issues and pull requests welcome. Please don't include your `meta.json` or any
API key in a bug report.

## License

Copyright (C) 2026 Ayumi-Assistant contributors

This program is free software: you can redistribute it and/or modify it under
the terms of the **GNU Affero General Public License** as published by the Free
Software Foundation, either version 3 of the License, or (at your option) any
later version.

This program is distributed in the hope that it will be useful, but WITHOUT ANY
WARRANTY; without even the implied warranty of MERCHANTABILITY or FITNESS FOR A
PARTICULAR PURPOSE. See the [GNU Affero General Public License](LICENSE) for
more details.

AGPL-3.0 is the same license Anki uses, which keeps this add-on compatible with
it.
