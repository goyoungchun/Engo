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
    # True when the feed carries only a summary and the full text has to be
    # read from the article page (VOA, NPR).
    fetch_page: bool = False
    # True when a page with no article prose means "not an article" and the
    # item should be dropped -- VOA feeds mix in video-programme pages whose
    # only text is a teaser. NPR always has a usable summary, so it falls back
    # instead of dropping.
    drop_if_no_body: bool = False


_VOA = "https://www.voanews.com/api/"

SOURCES = (
    Source("conversation", "The Conversation", "lic_cc", {
        "world":      "https://theconversation.com/us/world/articles.atom",
        "business":   "https://theconversation.com/us/business/articles.atom",
        "technology": "https://theconversation.com/us/technology/articles.atom",
        # The Conversation has no standalone science section; its environment
        # feed (climate, energy, ecology) is the closest science content and
        # lets every theme, science included, be picked with this source alone.
        "science":    "https://theconversation.com/us/environment/articles.atom",
        "health":     "https://theconversation.com/us/health/articles.atom",
    }),
    Source("npr", "NPR", "lic_public", {
        "world":      "https://feeds.npr.org/1004/rss.xml",
        "business":   "https://feeds.npr.org/1006/rss.xml",
        "technology": "https://feeds.npr.org/1019/rss.xml",
        "science":    "https://feeds.npr.org/1007/rss.xml",
        "health":     "https://feeds.npr.org/1128/rss.xml",
    }, fetch_page=True),
    Source("voa", "VOA", "lic_publicdomain", {
        # Not "International Edition" -- that feed is video programmes with no
        # prose. Europe is VOA's international-news feed of actual articles.
        "world":      _VOA + "zjbovl-vomx-tpebvmr",     # Europe
        "business":   _VOA + "zyboql-vomx-tpetvmi",     # Economy
        "technology": _VOA + "zyritl-vomx-tpettmq",     # Technology
        "science":    _VOA + "ztbopl-vomx-tpekvmm",     # Science & Health
        "health":     _VOA + "ztbopl-vomx-tpekvmm",     # (VOA folds the two)
    }, fetch_page=True, drop_if_no_body=True),
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
# The Conversation ends each article with an author disclosure in a
# class="fine-print" paragraph ("<name> does not work for, consult, own shares
# in..."). That is about the journalist, not the article, and has no place in
# a passage to translate -- drop it.
_FINEPRINT = re.compile(
    r"<(p|div)[^>]*class=[\"'][^\"']*fine-print[^\"']*[\"'][^>]*>.*?</\1>",
    re.S | re.I)
# A photo credit tacked onto the text -- NPR appends "(Image credit: Vipin)".
# It is about the picture, not the article, and was landing as its own row.
_IMGCREDIT = re.compile(r"\(\s*(?:image\s+credit|photo|credit)\s*:[^)]*\)",
                        re.I)
_SPACE = re.compile(r"[ \t ]+")
_BLANK = re.compile(r"\n\s*\n+")
_ENTITY = {"&amp;": "&", "&lt;": "<", "&gt;": ">", "&quot;": '"',
           "&#39;": "'", "&apos;": "'", "&nbsp;": " ", "&mdash;": "—",
           "&rsquo;": "’", "&lsquo;": "‘", "&ldquo;": "“",
           "&rdquo;": "”", "&hellip;": "…"}


_WS = re.compile(r"\s+")
# A sentinel for a heading's line break that the whitespace collapse cannot
# eat. A private-use code point, deliberately: Python counts the ASCII
# separators \x1c-\x1f as whitespace, so `\s+` would have swallowed those.
_HSEP = ""


def clean(raw: str) -> str:
    """HTML fragment -> plain text a person can read and translate."""
    if not raw:
        return ""
    text = _SCRIPT.sub(" ", raw)
    text = _FIGURE.sub(" ", text)
    text = _FINEPRINT.sub(" ", text)
    text = _IMGCREDIT.sub(" ", text)
    # Headings become their own line -- marked with a sentinel, not a newline,
    # so the whitespace collapse below leaves them standing alone. Inner tags
    # (a linked heading, say) are cleared by _TAG next.
    text = _HEADING.sub(_HSEP + r"## \1" + _HSEP, text)
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
    text = re.sub(r"&#[xX]([0-9a-fA-F]+);",
                  lambda m: chr(int(m.group(1), 16)), text)
    # Collapse every run of whitespace -- including newlines the source used
    # only to wrap its markup -- to one space, so a dateline like
    # "CAPE CANAVERAL, Florida —" joins the sentence it introduces rather than
    # standing alone. Sentence breaks come from punctuation, not from where the
    # HTML happened to wrap. The heading sentinels then become real lines.
    text = _WS.sub(" ", text)
    text = text.replace(_HSEP, "\n")
    text = re.sub(r" *\n *", "\n", text)
    text = re.sub(r"\n+", "\n", text)
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
    # xml.etree expands internal entities, so a crafted feed with an entity
    # bomb ("billion laughs") would balloon in memory. No real news feed
    # carries a DTD at all -- reject any that does before parsing.
    head = raw[:4096]
    if b"<!DOCTYPE" in head or b"<!ENTITY" in raw:
        raise ET.ParseError("DTD not allowed in a feed")
    root = ET.fromstring(raw)
    items = root.findall(".//item") or root.findall(f".//{_ATOM}entry")
    out: list[Article] = []
    for item in items:
        title = clean(_text_of(item.find("title"))
                      or _text_of(item.find(f"{_ATOM}title")))
        url = _link_of(item)
        # The link is data from the feed, and it gets fetched and displayed
        # as a clickable link later. Anything but http(s) is dropped here.
        if url and not url.lower().startswith(("http://", "https://")):
            url = ""
        guid = (_text_of(item.find("guid")) or _text_of(item.find(f"{_ATOM}id"))
                or url).strip()
        body = _best_body(item)
        if not guid or not title or len(body) < 30:
            continue        # nothing worth translating
        out.append(Article(guid=guid, title=title, text=body, url=url,
                           source_key=source.key, source_name=source.name,
                           theme=theme))
    return out


# More than any feed or article page has business being. A response past this
# is either a mistake or an attack; either way it is not read into memory.
MAX_FETCH_BYTES = 8 * 1024 * 1024


def _fetch_feed(url: str) -> bytes:
    # http(s) only. Item links come from the feed, and urllib would happily
    # open file:// -- which would read a local file into a "passage".
    if not url.lower().startswith(("http://", "https://")):
        raise ValueError(f"unsupported url scheme: {url[:40]!r}")
    request = urllib.request.Request(url, headers={"User-Agent": _UA})
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        chunks: list[bytes] = []
        total = 0
        while chunk := response.read(1 << 16):
            total += len(chunk)
            if total > MAX_FETCH_BYTES:
                raise ValueError("response too large")
            chunks.append(chunk)
        return b"".join(chunks)


# Where the article prose lives on a page: VOA uses article-content / wsw,
# NPR uses storytext. Everything after the body is share widgets and links.
_BODY_MARKERS = ('id="article-content"', 'class="wsw"', 'id="storytext"')
_BODY_END = ('class="c-mmp', 'class="region', 'class="share',
             'id="comments', 'class="related', 'class="c-article-links')
# \b after the tag name so "<p" does not also match "<picture" -- which,
# because the backreference then closes on the caption's </p>, dragged the
# lead image's caption in as if it were the first paragraph.
_PARA = re.compile(r"<(p|h[23]|li)\b[^>]*>(.*?)</\1>", re.S | re.I)
# An image caption/credit block, spotted by its HTML markup -- NPR wraps the
# caption in class="caption"/class="credit"/class="hide-caption" -- so a body
# sentence that merely says the word "credit" is not mistaken for one.
_CAPTION = re.compile(r'class="[^"]*(?:credit|caption|hide-caption)'
                      r'|aria-label="Image', re.I)
# A related-story promo NPR drops beside the text: a "slug" section label and
# a headline whose link is tagged as recirculation. Not part of the article.
_RECIRC = re.compile(r'recirculation|class="[^"]*\bslug\b', re.I)
# The editorial footer -- editor credits and podcast/social/newsletter promos.
# Once one of these appears the article is over, so collection stops there.
_FOOTER = re.compile(
    r"\bwas edited by\b|\bedited this (?:story|piece)\b"
    r"|\bListen to\b.{0,60}\b(?:Apple Podcasts|Spotify|NPR One)\b"
    r"|\bFollow (?:us|the show) on\b|\bsign up for\b.{0,30}\bnewsletter\b"
    r"|\bLeave us a voicemail\b|\bSubscribe to\b.{0,40}\b(?:podcast|newsletter)\b",
    re.I)
# A newsletter greeting / subscription pitch at the top of an NPR newsletter
# edition: "You're reading the Up First newsletter... delivered to your inbox."
# Skipped, not a stop -- the real edition follows it.
_PROMO = re.compile(
    r"You(?:'re| are) reading the\b.{0,50}\bnewsletter\b"
    r"|\bdelivered to your inbox\b"
    r"|\bSubscribe\b.{0,30}\bto get it\b", re.I)
# A non-editorial list (navigation, related links). Body lists are marked
# edTag; drop the rest before pulling <li> items.
_NON_EDTAG_LIST = re.compile(r"<(ul|ol)(?![^>]*edTag)[^>]*>.*?</\1>", re.S | re.I)
# A leading decorative emoji on a list item ("🎧 Jordan, a ...").
_LEAD_EMOJI = re.compile(r"^[\U0001F000-\U0001FAFF☀-➿️]+\s*")


def _article_body(url: str) -> str:
    """The article's prose, read from its page, for feeds that carry only a
    summary (VOA, NPR). Returns '' when the page has no real article body --
    a VOA video-programme page, say -- so the caller can drop or fall back
    rather than keep a teaser. Never raises.
    """
    try:
        raw = _fetch_feed(url).decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError, ValueError):
        return ""
    start = -1
    for marker in _BODY_MARKERS:
        start = raw.find(marker)
        if start >= 0:
            break
    if start < 0:
        return ""
    region = raw[start:start + 40000]
    for marker in _BODY_END:                  # stop before the trailing widgets
        cut = region.find(marker, 200)
        if cut > 0:
            region = region[:cut]
    # Drop navigation/related lists so only editorial (edTag) list items are
    # left to pull as <li>.
    region = _NON_EDTAG_LIST.sub(" ", region)
    # Take the paragraphs, subheadings and list items in order. Pulling by tag
    # rather than cleaning the whole region leaves out image captions and
    # credits, which sit in their own elements.
    parts: list[str] = []
    for match in _PARA.finditer(region):
        opening = match.group(0)
        # Skip image captions and related-story promos -- title, subheadings,
        # and body only.
        if _CAPTION.search(opening) or _RECIRC.search(opening):
            continue
        text = _LEAD_EMOJI.sub("", clean(match.group(2)))
        if not text or _IMGCREDIT.search(text):
            continue
        if _PROMO.search(text):               # a newsletter greeting/pitch
            continue
        # The editor-credit / promo footer ends the article; stop here so it
        # and anything after it (share bars, more promos) are left out.
        if _FOOTER.search(text):
            break
        if match.group(1).lower().startswith("h"):
            text = "## " + text
        parts.append(text)
    return _cap("\n".join(parts))


