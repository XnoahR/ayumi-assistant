# SPDX-License-Identifier: AGPL-3.0-or-later
"""Ayumi-Assistant — an LLM study assistant docked beside the Anki reviewer."""

from __future__ import annotations

from aqt import gui_hooks, mw
from aqt.qt import QAction, QKeySequence, Qt, qconnect

from .config import ADDON_PACKAGE, load_config
from .panel import AssistantPanel

_panel: AssistantPanel | None = None


def get_panel() -> AssistantPanel:
    global _panel
    if _panel is None:
        _panel = AssistantPanel(mw)
        mw.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, _panel)
        if not load_config()["show_on_startup"]:
            _panel.hide()
    return _panel


def toggle_panel() -> None:
    panel = get_panel()
    if panel.isVisible():
        panel.hide()
        return

    panel.show()
    panel.raise_()
    panel.refresh_context()
    if load_config()["focus_input_on_open"]:
        panel.focus_input()


def _on_card_shown(_context=None) -> None:
    if _panel is not None and _panel.isVisible():
        _panel.refresh_context()


def _on_state_change(*_args) -> None:
    if _panel is not None and _panel.isVisible():
        _panel.refresh_context()


def _install_menu() -> None:
    action = QAction(f"Ayumi-Assistant", mw)
    action.setCheckable(False)
    shortcut = (load_config()["shortcut"] or "").strip()
    if shortcut:
        action.setShortcut(QKeySequence(shortcut))
    qconnect(action.triggered, toggle_panel)
    mw.form.menuTools.addAction(action)


def _on_config_saved(_text: str) -> None:
    if _panel is not None:
        _panel.reload_settings()


def _init() -> None:
    _install_menu()
    get_panel()

    gui_hooks.reviewer_did_show_question.append(_on_card_shown)
    gui_hooks.reviewer_did_show_answer.append(_on_card_shown)
    gui_hooks.state_did_change.append(_on_state_change)

    mw.addonManager.setConfigUpdatedAction(ADDON_PACKAGE, _on_config_saved)


gui_hooks.main_window_did_init.append(_init)
