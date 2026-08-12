# SPDX-License-Identifier: AGPL-3.0-or-later
"""The docked assistant panel."""

from __future__ import annotations

import html
import threading
from typing import Any

from aqt import mw
from aqt.qt import (
    QComboBox,
    QDockWidget,
    QHBoxLayout,
    QLabel,
    QPlainTextEdit,
    QPushButton,
    QSizePolicy,
    Qt,
    QTextBrowser,
    QTimer,
    QVBoxLayout,
    QWidget,
    qconnect,
)
from aqt.utils import openLink

from . import cardctx, markdown_lite, providers
from .config import (
    KeyLookupError,
    active_provider,
    build_system_prompt,
    language_names,
    load_config,
    provider_names,
    resolve_api_key,
    save_active_provider,
    save_target_language,
)

DOCK_OBJECT_NAME = "ayumiAssistantDock"
PANEL_TITLE = "Ayumi-Assistant"

_FLUSH_INTERVAL_MS = 60

_FALLBACK_FONTS = (
    '"Noto Sans CJK JP", "Noto Sans JP", "Hiragino Sans", "Yu Gothic", '
    '"Meiryo", "Source Han Sans", sans-serif'
)


def _theme() -> dict[str, str]:
    try:
        from aqt.theme import theme_manager

        night = bool(theme_manager.night_mode)
    except Exception:
        night = False

    if night:
        return {
            "user_bg": "#2f3640",
            "assistant_bg": "#23272e",
            "code_bg": "#1b1f24",
            "text": "#dfe3e8",
            "muted": "#96a0ad",
            "accent": "#7cc4ff",
            "quote": "#9aa7b5",
        }
    return {
        "user_bg": "#eef2f7",
        "assistant_bg": "#ffffff",
        "code_bg": "#f2f4f7",
        "text": "#1f2429",
        "muted": "#6b7684",
        "accent": "#1a6fb5",
        "quote": "#5c6773",
    }


class InputBox(QPlainTextEdit):
    """Multi-line input where Enter sends and Shift+Enter inserts a newline."""

    def __init__(self, on_submit) -> None:
        super().__init__()
        self._on_submit = on_submit
        self.setPlaceholderText("Ask anything…  (Enter to send, Shift+Enter for a new line)")
        self.setTabChangesFocus(True)
        self.setMaximumHeight(96)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Fixed)

    def keyPressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if event.key() in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            shift = event.modifiers() & Qt.KeyboardModifier.ShiftModifier
            if not shift:
                self._on_submit()
                return
        super().keyPressEvent(event)


