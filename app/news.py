"""Fetch reading material from news feeds, for the 원문 해석 tab.

The point of this tab has always been to translate real English the user
brought in. This just offers a shortcut to *finding* that English: pull a few
recent articles from a news feed, one theme at a time, so there is always
something to practise on.

Only three sources, chosen on purpose. Every one of them either publishes
under a licence that permits reuse or is outright public domain, so nothing
here reproduces text a publisher has told the world not to reproduce:

  * The Conversation -- Creative Commons (CC BY-ND). Its feed carries the full
    article body, which is why its passages are the longest.
  * NPR -- public broadcaster; the RSS summary is used, which is what an RSS
    feed is for.
  * VOA (Voice of America) -- U.S. government, public domain.

News organisations that have gone to court over AI use of their text (the New
York Times, the Guardian, and others) are deliberately excluded.

Everything here is stdlib-only and never raises: a caller gets a list of
articles and, separately, a human-readable error string when the network is
down. The disclaimer the user agrees to -- personal study only, they carry
any legal responsibility -- lives in the UI, not here.
"""

from __future__ import annotations

import random
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass

TIMEOUT = 15
_UA = "Mozilla/5.0 (Engo study app; personal use)"

# RSS/Atom namespaces the feeds actually use.
_ATOM = "{http://www.w3.org/2005/Atom}"
_CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"

# Bring the whole article -- a truncated passage is worse than a long one,
# and the reading tab is built for full texts. This is only a sanity ceiling
# against a feed that returns something pathologically large; a real article
# (The Conversation's full bodies run 7,000-8,000 characters) arrives whole.
# When it does have to cut, _cap ends at a sentence boundary, never mid-word.
MAX_BODY = 40000


# --------------------------------------------------------------------------
# what can be fetched

# The five themes offered in the UI. Not every source carries every one --
# The Conversation has no standalone science feed, VOA folds science into
# health -- and that is fine; a theme simply draws from whatever sources have
# it.
THEMES = ("world", "business", "technology", "science", "health")


@dataclass(frozen=True)
class Source:
    key: str
    name: str
    licence_key: str          # i18n key describing why reuse is allowed
    feeds: dict               # theme -> feed url


_VOA = "https://www.voanews.com/api/"

SOURCES = (
    Source("conversation", "The Conversation", "lic_cc", {
        "world":      "https://theconversation.com/us/world/articles.atom",
        "business":   "https://theconversation.com/us/business/articles.atom",
        "technology": "https://theconversation.com/us/technology/articles.atom",
        "health":     "https://theconversation.com/us/health/articles.atom",
    }),
    Source("npr", "NPR", "lic_public", {
        "world":      "https://feeds.npr.org/1004/rss.xml",
        "business":   "https://feeds.npr.org/1006/rss.xml",
        "technology": "https://feeds.npr.org/1019/rss.xml",
        "science":    "https://feeds.npr.org/1007/rss.xml",
        "health":     "https://feeds.npr.org/1128/rss.xml",
    }),
    Source("voa", "VOA", "lic_publicdomain", {
        "world":      _VOA + "zumgqol-vomx-tpeg--qi",   # International Edition
        "business":   _VOA + "zyboql-vomx-tpetvmi",     # Economy
        "technology": _VOA + "zyritl-vomx-tpettmq",     # Technology
        "science":    _VOA + "ztbopl-vomx-tpekvmm",     # Science & Health
        "health":     _VOA + "ztbopl-vomx-tpekvmm",     # (VOA folds the two)
    }),
)

SOURCE_BY_KEY = {s.key: s for s in SOURCES}


@dataclass
class Article:
    guid: str
    title: str
    text: str
    url: str
    source_key: str
    source_name: str
    theme: str


# --------------------------------------------------------------------------
# text cleaning

# A section heading is marked with a Markdown-style "## " prefix. It is
# readable if the user ever edits the raw text (they can add or remove one by
# hand), survives sentence-splitting as its own line, and the reading tab
# renders any line that starts with it as a heading rather than a sentence.
HEADING_PREFIX = "## "


def is_heading(line: str) -> bool:
    return line.startswith(HEADING_PREFIX)


def heading_text(line: str) -> str:
    return line[len(HEADING_PREFIX):].strip() if is_heading(line) else line


_TAG = re.compile(r"<[^>]+>")
_SCRIPT = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
_HEADING = re.compile(r"<h[1-6][^>]*>(.*?)</h[1-6]>", re.S | re.I)
# Lead images carry a caption and a photo credit ("... Getty Images") that
# would otherwise open every passage as a stray fragment before the article
# itself. Drop the figure wholesale.
_FIGURE = re.compile(r"<(figure|figcaption)[^>]*>.*?</\1>", re.S | re.I)
_SPACE = re.compile(r"[ \t ]+")
_BLANK = re.compile(r"\n\s*\n+")
_ENTITY = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
           "&#39;": "'", "&apos;": "'", "&nbsp;": " ", "&mdash;": "—",
           "&rsquo;": "’", "&lsquo;": "‘", "&ldquo;": "“",
           "&rdquo;": "”", "&hellip;": "…"}


