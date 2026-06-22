# mcp-job-search

[![CI](https://github.com/rajivdatta/mcp-job-search/actions/workflows/ci.yml/badge.svg)](https://github.com/rajivdatta/mcp-job-search/actions/workflows/ci.yml)

An MCP server that finds **recent job postings based on your LinkedIn profile**,
scores each against your **resume**, and logs the results — all without logging
into or scraping LinkedIn.

> **Why no LinkedIn scraping?** LinkedIn's User Agreement prohibits automated
> access, and scraping risks your account. Instead this server reads search
> terms from a LinkedIn export *you* download, and pulls listings from the
> **JSearch API**, which aggregates postings (including LinkedIn's) via Google
> for Jobs.

## How it works

```
LinkedIn export (CSV or PDF)  ->  search terms
                                      |
                              JSearch API (last week)
                                      |
                 filter to LinkedIn + drop already-seen
                                      |
              score vs resume (weighted skill coverage)
                                      |
            logs/matches-*.log  +  reports/job_match-*.html
```

## Tools

| Tool | What it does |
| --- | --- |
| `get_profile_terms` | Show the search terms derived from your LinkedIn export + the queries that will run. |
| `search_jobs` | Search all profile queries (default: last week), de-dupe, return new postings, write a log. |
| `match_jobs` | Like `search_jobs`, plus fetch each job's full description and **score it against your resume** (weighted skill-coverage %, knockout penalties), ranked best-fit first. Writes a text log **and a styled HTML report**. |
| `search_jobs_custom` | Run a single ad-hoc query. |
| `reset_seen_jobs` | Forget previously-seen jobs so the next run shows everything again. |

---

## Setup (step by step)

### 1. Install

```powershell
git clone https://github.com/rajivdatta/mcp-job-search.git
cd mcp-job-search
python -m venv .venv
.venv\Scripts\activate          # Windows  (use: source .venv/bin/activate on macOS/Linux)
pip install -r requirements.txt
```

### 2. Get a JSearch API key (free)

1. Create a RapidAPI account → https://rapidapi.com/auth/sign-up
2. Open the JSearch API → https://rapidapi.com/letscrape-6bRBa3QguO5/api/jsearch
3. Click **Subscribe to Test** (or the **Pricing** tab) and choose the **Basic / Free** plan → **Subscribe**.
4. On the **Endpoints** tab, the right-hand code panel shows a header
   `X-RapidAPI-Key: <your-key>`. Copy that key.

### 3. Create your `.env`

Copy [`.env.example`](.env.example) to `.env` and paste your key:

```
RAPIDAPI_KEY=your-rapidapi-key-here
```

`.env` is git-ignored — your key never leaves your machine.

### 4. Provide your LinkedIn profile

Either form works (CSV is more precise; PDF is quicker):

- **CSV export** — LinkedIn → *Settings → Data Privacy → Get a copy of your
  data* → include **Profile**, **Positions**, **Skills** → download and extract
  the ZIP into a folder.
- **PDF** — your profile page → *More → Save to PDF*. Drop the PDF into a folder.

The server reads your most-recent titles, headline, and top skills to build
search queries.

### 5. Create your `config.json`

Copy [`config.example.json`](config.example.json) to `config.json` and edit it:

```jsonc
{
  "linkedin_export_dir": "C:\\path\\to\\LinkedInExport",  // folder with your CSV export or PDF
  "resume_path":         "C:\\path\\to\\resume.pdf",      // .pdf or .txt, used by match_jobs
  "location":            "Toronto, Ontario, Canada",       // appended to each query
  "country":             "ca",                             // JSearch 2-letter country code
  "date_posted":         "week",                           // today | 3days | week | month
  "num_pages":           1,                                // JSearch pages per query (~10 jobs/page)
  "max_queries":         3,                                // how many profile titles to search
  "log_dir":             "logs",                           // where text logs are written
  "query_override":      [],                               // set explicit queries to skip profile parsing
  "only_linkedin":       true,                             // keep only LinkedIn-sourced postings
  "only_new":            true                              // across runs, return only jobs not seen before
}
```

#### Config field reference

| Field | Required | Notes |
| --- | --- | --- |
| `linkedin_export_dir` | for profile-based search | Folder containing your LinkedIn CSV export **or** a profile PDF. |
| `resume_path` | for `match_jobs` | Path to your resume (`.pdf` or `.txt`). |
| `location` | recommended | Free-text location appended to each query, e.g. `"Toronto, Ontario, Canada"`. |
| `country` | recommended | JSearch country code (`ca`, `us`, `gb`, …). |
| `date_posted` | optional | Recency window: `today`, `3days`, `week` (default), `month`. |
| `num_pages` | optional | Pages fetched per query; each page ≈ 10 jobs. Higher = more results + more API usage. |
| `max_queries` | optional | Caps how many profile-derived titles are searched (to limit API calls). |
| `log_dir` | optional | Directory for text logs (default `logs`). |
| `query_override` | optional | A list of explicit query strings. If non-empty, profile parsing is skipped and these are used verbatim. |
| `only_linkedin` | optional | `true` keeps only postings whose source is LinkedIn. |
| `only_new` | optional | `true` remembers shown jobs (in `state/seen_jobs.json`) and returns only unseen ones on later runs. |

### 6. Test it standalone

```powershell
.venv\Scripts\activate
python -c "import json, server; print(server.get_profile_terms())"   # check derived queries
python -c "import json, server; print(server.match_jobs())"          # live search + match
```

Outputs land in `logs/` and `reports/`.

### 7. Register with your MCP host

Add a server entry pointing at the venv's Python and `server.py` (see
[`examples/mcp.json`](examples/mcp.json)):

```json
{
  "mcpServers": {
    "job-search": {
      "command": "C:\\path\\to\\mcp-job-search\\.venv\\Scripts\\python.exe",
      "args": ["C:\\path\\to\\mcp-job-search\\server.py"],
      "env": { "RAPIDAPI_KEY": "your-key-or-leave-it-in-.env" }
    }
  }
}
```

Restart your MCP client, then try: *"using job-search, match jobs"*.

---

## Scheduling (optional)

To run the search automatically each day, use the included helpers — they call
the same `match_jobs` logic directly, so no MCP host needs to be running:

- `run_daily.py` — runs `match_jobs`, writes the report/log, appends a status
  line to `logs/daily_runs.log`.
- `run_daily_hidden.vbs` — launches `run_daily.py` via the venv Python with **no
  console window** (self-locating; works from any folder).
- `setup_schedule.ps1` — registers a Windows Scheduled Task.

```powershell
# from the repo folder, after creating .venv and installing requirements:
.\setup_schedule.ps1               # daily at 16:00 (4 PM)
.\setup_schedule.ps1 -At "08:30"   # custom time
```

The task runs when you're logged on. To run while logged off, enable "Run
whether the user is logged on or not" in Task Scheduler (stores your password).
Remove it with `Unregister-ScheduledTask -TaskName "MCP Job Search Daily"`.

On macOS/Linux, schedule `python run_daily.py` with cron instead.

## Dedupe across runs

With `only_new: true`, `search_jobs` and `match_jobs` remember every posting they
show (in `state/seen_jobs.json`) and return only postings you haven't seen on
later runs. Each result reports `total_found`, `new_jobs`, and
`suppressed_already_seen`. Pass `only_new=false` to a single call to see the full
list once, or call `reset_seen_jobs` to clear the memory.

## Matching (how the score works)

`match_jobs` detects known skills in the job description and your resume, then
scores **weighted coverage** = (weighted skills you have that the job asks for) /
(weighted skills the job asks for), with:
- **core skills weighted higher** than peripheral ones,
- a **denominator floor** so sparse ads can't auto-score 100%,
- a **knockout penalty** when a specialized must-have (e.g. SAS, Workday,
  Salesforce Data Cloud) is required but missing.

Each job reports `matched_skills`, `missing_skills`, and `knockouts_missing`, so
the number is explainable. It's a fast first pass — it does not model seniority
or non-skill credential gates. Tune the skill sets and constants at the top of
[`match.py`](match.py).

## Output & privacy

- `logs/` — text logs of each search/match run
- `reports/job_match_<date>.html` — a **cumulative** styled match report per day.
  Re-running on the same day merges in new matches and keeps earlier ones; the
  latest run's additions are flagged **NEW** (so a second run never shrinks it).
- `state/seen_jobs.json` — the all-time dedupe memory
- `state/results_<date>.json` — today's accumulated matches (backs the cumulative report)

`.env`, `config.json`, `logs/`, `reports/`, `state/`, and the export folder are
all git-ignored — nothing personal is committed.

## License

[MIT](LICENSE)
