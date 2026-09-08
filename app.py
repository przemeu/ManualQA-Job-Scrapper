from typing import Optional
import csv
import io
import re
from fastapi import FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel
import sqlite3
import asyncio
import logging
from datetime import datetime, timezone
import database
import notifier

logger = logging.getLogger(__name__)

app = FastAPI()

# Initialize DB on startup
database.init_db()

import json
import urllib.request
from bs4 import BeautifulSoup
import parsers

class StatusUpdate(BaseModel):
    status: str

class PipelineUpdate(BaseModel):
    stage: Optional[str] = None
    notes: Optional[str] = None
    salary_asked: Optional[str] = None
    interview_date: Optional[str] = None

class SettingsUpdate(BaseModel):
    auto_scan_enabled: str = "false"
    scan_interval_minutes: str = "60"
    desktop_notifications: str = "true"
    telegram_notifications: str = "false"
    telegram_token: str = ""
    telegram_chat_id: str = ""

class TestNotificationRequest(BaseModel):
    channel: str # 'desktop' or 'telegram'
    token: str = ""
    chat_id: str = ""

class ManualJobRequest(BaseModel):
    url: str
    title: Optional[str] = ""
    company: Optional[str] = ""
    source: Optional[str] = ""
    city: Optional[str] = ""
    pay: Optional[str] = ""
    contract_type: Optional[str] = ""
    override: Optional[bool] = False

class PreviewUrlRequest(BaseModel):
    url: str

def detect_source_from_url(url: str) -> str:
    u = url.lower()
    if 'linkedin.com' in u: return 'LinkedIn'
    if 'pracuj.pl' in u: return 'Pracuj'
    if 'nofluffjobs.com' in u: return 'NFJ'
    if 'justjoin.it' in u: return 'JJIT'
    if 'theprotocol.it' in u: return 'Protocol'
    if 'bulldogjob.pl' in u: return 'Bulldog'
    if 'solid.jobs' in u: return 'Solid'
    if '4programmers.net' in u: return '4programmers'
    if 'rocketjobs.pl' in u: return 'RocketJobs'
    if 'qaboard.pl' in u: return 'QABoard'
    
    m = re.search(r'https?://(?:www\.)?([^/]+)', url)
    if m:
        domain = m.group(1).split('.')[0].title()
        return domain
    return 'Manual'

