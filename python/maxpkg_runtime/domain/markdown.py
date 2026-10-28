"""Markdown to Qt rich-text HTML for package descriptions written on maxpkg.dev.

Covers what the site's editor produces and what GitHub-style descriptions use:
- blocks: headings (# to ###### and setext), paragraphs with hard breaks, nested ordered/unordered lists,
  task lists, block quotes, fenced code (``` and ~~~), horizontal rules and pipe tables with alignment;
- inline: **bold**/__bold__, *italic*/_italic_, ~~strike~~, `code`, [links](url "title"), <autolinks>, bare
  URLs, ![images](url) (shown as links: QTextBrowser does not fetch remote images) and backslash escapes.

All text is HTML-escaped; links keep only http(s), mailto and site-relative targets (maxpkg.dev).
"""

import html
import re

SITE = "https://maxpkg.dev"

_ESCAPABLE = "\\`*_{}[]()#+-.!|~>"
_CODE = re.compile(r"(`+)(.+?)\1", re.S)
_IMAGE = re.compile(r"!\[([^\]]*)\]\(\s*([^)\s]+)(?:\s+\"[^\"]*\")?\s*\)")
_LINK = re.compile(r"\[([^\]]+)\]\(\s*([^)\s]+)(?:\s+\"([^\"]*)\")?\s*\)")
_AUTOLINK = re.compile(r"<((?:https?://|mailto:)[^>\s]+)>")
_BARE_URL = re.compile(r"(?<![\"'=\w/])(https?://[^\s<]+[^\s<.,:;!?)\]'\"])")
_BOLD = re.compile(r"(\*\*|__)(?=\S)(.+?)(?<=\S)\1")
_ITALIC_STAR = re.compile(r"(?<![*\w])\*(?=\S)(.+?)(?<=\S)\*(?![*\w])")
_ITALIC_UNDERSCORE = re.compile(r"(?<![_\w])_(?=\S)(.+?)(?<=\S)_(?![_\w])")
_STRIKE = re.compile(r"~~(?=\S)(.+?)(?<=\S)~~")
_TOKEN = re.compile("\x00(\\d+)\x00")

_FENCE = re.compile(r"^\s{0,3}(`{3,}|~{3,})")
_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*#*\s*$")
_RULE = re.compile(r"^\s{0,3}([-*_])(?:\s*\1){2,}\s*$")
_SETEXT = re.compile(r"^\s{0,3}(=+|-+)\s*$")
_LIST_ITEM = re.compile(r"^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)$")
_TASK = re.compile(r"^\[([ xX])\]\s+(.*)$")
_TABLE_SEPARATOR = re.compile(r"^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$")


def safe_href(target):
    target = target.strip()
    if re.match(r"^(https?://|mailto:)", target, re.I):
        return target
    if target.startswith("/") and not target.startswith("//"):
        return SITE + target
    return ""


def inline(text):
    """One line (or a joined paragraph) of inline Markdown to HTML."""
    stash = []

    def keep(fragment):
        stash.append(fragment)
        return "\x00{}\x00".format(len(stash) - 1)

    def link(label, target, title=""):
        href = safe_href(target)
        if not href:
            return label
        tip = ' title="{}"'.format(html.escape(title)) if title else ""
        return keep('<a href="{}"{}>'.format(html.escape(href), tip)) + label + keep("</a>")

    # Escapes and code spans first: nothing inside them is Markdown.
    text = re.sub(r"\\([" + re.escape(_ESCAPABLE) + "])", lambda match: keep(html.escape(match.group(1))), text)
    text = _CODE.sub(lambda match: keep("<code>" + html.escape(match.group(2).strip()) + "</code>"), text)
    text = _IMAGE.sub(lambda match: link(html.escape(match.group(1) or "Image"), match.group(2)), text)
    text = _LINK.sub(lambda match: link(match.group(1), match.group(2), match.group(3) or ""), text)
    text = _AUTOLINK.sub(lambda match: link(html.escape(match.group(1)), match.group(1)), text)
    text = _BARE_URL.sub(lambda match: link(html.escape(match.group(1)), match.group(1)), text)
    text = html.escape(text, quote=False)
    text = _BOLD.sub(r"<b>\2</b>", text)
    text = _ITALIC_STAR.sub(r"<i>\1</i>", text)
    text = _ITALIC_UNDERSCORE.sub(r"<i>\1</i>", text)
    text = _STRIKE.sub(r"<s>\1</s>", text)
    while _TOKEN.search(text):
        text = _TOKEN.sub(lambda match: stash[int(match.group(1))], text)
    return text


def _paragraph_html(lines):
    """Lines of one paragraph: soft breaks become spaces, two trailing spaces or a backslash break the line."""
    parts = []
    for position, line in enumerate(lines):
        last = position == len(lines) - 1
        hard = not last and (line.endswith("  ") or line.rstrip().endswith("\\"))
        content = line.strip()
        if hard and content.endswith("\\"):
            content = content[:-1]
        parts.append(inline(content) + ("<br>" if hard else ("" if last else " ")))
    return "".join(parts)


