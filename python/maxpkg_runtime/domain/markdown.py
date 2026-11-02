"""Markdown to Qt rich-text HTML for package descriptions written on maxpkg.dev.

Covers what the site's editor produces and what GitHub-style descriptions use:
- blocks: headings (# to ###### and setext), paragraphs (every newline is a line break), nested ordered/unordered lists,
  task lists, block quotes, fenced code (``` and ~~~), horizontal rules and pipe tables with alignment;
- inline: **bold**/__bold__, *italic*/_italic_, ~~strike~~, `code`, [links](url "title"), <autolinks>, bare
  URLs, ![images](url) inside a sentence (shown as links: QTextBrowser does not fetch remote images) and
  backslash escapes. Pictures on lines of their own are split off by split_media() and shown as images.

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
_BARE_URL = re.compile(r"(?<![\"'=\w/\x00])(https?://[^\s<]+[^\s<.,:;!?)\]'\"])")
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


PICTURE_LINK = "maxpkg-picture:"  # href of an inline picture: maxpkg-picture:<position in the description>


def cdn_origin(site):
    """The content CDN of a maxpkg.dev environment: https://maxpkg.dev -> https://cdn.maxpkg.dev,
    https://dev.maxpkg.dev -> https://cdn-dev.maxpkg.dev."""
    match = re.match(r"^https?://([^/:]+)", site or "")
    host = match.group(1).lower() if match else "maxpkg.dev"
    labels = host.split(".")
    if len(labels) > 2:  # an environment such as dev.maxpkg.dev
        return "https://cdn-" + labels[0] + "." + ".".join(labels[1:])
    return "https://cdn." + host


class Pictures:
    """The pictures of one description: which links may be loaded, and their positions in document order.

    Like maxpkg.dev, a picture loads only from the content CDN of the service's environment over https, or from a
    site-relative path ("/...", not "//...") on the service's own origin; any other picture shows its alt text and is
    never requested. `items` lists (alt, url) in document order, including gallery pictures: a lightbox walks them
    by position, since the same picture may appear twice.
    """

    def __init__(self, site=SITE, cdn=None):
        self.site = site.rstrip("/")
        self.cdn = (cdn or cdn_origin(site)).rstrip("/").lower()
        self.items = []

    def resolve(self, target):
        """The URL to load, or '' when the picture must not be loaded."""
        target = target.strip()
        if target.startswith("/") and not target.startswith("//"):
            return self.site + target
        if self.cdn.startswith("https://") and target.lower().startswith(self.cdn + "/"):
            return target
        return ""

    def add(self, alt, url):
        self.items.append((alt, url))
        return len(self.items) - 1


def safe_href(target):
    target = target.strip()
    if re.match(r"^(https?://|mailto:)", target, re.I):
        return target
    if target.startswith("/") and not target.startswith("//"):
        return SITE + target
    return ""


def inline(text, pictures=None):
    """One line (or a joined paragraph) of inline Markdown to HTML. With `pictures`, an allowed picture becomes an
    <img> inside a maxpkg-picture:<position> link; any other picture is its alt text."""
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
    def picture(match):
        alt = match.group(1).strip()
        url = pictures.resolve(match.group(2)) if pictures is not None else ""
        if not url:
            return keep(html.escape(alt))
        return keep('<a href="{}{}"><img src="{}" alt="{}"></a>'.format(
            PICTURE_LINK, pictures.add(alt, url), html.escape(url), html.escape(alt)))

    text = _IMAGE.sub(picture, text)
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


def _paragraph_html(lines, pictures=None):
    """Lines of one paragraph, each on its own line, as on maxpkg.dev.

    The runtime API drops blank lines from descriptions, so a single newline is often the author's paragraph
    break: joining such lines with spaces would run "Website: ... User Guide: ..." into one line.
    """
    parts = []
    for line in lines:
        content = line.strip()
        if content.endswith("\\") and not content.endswith("\\\\"):
            content = content[:-1].rstrip()  # backslash hard break: the line break is already there
        parts.append(inline(content, pictures))
    return "<br>".join(parts)


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