def clean_company_name(text: str) -> str:
    if not text:
        return ""
    t = text
    # Fix common mojibake/corrupted polish characters in company names
    t = re.sub(r'(?i)\bsp[^\s]*ka\s+z\s+ograniczon[^\s]*\s+odpowiedzialno[^\s]*\b', 'Sp. z o.o.', t)
    t = t.replace('SPӣKA', 'SPÓŁKA').replace('Spӣka', 'Spółka')
    t = re.sub(r'[\uFFFD\u00A0]', ' ', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def scrape_metadata_from_url(url: str) -> dict:
    url = url.strip()
    if not url.startswith('http://') and not url.startswith('https://'):
        url = 'https://' + url

    source = detect_source_from_url(url)
    title = ""
    company = ""
    city = ""
    pay = ""
    contract_type = ""
    description_text = ""
    published_at = datetime.now().strftime('%Y-%m-%d')
    
    try:
        req = urllib.request.Request(
            url,
            headers={
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36',
                'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
                'Accept-Encoding': 'identity'
            }
        )
        with urllib.request.urlopen(req, timeout=8) as response:
            raw = response.read()
            try:
                html = raw.decode('utf-8')
            except:
                html = raw.decode('iso-8859-2', errors='ignore')
                
            soup = BeautifulSoup(html, 'html.parser')
            body_text = soup.get_text(separator=' ', strip=True)
            
            # 1. JSON-LD structured data extraction
            for s in soup.find_all('script', type='application/ld+json'):
                if not s.string: continue
                try:
                    d = json.loads(s.string)
                    items = d.get('@graph', [d]) if isinstance(d, dict) else [d]
                    for item in items:
                        if not isinstance(item, dict): continue
                        if item.get('@type') in ['JobPosting', 'Posting'] or 'hiringOrganization' in item or 'jobLocation' in item:
                            if not title and item.get('title'):
                                title = item['title'].strip()
                            if not company and item.get('hiringOrganization', {}).get('name'):
                                company = item['hiringOrganization']['name'].strip()
                            if not city:
                                loc = item.get('jobLocation', {})
                                if isinstance(loc, dict):
                                    addr = loc.get('address', {})
                                    if isinstance(addr, dict) and addr.get('addressLocality'):
                                        city = addr['addressLocality'].strip()
                            if item.get('datePosted'):
                                published_at = item['datePosted'][:10]
                            if item.get('description'):
                                description_text += " " + item['description']
                except:
                    pass
            
            # 2. Title extraction fallback
            if not title:
                og_title = soup.find('meta', property='og:title') or soup.find('meta', attrs={'name': 'twitter:title'})
                if og_title and og_title.get('content'):
                    title = og_title['content'].strip()
                elif soup.find('h1'):
                    title = soup.find('h1').get_text(strip=True)
                elif soup.title:
                    title = soup.title.get_text(strip=True)
                
            if title:
                # Clean title suffixes from portals
                title = re.sub(r'(?i)\s*(\||-|•)\s*(pracuj\.pl|no\s*fluff\s*jobs|just\s*join\s*it|the\s*protocol|bulldogjob|solid\s*jobs|rocketjobs|linkedin|goldenline).*$', '', title).strip()
            
            # 3. Company extraction fallback
            if not company:
                og_site = soup.find('meta', property='og:site_name')
                if og_site and og_site.get('content'):
                    candidate = og_site['content'].strip()
                    if candidate.lower() not in ['pracuj.pl', 'justjoin.it', 'nofluffjobs', 'theprotocol', 'linkedin', 'bulldogjob', 'solid.jobs', 'rocketjobs']:
                        company = candidate
                        
            company = clean_company_name(company)
                        
            # 4. Location / City extraction fallback
            if not city:
                city = parsers.extract_city(body_text)
            
            # 5. Pay extraction
            if source == 'Pracuj':
                pay = parsers.extract_pracuj_salary(soup)
            elif source == 'Protocol':
                pay = parsers.extract_protocol_salary(soup)
            elif source == 'JJIT':
                pay = parsers.extract_jjit_salary(soup)
            elif source == 'NFJ':
                pay = parsers.extract_nfj_salary(soup)
            else:
                pay_m = parsers.PAY_REGEX.search(body_text[:1500])
                if pay_m:
                    pay = parsers.clean_pay(pay_m.group(0))
                    
            if not pay or pay in ['Not given', 'brak widełek']:
                pay_m = parsers.PAY_REGEX.search(description_text[:2000])
                if pay_m:
                    pay = parsers.clean_pay(pay_m.group(0))
                else:
                    pay = 'Not given'
                    
            if not published_at:
                pub = parsers.extract_published_date(soup, body_text)
                if pub:
                    published_at = pub

            # 6. Contract type inference
            contract_type = database.infer_contract_type(
                title=title,
                url=url,
                source=source,
                pay=pay,
                full_text=description_text + " " + body_text[:2000]
            )

    except Exception as e:
        logger.warning(f"Could not auto-scrape metadata for {url}: {e}")
        
    if not title:
        slug = url.rstrip('/').split('/')[-1].split('?')[0]
        title = re.sub(r'[-_]+', ' ', slug).strip().title()
        if not title:
            title = f"Manual Offer ({source})"
            
    if not company:
        temp_row = {'id': 0, 'title': title, 'url': url, 'source': source}
        company = database.infer_company_from_job(temp_row)
        if company == 'Unknown Company':
            company = ''
            
    if not pay or pay == 'Not given':
        pay = 'Not given'
        
    return {
        'url': url,
        'title': title,
        'company': company,
        'source': source,
        'city': city or 'Remote',
        'pay': pay,
        'contract_type': contract_type or 'B2B / UoP',
        'published_at': published_at
    }


def auto_scrape_and_notify():
    try:
        import scraper
        scrape_res = scraper.run_scraper(portal='ALL', deep=False)
        new_jobs = scrape_res.get('jobs', []) if isinstance(scrape_res, dict) else (scrape_res or [])
        conn = database.get_db()
        cursor = conn.cursor()
        added_jobs = []
        for job in new_jobs:
            try:
                contract_type = job.get('contract_type') or database.infer_contract_type(job['title'], job['url'], job['source'], job.get('pay', ''))
                cursor.execute(
                    "INSERT INTO jobs (title, company, url, source, city, pay, published_at, status, contract_type) VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', ?)",
                    (job['title'], job.get('company', ''), job['url'], job['source'], job.get('city', ''), job.get('pay', ''), job.get('published_at', ''), contract_type)
                )
                added_jobs.append(job)
            except sqlite3.IntegrityError:
                pass
        conn.commit()
        conn.close()
        
        if added_jobs:
            logger.info(f"Auto-scan found {len(added_jobs)} new jobs! Sending alerts...")
            notifier.notify_new_jobs(added_jobs)
        else:
            logger.info("Auto-scan completed: 0 new jobs.")
    except Exception as e:
        logger.error(f"Error in auto_scrape_and_notify: {e}")

async def background_scheduler_loop():
    while True:
        try:
            await asyncio.sleep(20)
            auto_enabled = database.get_setting('auto_scan_enabled', 'false').lower() == 'true'
            if not auto_enabled:
                continue
                
            interval_minutes = int(database.get_setting('scan_interval_minutes', '60'))
            last_scan = database.get_setting('last_scan_time', '')
            
            now = datetime.now(timezone.utc)
            should_run = False
            if not last_scan:
                should_run = True
            else:
                try:
                    last_dt = datetime.fromisoformat(last_scan)
                    if (now - last_dt).total_seconds() >= interval_minutes * 60:
                        should_run = True
                except:
                    should_run = True
                    
            if should_run:
                database.set_setting('last_scan_time', now.isoformat())
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, auto_scrape_and_notify)
        except Exception as e:
            logger.error(f"Error in background scheduler: {e}")

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(background_scheduler_loop())

