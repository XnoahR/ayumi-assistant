# SPDX-License-Identifier: AGPL-3.0-or-later
"""A small markdown-to-HTML renderer targeting Qt's rich-text subset.

Qt's QTextBrowser understands only a slice of HTML/CSS, so this deliberately
emits simple block markup rather than using a full markdown library (which the
add-on could not depend on anyway).
"""

from __future__ import annotations

import html
import re

_FENCE_RE = re.compile(r"^\s*```(\w*)\s*$")
_HEADING_RE = re.compile(r"^(#{1,6})\s+(.*)$")
_BULLET_RE = re.compile(r"^\s*[-*+]\s+(.*)$")
_ORDERED_RE = re.compile(r"^\s*(\d+)[.)]\s+(.*)$")
_QUOTE_RE = re.compile(r"^\s*>\s?(.*)$")
_RULE_RE = re.compile(r"^\s*([-*_])(\s*\1){2,}\s*$")

# A table is a row of pipe-separated cells followed by a `|---|:--:|` rule.
# A single dash is legal (`:-:`), and the rule must itself contain a pipe so a
# plain `---` horizontal rule after a line with pipes isn't mistaken for one.
_TABLE_SEP_RE = re.compile(r"^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$")

_CODE_SPAN_RE = re.compile(r"`([^`]+)`")
_BOLD_RE = re.compile(r"\*\*(.+?)\*\*", re.DOTALL)
_ITALIC_RE = re.compile(r"(?<![\w*])\*(?!\s)([^*]+?)(?<!\s)\*(?![\w*])")
_STRIKE_RE = re.compile(r"~~(.+?)~~", re.DOTALL)
_LINK_RE = re.compile(r"\[([^\]]+)\]\((https?://[^\s)]+)\)")


def render(text: str) -> str:
    """Render markdown to Qt-friendly HTML. Input is never trusted as HTML."""
    if not text:
        return ""

    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    out: list[str] = []
    paragraph: list[str] = []
    list_stack: list[str] = []  # "ul" / "ol"
    code_lines: list[str] | None = None

    def flush_paragraph() -> None:
        if paragraph:
            out.append(f"<p>{'<br>'.join(paragraph)}</p>")
            paragraph.clear()

    def close_lists() -> None:
        while list_stack:
            out.append(f"</{list_stack.pop()}>")

    def open_list(kind: str) -> None:
        if list_stack and list_stack[-1] == kind:
            return
        close_lists()
        list_stack.append(kind)
        out.append(f"<{kind}>")

    index = -1
    while index + 1 < len(lines):
        index += 1
        line = lines[index]
        fence = _FENCE_RE.match(line)

        # Tables need one line of lookahead, so they are handled before the
        # single-line block rules below.
        if code_lines is None and "|" in line and index + 1 < len(lines):
            nxt = lines[index + 1]
            if "|" in nxt and _TABLE_SEP_RE.match(nxt) and _split_row(line):
                flush_paragraph()
                close_lists()
                index = _emit_table(lines, index, out)
                continue

        if code_lines is not None:
            if fence:
                body = html.escape("\n".join(code_lines))
                out.append(f'<pre class="code">{body}</pre>')
                code_lines = None
            else:
                code_lines.append(line)
            continue

        if fence:
            flush_paragraph()
            close_lists()
            code_lines = []
            continue

        if not line.strip():
            flush_paragraph()
            close_lists()
            continue

        if _RULE_RE.match(line):
            flush_paragraph()
            close_lists()
            out.append("<hr>")
            continue

        heading = _HEADING_RE.match(line)
        if heading:
            flush_paragraph()
            close_lists()
            level = min(len(heading.group(1)) + 2, 6)
            out.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            continue

        quote = _QUOTE_RE.match(line)
        if quote:
            flush_paragraph()
            close_lists()
            out.append(f'<p class="quote">{_inline(quote.group(1))}</p>')
            continue

        bullet = _BULLET_RE.match(line)
        if bullet:
            flush_paragraph()
            open_list("ul")
            out.append(f"<li>{_inline(bullet.group(1))}</li>")
            continue

        ordered = _ORDERED_RE.match(line)
        if ordered:
            flush_paragraph()
            open_list("ol")
            out.append(f"<li>{_inline(ordered.group(2))}</li>")
            continue

        close_lists()
        paragraph.append(_inline(line.strip()))

    if code_lines is not None:  # unterminated fence
        out.append(f'<pre class="code">{html.escape(chr(10).join(code_lines))}</pre>')

    flush_paragraph()
    close_lists()
    return "".join(out)


def _split_row(line: str) -> list[str]:
    """Split `| a | b |` into cells. Returns [] if it isn't a table row."""
    stripped = line.strip()
    if "|" not in stripped:
        return []
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|"):
        stripped = stripped[:-1]
    return [cell.strip() for cell in stripped.split("|")]


def _alignments(separator: str) -> list[str]:
    out: list[str] = []
    for cell in _split_row(separator):
        left, right = cell.startswith(":"), cell.endswith(":")
        out.append("center" if left and right else "right" if right else "left")
    return out


def _emit_table(lines: list[str], start: int, out: list[str]) -> int:
    """Render the table beginning at `start`; return the last line consumed."""
    header = _split_row(lines[start])
    aligns = _alignments(lines[start + 1])
    width = len(header)

    # Qt's rich-text engine honours these attributes but ignores most table CSS.
    out.append('<table border="1" cellspacing="0" cellpadding="4" width="100%">')

    def row(cells: list[str], tag: str) -> None:
        padded = (cells + [""] * width)[:width]
        parts = []
        for i, cell in enumerate(padded):
            align = aligns[i] if i < len(aligns) else "left"
            parts.append(f'<{tag} align="{align}">{_inline(cell)}</{tag}>')
        out.append("<tr>" + "".join(parts) + "</tr>")

    row(header, "th")

    index = start + 2
    while index < len(lines):
        cells = _split_row(lines[index])
        if not cells or not lines[index].strip():
            break
        row(cells, "td")
        index += 1

    out.append("</table>")
    return index - 1


def _inline(text: str) -> str:
    """Escape, then re-introduce the inline markup we support."""
    escaped = html.escape(text)

    # Code spans are extracted first so their contents are not re-processed.
    spans: list[str] = []

    def stash(match: re.Match[str]) -> str:
        spans.append(match.group(1))
        return f"\x00{len(spans) - 1}\x00"

    escaped = _CODE_SPAN_RE.sub(stash, escaped)

    escaped = _LINK_RE.sub(r'<a href="\2">\1</a>', escaped)
    escaped = _BOLD_RE.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC_RE.sub(r"<i>\1</i>", escaped)
    escaped = _STRIKE_RE.sub(r"<s>\1</s>", escaped)

    def restore(match: re.Match[str]) -> str:
        return f'<code>{spans[int(match.group(1))]}</code>'

    return re.sub(r"\x00(\d+)\x00", restore, escaped)
