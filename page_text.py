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
#
# The lookbehind is (?<![-\w]) rather than \b: \b treats "-" as a boundary,
# so \btype= also matches inside data-type="application/json" and
# content-type="application/json", attributes this pattern has no business
# reading. (?<![-\w]) requires the character before "type" to be neither a
# word character nor a hyphen, so it matches a bare type= attribute only.
JSON_SCRIPT = re.compile(
    r"""<script[^>]*(?<![-\w])type=["']?application/json["']?[^>]*>(.*?)</script>""",
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
        # Accumulate into a block-local list and only extend `out` once the
        # whole block has been walked. _strings appends directly into
        # whatever list it is given, so appending into `out` itself would let
        # a RecursionError raised partway through leave everything appended
        # before the raise in place -- a block truncated at an arbitrary
        # point set by nesting depth, not skipped as the except below intends.
        block = []
        try:
            data = json.loads(m.group(1))
            _strings(data, block)
        except (ValueError, RecursionError):
            # ValueError: syntactically broken JSON. RecursionError: the walk
            # in _strings adds a Python frame per level of nesting and can
            # exceed the recursion limit even though json.loads itself
            # accepts the same document as syntactically valid. Both must be
            # skipped to prevent discarding visible text already extracted.
            continue
        out.extend(block)
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
    # Only recover strings containing whitespace. A date has the form
    # "Month D, YYYY", which requires whitespace, so this filter cannot lose
    # a date; it drops URLs, UUIDs, base64 blobs and single-word tokens that
    # are noise in the body text. It also drops the empty string, since "" is
    # a string with no characters and so has none that are whitespace -- no
    # separate empty-string filter is needed. The claim that this cannot lose
    # a date rests on regex \s and str.isspace() agreeing on every code
    # point, which was checked (not merely assumed) across the full Unicode
    # range before relying on it here.
    recovered = [s for s in recovered if any(c.isspace() for c in s)]
    # Only prepend `visible` when it is non-empty, so a page whose only
    # content is a payload does not open with a bare separator (" | a
    # phrase"). Harmless to the date parser, since PAYLOAD_SEP never matches
    # DATE_RE, but it is an artefact and it inflates the probe's `chars`
    # column, which the spec asks readers to use as a diagnostic.
    text = PAYLOAD_SEP.join(([visible] if visible else []) + recovered) \
        if recovered else visible
    # `limit` bounds characters, not bytes, even though the constant this is
    # sized against (BODY_MAX_BYTES, in press_monitor.py) is named in bytes.
    # That is deliberate rather than an oversight: the byte bound is already
    # enforced upstream on the raw download, and adding encoding-aware
    # slicing here would duplicate that cap for no reader-visible benefit.
    return text[:limit] if limit is not None else text

import nonexistent_module_xyz  # TEMPORARY
