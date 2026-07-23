import sqlite3
from datetime import datetime

conn = sqlite3.connect('results/jobs.db')
conn.row_factory = sqlite3.Row
city = 'sevilla'

rows = conn.execute("""
    SELECT id, title, company, work_mode, location FROM jobs 
    WHERE archived = 0 AND (location NOT LIKE '%sevilla%' OR location IS NULL OR location = '')
""").fetchall()

archived = 0
for r in rows:
    loc = (r['location'] or '').lower()
    wm = r['work_mode'] or 'Presencial'
    if wm == 'Remoto':
        continue
    if city in loc:
        continue
    reason = f"{wm} fuera de ciudad objetivo ({r['location']})"
    conn.execute("UPDATE jobs SET archived = 1, archive_reason = ?, _last_seen = ? WHERE id = ?",
                 (reason, datetime.now().isoformat(), r['id']))
    archived += 1
    print(f"  Archivada: {r['title'][:50]} @ {r['company'][:25]} | {wm} | {r['location']}")

conn.commit()
conn.close()
print(f"\nOK: {archived} archivadas")