def _table(header, separator, rows, pictures=None):
    aligns = []
    for cell in _split_row(separator):
        left, right = cell.startswith(":"), cell.endswith(":")
        aligns.append("center" if left and right else ("right" if right else "left"))
    columns = len(aligns)

    def cells(row, tag):
        values = (_split_row(row) + [""] * columns)[:columns]
        return "".join('<{0} align="{1}">{2}</{0}>'.format(tag, aligns[index], inline(value, pictures))
                       for index, value in enumerate(values))

    body = "".join("<tr>" + cells(row, "td") + "</tr>" for row in rows)
    return ('<table class="md" width="100%" cellspacing="0" cellpadding="6">'
            "<thead><tr>" + cells(header, "th") + "</tr></thead><tbody>" + body + "</tbody></table>")


def _is_table_start(lines, index):
    return (index + 1 < len(lines) and "|" in lines[index] and _TABLE_SEPARATOR.match(lines[index + 1])
            and "-" in lines[index + 1])


def _list_html(lines, index, pictures=None):
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
                output.append(" " + inline(line.strip(), pictures))  # continuation of the current item
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
            output.append("<li>" + box + " " + inline(text, pictures))
        else:
            output.append("<li>" + inline(text, pictures))
        index += 1
    while stack:
        output.append("</li></{}>".format(stack.pop()[1]))
    return "".join(output), index


def image_line(line, pictures):
    """[(alt, url)] when a line holds only pictures that may be loaded, else []: the line stays text, where a
    picture that may not be loaded shows its alt text."""
    rest = _IMAGE.sub("", line).strip()
    if rest or not _IMAGE.search(line):
        return []
    found = []
    for match in _IMAGE.finditer(line):
        url = pictures.resolve(match.group(2))
        if not url:
            return []
        found.append((match.group(1).strip(), url))
    return found


def split_media(source, pictures):
    """Description Markdown in reading order as ("text", markdown) and ("images", [(alt, url)]) blocks.

    Like maxpkg.dev (its MarkdownRenderer), pictures on lines of their own become image blocks: pictures on
    consecutive lines are one gallery, a single one stands alone, and a blank line ends a gallery. Pictures inside a
    sentence and in code blocks stay in the text.
    """
    blocks = []
    text = []
    fence = None
    for line in (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        marker = _FENCE.match(line)
        if fence is None and marker:
            fence = marker.group(1)
        elif fence is not None and line.strip().startswith(fence):
            fence = None
        found = image_line(line, pictures) if fence is None and not marker else []
        if not found:
            text.append(line)
            continue
        if text:
            if any(part.strip() for part in text):
                blocks.append(("text", "\n".join(text)))
            else:
                blocks.append(("break", ""))  # a blank line between pictures: the next ones start a new gallery
        text = []
        if blocks and blocks[-1][0] == "images":
            blocks[-1][1].extend(found)
        else:
            blocks.append(("images", found))
    if any(part.strip() for part in text):
        blocks.append(("text", "\n".join(text)))
    return [block for block in blocks if block[0] != "break"]


def to_html(source, pictures=None):
    lines = (source or "").replace("\r\n", "\n").replace("\r", "\n").split("\n")
    output = []
    paragraph = []

    def flush():
        if paragraph:
            output.append("<p>" + _paragraph_html(paragraph, pictures) + "</p>")
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
            output.append("<h{0}>{1}</h{0}>".format(level, inline(paragraph[0].strip(), pictures)))
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
            output.append("<h{0}>{1}</h{0}>".format(level, inline(heading.group(2), pictures)))
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
            output.append(_table(header, separator, rows, pictures))
            continue
        if stripped.startswith(">"):
            flush()
            quote = []
            while index < len(lines) and lines[index].strip().startswith(">"):
                quote.append(re.sub(r"^\s*>\s?", "", lines[index]))
                index += 1
            output.append("<blockquote>" + to_html("\n".join(quote), pictures) + "</blockquote>")
            continue
        if _LIST_ITEM.match(line) and not paragraph:
            flush()
            block, index = _list_html(lines, index, pictures)
            output.append(block)
            continue
        if _LIST_ITEM.match(line) and paragraph:
            flush()
            continue
        paragraph.append(line)
        index += 1
    flush()
    return "".join(output)