@app.get("/api/jobs")
def get_jobs(status: str = 'NEW'):
    conn = database.get_db()
    cursor = conn.cursor()
    status_upper = status.upper()
    if status_upper == 'ALL':
        cursor.execute(
            "SELECT * FROM jobs WHERE status != 'WRONG' ORDER BY created_at DESC"
        )
    elif status_upper in ['ACCEPTED', 'APPLIED']:
        cursor.execute(
            "SELECT * FROM jobs WHERE status IN ('APPLIED', 'ACCEPTED') ORDER BY created_at DESC"
        )
    else:
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", 
            (status_upper,)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.put("/api/jobs/{job_id}/status")
def update_job_status(job_id: int, update: StatusUpdate):
    raw_status = update.status.upper()
    if raw_status in ['ACCEPTED', 'APPLIED']:
        status_val = 'APPLIED'
    elif raw_status in ['NEW', 'IGNORED', 'WRONG']:
        status_val = raw_status
    else:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    conn = database.get_db()
    cursor = conn.cursor()
    if status_val == 'APPLIED':
        cursor.execute(
            "UPDATE jobs SET status = ?, is_manual = 0, stage = CASE WHEN stage IS NULL OR stage = '' THEN 'To Apply' ELSE stage END WHERE id = ?",
            (status_val, job_id)
        )
    elif status_val in ['IGNORED', 'WRONG']:
        cursor.execute(
            "UPDATE jobs SET status = ?, is_manual = 0 WHERE id = ?",
            (status_val, job_id)
        )
    else:
        cursor.execute(
            "UPDATE jobs SET status = ? WHERE id = ?",
            (status_val, job_id)
        )
    conn.commit()
    conn.close()
    return {"message": "Status updated"}

