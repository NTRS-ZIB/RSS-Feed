#!/usr/bin/env python3
"""Which company a Schedule 13D/G is ABOUT, as opposed to who filed it.

THE DEFECT THIS EXISTS FOR HAS PUBLISHED. EDGAR lists a 13D/G under every
reporting person's CIK as well as the subject's, and a component that iterates
its roster and labels each filing with the loop's ticker turns "appears in
RIOT's index" into "somebody holds 16.3% of RIOT". On 2026-08-14 run
31810564097 posted nine such embeds, opening

    RIOT, activist stake disclosed
    Riot Platforms, Inc.
    16.30% of class

and walking down 14.60, 13.40, 12.30, 11.20, 9.80, 8.30, 7.20, 4.60. Every one
of those is Riot's own filing about Bitfarms Ltd.

MEASURED ON THE RUNNER, 2026-09-10, over all 350 structured 13D/G under the 22
roster CIKs across every index page (probe_holders.py, phase `subjects`):

  * the subject CIK is present in 350 of 350, always at the single path
    edgarSubmission/formData/coverPageHeader/issuerInfo/, so there is no
    "cannot determine" branch to design a policy around today
  * THE SPELLING SPLITS ON FORM FAMILY: `issuerCIK` in 103 of 103 13Ds and
    `issuerCik` in 247 of 247 13Gs. Nothing else in the document differs, and
    ElementTree tag comparison is case sensitive, so a rule accepting one
    spelling silently drops seven filings in ten
  * 15 of 350 are read under a company they are not about: RIOT 9 (Bitfarms),
    CRWV 2 (Applied Digital), APLD 2 (ChronoScale), CIFR 1 (Canaan), HUT 1
    (American Bitcoin)

WHY THE MATCH IS CASE-INSENSITIVE RATHER THAN A TUPLE OF KNOWN SPELLINGS. Two
spellings measured is not two spellings guaranteed, and this repo has the SC
13D case on record: a form type renamed under the component's nose and prefix
matching silently missed 117 filings for eight months. Freezing
`("issuerCIK", "issuerCik")` would be the same bet. Lowercasing the tag costs
nothing and survives a third.

WHY IT IS SCOPED TO issuerInfo RATHER THAN SCANNING THE TREE. probe_holders'
own header records what a bare tag scan cost the last time: `personName` under
`coverPageHeader/authorizedPersons/notificationInfo` precedes the reporting
persons in document order, so every filing was credited to the filing agent's
clerk and two plausible numbers were nearly reported as findings. The scope
loses nothing measurable, because all 350 hits sit under `issuerInfo`, and it
means a future sibling tag ending in "cik" cannot be mistaken for this one.
`reportingPersonInfo` already carries `reportingPersonCIK`.

WHY IT RETURNS None RATHER THAN GUESSING. Absent and present-but-empty are the
same answer, "this document does not say", and neither is a CIK. The caller
decides what to do about that, and for an attribution the safe direction is to
refuse rather than to fall back on the index it was read from, which is exactly
the assumption that produced the nine embeds.

STILL TO ADOPT THIS. `build_snapshot` labels by the same roster loop and
publishes `issuers/RIOT/filings/SCHEDULE 13D count 9` to snapshot.json, a
public file, where the true count is zero. `press_monitor` is NOT exposed: it
claims only that a filing exists under a CIK, and "RIOT filed a SCHEDULE 13D"
is true. The distinction is worth keeping: this module is needed wherever a
component converts presence in an index into a statement about ownership.
"""


def tag_of(el):
    """The local name, with any XML namespace stripped."""
    return el.tag.split("}")[-1]


def as_cik(text):
    """A CIK as an int, or None.

    INTEGERS, NEVER STRINGS. watchlist pins CIKs zero-padded to ten characters
    and EDGAR writes them both ways in the same payload, so a string comparison
    reports every filing as a mismatch: a wrong answer that arrives looking
    like a dramatic finding.

    Empty returns None rather than 0. An earlier draft of the probe reached
    int() through an `lstrip("0") or "0"` fallback, which turns an empty
    element into 0, and 0 compares unequal to every roster CIK, so a document
    that simply did not say would have been reported as misattributed.
    """
    raw = str(text or "").strip()
    if not raw:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        return None


def subject_cik(root):
    """The CIK of the company this 13D/G is about, or None if it does not say.

    `root` is the parsed primary_doc.xml, which a caller reading holder details
    has already downloaded, so this costs no extra request.
    """
    for block in root.iter():
        if tag_of(block).lower() != "issuerinfo":
            continue
        for el in block.iter():
            if tag_of(el).lower() != "issuercik":
                continue
            got = as_cik(el.text)
            if got is not None:
                return got
    return None
