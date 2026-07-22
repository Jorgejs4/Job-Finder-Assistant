import sqlite3
import json
import os
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent / "results" / "jobs.db"

JSON_FIELDS = {
    "tech_stack", "cv_experience_adapted", "cv_skills", "cv_projects",
    "interview_prep", "company_profile", "project_match",
    "scraper_stats", "errors", "profile_skills", "profile_roles",
}


def _serialize(val):
    if val is None:
        return None
    if isinstance(val, (list, dict)):
        return json.dumps(val, ensure_ascii=False)
    return val


def _deserialize(val, field):
    if val is None:
        return None
    if field in JSON_FIELDS:
        try:
            return json.loads(val)
        except (json.JSONDecodeError, TypeError):
            return val
    return val


def _row_to_dict(row, columns):
    d = {}
    for i, col in enumerate(columns):
        val = row[i]
        d[col] = _deserialize(val, col)
    return d


class Database:
    _instance = None
    _connection = None

    def __new__(cls, db_path=None):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_path=None):
        if self._connection is not None:
            return
        path = db_path or DB_PATH
        os.makedirs(os.path.dirname(path), exist_ok=True)
        self.db_path = path
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._init_tables()

    def _init_tables(self):
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                link TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                location TEXT,
                description TEXT,
                date_posted TEXT,
                source TEXT,
                _scraper TEXT,
                match_score INTEGER,
                tech_stack TEXT,
                work_mode TEXT,
                salary TEXT,
                salary_is_estimate INTEGER DEFAULT 0,
                required_experience INTEGER,
                tailored_advice TEXT,
                cover_letter TEXT,
                cv_summary TEXT,
                cv_experience_adapted TEXT,
                cv_skills TEXT,
                cv_projects TEXT,
                custom_cv_url TEXT,
                custom_cv_html TEXT,
                cover_letter_pdf_url TEXT,
                interview_prep TEXT,
                company_profile TEXT,
                project_match TEXT,
                language TEXT,
                status TEXT DEFAULT 'Nuevo',
                archived INTEGER DEFAULT 0,
                archive_reason TEXT,
                needs_analysis INTEGER DEFAULT 1,
                _first_seen TEXT,
                _last_seen TEXT,
                _last_run_id TEXT,
                _also_on TEXT
            );

            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY,
                timestamp TEXT NOT NULL,
                scraper_stats TEXT,
                errors TEXT,
                _total_added INTEGER DEFAULT 0,
                _analyzed_count INTEGER DEFAULT 0,
                _analyzed_by_gemini INTEGER DEFAULT 0,
                profile_skills TEXT,
                profile_roles TEXT,
                profile_summary TEXT
            );

            CREATE TABLE IF NOT EXISTS run_jobs (
                run_id TEXT NOT NULL,
                job_link TEXT NOT NULL,
                PRIMARY KEY (run_id, job_link),
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (job_link) REFERENCES jobs(link)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_archived ON jobs(archived);
            CREATE INDEX IF NOT EXISTS idx_jobs_match ON jobs(match_score);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
            CREATE INDEX IF NOT EXISTS idx_run_jobs_run ON run_jobs(run_id);
        """)
        self._connection.commit()

    def close(self):
        if self._connection:
            self._connection.close()
            Database._connection = None
            Database._instance = None

    # ── Migración ──

    def migrate_from_json(self, json_path: str) -> dict:
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        runs = data.get("runs", [])
        total_jobs = 0
        total_runs = 0

        for run in runs:
            run_id = run.get("run_id", "")
            if not run_id:
                continue

            scraper_stats = _serialize(run.get("scraper_stats", {}))
            errors_data = _serialize(run.get("errors", []))
            profile_skills = _serialize(run.get("profile_skills", []))
            profile_roles = _serialize(run.get("profile_roles", []))
            profile_summary = run.get("profile_summary", "")

            self._connection.execute("""
                INSERT OR IGNORE INTO runs
                    (run_id, timestamp, scraper_stats, errors,
                     _total_added, _analyzed_count, _analyzed_by_gemini,
                     profile_skills, profile_roles, profile_summary)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                run_id, run.get("timestamp", ""),
                scraper_stats, errors_data,
                run.get("_total_added", 0),
                run.get("_analyzed_count", 0),
                run.get("_analyzed_by_gemini", 0),
                profile_skills, profile_roles, profile_summary,
            ))
            total_runs += 1

            for job in run.get("jobs", []):
                self._upsert_job_tx(job)
                link = job.get("link", "")
                if link:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO run_jobs (run_id, job_link) VALUES (?, ?)",
                        (run_id, link),
                    )
                    total_jobs += 1

        self._connection.commit()

        # Mark migrated jobs without match_score as needs_analysis=1
        self._connection.execute(
            "UPDATE jobs SET needs_analysis = 1 WHERE match_score IS NULL"
        )
        self._connection.execute(
            "UPDATE jobs SET needs_analysis = 0 WHERE match_score IS NOT NULL"
        )
        self._connection.commit()

        return {"runs": total_runs, "jobs": total_jobs}

    # ── Job CRUD ──

    def _upsert_job_tx(self, job: dict):
        link = job.get("link", "")
        if not link:
            return

        now = datetime.now().isoformat()

        existing = self._connection.execute(
            "SELECT _first_seen, _last_seen, match_score, needs_analysis FROM jobs WHERE link = ?",
            (link,),
        ).fetchone()

        if existing:
            first_seen = existing["_first_seen"]
            last_seen = now
            existing_needs = existing["needs_analysis"]
            needs_analysis = 0 if job.get("match_score") is not None else existing_needs
        else:
            first_seen = now
            last_seen = now
            needs_analysis = 1 if job.get("match_score") is None else 0

        self._connection.execute("""
            INSERT INTO jobs (
                link, title, company, location, description,
                date_posted, source, _scraper,
                match_score, tech_stack, work_mode,
                salary, salary_is_estimate, required_experience,
                tailored_advice, cover_letter, cv_summary,
                cv_experience_adapted, cv_skills, cv_projects,
                custom_cv_url, custom_cv_html, cover_letter_pdf_url,
                interview_prep, company_profile, project_match,
                language, status, archived, archive_reason,
                needs_analysis, _first_seen, _last_seen, _last_run_id, _also_on
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?
            ) ON CONFLICT(link) DO UPDATE SET
                title = COALESCE(EXCLUDED.title, jobs.title),
                company = COALESCE(EXCLUDED.company, jobs.company),
                location = COALESCE(EXCLUDED.location, jobs.location),
                description = COALESCE(EXCLUDED.description, jobs.description),
                date_posted = COALESCE(EXCLUDED.date_posted, jobs.date_posted),
                source = COALESCE(EXCLUDED.source, jobs.source),
                _scraper = COALESCE(EXCLUDED._scraper, jobs._scraper),
                match_score = COALESCE(EXCLUDED.match_score, jobs.match_score),
                tech_stack = COALESCE(EXCLUDED.tech_stack, jobs.tech_stack),
                work_mode = COALESCE(EXCLUDED.work_mode, jobs.work_mode),
                salary = COALESCE(EXCLUDED.salary, jobs.salary),
                salary_is_estimate = COALESCE(EXCLUDED.salary_is_estimate, jobs.salary_is_estimate),
                required_experience = COALESCE(EXCLUDED.required_experience, jobs.required_experience),
                tailored_advice = COALESCE(EXCLUDED.tailored_advice, jobs.tailored_advice),
                cover_letter = COALESCE(EXCLUDED.cover_letter, jobs.cover_letter),
                cv_summary = COALESCE(EXCLUDED.cv_summary, jobs.cv_summary),
                cv_experience_adapted = COALESCE(EXCLUDED.cv_experience_adapted, jobs.cv_experience_adapted),
                cv_skills = COALESCE(EXCLUDED.cv_skills, jobs.cv_skills),
                cv_projects = COALESCE(EXCLUDED.cv_projects, jobs.cv_projects),
                custom_cv_url = COALESCE(EXCLUDED.custom_cv_url, jobs.custom_cv_url),
                custom_cv_html = COALESCE(EXCLUDED.custom_cv_html, jobs.custom_cv_html),
                cover_letter_pdf_url = COALESCE(EXCLUDED.cover_letter_pdf_url, jobs.cover_letter_pdf_url),
                interview_prep = COALESCE(EXCLUDED.interview_prep, jobs.interview_prep),
                company_profile = COALESCE(EXCLUDED.company_profile, jobs.company_profile),
                project_match = COALESCE(EXCLUDED.project_match, jobs.project_match),
                language = COALESCE(EXCLUDED.language, jobs.language),
                status = COALESCE(EXCLUDED.status, jobs.status),
                archived = COALESCE(EXCLUDED.archived, jobs.archived),
                archive_reason = COALESCE(EXCLUDED.archive_reason, jobs.archive_reason),
                needs_analysis = COALESCE(EXCLUDED.needs_analysis, jobs.needs_analysis),
                _first_seen = COALESCE(EXCLUDED._first_seen, jobs._first_seen),
                _last_seen = EXCLUDED._last_seen,
                _last_run_id = COALESCE(EXCLUDED._last_run_id, jobs._last_run_id),
                _also_on = COALESCE(EXCLUDED._also_on, jobs._also_on)
        """, (
            link, job.get("title"), job.get("company"), job.get("location"), job.get("description"),
            job.get("date_posted"), job.get("source"), job.get("_scraper"),
            job.get("match_score"), _serialize(job.get("tech_stack")), job.get("work_mode"),
            str(job.get("salary", "")) if job.get("salary") is not None else None,
            1 if job.get("salary_is_estimate") else 0,
            job.get("required_experience"),
            job.get("tailored_advice"), job.get("cover_letter"), job.get("cv_summary"),
            _serialize(job.get("cv_experience_adapted")),
            _serialize(job.get("cv_skills")),
            _serialize(job.get("cv_projects")),
            job.get("custom_cv_url"), job.get("custom_cv_html"), job.get("cover_letter_pdf_url"),
            _serialize(job.get("interview_prep")),
            _serialize(job.get("company_profile")),
            _serialize(job.get("project_match")),
            job.get("language"), job.get("status", "Nuevo"),
            1 if job.get("archived") else 0,
            job.get("archive_reason"),
            needs_analysis, first_seen, last_seen,
            job.get("_last_run_id"), job.get("_also_on"),
        ))

    def upsert_job(self, job: dict):
        self._upsert_job_tx(job)
        self._connection.commit()

    def get_job_by_link(self, link: str) -> Optional[dict]:
        row = self._connection.execute(
            "SELECT * FROM jobs WHERE link = ?", (link,)
        ).fetchone()
        if row is None:
            return None
        return _row_to_dict(row, row.keys())

    def get_all_jobs(self) -> list:
        rows = self._connection.execute(
            "SELECT * FROM jobs ORDER BY _last_seen DESC"
        ).fetchall()
        return [_row_to_dict(r, r.keys()) for r in rows] if rows else []

    def get_jobs_needing_analysis(self) -> list:
        rows = self._connection.execute(
            "SELECT * FROM jobs WHERE needs_analysis = 1 ORDER BY _last_seen DESC"
        ).fetchall()
        return [_row_to_dict(r, r.keys()) for r in rows] if rows else []

    def get_archived_jobs(self) -> list:
        rows = self._connection.execute(
            "SELECT * FROM jobs WHERE archived = 1 ORDER BY _last_seen DESC"
        ).fetchall()
        return [_row_to_dict(r, r.keys()) for r in rows] if rows else []

    def update_job(self, link: str, updates: dict):
        if not updates:
            return
        sets = []
        vals = []
        for key, val in updates.items():
            if key == "link":
                continue
            if key in JSON_FIELDS:
                sets.append(f"{key} = ?")
                vals.append(_serialize(val))
            elif key == "salary_is_estimate":
                sets.append(f"{key} = ?")
                vals.append(1 if val else 0)
            elif key == "archived":
                sets.append(f"{key} = ?")
                vals.append(1 if val else 0)
            elif key == "needs_analysis":
                sets.append(f"{key} = ?")
                vals.append(1 if val else 0)
            elif key == "match_score":
                sets.append(f"{key} = ?")
                vals.append(int(val) if val is not None else None)
            else:
                sets.append(f"{key} = ?")
                vals.append(val)
        sets.append("_last_seen = ?")
        vals.append(datetime.now().isoformat())
        vals.append(link)
        sql = f"UPDATE jobs SET {', '.join(sets)} WHERE link = ?"
        self._connection.execute(sql, vals)
        self._connection.commit()

    def update_job_status(self, link: str, status: str) -> bool:
        self._connection.execute(
            "UPDATE jobs SET status = ?, _last_seen = ? WHERE link = ?",
            (status, datetime.now().isoformat(), link),
        )
        self._connection.commit()
        return self._connection.total_changes > 0

    def update_job_archived(self, link: str, archived: bool, reason: str = None) -> bool:
        self._connection.execute(
            "UPDATE jobs SET archived = ?, archive_reason = ?, _last_seen = ? WHERE link = ?",
            (1 if archived else 0, reason, datetime.now().isoformat(), link),
        )
        self._connection.commit()
        return self._connection.total_changes > 0

    def update_job_analysis(self, link: str, updates: dict) -> bool:
        updates["needs_analysis"] = False
        self.update_job(link, updates)
        return True

    # ── Run CRUD ──

    def create_run(self, run_data: dict) -> str:
        run_id = run_data.get("run_id", datetime.now().strftime("%Y%m%d_%H%M%S"))
        self._connection.execute("""
            INSERT OR REPLACE INTO runs
                (run_id, timestamp, scraper_stats, errors,
                 _total_added, _analyzed_count, _analyzed_by_gemini,
                 profile_skills, profile_roles, profile_summary)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            run_id, run_data.get("timestamp", datetime.now().isoformat()),
            _serialize(run_data.get("scraper_stats", {})),
            _serialize(run_data.get("errors", [])),
            run_data.get("_total_added", 0),
            run_data.get("_analyzed_count", 0),
            run_data.get("_analyzed_by_gemini", 0),
            _serialize(run_data.get("profile_skills", [])),
            _serialize(run_data.get("profile_roles", [])),
            run_data.get("profile_summary", ""),
        ))
        self._connection.commit()
        return run_id

    def get_all_runs(self) -> list:
        rows = self._connection.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC"
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            for field in ("scraper_stats", "errors", "profile_skills", "profile_roles"):
                d[field] = _deserialize(d[field], field)
            result.append(d)
        return result

    def get_run(self, run_id: str) -> Optional[dict]:
        row = self._connection.execute(
            "SELECT * FROM runs WHERE run_id = ?", (run_id,)
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        for field in ("scraper_stats", "errors", "profile_skills", "profile_roles"):
            d[field] = _deserialize(d[field], field)
        return d

    def get_latest_run(self) -> Optional[dict]:
        row = self._connection.execute(
            "SELECT * FROM runs ORDER BY timestamp DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        d = dict(row)
        for field in ("scraper_stats", "errors", "profile_skills", "profile_roles"):
            d[field] = _deserialize(d[field], field)
        return d

    def add_run_jobs(self, run_id: str, links: list):
        for link in links:
            self._connection.execute(
                "INSERT OR IGNORE INTO run_jobs (run_id, job_link) VALUES (?, ?)",
                (run_id, link),
            )
        self._connection.commit()

    def get_run_job_links(self, run_id: str) -> list:
        rows = self._connection.execute(
            "SELECT job_link FROM run_jobs WHERE run_id = ?", (run_id,)
        ).fetchall()
        return [r["job_link"] for r in rows] if rows else []

    # ── Feedback (simple JSON file, still simple enough) ──
    # Feedback stays in JSON for now — no need to overcomplicate

    # ── Stats helpers ──

    def get_job_count(self) -> int:
        row = self._connection.execute("SELECT COUNT(*) as c FROM jobs").fetchone()
        return row["c"] if row else 0

    def get_analyzed_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE needs_analysis = 0"
        ).fetchone()
        return row["c"] if row else 0

    def get_unanalyzed_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE needs_analysis = 1"
        ).fetchone()
        return row["c"] if row else 0

    def get_archived_count(self) -> int:
        row = self._connection.execute(
            "SELECT COUNT(*) as c FROM jobs WHERE archived = 1"
        ).fetchone()
        return row["c"] if row else 0

    # ── Export ──

    def export_data_json(self, output_path: str = None):
        """Exporta toda la DB al formato data.json compatible con CI/CD."""
        runs = self.get_all_runs()
        output = {"runs": []}
        for run in runs:
            run_id = run["run_id"]
            job_links = self.get_run_job_links(run_id)
            jobs = []
            for link in job_links:
                job = self.get_job_by_link(link)
                if job:
                    jobs.append(job)
            run["jobs"] = jobs
            output["runs"].append(run)
        if output_path is None:
            output_path = os.path.join(os.path.dirname(self.db_path), "data.json")
        with open(output_path, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)
        print(f"[DB] Exportado data.json ({sum(len(r.get('jobs', [])) for r in output['runs'])} jobs en {len(output['runs'])} runs)")