@app.post("/api/jobs/preview-url")
def preview_url_endpoint(req: PreviewUrlRequest):
    raw_url = req.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
    meta = scrape_metadata_from_url(raw_url)
    return meta

@app.post("/api/jobs/manual")
def add_manual_job(req: ManualJobRequest):
    raw_url = req.url.strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="URL cannot be empty")
        
    if not raw_url.startswith('http://') and not raw_url.startswith('https://'):
        raw_url = 'https://' + raw_url
        
    # Auto-scrape metadata if any key fields are missing
    meta = {}
    if not req.title or not req.company or not req.source or not req.city or not req.pay or not req.contract_type:
        meta = scrape_metadata_from_url(raw_url)
        
    final_title = req.title.strip() if req.title and req.title.strip() else meta.get('title', 'Manual Offer')
    final_company = req.company.strip() if req.company and req.company.strip() else meta.get('company', '')
    final_source = req.source.strip() if req.source and req.source.strip() else meta.get('source', detect_source_from_url(raw_url))
    final_city = req.city.strip() if req.city and req.city.strip() else meta.get('city', 'Remote')
    final_pay = req.pay.strip() if req.pay and req.pay.strip() else meta.get('pay', 'Not given')
    final_contract = req.contract_type.strip() if req.contract_type and req.contract_type.strip() else (meta.get('contract_type') or database.infer_contract_type(final_title, raw_url, final_source, final_pay))
    final_published = meta.get('published_at', datetime.now().strftime('%Y-%m-%d'))
    
    conn = database.get_db()
    cursor = conn.cursor()
    
    # Check if URL already exists
    cursor.execute("SELECT id, title, company, status, stage, is_manual FROM jobs WHERE url = ?", (raw_url,))
    existing = cursor.fetchone()
    
    if existing:
        existing_id = existing['id']
        existing_status = existing['status']
        existing_stage = existing['stage'] or 'To Apply'
        
        if not req.override:
            conn.close()
            return {
                "already_exists": True,
                "job_id": existing_id,
                "title": existing['title'],
                "company": existing['company'],
                "status": existing_status,
                "stage": existing_stage,
                "is_manual": existing['is_manual'],
                "message": f"This offer is already in your tracker ({existing_status} queue, Stage: {existing_stage})."
            }
        else:
            # Overwrite & Move to NEW
            cursor.execute(
                "UPDATE jobs SET status = 'NEW', stage = 'To Apply', is_manual = 1, title = ?, company = ?, source = ?, city = ?, pay = ?, contract_type = ? WHERE id = ?",
                (final_title, final_company, final_source, final_city, final_pay, final_contract, existing_id)
            )
            conn.commit()
            conn.close()
            return {
                "message": "Offer overridden and moved to NEW queue with highlight!",
                "job_id": existing_id,
                "status": "NEW",
                "overridden": True
            }
            
    # Fresh insert
    cursor.execute(
        "INSERT INTO jobs (title, company, url, source, city, pay, published_at, status, is_manual, contract_type, stage) VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', 1, ?, 'To Apply')",
        (final_title, final_company, raw_url, final_source, final_city, final_pay, final_published, final_contract)
    )
    new_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return {
        "message": "Offer successfully added to NEW queue!",
        "job_id": new_id,
        "status": "NEW"
    }

@app.patch("/api/jobs/{job_id}/pipeline")
def update_pipeline(job_id: int, update: PipelineUpdate):
    database.update_job_pipeline(
        job_id=job_id,
        stage=update.stage,
        notes=update.notes,
        salary_asked=update.salary_asked,
        interview_date=update.interview_date
    )
    return {"message": "Pipeline updated", "job_id": job_id}

