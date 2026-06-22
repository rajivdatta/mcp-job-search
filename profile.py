"""Derive job-search terms from a LinkedIn profile, with two supported inputs:

1. A LinkedIn "Get a copy of your data" CSV export (Positions/Skills/Profile).
2. A LinkedIn "Save to PDF" profile export (e.g. RajivLinkedIn.pdf).

Whichever is found in the configured export folder is used (CSV preferred).
Neither involves logging into or scraping LinkedIn -- both are exports you
download yourself.
"""
from __future__ import annotations

import csv
import os
import pathlib
import re

# ----------------------------- CSV parsing ------------------------------ #
def _find_csv(folder: pathlib.Path, name: str) -> pathlib.Path | None:
    exact = folder / name
    if exact.exists():
        return exact
    stem = name.replace(".csv", "").lower()
    for p in folder.glob("*.csv"):
        if p.stem.lower() == stem:
            return p
    return None


def _read_rows(path: pathlib.Path | None) -> list[dict]:
    if not path:
        return []
    with open(path, newline="", encoding="utf-8-sig") as f:
        return list(csv.DictReader(f))


def _col(row: dict, *candidates: str) -> str:
    lower = {k.lower().strip(): (v or "") for k, v in row.items()}
    for c in candidates:
        v = lower.get(c.lower(), "").strip()
        if v:
            return v
    return ""


def _derive_from_csv(folder: pathlib.Path, max_titles: int) -> dict | None:
    positions = _read_rows(_find_csv(folder, "Positions.csv"))
    if not positions:
        return None  # no CSV export -> let caller fall back to PDF
    skills = _read_rows(_find_csv(folder, "Skills.csv"))
    profile_rows = _read_rows(_find_csv(folder, "Profile.csv"))

    titles: list[str] = []
    for r in positions:
        t = _col(r, "Title")
        if t and t not in titles:
            titles.append(t)
    headline = _col(profile_rows[0], "Headline") if profile_rows else ""
    geo = _col(profile_rows[0], "Geo Location", "Address", "Zip Code") if profile_rows else ""
    skill_names = [s for s in (_col(r, "Name") for r in skills) if s]

    return {
        "source": "csv",
        "headline": headline,
        "geo": geo,
        "titles": (titles[:max_titles] if titles else ([headline] if headline else [])),
        "skills": skill_names[:15],
    }


# ----------------------------- PDF parsing ------------------------------ #
_MONTHS = (r"(?:January|February|March|April|May|June|July|August|September|"
           r"October|November|December)")
_DATE_LINE = re.compile(rf"\b{_MONTHS}\s+\d{{4}}\b", re.IGNORECASE)
_SECTION_STOP = {"languages", "certifications", "summary", "experience",
                 "education", "honors", "publications"}


def _derive_from_pdf(folder: pathlib.Path, max_titles: int) -> dict | None:
    pdfs = sorted(folder.glob("*.pdf"))
    if not pdfs:
        return None
    try:
        from pypdf import PdfReader
    except ImportError:
        return {"error": "A PDF was found but pypdf is not installed. Run: pip install pypdf"}

    text = "\n".join((p.extract_text() or "") for p in PdfReader(str(pdfs[0])).pages)
    lines = [ln.strip() for ln in text.splitlines() if ln.strip()]

    # Headline: the line immediately before the "Summary" section, which on a
    # LinkedIn PDF holds the role(s), e.g. "Senior Data Architect | Fabric | ...".
    # A LinkedIn headline is pipe-separated (e.g. "Senior Data Architect | ...").
    # Prefer that; only fall back to the line before "Summary" if no pipe exists.
    headline = next((ln for ln in lines if " | " in ln), "")
    if not headline:
        for i, ln in enumerate(lines):
            if ln.lower() == "summary" and i > 0:
                headline = lines[i - 1]
                break

    # Experience titles: each role prints as Company / Title / "<Month YYYY ...>",
    # so the line directly before a date line is the job title.
    exp_titles: list[str] = []
    for i, ln in enumerate(lines):
        if _DATE_LINE.search(ln) and i >= 1:
            cand = lines[i - 1]
            if cand and not _DATE_LINE.search(cand) and 2 < len(cand) < 80:
                if cand not in exp_titles:
                    exp_titles.append(cand)

    # Top Skills block (the few lines after a "Top Skills" header).
    skills: list[str] = []
    for i, ln in enumerate(lines):
        if ln.lower() == "top skills":
            for nxt in lines[i + 1:i + 8]:
                if nxt.lower() in _SECTION_STOP:
                    break
                skills.append(nxt)
            break

    # Assemble titles: headline's primary role first, then recent experience.
    titles: list[str] = []
    primary = headline.split("|")[0].strip() if headline else ""
    if primary:
        titles.append(primary)
    for t in exp_titles:
        if t not in titles:
            titles.append(t)

    return {
        "source": "pdf",
        "headline": headline,
        "geo": "",
        "titles": titles[:max_titles],
        "skills": skills[:15],
    }


# ------------------------------- public --------------------------------- #
def derive(export_dir: str, max_titles: int = 3) -> dict:
    """Return {source, headline, geo, titles[], skills[]} from a CSV or PDF
    LinkedIn export in `export_dir` (CSV preferred, PDF fallback)."""
    folder = pathlib.Path(os.path.expandvars(export_dir))
    if not folder.is_dir():
        return {
            "error": (
                f"LinkedIn export folder not found: {folder}. Put your LinkedIn "
                "CSV export (Positions/Skills/Profile) or a 'Save to PDF' profile "
                "in that folder, and point config.json 'linkedin_export_dir' at it."
            )
        }

    result = _derive_from_csv(folder, max_titles) or _derive_from_pdf(folder, max_titles)
    if result is None:
        return {
            "source": "none",
            "headline": "",
            "geo": "",
            "titles": [],
            "skills": [],
            "note": "No Positions.csv and no PDF found in the export folder.",
        }
    return result