# Passage length, by sentence count -- the same thresholds the reading tab
# shows as 짧음 / 중간 / 김.
LENGTHS = ("short", "medium", "long")
LENGTH_MEDIUM_MIN, LENGTH_LONG_MIN = 11, 26


def length_category_by_count(sentences: int) -> str:
    if sentences < LENGTH_MEDIUM_MIN:
        return "short"
    if sentences < LENGTH_LONG_MIN:
        return "medium"
    return "long"


def length_category(text: str) -> str:
    from . import repo        # split with the same splitter the tab counts by
    return length_category_by_count(len(repo.split_sentences(text)))


def available_themes(source_keys) -> list[str]:
    """Themes that at least one of the chosen sources actually carries."""
    keys = set(source_keys)
    return [t for t in THEMES
            if any(t in SOURCE_BY_KEY[k].feeds
                   for k in keys if k in SOURCE_BY_KEY)]


def fetch(source_keys, theme_keys, count, seen=None, should_stop=None,
          progress=None, rng=None, lengths=None):
    """Pull recent articles for the chosen sources/themes.

    Returns (articles, error). `error` is an i18n key ('' on success):
    'news_offline' if nothing could be reached, 'news_empty' if every feed
    came back but held nothing new after de-duplication and filtering.

    `lengths`, if given, is a set of 'short'/'medium'/'long' to keep. Never
    raises. Already-seen guids (from repo) are excluded; the rest are shuffled
    and the first `count` that survive the filters returned, so the same
    articles do not come back run after run.
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

    # Walk the shuffled pool, reading the full page body where the feed gave
    # only a summary (VOA, NPR), dropping pages that turn out not to be
    # articles, and keeping only the chosen lengths -- until `count` survive.
    # Page fetches are capped so a strict filter cannot scan the pool forever.
    wanted = set(lengths) if lengths else None
    budget = count * 8 + 24
    chosen: list[Article] = []
    for article in pool:
        if len(chosen) >= count or budget <= 0:
            break
        if should_stop and should_stop():
            break
        source = SOURCE_BY_KEY.get(article.source_key)
        if source and source.fetch_page and article.url:
            budget -= 1
            full = _article_body(article.url)
            if full:
                article.text = full
            elif source.drop_if_no_body:
                continue          # a video-programme page, not an article
        if wanted is not None and length_category(article.text) not in wanted:
            continue
        chosen.append(article)

    if not chosen:
        return [], "news_empty"
    return chosen, ""
