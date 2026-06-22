"""mcp-job-search - an MCP server that searches recent job postings based on
your LinkedIn profile export and logs the results to a file.

Profile terms come from a LinkedIn data export (see profile.py); listings come
from the JSearch API (see jsearch.py). Nothing logs into or scrapes LinkedIn.

Tools:
  get_profile_terms     - show the search terms derived from your export
  search_jobs           - search all profile queries (default: last week), log results
  search_jobs_custom    - run a single ad-hoc query

Run standalone:  python server.py
"""
from __future__ import annotations

import datetime
import html
import json
import os
import pathlib

from dotenv import load_dotenv
from fastmcp import FastMCP

import jsearch
import match
import profile as profile_mod

HERE = pathlib.Path(__file__).parent
load_dotenv(HERE / ".env")

_cfg_path = HERE / "config.json"
if not _cfg_path.exists():
    _cfg_path = HERE / "config.example.json"
CONFIG = json.loads(_cfg_path.read_text(encoding="utf-8"))

mcp = FastMCP("mcp-job-search")


def _api_key() -> str:
    key = os.environ.get("RAPIDAPI_KEY")
    if not key:
        raise RuntimeError("RAPIDAPI_KEY is not set. Add it to .env or the MCP host env block.")
    return key


def _queries() -> list[str]:
    if CONFIG.get("query_override"):
        return list(CONFIG["query_override"])
    terms = profile_mod.derive(CONFIG["linkedin_export_dir"], CONFIG.get("max_queries", 3))
    if "error" in terms:
        raise RuntimeError(terms["error"])
    location = CONFIG.get("location", "").strip()
    titles = terms.get("titles") or []
    queries = [f"{t} in {location}" if location else t for t in titles]
    if not queries and location:
        queries = [location]
    return queries


def _normalize(job: dict, matched_query: str) -> dict:
    loc = ", ".join(x for x in [job.get("job_city"), job.get("job_state"),
                                job.get("job_country")] if x)
    return {
        "title": job.get("job_title"),
        "company": job.get("employer_name"),
        "location": loc,
        "posted": job.get("job_posted_at_datetime_utc"),
        "source": job.get("job_publisher"),
        "apply_link": job.get("job_apply_link"),
        "matched_query": matched_query,
    }


def _write_log(jobs: list[dict], date_posted: str) -> str:
    log_dir = HERE / CONFIG.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    path = log_dir / f"jobs_{now:%Y-%m-%d}.log"
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"Job search run {now:%Y-%m-%d %H:%M:%S}  |  window: {date_posted}  |  {len(jobs)} jobs\n")
        f.write("=" * 72 + "\n")
        for i, j in enumerate(jobs, 1):
            f.write(f"{i:>3}. {j['title']}  @  {j['company']}\n")
            f.write(f"     Location: {j['location'] or 'n/a'}\n")
            f.write(f"     Posted:   {j['posted'] or 'n/a'}    Source: {j['source'] or 'n/a'}\n")
            f.write(f"     Apply:    {j['apply_link'] or 'n/a'}\n")
            f.write(f"     Matched:  {j['matched_query']}\n")
    return str(path)


STATE_DIR = HERE / "state"
SEEN_FILE = STATE_DIR / "seen_jobs.json"


def _load_seen() -> dict:
    if SEEN_FILE.exists():
        try:
            return json.loads(SEEN_FILE.read_text(encoding="utf-8"))
        except Exception:
            return {}
    return {}


