"""
One-time fix: archive all Presencial/Hibrido jobs outside Sevilla that leaked through.
"""
import sqlite3
import sys
from datetime import datetime

DB_PATH = "results/jobs.db"
USER_CITY = "sevilla"

conn = sqlite3.connect(DB_PATH)
conn.row_factory = sqlite3.Row

rows = conn.execute("""
    SELECT id, title, company, work_mode, location, match_score, archived, archive_reason
    FROM jobs
    WHERE archived = 0
      AND work_mode IN ('Presencial', 'Híbrido')
""").fetchall()

archived_count = 0
kept_count = 0
city = USER_CITY

for r in rows:
    loc = (r['location'] or '').lower()
    if city in loc:
        kept_count += 1
        continue
    reason = f"{r['work_mode']} fuera de ciudad objetivo ({r['location']})"
    conn.execute(
        "UPDATE jobs SET archived = 1, archive_reason = ?, _last_seen = ? WHERE id = ?",
        (reason, datetime.now().isoformat(), r['id'])
    )
    archived_count += 1
    print(f"  Archivada: {r['title'][:50]} @ {r['company'][:25]} | {r['work_mode']} | {r['location']}")

conn.commit()
conn.close()
print(f"\nOK: {archived_count} archivadas, {kept_count} mantenidas (en Sevilla)")
