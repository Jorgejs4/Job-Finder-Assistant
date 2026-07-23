"""
Apply archive rules to ALL non-archived jobs in the DB.
This fixes jobs that were analyzed before the archive logic existed,
or that leaked through due to bugs in the archive pipeline.
"""
import sqlite3
import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.dirname(__file__))
import config

DB_PATH = os.path.join(os.path.dirname(__file__), "results", "jobs.db")
USER_CITY = config.USER_CITY

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT id, title, company, work_mode, location, match_score, description,
           archived, archive_reason
    FROM jobs
    WHERE archived = 0
""").fetchall()

archived_count = 0
kept_count = 0
skipped_count = 0

for r in rows:
    job_id = r["id"]
    title = r["title"] or ""
    company = r["company"] or ""
    location = r["location"] or ""
    description = r["description"] or ""
    match_score = r["match_score"]

    # Reclassify work_mode using text rules
    job_dict = {
        "title": title,
        "company": company,
        "location": location,
        "description": description,
        "work_mode": r["work_mode"] or "",
    }
    wm = config.reclassify_work_mode(job_dict)

    reason = None

    # 1. Geo-restriction keywords
    loc_title_desc = f"{location} {title} {description}".lower()
    for kw in config.GEO_RESTRICT_KEYWORDS:
        if kw in loc_title_desc:
            reason = config.ArchiveReason.geo_restriction(kw)
            break

    # 2. Low match
    if not reason and match_score is not None and match_score < config.MIN_MATCH_TO_ARCHIVE:
        reason = config.ArchiveReason.low_match(match_score)

    # 3. Modalidad + ubicacion
    if not reason and wm != "Remoto":
        loc_lower = location.lower()
        if USER_CITY not in loc_lower:
            reason = config.ArchiveReason.location_mismatch(wm, location)

    if reason:
        conn.execute(
            "UPDATE jobs SET archived = 1, archive_reason = ?, work_mode = ?, _last_seen = ? WHERE id = ?",
            (reason, wm, datetime.now().isoformat(), job_id)
        )
        archived_count += 1
        print(f"  ARCHIVADA: {title[:50]} @ {company[:25]} | {wm} | {location} | {reason}")
    else:
        # Update work_mode even if not archiving
        if wm != (r["work_mode"] or ""):
            conn.execute(
                "UPDATE jobs SET work_mode = ?, _last_seen = ? WHERE id = ?",
                (wm, datetime.now().isoformat(), job_id)
            )
        kept_count += 1

conn.commit()

# Summary
print(f"\n{'='*60}")
print(f"RESUMEN:")
print(f"  Archivadas: {archived_count}")
print(f"  Mantenidas: {kept_count}")

# Verify: how many Presencial/Hibrido outside Sevilla remain non-archived?
verify = conn.execute("""
    SELECT COUNT(*) as c FROM jobs
    WHERE archived = 0
    AND work_mode IN ('Presencial', 'Híbrido')
    AND (location IS NULL OR location NOT LIKE '%sevilla%')
""").fetchone()
print(f"  Presencial/Hibrido fuera de Sevilla sin archivar: {verify['c']}")

# How many total archived now?
total_arch = conn.execute("SELECT COUNT(*) as c FROM jobs WHERE archived = 1").fetchone()
total_all = conn.execute("SELECT COUNT(*) as c FROM jobs").fetchone()
print(f"  Total archivadas: {total_arch['c']} / {total_all['c']}")

conn.close()
