"""Heuristic resume <-> job matching by skill-keyword coverage.

The score is transparent and deterministic:
  * skills are detected in the job text and in your resume;
  * coverage is WEIGHTED -- signature skills count 3, peripheral ones 1, the
    rest 2 (see CORE_SKILLS / MINOR_SKILLS);
  * a denominator floor (MIN_DENOM) stops sparse job ads from auto-scoring 100%;
  * each missing KNOCKOUT skill (a specialized must-have like SAS / Workday /
    Salesforce Data Cloud) multiplies the score down (KO_FACTOR).
It returns matched, missing, and knockout-missing skills so the score is
explainable.

Note: it still does not model seniority or non-skill credential gates
(e.g. a required degree), so treat it as a strong first pass, not a verdict.
"""
from __future__ import annotations

import os
import pathlib
import re

# Canonical skill -> alias regexes (matched case-insensitively against text).
SKILL_ALIASES: dict[str, list[str]] = {
    "Microsoft Fabric": [r"microsoft fabric", r"\bfabric\b"],
    "Azure Databricks": [r"databricks"],
    "Delta Lake": [r"delta lake"],
    "PySpark": [r"pyspark"],
    "Apache Spark": [r"\bspark\b"],
    "Synapse": [r"synapse"],
    "Azure Data Factory": [r"azure data factory", r"\badf\b"],
    "Fabric Pipelines": [r"fabric pipelines"],
    "Fivetran": [r"fivetran"],
    "Kafka": [r"kafka"],
    "Collibra": [r"collibra"],
    "Data Governance": [r"data governance"],
    "Data Lineage": [r"lineage"],
    "Metadata Management": [r"metadata"],
    "Power BI": [r"power\s*bi"],
    "DAX": [r"\bdax\b"],
    "Tableau": [r"tableau"],
    "Looker": [r"looker"],
    "Python": [r"\bpython\b"],
    "SQL": [r"\bsql\b"],
    "T-SQL": [r"t-sql", r"tsql"],
    "PL/SQL": [r"pl/sql", r"plsql"],
    "SAS": [r"\bsas\b"],
    "Oracle": [r"\boracle\b"],
    "OBIEE": [r"obiee"],
    "Oracle Analytics Cloud": [r"oracle analytics", r"\boac\b"],
    "Data Modeling": [r"data model", r"dimensional model"],
    "Medallion/Lakehouse": [r"medallion", r"lakehouse"],
    "Data Mesh": [r"data mesh"],
    "ETL/ELT": [r"\betl\b", r"\belt\b"],
    "CI/CD": [r"ci/cd", r"\bci cd\b"],
    "Azure": [r"\bazure\b"],
    "Entra ID / Azure AD": [r"entra", r"azure ad"],
    "Azure Key Vault": [r"key vault"],
    "Semantic Model": [r"semantic model", r"semantic layer"],
    "Snowflake": [r"snowflake"],
    "BigQuery": [r"bigquery"],
    "Row-Level Security": [r"row-level security", r"row level security"],
    "Power Query / M": [r"power query"],
    "Power Automate": [r"power automate"],
    "Essbase": [r"essbase"],
    "HFM/FDMEE": [r"\bhfm\b", r"fdmee"],
    # Skills commonly required but NOT in this resume -- surface as gaps:
    "Workday": [r"workday"],
    "Salesforce Data Cloud": [r"data cloud", r"salesforce"],
    "Identity Resolution / CDP": [r"identity resolution", r"\bcdp\b"],
    "Clinical Coding (ICD-10/CIHI)": [r"icd-10", r"\bcihi\b", r"\bchima\b", r"abstracting"],
    "Crystal Reports": [r"crystal reports"],
    "Statistics/Forecasting": [r"forecasting", r"predictive model", r"statistical analysis"],
}


# Signature / high-value skills (weight 3).
CORE_SKILLS = {
    "Microsoft Fabric", "Azure Databricks", "Delta Lake", "PySpark", "Synapse",
    "Azure Data Factory", "Collibra", "Power BI", "DAX", "T-SQL", "PL/SQL",
    "OBIEE", "Oracle Analytics Cloud", "Oracle", "Medallion/Lakehouse",
    "Data Governance", "Semantic Model", "Data Modeling",
}
# Nice-to-have / peripheral skills (weight 1) -- missing these barely hurts.
MINOR_SKILLS = {
    "Snowflake", "Looker", "Apache Spark", "Crystal Reports", "Statistics/Forecasting",
}
# Specialized skills that, when a job requires them and the resume lacks them,
# are near disqualifying. Each missing knockout multiplies the score down.
KNOCKOUT_SKILLS = {
    "Workday", "Salesforce Data Cloud", "Identity Resolution / CDP",
    "Clinical Coding (ICD-10/CIHI)", "SAS",
}
MIN_DENOM = 10.0     # floor on weighted job skills, so sparse JDs can't auto-100%
KO_FACTOR = 0.6      # score multiplier applied per missing knockout skill


def _weight(skill: str) -> float:
    if skill in CORE_SKILLS:
        return 3.0
    if skill in MINOR_SKILLS:
        return 1.0
    return 2.0


def _skills_in(text: str) -> set[str]:
    t = (text or "").lower()
    return {skill for skill, pats in SKILL_ALIASES.items()
            if any(re.search(p, t) for p in pats)}


def resume_skills(resume_text: str) -> set[str]:
    s = _skills_in(resume_text)
    if "PySpark" in s:        # PySpark experience implies Spark
        s.add("Apache Spark")
    return s


def score_job(job_text: str, res_skills: set[str]) -> dict:
    job_skills = _skills_in(job_text)
    if not job_skills:
        return {"match": 0, "matched": [], "missing": [], "knockouts_missing": []}

    matched = job_skills & res_skills
    missing = job_skills - res_skills

    # Weighted coverage over the non-knockout skills, with a denominator floor.
    non_ko = [s for s in job_skills if s not in KNOCKOUT_SKILLS]
    numer = sum(_weight(s) for s in matched if s not in KNOCKOUT_SKILLS)
    denom = max(sum(_weight(s) for s in non_ko), MIN_DENOM)
    base = min(100.0, 100.0 * numer / denom)

    # Knockout penalty: each required-but-missing specialized skill scales it down.
    ko_missing = sorted(s for s in missing if s in KNOCKOUT_SKILLS)
    score = base * (KO_FACTOR ** len(ko_missing))

    return {
        "match": round(score),
        "matched": sorted(matched),
        "missing": sorted(missing),
        "knockouts_missing": ko_missing,
    }


def load_resume_text(resume_path: str) -> str:
    p = pathlib.Path(os.path.expandvars(resume_path or ""))
    if not p.exists():
        return ""
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader
        return "\n".join((pg.extract_text() or "") for pg in PdfReader(str(p)).pages)
    return p.read_text(encoding="utf-8", errors="ignore")
