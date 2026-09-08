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

def auto_scrape_and_notify():
    try:
        import scraper
        logger.info("Auto-scan started...")
        new_jobs = scraper.run_scraper(portal='ALL', deep=False)
        conn = database.get_db()
        cursor = conn.cursor()
        added_jobs = []
        for job in new_jobs:
            try:
                cursor.execute(
                    "INSERT INTO jobs (title, company, url, source, city, pay, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW')",
                    (job['title'], job.get('company', ''), job['url'], job['source'], job.get('city', ''), job.get('pay', ''), job.get('published_at', ''))
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
    if status.upper() == 'ALL':
        cursor.execute(
            "SELECT * FROM jobs WHERE status != 'WRONG' ORDER BY created_at DESC"
        )
    else:
        cursor.execute(
            "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC", 
            (status.upper(),)
        )
    rows = cursor.fetchall()
    conn.close()
    return [dict(row) for row in rows]

@app.put("/api/jobs/{job_id}/status")
def update_job_status(job_id: int, update: StatusUpdate):
    if update.status not in ['NEW', 'APPLIED', 'IGNORED', 'WRONG']:
        raise HTTPException(status_code=400, detail="Invalid status")
        
    conn = database.get_db()
    cursor = conn.cursor()
    cursor.execute(
        "UPDATE jobs SET status = ? WHERE id = ?",
        (update.status, job_id)
    )
    conn.commit()
    conn.close()
    return {"message": "Status updated"}

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
    is_daily = any(x in pay.lower() for x in ['dziennie', '/ day', 'dzień'])
    is_yearly = any(x in pay.lower() for x in ['rocznie', '/ year', 'rok'])
    
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
    elif is_daily or (300 <= min_val <= 2500 and 'dzien' in pay.lower()):
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

@app.post("/api/refresh")
def refresh_jobs(portal: str = 'ALL', deep: bool = False):
    import scraper
    
    # Run scraping orchestration
    scrape_result = scraper.run_scraper(portal, deep)
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
            cursor.execute(
                "INSERT INTO jobs (title, company, url, source, city, pay, published_at, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'NEW')",
                (job['title'], job.get('company', ''), job['url'], job['source'], job.get('city', ''), job.get('pay', ''), job.get('published_at', ''))
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
    a_provided = added
    x_total = a_provided + y_duplicates + z_automation

    message = f"Found {x_total} jobs — {y_duplicates} of them duplicates, {z_automation} of them automation jobs — provided {a_provided} = {x_total} - {y_duplicates} - {z_automation} to the site"
    
    return {
        "message": message,
        "stats": {
            "total_found": x_total,
            "duplicates": y_duplicates,
            "automation_rejected": z_automation,
            "provided": a_provided
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
