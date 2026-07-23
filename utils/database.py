import sqlite3
import json
import os
import hashlib
import unicodedata
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent / "results" / "jobs.db"

JSON_FIELDS = {
    "tech_stack", "cv_experience_adapted", "cv_skills", "cv_projects",
    "interview_prep", "company_profile", "project_match",
    "scraper_stats", "errors", "profile_skills", "profile_roles",
    "all_links",
}


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text)
    text = "".join(c for c in text if not unicodedata.combining(c))
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def generate_job_id(title: str, company: str) -> str:
    raw = f"{_normalize_text(title)}|{_normalize_text(company)}"
    return hashlib.md5(raw.encode("utf-8")).hexdigest()[:12]


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
        self._lock = threading.RLock()
        self._connection = sqlite3.connect(str(path), check_same_thread=False)
        self._connection.row_factory = sqlite3.Row
        self._connection.execute("PRAGMA journal_mode=WAL")
        self._connection.execute("PRAGMA busy_timeout=5000")
        self._init_tables()
        self._migrate_schema()

    def _init_tables(self):
        self._connection.executescript("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                title TEXT,
                company TEXT,
                link TEXT,
                all_links TEXT,
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
                _last_run_id TEXT
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
                job_id TEXT NOT NULL,
                PRIMARY KEY (run_id, job_id),
                FOREIGN KEY (run_id) REFERENCES runs(run_id),
                FOREIGN KEY (job_id) REFERENCES jobs(id)
            );

            CREATE INDEX IF NOT EXISTS idx_jobs_archived ON jobs(archived);
            CREATE INDEX IF NOT EXISTS idx_jobs_match ON jobs(match_score);
            CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
            CREATE INDEX IF NOT EXISTS idx_jobs_source ON jobs(source);
            CREATE INDEX IF NOT EXISTS idx_run_jobs_run ON run_jobs(run_id);
        """)
        self._connection.commit()

    def _migrate_schema(self):
        cursor = self._connection.execute("PRAGMA table_info(jobs)")
        cols = {row[1] for row in cursor.fetchall()}
        if "id" in cols:
            return
        old_data = []
        cursor = self._connection.execute("SELECT * FROM jobs")
        col_names = [d[0] for d in cursor.description]
        for row in cursor.fetchall():
            old_data.append(dict(zip(col_names, row)))
        old_rj = []
        cursor = self._connection.execute("SELECT * FROM run_jobs")
        rj_cols = [d[0] for d in cursor.description]
        for row in cursor.fetchall():
            old_rj.append(dict(zip(rj_cols, row)))
        self._connection.executescript("DROP TABLE IF EXISTS run_jobs; DROP TABLE IF EXISTS jobs;")
        self._connection.commit()
        self._init_tables()
        merged = {}
        for job in old_data:
            title = job.get("title", "")
            company = job.get("company", "")
            jid = generate_job_id(title, company)
            link = job.get("link", "")
            if jid in merged:
                existing = merged[jid]
                all_links = json.loads(existing.get("all_links") or "[]")
                if link and link not in all_links:
                    all_links.append(link)
                if len(all_links) > 1:
                    existing["all_links"] = _serialize(all_links)
                if not existing.get("link") and link:
                    existing["link"] = link
                if job.get("match_score") is not None and (existing.get("match_score") is None or job["_last_seen"] > existing.get("_last_seen", "")):
                    for k, v in job.items():
                        if k in ("link", "title", "company", "id"):
                            continue
                        if v is not None:
                            existing[k] = v
            else:
                all_links = [link] if link else []
                job["id"] = jid
                job["all_links"] = _serialize(all_links) if len(all_links) > 1 else None
                if "link" in job:
                    del job["link"]
                job.pop("_also_on", None)
                merged[jid] = job
        for jid, job in merged.items():
            self._upsert_job_tx(job)
        link_to_id = {}
        for jid, job in merged.items():
            orig_link = job.get("link", "")
            if orig_link:
                link_to_id[orig_link] = jid
            all_l = json.loads(job.get("all_links") or "[]")
            for l in all_l:
                link_to_id[l] = jid
        for rj in old_rj:
            old_link = rj.get("job_link", "")
            new_id = link_to_id.get(old_link)
            if new_id:
                self._connection.execute(
                    "INSERT OR IGNORE INTO run_jobs (run_id, job_id) VALUES (?, ?)",
                    (rj["run_id"], new_id),
                )
        self._connection.commit()
        print(f"[DB] Migrated schema: {len(merged)} jobs, {len(link_to_id)} link mappings")

    def close(self):
        if self._connection:
            self._connection.close()
            Database._connection = None
            Database._instance = None

    # ── Migración desde JSON ──

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
                jid = job.get("id") or generate_job_id(
                    job.get("title", ""), job.get("company", "")
                )
                if jid:
                    self._connection.execute(
                        "INSERT OR IGNORE INTO run_jobs (run_id, job_id) VALUES (?, ?)",
                        (run_id, jid),
                    )
                    total_jobs += 1

        self._connection.commit()

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
        title = job.get("title", "")
        company = job.get("company", "")
        jid = job.get("id") or generate_job_id(title, company)
        if not jid:
            return

        now = datetime.now().isoformat()
        link = job.get("link", "")
        existing = self._connection.execute(
            "SELECT _first_seen, _last_seen, match_score, needs_analysis, all_links FROM jobs WHERE id = ?",
            (jid,),
        ).fetchone()

        if existing:
            first_seen = existing["_first_seen"]
            last_seen = now
            existing_needs = existing["needs_analysis"]
            needs_analysis = 0 if job.get("match_score") is not None else existing_needs
            old_links = json.loads(existing["all_links"] or "[]") if existing["all_links"] else []
        else:
            first_seen = now
            last_seen = now
            needs_analysis = 1 if job.get("match_score") is None else 0
            old_links = []

        all_links = list(old_links)
        if link and link not in all_links:
            all_links.append(link)
        all_links_ser = _serialize(all_links) if len(all_links) > 1 else None

        self._connection.execute("""
            INSERT INTO jobs (
                id, title, company, link, all_links, location, description,
                date_posted, source, _scraper,
                match_score, tech_stack, work_mode,
                salary, salary_is_estimate, required_experience,
                tailored_advice, cover_letter, cv_summary,
                cv_experience_adapted, cv_skills, cv_projects,
                custom_cv_url, custom_cv_html, cover_letter_pdf_url,
                interview_prep, company_profile, project_match,
                language, status, archived, archive_reason,
                needs_analysis, _first_seen, _last_seen, _last_run_id
            ) VALUES (
                ?, ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?
            ) ON CONFLICT(id) DO UPDATE SET
                title = COALESCE(EXCLUDED.title, jobs.title),
                company = COALESCE(EXCLUDED.company, jobs.company),
                link = CASE
                    WHEN EXCLUDED.link IS NOT NULL AND EXCLUDED.link != '' THEN EXCLUDED.link
                    ELSE jobs.link
                END,
                all_links = COALESCE(EXCLUDED.all_links, jobs.all_links),
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
                _last_run_id = COALESCE(EXCLUDED._last_run_id, jobs._last_run_id)
        """, (
            jid, title, company, link or (old_links[0] if old_links else None), all_links_ser,
            job.get("location"), job.get("description"),
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
            job.get("_last_run_id"),
        ))

    def upsert_job(self, job: dict):
        self._upsert_job_tx(job)
        self._connection.commit()

    def get_job_by_id(self, jid: str) -> Optional[dict]:
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM jobs WHERE id = ?", (jid,)
            ).fetchone()
            if row is None:
                return None
            return _row_to_dict(row, row.keys())

    def get_all_jobs(self) -> list:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM jobs ORDER BY _last_seen DESC"
            ).fetchall()
            return [_row_to_dict(r, r.keys()) for r in rows] if rows else []

    def get_jobs_needing_analysis(self) -> list:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM jobs WHERE needs_analysis = 1 ORDER BY _last_seen DESC"
            ).fetchall()
            return [_row_to_dict(r, r.keys()) for r in rows] if rows else []

    def get_archived_jobs(self) -> list:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM jobs WHERE archived = 1 ORDER BY _last_seen DESC"
            ).fetchall()
            return [_row_to_dict(r, r.keys()) for r in rows] if rows else []

    def update_job(self, jid: str, updates: dict):
        if not updates:
            return
        with self._lock:
            sets = []
            vals = []
            for key, val in updates.items():
                if key in ("id", "link", "all_links"):
                    continue
                if key in JSON_FIELDS:
                    sets.append(f"{key} = ?")
                    vals.append(_serialize(val))
                elif key in ("salary_is_estimate", "archived", "needs_analysis"):
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
            vals.append(jid)
            sql = f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?"
            self._connection.execute(sql, vals)
            self._connection.commit()

    def update_job_status(self, jid: str, status: str) -> bool:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET status = ?, _last_seen = ? WHERE id = ?",
                (status, datetime.now().isoformat(), jid),
            )
            self._connection.commit()
            return self._connection.total_changes > 0

    def update_job_archived(self, jid: str, archived: bool, reason: str = None) -> bool:
        with self._lock:
            self._connection.execute(
                "UPDATE jobs SET archived = ?, archive_reason = ?, _last_seen = ? WHERE id = ?",
                (1 if archived else 0, reason, datetime.now().isoformat(), jid),
            )
            self._connection.commit()
            return self._connection.total_changes > 0

    def update_job_analysis(self, jid: str, updates: dict) -> bool:
        updates["needs_analysis"] = False
        self.update_job(jid, updates)
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
        with self._lock:
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
        with self._lock:
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
        with self._lock:
            row = self._connection.execute(
                "SELECT * FROM runs ORDER BY timestamp DESC LIMIT 1"
            ).fetchone()
            if row is None:
                return None
            d = dict(row)
            for field in ("scraper_stats", "errors", "profile_skills", "profile_roles"):
                d[field] = _deserialize(d[field], field)
            return d

    def add_run_jobs(self, run_id: str, job_ids: list):
        with self._lock:
            for jid in job_ids:
                self._connection.execute(
                    "INSERT OR IGNORE INTO run_jobs (run_id, job_id) VALUES (?, ?)",
                    (run_id, jid),
                )
            self._connection.commit()

    def get_run_job_ids(self, run_id: str) -> list:
        with self._lock:
            rows = self._connection.execute(
                "SELECT job_id FROM run_jobs WHERE run_id = ?", (run_id,)
            ).fetchall()
            return [r["job_id"] for r in rows] if rows else []

    # ── Stats helpers ──

    def get_job_count(self) -> int:
        with self._lock:
            row = self._connection.execute("SELECT COUNT(*) as c FROM jobs").fetchone()
            return row["c"] if row else 0

    def get_analyzed_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) as c FROM jobs WHERE needs_analysis = 0"
            ).fetchone()
            return row["c"] if row else 0

    def get_unanalyzed_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) as c FROM jobs WHERE needs_analysis = 1"
            ).fetchone()
            return row["c"] if row else 0

    def get_archived_count(self) -> int:
        with self._lock:
            row = self._connection.execute(
                "SELECT COUNT(*) as c FROM jobs WHERE archived = 1"
            ).fetchone()
            return row["c"] if row else 0

    def get_history(self) -> list:
        with self._lock:
            rows = self._connection.execute(
                "SELECT * FROM runs ORDER BY timestamp ASC"
            ).fetchall()
            result = []
            for r in rows:
                d = dict(r)
                for field in ("scraper_stats", "errors", "profile_skills", "profile_roles"):
                    d[field] = _deserialize(d[field], field)
                stats = d.get("scraper_stats", {}) or {}
                scrapers_ok = sum(1 for s in stats.values() if not s.get("failed") and s.get("found", 0) > 0)
                scrapers_fail = sum(1 for s in stats.values() if s.get("failed") or s.get("error"))
                result.append({
                    "Fecha": d.get("timestamp", "")[:10],
                    "Encontradas": sum(s.get("found", 0) for s in stats.values()),
                    "Anadidas": d.get("_total_added", 0),
                    "Analizadas": d.get("_analyzed_by_gemini", 0),
                    "Scrapers OK": scrapers_ok,
                    "Scrapers FAIL": scrapers_fail,
                })
            return result

    # ── Export ──

    def export_data_json(self, output_path: str = None):
        with self._lock:
            runs = self.get_all_runs()
            exported_job_ids = set()
            output = {"runs": []}
            for run in runs:
                run_id = run["run_id"]
                job_ids = self.get_run_job_ids(run_id)
                jobs = []
                for jid in job_ids:
                    job = self.get_job_by_id(jid)
                    if job:
                        jobs.append(job)
                        exported_job_ids.add(jid)
                run["jobs"] = jobs
                output["runs"].append(run)

            orphans = self._connection.execute(
                "SELECT id FROM jobs WHERE id NOT IN ({})".format(
                    ",".join("?" for _ in exported_job_ids) if exported_job_ids else "''"
                ),
                list(exported_job_ids) if exported_job_ids else ()
            ).fetchall()
            if orphans:
                orphan_run = {
                    "run_id": "_orphan",
                    "timestamp": "",
                    "jobs": []
                }
                for row in orphans:
                    job = self.get_job_by_id(row[0])
                    if job:
                        orphan_run["jobs"].append(job)
                if orphan_run["jobs"]:
                    output["runs"].append(orphan_run)

            if output_path is None:
                output_path = os.path.join(os.path.dirname(self.db_path), "data.json")
            with open(output_path, "w", encoding="utf-8") as f:
                json.dump(output, f, ensure_ascii=False, indent=2)
            total = sum(len(r.get('jobs', [])) for r in output['runs'])
            print(f"[DB] Exportado data.json ({total} jobs en {len(output['runs'])} runs)")