class AssistantPanel(QDockWidget):
    def __init__(self, parent) -> None:
        super().__init__(PANEL_TITLE, parent)
        self.setObjectName(DOCK_OBJECT_NAME)
        self.setAllowedAreas(
            Qt.DockWidgetArea.RightDockWidgetArea | Qt.DockWidgetArea.LeftDockWidgetArea
        )
        self.setFeatures(
            QDockWidget.DockWidgetFeature.DockWidgetClosable
            | QDockWidget.DockWidgetFeature.DockWidgetMovable
            | QDockWidget.DockWidgetFeature.DockWidgetFloatable
        )

        # role -> "user" | "assistant"; text is raw markdown.
        self._turns: list[dict[str, str]] = []
        self._context: cardctx.CardContext | None = None

        self._pending: list[str] = []
        self._pending_lock = threading.Lock()
        self._stop_event: threading.Event | None = None
        self._streaming = False
        self._status_transient = False

        self._build_ui()

        self._flush_timer = QTimer(self)
        self._flush_timer.setInterval(_FLUSH_INTERVAL_MS)
        qconnect(self._flush_timer.timeout, self._flush_pending)

        self.refresh_context()
        self._render()

    # ---------------------------------------------------------------- UI ---

    def _build_ui(self) -> None:
        container = QWidget(self)
        layout = QVBoxLayout(container)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(6)

        top_row = QHBoxLayout()
        top_row.setSpacing(6)

        self._context_label = QLabel()
        self._context_label.setWordWrap(True)
        self._context_label.setTextFormat(Qt.TextFormat.RichText)
        self._context_label.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred
        )
        top_row.addWidget(self._context_label, 1)

        self._language_combo = QComboBox()
        self._language_combo.setEditable(True)
        self._language_combo.setToolTip(
            "The language you are studying.\n"
            "Type any language here — it does not have to be in the list."
        )
        self._language_combo.setMinimumContentsLength(9)
        qconnect(self._language_combo.activated, self._on_language_changed)
        qconnect(self._language_combo.lineEdit().editingFinished,
                 self._on_language_typed)
        top_row.addWidget(self._language_combo, 0)

        self._provider_combo = QComboBox()
        self._provider_combo.setToolTip(
            "Which configured provider to send to.\n"
            "Edit the list under Tools → Add-ons → Ayumi-Assistant → Config."
        )
        qconnect(self._provider_combo.activated, self._on_provider_changed)
        top_row.addWidget(self._provider_combo, 0)

        layout.addLayout(top_row)
        self._reload_providers()
        self._reload_languages()

        self._quick_row = QHBoxLayout()
        self._quick_row.setSpacing(4)
        quick_holder = QWidget()
        quick_holder.setLayout(self._quick_row)
        layout.addWidget(quick_holder)
        self._rebuild_quick_prompts()

        self._transcript = QTextBrowser()
        self._transcript.setOpenExternalLinks(False)
        self._transcript.setOpenLinks(False)
        qconnect(self._transcript.anchorClicked, lambda url: openLink(url.toString()))
        layout.addWidget(self._transcript, 1)

        self._status = QLabel("")
        self._status.setWordWrap(True)
        layout.addWidget(self._status)

        self._input = InputBox(self._on_submit)
        layout.addWidget(self._input)

        buttons = QHBoxLayout()
        buttons.setSpacing(4)

        self._send_button = QPushButton("Send")
        self._send_button.setDefault(True)
        qconnect(self._send_button.clicked, self._on_submit)
        buttons.addWidget(self._send_button)

        self._stop_button = QPushButton("Stop")
        self._stop_button.setEnabled(False)
        qconnect(self._stop_button.clicked, self.stop_streaming)
        buttons.addWidget(self._stop_button)

        buttons.addStretch(1)

        clear_button = QPushButton("Clear")
        qconnect(clear_button.clicked, self.clear_conversation)
        buttons.addWidget(clear_button)

        layout.addLayout(buttons)
        self.setWidget(container)

    def _rebuild_quick_prompts(self) -> None:
        while self._quick_row.count():
            item = self._quick_row.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()

        cfg = load_config()
        for entry in cfg.get("quick_prompts") or []:
            if not isinstance(entry, dict):
                continue
            label = str(entry.get("label") or "").strip()
            template = str(entry.get("prompt") or "").strip()
            if not label or not template:
                continue
            button = QPushButton(label)
            button.setToolTip(template)
            qconnect(
                button.clicked,
                lambda _checked=False, tpl=template: self.send_prompt(self._expand(tpl)),
            )
            self._quick_row.addWidget(button)

        self._quick_row.addStretch(1)

    # ---------------------------------------------------------- language ---

    def _reload_languages(self) -> None:
        cfg = load_config()
        names = language_names(cfg)
        current = str(cfg.get("target_language") or "")

        self._language_combo.blockSignals(True)
        self._language_combo.clear()
        self._language_combo.addItems(names)
        self._language_combo.setCurrentText(current)
        self._language_combo.blockSignals(False)

    def _apply_language(self, language: str) -> None:
        language = (language or "").strip()
        if not language:
            self._reload_languages()
            return
        if language == str(load_config().get("target_language") or ""):
            return
        try:
            save_target_language(language)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not save language: {exc}", error=True)
            return
        self._set_status(f"Studying {language}.")

    def _on_language_changed(self, index: int) -> None:
        self._apply_language(self._language_combo.itemText(index))

    def _on_language_typed(self) -> None:
        self._apply_language(self._language_combo.currentText())

    # ---------------------------------------------------------- providers ---

    def _reload_providers(self) -> None:
        cfg = load_config()
        names = provider_names(cfg)
        current = active_provider(cfg)["name"]

        self._provider_combo.blockSignals(True)
        self._provider_combo.clear()
        self._provider_combo.addItems(names)
        if current in names:
            self._provider_combo.setCurrentIndex(names.index(current))
        self._provider_combo.blockSignals(False)

    def _on_provider_changed(self, index: int) -> None:
        name = self._provider_combo.itemText(index)
        if not name:
            return
        try:
            save_active_provider(name)
        except Exception as exc:  # noqa: BLE001
            self._set_status(f"Could not save provider choice: {exc}", error=True)
            return
        self._set_status(f"Using {name}.")

    # ----------------------------------------------------------- context ---

    def refresh_context(self) -> None:
        cfg = load_config()
        try:
            self._context = cardctx.current_context(cfg["max_context_chars"])
        except Exception:
            self._context = None

        colors = _theme()
        if self._context and self._context.word:
            word = html.escape(self._context.word)
            deck = html.escape(self._context.deck or "")
            suffix = (
                f' <span style="color:{colors["muted"]};">· {deck}</span>' if deck else ""
            )
            self._context_label.setText(
                f'<span style="color:{colors["muted"]};">Card:</span> '
                f'<b style="color:{colors["accent"]};">{word}</b>{suffix}'
            )
        else:
            self._context_label.setText(
                f'<span style="color:{colors["muted"]};">'
                "No card in view — ask anything, or select text on a card."
                "</span>"
            )

    def _expand(self, template: str) -> str:
        context = self._context
        word = (context.word if context else "") or "this word"
        selection = (context.selection if context else "") or word
        card = context.summary(load_config()["max_context_chars"]) if context else ""
        return (
            template.replace("{word}", word)
            .replace("{selection}", selection)
            .replace("{card}", card)
        )

    # -------------------------------------------------------- conversation ---

    def _on_submit(self) -> None:
        text = self._input.toPlainText().strip()
        if not text:
            return
        self._input.clear()
        self.send_prompt(text)

    def send_prompt(self, text: str) -> None:
        text = (text or "").strip()
        if not text or self._streaming:
            return

        self.refresh_context()

        cfg = load_config()
        provider = active_provider(cfg)

        # Resolve the key up front so a bad api_key_file surfaces immediately,
        # rather than as a mysterious auth failure a second later.
        try:
            api_key = resolve_api_key(provider)
        except KeyLookupError as exc:
            self._set_status(str(exc), error=True)
            return

        system, messages = self._build_request(cfg, text)

        self._turns.append({"role": "user", "text": text})
        self._turns.append({"role": "assistant", "text": ""})
        self._render()

        self._streaming = True
        self._stop_event = threading.Event()
        self._send_button.setEnabled(False)
        self._stop_button.setEnabled(True)
        self._set_status(f"Waiting for {provider['name']}…")
        self._flush_timer.start()

        stop_event = self._stop_event

        def on_text(chunk: str) -> None:
            with self._pending_lock:
                self._pending.append(chunk)

        def on_status(message: str) -> None:
            mw.taskman.run_on_main(lambda: self._set_status(message))

        def task() -> None:
            providers.stream_completion(
                provider,
                api_key,
                system,
                messages,
                max_tokens=cfg["max_tokens"],
                timeout=cfg["timeout_seconds"],
                on_text=on_text,
                on_status=on_status,
                should_stop=stop_event.is_set,
            )

        def done(future) -> None:
            error: BaseException | None = None
            try:
                future.result()
            except BaseException as exc:  # noqa: BLE001 - surfaced to the user
                error = exc
            self._finish_stream(error)

        mw.taskman.run_in_background(task, done, uses_collection=False)

    def _build_request(
        self, cfg: dict[str, Any], text: str
    ) -> tuple[str, list[dict[str, str]]]:
        system = build_system_prompt(cfg)

        messages: list[dict[str, str]] = []
        max_turns = max(0, cfg["max_history_turns"])
        history = [t for t in self._turns if t["text"].strip()]
        for turn in history[-max_turns:] if max_turns else []:
            messages.append({"role": turn["role"], "content": turn["text"]})

        content = text
        if cfg.get("send_card_context") and self._context is not None:
            summary = self._context.summary(cfg["max_context_chars"])
            preamble: list[str] = []
            if summary:
                preamble.append("Card currently under review:\n" + summary)
            if self._context.selection:
                preamble.append(f"Text the user selected: {self._context.selection}")
            if preamble:
                content = "\n\n".join(preamble) + "\n\n---\n\n" + text

        messages.append({"role": "user", "content": content})
        return system, messages

    def stop_streaming(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        self._set_status("Stopping…")

    def clear_conversation(self) -> None:
        if self._streaming:
            self.stop_streaming()
        self._turns.clear()
        with self._pending_lock:
            self._pending.clear()
        self._set_status("")
        self._render()

    # ------------------------------------------------------------ streaming ---

    def _flush_pending(self) -> None:
        with self._pending_lock:
            if not self._pending:
                return
            chunk = "".join(self._pending)
            self._pending.clear()

        if not self._turns or self._turns[-1]["role"] != "assistant":
            self._turns.append({"role": "assistant", "text": ""})

        self._turns[-1]["text"] += chunk
        if self._status_transient:
            self._set_status("")
        self._render()

    def _finish_stream(self, error: BaseException | None) -> None:
        def apply() -> None:
            self._flush_timer.stop()
            self._flush_pending()
            self._streaming = False
            self._stop_event = None
            self._send_button.setEnabled(True)
            self._stop_button.setEnabled(False)

            if error is not None:
                message = (
                    str(error)
                    if isinstance(error, providers.ProviderError)
                    else f"{type(error).__name__}: {error}"
                )
                if self._turns and self._turns[-1]["role"] == "assistant":
                    if not self._turns[-1]["text"].strip():
                        self._turns.pop()
                self._set_status(message, error=True)
                self._render()
                return

            # A stopped or empty response leaves a blank bubble behind.
            if self._turns and self._turns[-1]["role"] == "assistant":
                if not self._turns[-1]["text"].strip():
                    self._turns.pop()
                    self._render()

            if self._status_transient:
                self._set_status("")

            self._input.setFocus()

        mw.taskman.run_on_main(apply)

    # ------------------------------------------------------------ rendering ---

    def _set_status(self, message: str, error: bool = False) -> None:
        # Progress notes ("Thinking…", "Waiting for X…") are cleared once real
        # output arrives; errors and warnings stay put until the next send.
        self._status_transient = bool(message) and not error and message.endswith("…")

        colors = _theme()
        color = "#d9534f" if error else colors["muted"]
        self._status.setText(
            f'<span style="color:{color};">{html.escape(message).replace(chr(10), "<br>")}</span>'
            if message
            else ""
        )

    def _empty_state(self, cfg: dict[str, Any], colors: dict[str, str]) -> str:
        """First-run guidance — a missing key should read as setup, not failure."""
        provider = active_provider(cfg)
        try:
            has_key = bool(resolve_api_key(provider)) or "localhost" in provider["base_url"]
        except KeyLookupError:
            has_key = False

        if has_key:
            return (
                '<p class="role">Ask about the word on the current card, or anything '
                "else. Answers stream in here.</p>"
            )

        name = html.escape(provider["name"])
        return (
            f'<p><b style="color:{colors["accent"]};">Almost ready — '
            f"one step left.</b></p>"
            f"<p>Ayumi needs an API key to reach an AI service. "
            f'You are currently set to <b>{name}</b>.</p>'
            "<p><b>1.</b> Create a free account and copy a key:<br>"
            '<a href="https://openrouter.ai/keys">openrouter.ai/keys</a></p>'
            "<p><b>2.</b> In Anki: <b>Tools → Add-ons → Ayumi-Assistant → "
            "Config</b>, then paste it into the <code>api_key</code> field of "
            f"the <b>{name}</b> entry and press Save.</p>"
            f'<p class="role">No account wanted? Install '
            '<a href="https://ollama.com">Ollama</a>, run '
            "<code>ollama pull qwen2.5:14b</code>, and choose "
            "<b>Ollama (local, free)</b> from the dropdown above — no key, "
            "no cost, nothing leaves your computer.</p>"
        )

    def _render(self) -> None:
        cfg = load_config()
        colors = _theme()
        family = (cfg.get("font_family") or "").strip()
        font_stack = f'"{family}", {_FALLBACK_FONTS}' if family else _FALLBACK_FONTS

        css = f"""
        body {{ color: {colors['text']}; font-family: {font_stack};
                font-size: {cfg['font_size']}px; }}
        p {{ margin-top: 2px; margin-bottom: 6px; }}
        .role {{ color: {colors['muted']}; font-size: {max(9, cfg['font_size'] - 3)}px; }}
        .user {{ background-color: {colors['user_bg']}; }}
        .assistant {{ background-color: {colors['assistant_bg']}; }}
        .quote {{ color: {colors['quote']}; }}
        code {{ background-color: {colors['code_bg']}; font-family: monospace; }}
        pre.code {{ background-color: {colors['code_bg']}; font-family: monospace; }}
        a {{ color: {colors['accent']}; }}
        """
        self._transcript.document().setDefaultStyleSheet(css)

        if not self._turns:
            body = self._empty_state(cfg, colors)
        else:
            parts: list[str] = []
            for turn in self._turns:
                label = "You" if turn["role"] == "user" else "Ayumi"
                rendered = markdown_lite.render(turn["text"]) or "<p></p>"
                parts.append(
                    f'<div class="{turn["role"]}">'
                    f'<p class="role">{label}</p>{rendered}</div>'
                )
            body = "<hr>".join(parts)

        scrollbar = self._transcript.verticalScrollBar()
        at_bottom = scrollbar.value() >= scrollbar.maximum() - 4
        previous = scrollbar.value()

        self._transcript.setHtml(f"<body>{body}</body>")

        scrollbar.setValue(scrollbar.maximum() if at_bottom else previous)

    # -------------------------------------------------------------- helpers ---

    def focus_input(self) -> None:
        self._input.setFocus()

    def reload_settings(self) -> None:
        self._reload_providers()
        self._reload_languages()
        self._rebuild_quick_prompts()
        self.refresh_context()
        self._render()