@app.get("/api/export/csv")
def export_jobs_csv(status: Optional[str] = None):
    conn = database.get_db()
    cursor = conn.cursor()
    if status and status.upper() == 'ALL':
        cursor.execute("SELECT * FROM jobs WHERE status != 'WRONG' ORDER BY created_at DESC")
    elif status and status.upper() in ['ACCEPTED', 'APPLIED']:
        cursor.execute("SELECT * FROM jobs WHERE status IN ('APPLIED', 'ACCEPTED') ORDER BY created_at DESC")
    elif status and status.upper() != 'ALL_WITH_WRONG':
        cursor.execute("SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", (status.upper(),))
    else:
        cursor.execute("SELECT * FROM jobs WHERE status != 'WRONG' ORDER BY status, created_at DESC")
    rows = cursor.fetchall()
    conn.close()
    
    output = io.StringIO()
    # Write UTF-8 BOM so Excel opens Polish characters seamlessly
    output.write('\ufeff')
    writer = csv.writer(output, delimiter=';', quoting=csv.QUOTE_MINIMAL)
    writer.writerow([
        "ID", "Title", "Company", "Source", "City", "Pay", "Status", 
        "Stage", "Salary Asked", "Interview Date", "Notes", "URL", "Date Added"
    ])
    for r in rows:
        writer.writerow([
            r['id'],
            r['title'],
            r['company'] or '',
            r['source'],
            r['city'],
            r['pay'],
            r['status'],
            r['stage'] or '',
            r['salary_asked'] or '',
            r['interview_date'] or '',
            r['notes'] or '',
            r['url'],
            r['created_at']
        ])
    
    filename = f"jobs_export_{status.lower() if status else 'all'}_{datetime.now().strftime('%Y%m%d')}.csv"
    return Response(
        content=output.getvalue().encode('utf-8'),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f"attachment; filename={filename}"}
    )

def parse_salary_range(pay: str):
    if not pay or pay in ['Not given', 'brak widełek']:
        return None
    is_eur = 'EUR' in pay or '€' in pay
    eur_rate = 4.3 if is_eur else 1.0
    is_hourly = any(x in pay.lower() for x in ['godzinowo', '/ hour', '/ h', '/h', 'godz'])
    is_daily = any(x in pay.lower() for x in ['dziennie', '/ day', '/ d', '/d', 'dzień', 'dzien'])
    is_yearly = any(x in pay.lower() for x in ['rocznie', '/ year', '/ y', '/y', 'rok'])
    
    s = pay.replace('\xa0', ' ').replace(',', '.')
    cleaned = re.sub(r'(\d+)\s+(\d{3})', r'\1\2', s)
    nums = re.findall(r'\b\d+(?:\.\d+)?\b', cleaned)
    floats = [float(n) for n in nums if float(n) > 5]
    if not floats:
        return None
    min_val = min(floats)
    max_val = max(floats)
    mult = 1.0
    if is_hourly or (min_val < 300 and not is_daily and not is_eur):
        mult = 168.0
    elif is_daily or (300 <= min_val <= 2500 and ('dzien' in pay.lower() or '/ d' in pay.lower() or '/d' in pay.lower())):
        mult = 21.0
    elif is_yearly or min_val > 100000:
        mult = 1.0 / 12.0
    return round(min_val * mult * eur_rate), round(max_val * mult * eur_rate)

