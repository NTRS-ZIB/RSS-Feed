#!/usr/bin/env python3
"""Turn a page's HTML into the text a date parser should read.

Stdlib only, and that is load-bearing rather than incidental. This logic
used to sit inside press_monitor.announcement_body, where it could not be
tested: press_monitor imports feedparser, which is absent from a plain
working copy, so importing it to test three lines of regex was impossible.
Extraction is the half worth testing and the fetch is the half that needs
the network, so they are separated.
"""

import re

SCRIPT_OR_STYLE = re.compile(r"<(script|style)[^>]*>.*?</\1>", re.S | re.I)
TAG = re.compile(r"<[^>]+>")


def extract_text(html):
    """The visible text of a page, whitespace collapsed."""
    stripped = SCRIPT_OR_STYLE.sub(" ", html or "")
    return " ".join(TAG.sub(" ", stripped).split())
