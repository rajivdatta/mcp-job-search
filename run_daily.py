"""Daily runner for Windows Task Scheduler.

Runs match_jobs (which respects `only_new` in config, so each day surfaces only
postings not seen before), writes the text log + HTML report, and appends a
one-line status to logs/daily_runs.log. No console interaction required.
"""
import os
import sys

# Under pythonw.exe (what the scheduler runs) there is no console, so
# sys.stdout/sys.stderr are None and some imports (e.g. FastMCP's logging)
# crash. Give them a sink before importing the server.
if sys.stdout is None:
    sys.stdout = open(os.devnull, "w", encoding="utf-8")
if sys.stderr is None:
    sys.stderr = open(os.devnull, "w", encoding="utf-8")

import datetime
import json
import pathlib

import server

HERE = pathlib.Path(__file__).parent


def main() -> None:
    stamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    try:
        out = json.loads(server.match_jobs())
        line = (f"{stamp}  OK  new={out.get('new_jobs')}  "
                f"total={out.get('total_found')}  report={out.get('html_report')}")
    except Exception as exc:  # never crash the scheduled task silently
        line = f"{stamp}  ERROR  {exc}"

    log_dir = HERE / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    with open(log_dir / "daily_runs.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line)


if __name__ == "__main__":
    main()