@app.get("/api/insights")
def get_market_insights():
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM jobs")
    rows = cursor.fetchall()
    conn.close()

    total_jobs = len(rows)
    if total_jobs == 0:
        return {
            "total_jobs": 0,
            "salary": {},
            "portals": {},
            "locations": {},
            "pipeline": {},
            "skills": []
        }

    salary_pairs = []
    disclosed_count = 0
    salary_brackets = {
        "< 10k": 0,
        "10k - 14k": 0,
        "14k - 18k": 0,
        "18k - 22k": 0,
        "> 22k": 0
    }

    portals = {}
    remote_count = 0
    tricity_count = 0
    other_locations = {}

    pipeline_counts = {
        "To Apply": 0,
        "Applied": 0,
        "Recruiter Screen": 0,
        "Tech Interview": 0,
        "Offer": 0,
        "Rejected": 0
    }
    status_counts = {
        "NEW": 0,
        "APPLIED": 0,
        "IGNORED": 0,
        "WRONG": 0
    }

    skills_keywords = {
        "Manual / QA": ["manual", "tester", "qa", "quality assurance"],
        "API / Postman": ["api", "postman", "rest", "soap"],
        "SQL / DB": ["sql", "database", "baza"],
        "Mobile": ["mobile", "ios", "android", "mobilny"],
        "Web / Frontend": ["web", "frontend", "front-end"],
        "Automated / SDET": ["automat", "automation", "sdet", "cypress", "playwright", "selenium"]
    }
    skill_matches = {k: 0 for k in skills_keywords}

    for r in rows:
        title = (r['title'] or '').lower()
        city = (r['city'] or '').lower()
        source = r['source'] or 'Unknown'
        pay = r['pay'] or ''
        status = r['status'] or 'NEW'
        stage = r['stage'] or 'Applied'

        status_counts[status] = status_counts.get(status, 0) + 1
        if status == 'APPLIED':
            pipeline_counts[stage] = pipeline_counts.get(stage, 0) + 1

        portals[source] = portals.get(source, 0) + 1

        is_remote = 'remote' in city or 'zdaln' in city or 'remote' in title or 'zdaln' in title
        if is_remote:
            remote_count += 1
        is_tri = any(c in city for c in ['gdańsk', 'gdansk', 'gdynia', 'sopot', 'trójmiasto', 'trojmiasto'])
        if is_tri:
            tricity_count += 1
        if not is_remote and city:
            main_city = city.split(',')[0].strip().title()
            other_locations[main_city] = other_locations.get(main_city, 0) + 1

        sal = parse_salary_range(pay)
        if sal:
            disclosed_count += 1
            salary_pairs.append(sal)
            avg_mid = (sal[0] + sal[1]) / 2
            if avg_mid < 10000:
                salary_brackets["< 10k"] += 1
            elif avg_mid < 14000:
                salary_brackets["10k - 14k"] += 1
            elif avg_mid < 18000:
                salary_brackets["14k - 18k"] += 1
            elif avg_mid < 22000:
                salary_brackets["18k - 22k"] += 1
            else:
                salary_brackets["> 22k"] += 1

        for skill_name, kws in skills_keywords.items():
            if any(kw in title for kw in kws):
                skill_matches[skill_name] += 1

    avg_min = round(sum(p[0] for p in salary_pairs) / len(salary_pairs)) if salary_pairs else 0
    avg_max = round(sum(p[1] for p in salary_pairs) / len(salary_pairs)) if salary_pairs else 0
    avg_overall = round((avg_min + avg_max) / 2) if salary_pairs else 0

    return {
        "total_jobs": total_jobs,
        "salary": {
            "disclosed_count": disclosed_count,
            "disclosed_pct": round((disclosed_count / total_jobs) * 100, 1),
            "avg_min": avg_min,
            "avg_max": avg_max,
            "avg_overall": avg_overall,
            "brackets": salary_brackets
        },
        "portals": portals,
        "locations": {
            "remote_count": remote_count,
            "remote_pct": round((remote_count / total_jobs) * 100, 1),
            "tricity_count": tricity_count,
            "tricity_pct": round((tricity_count / total_jobs) * 100, 1),
            "top_cities": sorted(other_locations.items(), key=lambda x: x[1], reverse=True)[:5]
        },
        "pipeline": {
            "status_breakdown": status_counts,
            "funnel": pipeline_counts,
            "applied_total": status_counts.get("APPLIED", 0)
        },
        "skills": sorted(skill_matches.items(), key=lambda x: x[1], reverse=True)
    }