def clean(raw: str) -> str:
    """HTML fragment -> plain text a person can read and translate."""
    if not raw:
        return ""
    text = _SCRIPT.sub(" ", raw)
    text = _FIGURE.sub(" ", text)
    # Turn headings into their own marked line before the tags are stripped,
    # so the paragraph structure that tells a heading from body text is not
    # lost. Inner tags (a linked heading, say) are cleared by _TAG next.
    text = _HEADING.sub(r"\n\n## \1\n\n", text)
    text = _TAG.sub(" ", text)
    # Feeds carry malformed HTML -- NPR ends an image tag as a bare
    # `...support.'/>`. Once well-formed tags are gone, a tag-close remnant
    # (a quote or slash right before `>`) or a truncated tag with no close is
    # an orphan to drop; plain prose does not write `/>` or `'>`.
    text = re.sub(r"""\s*['"/]+\s*>""", "", text)
    text = re.sub(r"<[a-zA-Z/][^>]*$", "", text)
    for entity, char in _ENTITY.items():
        text = text.replace(entity, char)
    text = re.sub(r"&#(\d+);", lambda m: chr(int(m.group(1))), text)
    text = _SPACE.sub(" ", text)
    text = _BLANK.sub("\n", text)
    return text.strip()


def _cap(text: str, limit: int = MAX_BODY) -> str:
    """Trim to the last sentence end before `limit`, so it does not stop mid-word."""
    if len(text) <= limit:
        return text
    window = text[:limit]
    cut = max(window.rfind(". "), window.rfind("? "), window.rfind("! "))
    return (window[:cut + 1] if cut > limit // 2 else window).strip()


# --------------------------------------------------------------------------
# fetching

def _text_of(node) -> str:
    if node is None:
        return ""
    return "".join(node.itertext())


def _best_body(item) -> str:
    """The fullest clean text an item offers, capped to a study-sized passage.

    Atom content and content:encoded carry the whole article where a feed
    provides it (The Conversation); otherwise it falls back to the summary.
    """
    candidates = [
        _text_of(item.find(f"{_ATOM}content")),
        _text_of(item.find(_CONTENT)),
        _text_of(item.find("description")),
        _text_of(item.find(f"{_ATOM}summary")),
    ]
    cleaned = [clean(c) for c in candidates]
    best = max(cleaned, key=len) if cleaned else ""
    return _cap(best)


def _link_of(item) -> str:
    link = item.find("link")
    if link is not None and link.text:
        return link.text.strip()
    # Atom links are attributes, and there can be several; the alternate is
    # the article page.
    alt = ""
    for node in item.findall(f"{_ATOM}link"):
        href = node.get("href", "")
        if node.get("rel", "alternate") == "alternate":
            return href
        alt = alt or href
    return alt


def _parse(raw: bytes, source: Source, theme: str) -> list[Article]:
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
    out: list[Article] = []
    for item in items:
        title = clean(_text_of(item.find("title"))
                      or _text_of(item.find(f"{_ATOM}title")))
        url = _link_of(item)
        guid = (_text_of(item.find("guid")) or _text_of(item.find(f"{_ATOM}id"))
                or url).strip()
        body = _best_body(item)
        if not guid or not title or len(body) < 30:
            continue        # nothing worth translating
        out.append(Article(guid=guid, title=title, text=body, url=url,
                           source_key=source.key, source_name=source.name,
                           theme=theme))
    return out


def _fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return response.read()


def available_themes(source_keys) -> list[str]:
    """Themes that at least one of the chosen sources actually carries."""
    keys = set(source_keys)
    return [t for t in THEMES
            if any(t in SOURCE_BY_KEY[k].feeds
                   for k in keys if k in SOURCE_BY_KEY)]


def fetch(source_keys, theme_keys, count, seen=None, should_stop=None,
          progress=None, rng=None):
    """Pull recent articles for the chosen sources/themes.

    Returns (articles, error). `error` is an i18n key ('' on success):
    'news_offline' if nothing could be reached, 'news_empty' if every feed
    came back but held nothing new after de-duplication.

    Never raises. Already-seen guids (from repo) are excluded; the rest are
    shuffled and the first `count` returned, so the same articles do not come
    back run after run.
    """
    seen = set(seen or ())
    rng = rng or random
    collected: dict[str, Article] = {}
    reached = False
    pairs = [(SOURCE_BY_KEY[s], t) for s in source_keys if s in SOURCE_BY_KEY
             for t in theme_keys if t in SOURCE_BY_KEY[s].feeds]

    for index, (source, theme) in enumerate(pairs):
        if should_stop and should_stop():
            break
        if progress:
            progress(index, len(pairs))
        try:
            raw = _fetch_feed(source.feeds[theme])
        except (urllib.error.URLError, TimeoutError, OSError, ValueError):
            continue        # this feed is unreachable; others may still work
        reached = True
        try:
            articles = _parse(raw, source, theme)
        except ET.ParseError:
            continue
        for article in articles:
            if article.guid in seen or article.guid in collected:
                continue
            collected[article.guid] = article

    if not reached:
        return [], "news_offline"

    pool = list(collected.values())
    if not pool:
        return [], "news_empty"
    rng.shuffle(pool)
    return pool[:count], ""