def _save_seen(seen: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    SEEN_FILE.write_text(json.dumps(seen, indent=2), encoding="utf-8")


def _job_key(raw: dict) -> str:
    """Stable identity for a posting across runs."""
    jid = raw.get("job_id")
    if jid:
        return str(jid)
    link = raw.get("job_apply_link") or raw.get("apply_link") or ""
    if link:
        return link.split("?")[0]
    title = raw.get("job_title") or raw.get("title") or ""
    comp = raw.get("employer_name") or raw.get("company") or ""
    return f"{title}|{comp}".lower()


def _apply_only_new(items: list[dict], only_new: bool | None):
    """Drop postings already recorded in the seen-store, then record the current
    batch. Returns (items_to_return, suppressed_count). Each item must carry '_key'.
    When dedupe is off, just strips the internal key. """
    use = CONFIG.get("only_new", True) if only_new is None else only_new
    if not use:
        for it in items:
            it.pop("_key", None)
        return items, 0
    seen = _load_seen()
    fresh = [it for it in items if it["_key"] not in seen]
    suppressed = len(items) - len(fresh)
    now = datetime.datetime.now().isoformat(timespec="seconds")
    for it in items:
        seen.setdefault(it["_key"], {"first_seen": now,
                                     "title": it.get("title"),
                                     "company": it.get("company")})
    _save_seen(seen)
    for it in items:
        it.pop("_key", None)
    return fresh, suppressed


@mcp.tool()
def get_profile_terms() -> str:
    """Show the search terms derived from your LinkedIn data export, and the
    exact queries that `search_jobs` will run."""
    terms = profile_mod.derive(CONFIG["linkedin_export_dir"], CONFIG.get("max_queries", 3))
    if "error" not in terms:
        terms["queries_that_will_run"] = _queries()
    return json.dumps(terms, indent=2)


@mcp.tool()
def search_jobs(date_posted: str | None = None, write_log: bool = True,
                only_new: bool | None = None) -> str:
    """Search jobs for every profile-derived query, de-duplicate, sort newest
    first, and (by default) append them to a dated logfile.

    date_posted: today | 3days | week | month  (default from config = 'week').
    """
    dp = date_posted or CONFIG.get("date_posted", "week")
    key = _api_key()
    country = CONFIG.get("country")
    num_pages = CONFIG.get("num_pages", 1)

    seen: set = set()
    jobs: list[dict] = []
    for q in _queries():
        for raw in jsearch.search(q, key, date_posted=dp, num_pages=num_pages, country=country):
            jid = raw.get("job_id") or (raw.get("job_title"), raw.get("employer_name"), raw.get("job_city"))
            if jid in seen:
                continue
            seen.add(jid)
            item = _normalize(raw, q)
            item["_key"] = _job_key(raw)
            jobs.append(item)

    if CONFIG.get("only_linkedin"):
        jobs = [j for j in jobs if (j.get("source") or "").lower() == "linkedin"]

    jobs.sort(key=lambda x: x["posted"] or "", reverse=True)
    total = len(jobs)
    jobs, suppressed = _apply_only_new(jobs, only_new)
    result = {
        "date_posted": dp,
        "queries": _queries(),
        "only_linkedin": bool(CONFIG.get("only_linkedin")),
        "total_found": total,
        "new_jobs": len(jobs),
        "suppressed_already_seen": suppressed,
        "jobs": jobs,
    }
    if write_log:
        result["logfile"] = _write_log(jobs, dp)
    return json.dumps(result, indent=2, default=str)


def _write_match_log(jobs: list[dict], date_posted: str, skill_count: int) -> str:
    log_dir = HERE / CONFIG.get("log_dir", "logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    path = log_dir / f"matches_{now:%Y-%m-%d}.log"
    with open(path, "a", encoding="utf-8") as f:
        f.write("\n" + "=" * 72 + "\n")
        f.write(f"Job-match run {now:%Y-%m-%d %H:%M:%S}  |  window: {date_posted}  |  "
                f"{len(jobs)} jobs  |  {skill_count} resume skills\n")
        f.write("=" * 72 + "\n")
        for i, j in enumerate(jobs, 1):
            f.write(f"{i:>3}. [{j['match']:>3}%]  {j['title']}  @  {j['company']}\n")
            f.write(f"      matched: {', '.join(j['matched_skills']) or 'none'}\n")
            f.write(f"      missing: {', '.join(j['missing_skills']) or 'none'}\n")
            if j.get("knockouts_missing"):
                f.write(f"      KNOCKOUT gaps: {', '.join(j['knockouts_missing'])}\n")
            f.write(f"      {j['apply_link'] or 'n/a'}\n")
    return str(path)


def _match_color(pct: int) -> str:
    if pct >= 85:
        return "#1a7f37"   # green
    if pct >= 65:
        return "#9a6700"   # amber
    return "#b35900"       # orange


def _write_match_html(jobs: list[dict], date_posted: str, skill_count: int) -> str:
    rep_dir = HERE / "reports"
    rep_dir.mkdir(parents=True, exist_ok=True)
    now = datetime.datetime.now()
    path = rep_dir / f"job_match_{now:%Y-%m-%d}.html"
    new_count = sum(1 for j in jobs if j.get("is_new"))

    rows = ""
    for i, j in enumerate(jobs, 1):
        matched = html.escape(", ".join((j.get("matched_skills") or [])[:10]) or "-")
        kos = set(j.get("knockouts_missing") or [])
        parts = [(f'<b style="color:#b3261e;">{html.escape(m)}</b>' if m in kos else html.escape(m))
                 for m in (j.get("missing_skills") or [])]
        missing = ", ".join(parts) or "-"
        link = html.escape(j.get("apply_link") or "")
        badge = ('<span style="background:#1a7f37;color:#fff;font-size:10px;font-weight:700;'
                 'padding:1px 5px;border-radius:3px;margin-right:6px;">NEW</span>'
                 if j.get("is_new") else "")
        rows += (
            "<tr>"
            f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center;">{i}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;">{badge}<a href="{link}" '
            f'style="color:#0a66c2;text-decoration:none;">{html.escape(j.get("title") or "")}</a></td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;">{html.escape(j["company"] or "")}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center;font-weight:700;'
            f'color:{_match_color(j["match"])};">{j["match"]}%</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;color:#444;font-size:13px;">{matched}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;color:#444;font-size:13px;">{missing}</td>'
            f'<td style="padding:8px;border-bottom:1px solid #eee;text-align:center;white-space:nowrap;">'
            f'{(j.get("posted") or "")[:10]}</td>'
            "</tr>"
        )

    doc = (
        '<!doctype html><html><head><meta charset="utf-8"><title>Job Match Report</title></head>'
        '<body style="font-family:Segoe UI,Arial,sans-serif;color:#222;max-width:1080px;margin:24px auto;padding:0 16px;">'
        '<h2 style="margin-bottom:2px;">Job Match Report</h2>'
        f'<p style="color:#666;margin-top:0;">{len(jobs)} matches collected today (cumulative) - '
        f'{new_count} new in the latest run. Window: {html.escape(date_posted)}; '
        f'{skill_count} resume skills. Updated {now:%Y-%m-%d %H:%M}. Sorted best fit first.</p>'
        '<table style="border-collapse:collapse;width:100%;font-size:14px;">'
        '<thead><tr style="background:#0a66c2;color:#fff;text-align:left;">'
        '<th style="padding:9px;text-align:center;">#</th><th style="padding:9px;">Job Title (click to apply)</th>'
        '<th style="padding:9px;">Company</th><th style="padding:9px;text-align:center;">Match</th>'
        '<th style="padding:9px;">Matched skills</th><th style="padding:9px;">Gaps (knockouts in red)</th>'
        '<th style="padding:9px;text-align:center;">Posted</th></tr></thead>'
        f'<tbody>{rows}</tbody></table>'
        '<p style="color:#888;font-size:12px;margin-top:14px;">Cumulative for the day - re-running adds '
        'new matches without removing earlier ones. Weighted skill-coverage with a denominator floor '
        'and a knockout penalty; a heuristic first pass. Generated by the job-search MCP.</p>'
        '</body></html>'
    )
    path.write_text(doc, encoding="utf-8")
    return str(path)


def _merge_day_results(items: list[dict], now_iso: str) -> list[dict]:
    """Merge this run's jobs into today's cumulative store and return the full
    day's set (sorted by match), flagging which were added in this run."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    day = datetime.date.today().isoformat()
    path = STATE_DIR / f"results_{day}.json"
    store = {}
    if path.exists():
        try:
            store = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            store = {}
    before = set(store.keys())
    fields = ("title", "company", "location", "posted", "source", "apply_link",
              "match", "matched_skills", "missing_skills", "knockouts_missing", "matched_query")
    for it in items:
        k = it["_key"]
        rec = {f: it.get(f) for f in fields}
        rec["first_seen"] = store.get(k, {}).get("first_seen", now_iso)
        store[k] = rec
    path.write_text(json.dumps(store, indent=2, default=str), encoding="utf-8")
    out = []
    for k, rec in store.items():
        r = dict(rec)
        r["is_new"] = k not in before
        out.append(r)
    out.sort(key=lambda x: x.get("match", 0), reverse=True)
    return out


@mcp.tool()
def match_jobs(date_posted: str | None = None, write_log: bool = True,
               only_new: bool | None = None) -> str:
    """Search jobs (last week by default), fetch each job's full description, and
    score how well it matches your resume by skill-keyword coverage.

    Returns jobs ranked by match %, each with `matched_skills`, `missing_skills`,
    and `knockouts_missing` (specialized must-haves you lack). Scoring is weighted
    skill-coverage with a denominator floor and a penalty per missing knockout
    skill; it does not model seniority or non-skill credential gates.

    Requires `resume_path` in config.json (a .pdf or .txt resume).
    """
    dp = date_posted or CONFIG.get("date_posted", "week")
    key = _api_key()
    resume_text = match.load_resume_text(CONFIG.get("resume_path", ""))
    if not resume_text.strip():
        return ("Error: resume not found. Set 'resume_path' in config.json to your "
                "resume (.pdf or .txt).")
    res_skills = match.resume_skills(resume_text)
    country = CONFIG.get("country")
    num_pages = CONFIG.get("num_pages", 1)
    only_li = CONFIG.get("only_linkedin")

    seen: set = set()
    scored: list[dict] = []
    for q in _queries():
        for raw in jsearch.search(q, key, date_posted=dp, num_pages=num_pages, country=country):
            if only_li and (raw.get("job_publisher") or "").lower() != "linkedin":
                continue
            jid = raw.get("job_id") or (raw.get("job_title"), raw.get("employer_name"))
            if jid in seen:
                continue
            seen.add(jid)
            hl = raw.get("job_highlights") or {}
            blob = " ".join([
                raw.get("job_description") or "",
                " ".join(hl.get("Qualifications") or []),
                " ".join(hl.get("Responsibilities") or []),
            ])
            s = match.score_job(blob, res_skills)
            item = _normalize(raw, q)
            item.update(match=s["match"], matched_skills=s["matched"],
                        missing_skills=s["missing"],
                        knockouts_missing=s["knockouts_missing"])
            item["_key"] = _job_key(raw)
            scored.append(item)

    scored.sort(key=lambda x: x["match"], reverse=True)
    total = len(scored)
    use_only_new = CONFIG.get("only_new", True) if only_new is None else only_new
    now_iso = datetime.datetime.now().isoformat(timespec="seconds")

    # All-time "seen" store decides what is new; then record this batch.
    seen = _load_seen()
    new_keys = {it["_key"] for it in scored if it["_key"] not in seen}
    for it in scored:
        seen.setdefault(it["_key"], {"first_seen": now_iso,
                                     "title": it.get("title"), "company": it.get("company")})
    _save_seen(seen)

    # Merge into today's cumulative store so re-runs never shrink the report.
    day_jobs = _merge_day_results(scored, now_iso) if write_log else []

    # This call returns/logs only-new jobs (default) or the full run.
    returned = [dict(it) for it in scored if (it["_key"] in new_keys or not use_only_new)]
    for it in returned:
        it.pop("_key", None)

    result = {
        "date_posted": dp,
        "resume_skill_count": len(res_skills),
        "only_linkedin": bool(only_li),
        "total_found": total,
        "new_jobs": len(returned),
        "suppressed_already_seen": total - len(returned),
        "today_total": len(day_jobs),
        "jobs": returned,
    }
    if write_log:
        result["logfile"] = _write_match_log(returned, dp, len(res_skills))
        result["html_report"] = _write_match_html(day_jobs, dp, len(res_skills))
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def search_jobs_custom(query: str, date_posted: str = "week", write_log: bool = True) -> str:
    """Run a single ad-hoc job-search query (bypasses the profile-derived ones)."""
    key = _api_key()
    raw_jobs = jsearch.search(query, key, date_posted=date_posted,
                              num_pages=CONFIG.get("num_pages", 1), country=CONFIG.get("country"))
    jobs = [_normalize(j, query) for j in raw_jobs]
    jobs.sort(key=lambda x: x["posted"] or "", reverse=True)
    result = {"query": query, "date_posted": date_posted, "job_count": len(jobs), "jobs": jobs}
    if write_log:
        result["logfile"] = _write_log(jobs, date_posted)
    return json.dumps(result, indent=2, default=str)


@mcp.tool()
def reset_seen_jobs() -> str:
    """Forget all previously-seen jobs so the next search/match treats every
    result as new again."""
    n = len(_load_seen())
    _save_seen({})
    return f"Cleared {n} remembered jobs. The next run will show all results as new."


if __name__ == "__main__":
    mcp.run()