@app.get("/api/settings")
def get_settings():
    return database.get_all_settings()

@app.post("/api/settings")
def save_settings(update: SettingsUpdate):
    database.set_setting('auto_scan_enabled', update.auto_scan_enabled)
    database.set_setting('scan_interval_minutes', update.scan_interval_minutes)
    database.set_setting('desktop_notifications', update.desktop_notifications)
    database.set_setting('telegram_notifications', update.telegram_notifications)
    database.set_setting('telegram_token', update.telegram_token)
    database.set_setting('telegram_chat_id', update.telegram_chat_id)
    return {"message": "Settings saved successfully", "settings": database.get_all_settings()}

@app.post("/api/test-notification")
def test_notification(req: TestNotificationRequest):
    if req.channel == 'desktop':
        ok, msg = notifier.send_desktop_notification(
            "🎯 Test Notification",
            "Job Hunter QA: Desktop notifications are working properly!"
        )
        return {"success": ok, "message": msg}
    elif req.channel == 'telegram':
        ok, msg = notifier.send_telegram_test_message(req.token, req.chat_id)
        return {"success": ok, "message": msg}
    else:
        raise HTTPException(status_code=400, detail="Unknown notification channel")

@app.get("/api/scraper/status")
def get_scraper_status():
    import scraper
    return getattr(scraper, "SCRAPER_STATE", {})

@app.post("/api/refresh")
async def refresh_jobs(portal: str = 'ALL', deep: bool = False):
    import scraper
    
    # Run scraping orchestration in a background thread so live status polling works smoothly
    scrape_result = await asyncio.to_thread(scraper.run_scraper, portal, deep)
    if isinstance(scrape_result, dict):
        new_jobs = scrape_result.get("jobs", [])
        metrics = scrape_result.get("metrics", {})
    else:
        new_jobs = scrape_result
        metrics = {}
    
    conn = database.get_db()
    cursor = conn.cursor()
    added = 0
    db_duplicates = 0
    added_jobs = []
    for job in new_jobs:
        try:
            contract_type = job.get('contract_type') or database.infer_contract_type(job['title'], job['url'], job['source'], job.get('pay', ''))
            cursor.execute(
                "INSERT INTO jobs (title, company, url, source, city, pay, published_at, status, contract_type) VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW', ?)",
                (job['title'], job.get('company', ''), job['url'], job['source'], job.get('city', ''), job.get('pay', ''), job.get('published_at', ''), contract_type)
            )
            added += 1
            added_jobs.append(job)
        except sqlite3.IntegrityError:
            db_duplicates += 1
            
    conn.commit()
    conn.close()
    
    if added_jobs:
        notifier.notify_new_jobs(added_jobs)
        
    y_duplicates = metrics.get("duplicates", 0) + db_duplicates
    z_automation = metrics.get("automation_rejected", 0)
    other_rejected = metrics.get("other_rejected", 0)
    total_rejected = z_automation + other_rejected
    total_scanned = metrics.get("scanned", 0)
    if total_scanned == 0:
        total_scanned = added + y_duplicates + total_rejected

    message = f"Found {total_scanned} offers, rejected {total_rejected} of them, {added} were added to NEW."
    
    return {
        "message": message,
        "summary": {
            "total_found": total_scanned,
            "total_rejected": total_rejected,
            "automation_rejected": z_automation,
            "other_rejected": other_rejected,
            "duplicates": y_duplicates,
            "added": added
        }
    }

# Mount static files
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
def read_root():
    return FileResponse("static/index.html")

if __name__ == "__main__":
    import uvicorn
    # reload=False is required to prevent the server from restarting when scraper.log or jobs.db are written to.
    uvicorn.run("app:app", host="127.0.0.1", port=8000, reload=False)
