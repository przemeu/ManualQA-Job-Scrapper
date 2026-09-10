import sqlite3
import os
from typing import Optional, Dict, Any, List

DB_PATH = 'jobs.db'

def get_db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            url TEXT UNIQUE NOT NULL,
            source TEXT,
            city TEXT DEFAULT '',
            pay TEXT DEFAULT '',
            published_at TEXT DEFAULT '',
            status TEXT DEFAULT 'NEW',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    ''')
    # Migrate: add city, pay, and published_at columns if they don't exist yet
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN city TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN pay TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN published_at TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN stage TEXT DEFAULT 'To Apply'")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN notes TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN salary_asked TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN interview_date TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN company TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN is_manual INTEGER DEFAULT 0")
    except sqlite3.OperationalError:
        pass  # column already exists
    try:
        cursor.execute("ALTER TABLE jobs ADD COLUMN contract_type TEXT DEFAULT ''")
    except sqlite3.OperationalError:
        pass  # column already exists
    # Create settings table
    cursor.execute('''
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT
        )
    ''')
    # Default settings
    defaults = {
        'auto_scan_enabled': 'false',
        'scan_interval_minutes': '60',
        'desktop_notifications': 'true',
        'telegram_notifications': 'false',
        'telegram_token': '',
        'telegram_chat_id': '',
        'last_scan_time': ''
    }
    for k, v in defaults.items():
        cursor.execute("INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v))
        
    conn.commit()
    conn.close()
    
    # Automatically backfill company, clean pay, and contract types for legacy records
    backfill_empty_companies()
    backfill_clean_pay()
    backfill_contract_types()
    clean_database_duplicates()

def infer_contract_type(title="", url="", source="", pay="", full_text=""):
    import re
    combined = f"{title} {url} {pay} {full_text}".lower()
    
    has_b2b = bool(re.search(r'(?i)\b(b2b|kontrakt|faktura|faktur[eę]|vat)\b', combined))
    has_uop = bool(re.search(r'(?i)\b(uop|umow[ae]\s*o\s*prac[eę]|o\s*prac[eę]|permanent|etat|employment)\b', combined))
    
    pay_lower = pay.lower()
    if '/ h' in pay_lower or '/h' in pay_lower or '/ d' in pay_lower or '/d' in pay_lower:
        has_b2b = True
        
    if has_b2b and has_uop:
        return 'B2B / UoP'
    elif has_b2b:
        return 'B2B'
    elif has_uop:
        return 'UoP'
        
    if source == 'Pracuj':
        return 'UoP'
    elif source in ['JJIT', 'NFJ', 'Solid', 'Bulldog', 'QABoard']:
        if pay and any(k in pay_lower for k in ['/ h', '/ d', 'eur']):
            return 'B2B'
        return 'B2B / UoP'
    elif source == 'LinkedIn':
        return 'B2B / UoP'
        
    return 'B2B / UoP'

def backfill_contract_types():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, url, source, pay, contract_type FROM jobs WHERE contract_type IS NULL OR contract_type = ''")
    rows = cursor.fetchall()
    updated = 0
    for r in rows:
        ctype = infer_contract_type(title=r['title'] or '', url=r['url'] or '', source=r['source'] or '', pay=r['pay'] or '')
        if ctype:
            cursor.execute("UPDATE jobs SET contract_type = ? WHERE id = ?", (ctype, r['id']))
            updated += 1
    conn.commit()
    conn.close()
    return updated

def backfill_clean_pay():
    import parsers
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, pay FROM jobs WHERE pay IS NOT NULL AND pay != ''")
    rows = cursor.fetchall()
    updated = 0
    for r in rows:
        old_pay = r['pay']
        cleaned = parsers.clean_pay(old_pay)
        if cleaned != old_pay:
            cursor.execute("UPDATE jobs SET pay = ? WHERE id = ?", (cleaned, r['id']))
            updated += 1
    conn.commit()
    conn.close()
    return updated

def infer_company_from_job(row):
    jid = row['id']
    title = row['title'] or ''
    url = row['url'] or ''
    source = row['source'] or ''
    import re
    
    # 1. LinkedIn: ...-at-(company)-(digits)
    if 'linkedin.com' in url or source == 'LinkedIn':
        m = re.search(r'-at-([a-zA-Z0-9-]+?)-\d+$', url)
        if m:
            c = m.group(1).replace('-', ' ')
            return re.sub(r'\b(sp\s*z\s*o\s*o|sp\s*k|sa|inc|llc|gmbh)\b', '', c, flags=re.I).strip().title()
            
    # 2. JJIT: /job-offer/(company)-(title-tokens)...
    if 'justjoin.it' in url or source == 'JJIT':
        slug = url.split('/job-offer/')[-1].split('?')[0].rstrip('/')
        slug = re.sub(r'-[0-9a-f]{8,}$', '', slug)
        m = re.split(r'-(?:senior|junior|mid|regular|lead|qa|tester|manual|quality|test|software|application)', slug, maxsplit=1, flags=re.I)
        if m and m[0]:
            c = m[0].replace('-', ' ')
            return re.sub(r'\b(sp\s*z\s*o\s*o|sp\s*k|sa|inc|llc|gmbh)\b', '', c, flags=re.I).strip().title()
            
    # 3. NFJ: /job/(title)-(company)-(city)
    if 'nofluffjobs.com' in url or source == 'NFJ':
        slug = url.split('/job/')[-1].split('?')[0].rstrip('/')
        slug = re.sub(r'-\d+$', '', slug)
        slug = re.sub(r'-(?:remote|gdansk|warszawa|krakow|katowice|wroclaw|poznan|lodz|trojmiasto|gliwice|szczecin|bydgoszcz|lublin)$', '', slug, flags=re.I)
        tokens = slug.split('-')
        title_words = set(re.findall(r'\w+', title.lower()))
        comp_tokens = [t for t in tokens if t.lower() not in title_words and t.lower() not in ['k', 'm', 'f', 'x', 'senior', 'junior', 'lead', 'specjalista', 'inzynier']]
        if comp_tokens:
            c = ' '.join(comp_tokens)
            return re.sub(r'\b(sp\s*z\s*o\s*o|sp\s*k|sa|inc|llc|gmbh)\b', '', c, flags=re.I).strip().title()

    # 4. Solid: /offer/(id)/(company)-(title)
    if 'solid.jobs' in url or source == 'Solid':
        m = re.search(r'/offer/\d+/([^/]+)', url)
        if m:
            slug = m.group(1)
            parts = re.split(r'-(?:tester|qa|quality|manual)', slug, maxsplit=1, flags=re.I)
            if parts and parts[0]:
                return parts[0].replace('-', ' ').title()

    # 5. Bulldog: /jobs/(id)-(title)-(company)
    if 'bulldogjob.pl' in url or source == 'Bulldog':
        m = re.search(r'/jobs/\d+-(.*)', url)
        if m:
            slug = m.group(1)
            parts = slug.split('-')
            return (parts[-1] if len(parts) > 1 else parts[0]).replace('-', ' ').title()

    # 6. RocketJobs: /oferta-pracy/(company)-(title)...
    if 'rocketjobs.pl' in url or source == 'RocketJobs':
        slug = url.split('/oferta-pracy/')[-1].split('?')[0].rstrip('/')
        parts = slug.split('-')
        if parts:
            return parts[0].replace('-', ' ').title()

    if 'qaboard.pl' in url or source == 'QABoard':
        return "Quality Island"

    if source == 'Pracuj':
        return "Pracuj.pl Partner"
        
    return "Unknown Company"

def backfill_empty_companies():
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT id, title, url, source, company FROM jobs WHERE company IS NULL OR company = ''")
    rows = cursor.fetchall()
    updated = 0
    for r in rows:
        comp = infer_company_from_job(r)
        if comp:
            cursor.execute("UPDATE jobs SET company = ? WHERE id = ?", (comp, r['id']))
            updated += 1
    conn.commit()
    conn.close()
    return updated

def get_setting(key: str, default: str = "") -> str:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
    row = cursor.fetchone()
    conn.close()
    return row['value'] if row else default

def set_setting(key: str, value: str):
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value", (key, str(value)))
    conn.commit()
    conn.close()

def get_all_settings() -> dict:
    conn = get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM settings")
    rows = cursor.fetchall()
    conn.close()
    return {row['key']: row['value'] for row in rows}

def update_job_pipeline(job_id: int, stage: str = None, notes: str = None, salary_asked: str = None, interview_date: str = None):
    conn = get_db()
    cursor = conn.cursor()
    updates = []
    params = []
    if stage is not None:
        updates.append("stage = ?")
        params.append(stage)
    if notes is not None:
        updates.append("notes = ?")
        params.append(notes)
    if salary_asked is not None:
        updates.append("salary_asked = ?")
        params.append(salary_asked)
    if interview_date is not None:
        updates.append("interview_date = ?")
        params.append(interview_date)
        
    if updates:
        params.append(job_id)
        sql = f"UPDATE jobs SET {', '.join(updates)} WHERE id = ?"
        cursor.execute(sql, tuple(params))
        conn.commit()
    conn.close()

def find_duplicate_job(title: str, company: str, url: str, conn_or_cursor=None) -> Optional[dict]:
    """
    Check if a job offer already exists in the database.
    Matches by canonical clean_url OR by normalized (company, title) across portals.
    """
    import parsers
    cu = parsers.clean_url(url)
    nc = parsers.normalize_company(company)
    nt = parsers.normalize_title(title)
    
    close_at_end = False
    if conn_or_cursor is None:
        conn = get_db()
        cursor = conn.cursor()
        close_at_end = True
    elif isinstance(conn_or_cursor, sqlite3.Connection):
        conn = conn_or_cursor
        cursor = conn.cursor()
    else:
        cursor = conn_or_cursor
        conn = None

    try:
        # 1. Exact or clean URL match
        if cu:
            cursor.execute("SELECT * FROM jobs WHERE url = ? OR url LIKE ?", (cu, cu + '%'))
            row = cursor.fetchone()
            if row:
                return dict(row)
                
        # 2. Cross-portal (company, title) match
        if nc and nt and not parsers.is_generic_company(nc):
            cursor.execute("SELECT * FROM jobs")
            for r in cursor.fetchall():
                r_nc = parsers.normalize_company(r['company'] or '')
                r_nt = parsers.normalize_title(r['title'] or '')
                if r_nc == nc and r_nt == nt:
                    return dict(r)
    finally:
        if close_at_end and conn:
            conn.close()
            
    return None

def clean_database_duplicates(conn=None) -> dict:
    """
    Finds duplicate clusters across all portals in jobs.db and removes duplicates.
    Resolution priority:
    1. If any job in the cluster is APPLIED / ACCEPTED, keep that job (the only accepted one).
       If multiple are APPLIED, keep the one with most pipeline progress/earliest applied.
    2. If none are APPLIED, keep the earliest user-evaluated decision (IGNORED or WRONG).
    3. If none are evaluated (all NEW), keep the earliest created record.
    4. Merges rich metadata (specific company, salary, city, notes) into the winner before deleting losers.
    5. Normalizes all remaining URLs to clean canonical URLs.
    """
    import parsers
    from collections import defaultdict
    
    close_at_end = False
    if conn is None:
        conn = get_db()
        close_at_end = True
        
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs ORDER BY id ASC")
    rows = [dict(r) for r in cursor.fetchall()]
    
    if not rows:
        if close_at_end:
            conn.close()
        return {"clusters_found": 0, "deleted_count": 0, "remaining": 0}
        
    parent = {r['id']: r['id'] for r in rows}
    def find(i):
        if parent[i] != i:
            parent[i] = find(parent[i])
        return parent[i]

    def union(i, j):
        ri = find(i)
        rj = find(j)
        if ri != rj:
            parent[ri] = rj

    # 1. Group by clean_url
    url_map = defaultdict(list)
    for r in rows:
        cu = parsers.clean_url(r['url'])
        if cu:
            url_map[cu].append(r['id'])

    for ids in url_map.values():
        for a, b in zip(ids[:-1], ids[1:]):
            union(a, b)

    # 2. Group by normalized (company, title)
    comp_title_map = defaultdict(list)
    for r in rows:
        nc = parsers.normalize_company(r['company'] or '')
        nt = parsers.normalize_title(r['title'] or '')
        if nc and nt and not parsers.is_generic_company(nc):
            comp_title_map[(nc, nt)].append(r['id'])

    for ids in comp_title_map.values():
        for a, b in zip(ids[:-1], ids[1:]):
            union(a, b)

    clusters = defaultdict(list)
    for r in rows:
        clusters[find(r['id'])].append(r)

    dup_clusters = [c for c in clusters.values() if len(c) > 1]
    deleted_ids = []
    cluster_summaries = []
    
    for c in dup_clusters:
        c.sort(key=lambda x: x['id'])
        applied = [x for x in c if x.get('status') in ('APPLIED', 'ACCEPTED')]
        
        if applied:
            winner = sorted(applied, key=lambda x: (
                bool((x.get('notes') or '').strip() or (x.get('interview_date') or '').strip() or (x.get('stage') and x.get('stage') not in ('To Apply', 'Applied'))),
                -x['id']
            ), reverse=True)[0]
        else:
            evaluated = [x for x in c if x.get('status') in ('IGNORED', 'WRONG')]
            if evaluated:
                winner = evaluated[0]
            else:
                winner = c[0]

        losers = [x for x in c if x['id'] != winner['id']]
        loser_ids = [x['id'] for x in losers]
        deleted_ids.extend(loser_ids)
        
        # Merge useful metadata from losers to winner
        updated_fields = {}
        winner_nc = parsers.normalize_company(winner.get('company') or '')
        if parsers.is_generic_company(winner_nc):
            better_comp = next((x['company'] for x in c if not parsers.is_generic_company(parsers.normalize_company(x.get('company') or ''))), None)
            if better_comp:
                updated_fields['company'] = better_comp
                winner['company'] = better_comp

        if (not winner.get('pay') or winner.get('pay') == 'Not given') and any(x.get('pay') and x.get('pay') != 'Not given' for x in c):
            better_pay = next(x['pay'] for x in c if x.get('pay') and x.get('pay') != 'Not given')
            updated_fields['pay'] = better_pay
            winner['pay'] = better_pay

        if (not winner.get('city') or winner.get('city') == 'Remote') and any(x.get('city') and 'remote' not in x.get('city').lower() for x in c):
            better_city = next(x['city'] for x in c if x.get('city') and 'remote' not in x.get('city').lower())
            updated_fields['city'] = better_city
            winner['city'] = better_city

        # Merge notes if any
        loser_notes = [x['notes'].strip() for x in c if x['id'] != winner['id'] and (x.get('notes') or '').strip()]
        if loser_notes:
            winner_note = (winner.get('notes') or '').strip()
            all_notes = ([winner_note] if winner_note else []) + [n for n in loser_notes if n != winner_note]
            combined_notes = "\n".join(all_notes)
            if combined_notes != winner_note:
                updated_fields['notes'] = combined_notes
                winner['notes'] = combined_notes

        # Canonical clean URL
        winner_clean_url = parsers.clean_url(winner.get('url') or '')
        if winner_clean_url and winner_clean_url != winner.get('url'):
            updated_fields['url'] = winner_clean_url
            winner['url'] = winner_clean_url

        if updated_fields:
            set_clause = ", ".join([f"{k} = ?" for k in updated_fields.keys()])
            cursor.execute(f"UPDATE jobs SET {set_clause} WHERE id = ?", list(updated_fields.values()) + [winner['id']])

        cursor.execute(f"DELETE FROM jobs WHERE id IN ({','.join(['?']*len(loser_ids))})", loser_ids)
        
        cluster_summaries.append({
            "winner_id": winner['id'],
            "winner_title": winner['title'],
            "winner_company": winner['company'],
            "winner_status": winner['status'],
            "deleted_ids": loser_ids
        })

    # Ensure all remaining URLs are canonical clean URLs
    cursor.execute("SELECT id, url FROM jobs")
    for r in cursor.fetchall():
        cu = parsers.clean_url(r['url'])
        if cu and cu != r['url']:
            try:
                cursor.execute("UPDATE jobs SET url = ? WHERE id = ?", (cu, r['id']))
            except sqlite3.IntegrityError:
                cursor.execute("DELETE FROM jobs WHERE id = ?", (r['id'],))
                deleted_ids.append(r['id'])

    conn.commit()
    if close_at_end:
        conn.close()

    return {
        "total_before": len(rows),
        "clusters_found": len(dup_clusters),
        "deleted_count": len(deleted_ids),
        "remaining": len(rows) - len(deleted_ids),
        "clusters": cluster_summaries
    }

if __name__ == '__main__':
    init_db()
    print("Database initialized.")