def _split_row(line):
    row = line.strip()
    if row.startswith("|"):
        row = row[1:]
    if row.endswith("|") and not row.endswith("\\|"):
        row = row[:-1]
    cells, current, escaped = [], "", False
    for character in row:
        if character == "|" and not escaped:
            cells.append(current.strip())
            current = ""
            continue
        escaped = character == "\\" and not escaped
        current += character
    cells.append(current.strip())
    return cells


def _table(header, separator, rows):
    aligns = []
    for cell in _split_row(separator):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else ("right" if right else "left"))
    columns = len(aligns)

    def cells(row, tag):
        values = (_split_row(row) + [""] * columns)[:columns]
        return "".join('<{0} align="{1}">{2}</{0}>'.format(tag, aligns[index], inline(value))
                       for index, value in enumerate(values))

    body = "".join("<tr>" + cells(row, "td") + "</tr>" for row in rows)
    return ('<table class="md" width="100%" cellspacing="0" cellpadding="6">'
            "<thead><tr>" + cells(header, "th") + "</tr></thead><tbody>" + body + "</tbody></table>")


def _is_table_start(lines, index):
    return (index + 1 < len(lines) and "|" in lines[index] and _TABLE_SEPARATOR.match(lines[index + 1])
            and "-" in lines[index + 1])


def _list_html(lines, index):
    """Parse a (possibly nested) list starting at `index`. Returns (html, next index)."""
    output = []
    stack = []  # [(indent, tag, item open)]

    def close_to(indent):
        while stack and stack[-1][0] > indent:
            output.append("</li></{}>".format(stack.pop()[1]))

    while index < len(lines):
        line = lines[index]
        match = _LIST_ITEM.match(line)
        if match is None:
            if not line.strip():
                # A blank line ends the list unless the next line continues it (an item or indented text).
                following = lines[index + 1] if index + 1 < len(lines) else ""
                if _LIST_ITEM.match(following) or (following.startswith("  ") and following.strip() and stack):
                    index += 1
                    continue
                break
            if stack and (line.startswith(" ") or line.startswith("\t")) and not _FENCE.match(line):
                output.append(" " + inline(line.strip()))  # continuation of the current item
                index += 1
                continue
            break
        indent = len(match.group(1).replace("\t", "    "))
        marker, text = match.group(2), match.group(3)
        tag = "ul" if marker in "-*+" else "ol"
        if stack and indent > stack[-1][0]:
            start = "" if tag == "ul" or int(marker[:-1]) == 1 else ' start="{}"'.format(int(marker[:-1]))
            output.append("<{}{}>".format(tag, start))
            stack.append((indent, tag))
        else:
            close_to(indent)
            if stack and stack[-1][1] != tag:
                output.append("</li></{}>".format(stack.pop()[1]))
            if stack:
                output.append("</li>")
            else:
                start = "" if tag == "ul" or int(marker[:-1]) == 1 else ' start="{}"'.format(int(marker[:-1]))
                output.append("<{}{}>".format(tag, start))
                stack.append((indent, tag))
        task = _TASK.match(text)
        if task:
            box = "☑" if task.group(1).lower() == "x" else "☐"  # ballot box with / without check
            text = task.group(2)
            output.append("<li>" + box + " " + inline(text))
        else:
            output.append("<li>" + inline(text))
        index += 1
    while stack:
        output.append("</li></{}>".format(stack.pop()[1]))
    return "".join(output), index


def to_html(source):
    lines = (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    paragraph = []

    def flush():
        if paragraph:
            output.append("<p>" + _paragraph_html(paragraph) + "</p>")
            del paragraph[:]

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush()
            index += 1
            continue
        fence = _FENCE.match(line)
        if fence:
            flush()
            marker = fence.group(1)
            index += 1
            code = []
            while index < len(lines) and not lines[index].strip().startswith(marker):
                code.append(lines[index])
                index += 1
            index += 1
            output.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
            continue
        setext = _SETEXT.match(line)
        if setext and paragraph and len(paragraph) == 1:
            level = 3 if setext.group(1).startswith("=") else 4
            output.append("<h{0}>{1}</h{0}>".format(level, inline(paragraph[0].strip())))
            del paragraph[:]
            index += 1
            continue
        if _RULE.match(line):
            flush()
            output.append("<hr>")
            index += 1
            continue
        heading = _HEADING.match(line)
        if heading:
            flush()
            level = min(6, len(heading.group(1)) + 2)  # # -> h3: the page title is the package name
            output.append("<h{0}>{1}</h{0}>".format(level, inline(heading.group(2))))
            index += 1
            continue
        if _is_table_start(lines, index):
            flush()
            header, separator = lines[index], lines[index + 1]
            index += 2
            rows = []
            while index < len(lines) and lines[index].strip() and "|" in lines[index]:
                rows.append(lines[index])
                index += 1
            output.append(_table(header, separator, rows))
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            output.append("<blockquote>" + to_html("\n".join(quote)) + "</blockquote>")
            continue
        if _LIST_ITEM.match(line) and not paragraph:
            flush()
            block, index = _list_html(lines, index)
            output.append(block)
            continue
        if _LIST_ITEM.match(line) and paragraph:
            flush()
            continue
        paragraph.append(line)
        index += 1
    flush()
    return "".join(output)
