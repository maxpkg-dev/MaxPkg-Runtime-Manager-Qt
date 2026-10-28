"""Small Markdown subset to HTML for package descriptions (same subset as the HTML Manager).

Headings (#..####), paragraphs, ordered/unordered lists, block quotes, fenced code, **bold**,
*italic*, `code` and [links](https://...). Everything else is escaped text.
"""

import html
import re

_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITALIC = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")
_CODE = re.compile(r"`([^`]+)`")
_LIST = re.compile(r"^\s*(?:[-*+]|\d+\.)\s+")
_ORDERED = re.compile(r"^\s*\d+\.\s+")


def inline(text):
    escaped = html.escape(text, quote=False)
    escaped = _CODE.sub(r"<code>\1</code>", escaped)
    escaped = _LINK.sub(lambda match: '<a href="{}">{}</a>'.format(html.escape(match.group(2)), match.group(1)), escaped)
    escaped = _BOLD.sub(r"<b>\1</b>", escaped)
    escaped = _ITALIC.sub(r"<i>\1</i>", escaped)
    return escaped


def to_html(source):
    lines = (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    paragraph = []

    def flush():
        if paragraph:
            output.append("<p>" + "<br>".join(inline(line.strip()) for line in paragraph) + "</p>")
            del paragraph[:]

    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            flush()
            index += 1
            continue
        if stripped.startswith("```"):
            flush()
            index += 1
            code = []
            while index < len(lines) and not lines[index].strip().startswith("```"):
                code.append(lines[index])
                index += 1
            index += 1
            output.append("<pre>" + html.escape("\n".join(code)) + "</pre>")
            continue
        heading = re.match(r"^(#{1,4})\s+(.+)$", stripped)
        if heading:
            flush()
            level = min(6, len(heading.group(1)) + 2)
            output.append("<h{0}>{1}</h{0}>".format(level, inline(heading.group(2))))
            index += 1
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(lines[index].strip()[1:].strip())
                index += 1
            output.append("<blockquote>" + "<br>".join(inline(part) for part in quote) + "</blockquote>")
            continue
        if _LIST.match(line):
            flush()
            ordered = bool(_ORDERED.match(line))
            items = []
            while index < len(lines) and _LIST.match(lines[index]) and bool(_ORDERED.match(lines[index])) == ordered:
                items.append("<li>" + inline(_LIST.sub("", lines[index], count=1)) + "</li>")
                index += 1
            tag = "ol" if ordered else "ul"
            output.append("<{0}>{1}</{0}>".format(tag, "".join(items)))
            continue
        paragraph.append(line)
        index += 1
    flush()
    return "".join(output)
