#!/usr/bin/env python3
"""Turn a page's HTML into the text a date parser should read.

Stdlib only, and that is load-bearing rather than incidental. This logic
used to sit inside press_monitor.announcement_body, where it could not be
tested: press_monitor imports feedparser, which is absent from a plain
working copy, so importing it to test three lines of regex was impossible.
Extraction is the half worth testing and the fetch is the half that needs
the network, so they are separated.
"""

import json
import re

SCRIPT_OR_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")

# Only application/json. ld+json is schema.org metadata whose dates are
# ISO-formatted and so invisible to the date parser anyway; including it
# would be a guess about a source nobody has measured.
JSON_SCRIPT = re.compile(
    r"""<script[^>]*\btype=["']?application/json["']?[^>]*>(.*?)</script>""",
    re.S | re.I)

# NOT A SPACE, AND THE REASON IS NOT COSMETIC. Concatenating unrelated
# strings with whitespace can manufacture a date across a boundary present
# in neither: ["Revenue grew in August", "4, 2026 was a record"] joined with
# a space matches "August 4, 2026". The date pattern accepts \s+ between the
# month and the day, so a newline would not prevent it; a literal "|" cannot
# appear inside a match and ends it.
PAYLOAD_SEP = " | "


def _strings(node, out):
    """Every string value in a parsed JSON structure, in document order."""
    if isinstance(node, str):
        out.append(node)
    elif isinstance(node, list):
        for child in node:
            _strings(child, out)
    elif isinstance(node, dict):
        for child in node.values():
            _strings(child, out)


def payload_strings(html):
    """String values from every application/json block, in document order.

    Strings only, never the raw payload: keys, structure and escaping are
    noise the date parser would have to read past. A block that will not
    parse is skipped, because a site shipping broken JSON should cost the
    recovered text and nothing else.
    """
    out = []
    for m in JSON_SCRIPT.finditer(html or ""):
        try:
            data = json.loads(m.group(1))
        except ValueError:
            continue
        _strings(data, out)
    return out


def extract_text(html, limit=None):
    """The text of a page: what it renders, plus what it ships as JSON.

    SOME SITES SERVER-RENDER THE ARTICLE INTO A JSON PAYLOAD RATHER THAN
    INTO MARKUP, and stripping <script> then deletes the article and keeps
    the furniture. HUT is such a site: its release page returns 121,286
    bytes, of which the visible half is 1,227 characters of headline,
    posting date and a signup form, while the reporting date sits in a
    __NUXT_DATA__ payload. Recovering it is the difference between a body
    that offers no date and one that offers exactly the right one.
    """
    stripped = SCRIPT_OR_STYLE.sub(" ", html or "")
    visible = " ".join(TAG.sub(" ", stripped).split())
    recovered = [" ".join(s.split()) for s in payload_strings(html)]
    recovered = [s for s in recovered if s]
    text = PAYLOAD_SEP.join([visible] + recovered) if recovered else visible
    return text[:limit] if limit else text
