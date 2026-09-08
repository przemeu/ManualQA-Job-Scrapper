from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import parsers
import logging
import time
import json
import re

METRICS = {
    "scanned": 0,
    "duplicates": 0,
    "automation_rejected": 0,
    "other_rejected": 0
}

SCRAPER_STATE = {
    "is_running": False,
    "portal": "ALL",
    "deep": False,
    "scanned": 0,
    "passed": 0,
    "automation_rejected": 0,
    "other_rejected": 0,
    "duplicates": 0,
    "current_portal": "",
    "current_job": "",
    "current_status": "Idle"
}

def reset_metrics():
    global METRICS, SCRAPER_STATE
    METRICS = {
        "scanned": 0,
        "duplicates": 0,
        "automation_rejected": 0,
        "other_rejected": 0
    }
    SCRAPER_STATE = {
        "is_running": False,
        "portal": "ALL",
        "deep": False,
        "scanned": 0,
        "passed": 0,
        "automation_rejected": 0,
        "other_rejected": 0,
        "duplicates": 0,
        "current_portal": "",
        "current_job": "",
        "current_status": "Idle"
    }

def update_progress(portal: str = "", title: str = "", status: str = ""):
    global SCRAPER_STATE
    if portal:
        SCRAPER_STATE["current_portal"] = portal
    if title:
        SCRAPER_STATE["current_job"] = title
    if status:
        SCRAPER_STATE["current_status"] = status

def record_scanned(portal: str, title: str = ""):
    global SCRAPER_STATE, METRICS
    METRICS["scanned"] += 1
    SCRAPER_STATE["scanned"] += 1
    update_progress(portal, title, f"Checking: {title}" if title else f"Scanning {portal}...")

def record_rejected_automation(portal: str, title: str = ""):
    global SCRAPER_STATE, METRICS
    METRICS["automation_rejected"] += 1
    SCRAPER_STATE["automation_rejected"] += 1
    update_progress(portal, title, f"Rejected (Automation): {title}" if title else "Rejected automation")

def record_rejected_other(portal: str, title: str = "", reason: str = "Filter"):
    global SCRAPER_STATE, METRICS
    METRICS["other_rejected"] += 1
    SCRAPER_STATE["other_rejected"] += 1
    update_progress(portal, title, f"Rejected ({reason}): {title}" if title else f"Rejected {reason}")

def record_accepted(portal: str, title: str = ""):
    global SCRAPER_STATE
    SCRAPER_STATE["passed"] += 1
    update_progress(portal, title, f"Accepted: {title}" if title else "Accepted")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper.log", mode='w', encoding='utf-8'),
        logging.StreamHandler()
    ]
)
logger = logging.getLogger(__name__)


def create_stealth_context(browser):
    """Creates a browser context configured to evade bot detection / WAF (Cloudflare/Datadome/Akamai)."""
    context = browser.new_context(
        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36',
        locale='pl-PL',
        viewport={'width': 1366, 'height': 768},
        extra_http_headers={
            'Accept-Language': 'pl-PL,pl;q=0.9,en-US;q=0.8,en;q=0.7',
            'Sec-Ch-Ua': '"Chromium";v="128", "Not;A=Brand";v="24", "Google Chrome";v="128"',
            'Sec-Ch-Ua-Mobile': '?0',
            'Sec-Ch-Ua-Platform': '"Windows"'
        }
    )
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined
        });
        window.navigator.chrome = {
            runtime: {}
        };
        Object.defineProperty(navigator, 'languages', {
            get: () => ['pl-PL', 'pl', 'en-US', 'en']
        });
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5]
        });
    """)
    return context


def dismiss_cookie_consent(page):
    """Try to click cookie/consent popups that block SPA rendering."""
    for selector in [
        "button:has-text('Akceptuj wszystkie')",
        "button:has-text('Akceptuję')",
        "button:has-text('OK, rozumiem')",
        "button:has-text('Accept')",
        "button:has-text('Zgadzam się')",
        "#onetrust-accept-btn-handler",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                btn.click()
                page.wait_for_timeout(1000)
                logger.info(f"  Dismissed cookie consent: {selector}")
                return True
        except:
            pass
    return False


def get_job_urls(page, list_url, link_selector, prefix="", max_urls=15):
    """Helper to load a list page and extract job URLs."""
    try:
        page.goto(list_url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)
        dismiss_cookie_consent(page)
        
        # Scroll to load more — deep search scrolls much more
        scroll_count = 8 if max_urls > 15 else 2
        for _ in range(scroll_count):
            page.mouse.wheel(0, 2000)
            page.wait_for_timeout(1500)
        
        elements = page.query_selector_all('a')
        urls = []
        for el in elements:
            href = el.get_attribute('href')
            if href and link_selector in href:
                if href.startswith('/'):
                    href = prefix.rstrip('/') + href
                if href not in urls:
                    urls.append(href)
            if len(urls) >= max_urls:
                break
        logger.info(f"Found {len(urls)} URLs on {list_url}")
        return urls
    except Exception as e:
        logger.error(f"Error getting URLs from {list_url}: {e}")
        return []


def scrape_jjit(browser, deep=False):
    logger.info("Scraping Just Join IT...")
    update_progress("JJIT", "", "Scanning Just Join IT listings...")
    jobs = []
    page = browser.new_page()
    max_urls = 50 if deep else 15
    
    urls = []
    urls += get_job_urls(page, "https://justjoin.it/all-locations/testing", "/job-offer/", "https://justjoin.it", max_urls)
    urls += get_job_urls(page, "https://justjoin.it/trojmiasto/testing", "/job-offer/", "https://justjoin.it", max_urls)
    urls += get_job_urls(page, "https://justjoin.it/remote/testing", "/job-offer/", "https://justjoin.it", max_urls)
    urls = list(set(urls))
    
    for url in urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
            dismiss_cookie_consent(page)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            title_node = soup.find('h1')
            title = title_node.get_text(strip=True) if title_node else ""
            record_scanned("JJIT", title or url)
            
            if not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (JJIT) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("JJIT", title)
                else:
                    record_rejected_other("JJIT", title, "Title")
                continue
            
            # Extract location from structured ld+json and offer header
            is_remote = False
            city = ""
            for s in soup.find_all('script', type='application/ld+json'):
                if s.string:
                    try:
                        d = json.loads(s.string)
                        if d.get('jobLocationType') == 'TELECOMMUTE':
                            is_remote = True
                        loc = d.get('jobLocation')
                        if loc and isinstance(loc, dict):
                            addr = loc.get('address', {})
                            c_name = addr.get('addressLocality', '')
                            if parsers.POMERANIA_REGEX.search(c_name):
                                city = c_name
                    except: pass
            
            # Check offer header elements near h1
            header_node = title_node.find_parent('div') if title_node else None
            header_text = header_node.get_text(separator=' ') if header_node else ""
            if parsers.REMOTE_REGEX.search(header_text) or '100% remote' in header_text.lower():
                is_remote = True
            m_city = parsers.CITY_REGEX.search(header_text)
            if m_city:
                city = m_city.group(0).title()
                
            # Check for explicit on-site requirement (e.g. 100% stacjonarnie in non-Tricity)
            main_node = soup.find('main') or soup
            main_text = main_node.get_text(separator=' ')
            if '100% stacjonarnie' in main_text.lower() or 'praca stacjonarna' in main_text.lower():
                if not city:
                    is_remote = False
            
            if not is_remote and not city:
                logger.info(f"  REJECTED (JJIT) location: {title}")
                record_rejected_other("JJIT", title, "Location")
                continue
                
            # Check contract
            if not parsers.CONTRACT_REGEX.search(main_text):
                logger.info(f"  REJECTED (JJIT) contract: {title}")
                record_rejected_other("JJIT", title, "Contract")
                continue
            
            # Check automation tools in requirements & technology chips
            has_auto_tools = False
            for s in soup.find_all('script', type='application/ld+json'):
                if s.string:
                    try:
                        d = json.loads(s.string)
                        desc = d.get('description', '')
                        if desc and parsers.AUTOMATION_TOOLS_REGEX.search(desc):
                            for req_word in ['wymagania', 'oczekujemy', 'requirements', 'must have', 'required']:
                                if req_word in desc.lower():
                                    idx = desc.lower().find(req_word)
                                    if parsers.AUTOMATION_TOOLS_REGEX.search(desc[idx:idx+900]):
                                        has_auto_tools = True
                                        break
                    except: pass
                    
            if not has_auto_tools:
                for sec_kw in ['wymagania', 'oczekujemy', 'requirements', 'must have', 'required skills', 'technologie', 'skills']:
                    sec_el = soup.find(string=lambda s, kw=sec_kw: s and kw in s.lower())
                    if sec_el:
                        parent = sec_el.find_parent('section') or sec_el.find_parent('div')
                        if parent:
                            p_text = parent.get_text(separator=' ')
                            if parsers.AUTOMATION_TOOLS_REGEX.search(p_text):
                                has_auto_tools = True
                                break
                                
            if has_auto_tools:
                logger.info(f"  REJECTED (JJIT) automation tools: {title}")
                record_rejected_automation("JJIT", title)
                continue
            
            city_display = "Remote" if is_remote and not city else (f"{city} / Remote" if is_remote and city else city)
            company_node = soup.find(lambda t: t.name in ['h2', 'span', 'div'] and any(c in t.get('class', []) for c in ['company', 'employer']))
            company = company_node.get_text(strip=True) if company_node else "Just Join IT"
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': 'JJIT',
                'city': city_display,
                'pay': parsers.extract_jjit_salary(soup),
                'published_at': parsers.extract_published_date(soup, main_text)
            })
            record_accepted("JJIT", title)
            logger.info(f"  ACCEPTED (JJIT): {title} @ {company}")
            
        except Exception as e:
            logger.error(f"Error parsing JJIT job {url}: {e}")
            
    page.close()
    return jobs


def scrape_nfj(browser, deep=False):
    logger.info("Scraping No Fluff Jobs...")
    update_progress("NFJ", "", "Scanning No Fluff Jobs listings...")
    jobs = []
    page = browser.new_page()
    max_urls = 50 if deep else 15
    
    urls = []
    urls += get_job_urls(page, "https://nofluffjobs.com/pl/testing", "/pl/job/", "https://nofluffjobs.com", max_urls)
    urls += get_job_urls(page, "https://nofluffjobs.com/pl/praca-zdalna/testing", "/pl/job/", "https://nofluffjobs.com", max_urls)
    urls += get_job_urls(page, "https://nofluffjobs.com/pl/trojmiasto/testing", "/pl/job/", "https://nofluffjobs.com", max_urls)
    urls = list(set(urls))
    
    for url in urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
            dismiss_cookie_consent(page)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            
            title_node = soup.find('h1')
            title = title_node.get_text(strip=True) if title_node else ""
            record_scanned("NFJ", title or url)
            
            if not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (NFJ) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("NFJ", title)
                else:
                    record_rejected_other("NFJ", title, "Title")
                continue
            
            # Extract location from structured ld+json and header badges
            is_remote = False
            city = ""
            company = "No Fluff Jobs"
            
            for s in soup.find_all('script', type='application/ld+json'):
                if s.string:
                    try:
                        d = json.loads(s.string)
                        items = d.get('@graph', [d]) if isinstance(d, dict) else []
                        for item in items:
                            if not isinstance(item, dict): continue
                            if item.get('jobLocationType') == 'TELECOMMUTE':
                                is_remote = True
                            loc = item.get('jobLocation')
                            if loc and isinstance(loc, dict):
                                addr = loc.get('address', {})
                                c_name = addr.get('addressLocality', '')
                                if parsers.POMERANIA_REGEX.search(c_name):
                                    city = c_name
                            org = item.get('hiringOrganization')
                            if org and isinstance(org, dict):
                                company = org.get('name', company)
                    except: pass
                    
            # Check offer header elements (NOT the entire page)
            header_node = soup.find(attrs={'data-cy': 'job-header'}) or soup.find(class_=lambda c: c and 'posting-header' in str(c))
            if header_node:
                h_text = header_node.get_text(separator=' ')
                if parsers.REMOTE_REGEX.search(h_text) or 'zdaln' in h_text.lower():
                    is_remote = True
                m_city = parsers.CITY_REGEX.search(h_text)
                if m_city:
                    city = m_city.group(0).title()
            else:
                # Check near h1
                h1_parent = title_node.find_parent('div') if title_node else None
                if h1_parent:
                    hp_text = h1_parent.get_text(separator=' ')
                    if parsers.REMOTE_REGEX.search(hp_text) or 'zdaln' in hp_text.lower():
                        is_remote = True
                    m_city = parsers.CITY_REGEX.search(hp_text)
                    if m_city:
                        city = m_city.group(0).title()
                        
            main_node = soup.find('main') or soup
            main_text = main_node.get_text(separator=' ')
            
            if not is_remote and not city:
                logger.info(f"  REJECTED (NFJ) location: {title}")
                record_rejected_other("NFJ", title, "Location")
                continue
                
            # Check contract
            if not parsers.CONTRACT_REGEX.search(main_text):
                logger.info(f"  REJECTED (NFJ) contract: {title}")
                record_rejected_other("NFJ", title, "Contract")
                continue
                
            # Check automation tools in requirements (Polish & English headers)
            has_auto_tools = False
            for sec_kw in ['wymagania', 'oczekujemy', 'requirements', 'what you need', "what we're looking for", 'must have', 'expected technologies']:
                sec_el = soup.find(string=lambda s, kw=sec_kw: s and kw in s.lower())
                if sec_el:
                    parent = sec_el.find_parent('section') or sec_el.find_parent('div')
                    if parent:
                        p_text = parent.get_text(separator=' ')
                        if parsers.AUTOMATION_TOOLS_REGEX.search(p_text):
                            has_auto_tools = True
                            break
                            
            if not has_auto_tools:
                req_container = soup.find(attrs={'data-cy': 'requirements'}) or soup.find(class_=lambda c: c and 'requirements' in str(c).lower())
                if req_container:
                    if parsers.AUTOMATION_TOOLS_REGEX.search(req_container.get_text(separator=' ')):
                        has_auto_tools = True
                        
            if has_auto_tools:
                logger.info(f"  REJECTED (NFJ) automation tools: {title}")
                record_rejected_automation("NFJ", title)
                continue
                
            city_display = "Remote" if is_remote and not city else (f"{city} / Remote" if is_remote and city else city)
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': 'NFJ',
                'city': city_display,
                'pay': parsers.extract_nfj_salary(soup),
                'published_at': parsers.extract_published_date(soup, main_text)
            })
            record_accepted("NFJ", title)
            logger.info(f"  ACCEPTED (NFJ): {title} @ {company}")
            
        except Exception as e:
            logger.error(f"Error scraping NFJ {url}: {e}")
            
    page.close()
    return jobs


def scrape_pracuj(browser, deep=False):
    logger.info("Scraping Pracuj.pl...")
    update_progress("Pracuj", "", "Scanning Pracuj.pl listings...")
    jobs = []
    page = browser.new_page()
    max_urls = 50 if deep else 15
    
    # Two searches: Tricity area + Remote
    all_urls = []
    all_urls += get_job_urls(page, "https://it.pracuj.pl/praca/tester;kw/gdansk,gdynia,sopot;wp?rd=0", ",oferta,", "", max_urls)
    all_urls += get_job_urls(page, "https://it.pracuj.pl/praca/qa;kw/gdansk,gdynia,sopot;wp?rd=0", ",oferta,", "", max_urls)
    all_urls += get_job_urls(page, "https://it.pracuj.pl/praca/tester;kw?cc=5015001&rd=0", ",oferta,", "", max_urls)
    all_urls += get_job_urls(page, "https://it.pracuj.pl/praca/qa;kw?cc=5015001&rd=0", ",oferta,", "", max_urls)
    
    unique_urls = list(set(all_urls))
    logger.info(f"Pracuj total unique URLs to visit: {len(unique_urls)}")
    page.close()
    
    for url in unique_urls:
        job_page = browser.new_page()
        try:
            job_page.goto(url, wait_until="domcontentloaded", timeout=25000)
            job_page.wait_for_timeout(2000)
            dismiss_cookie_consent(job_page)
            
            # Wait for the SPA to render the job title
            try:
                job_page.wait_for_selector('[data-test="text-positionName"]', timeout=8000)
            except:
                logger.info(f"  SKIPPED (Pracuj): SPA did not render for {url[:60]}...")
                job_page.close()
                continue
            
            job_page.wait_for_timeout(500)
            soup = BeautifulSoup(job_page.content(), 'html.parser')
            
            # Use Pracuj's data-test attributes for reliable extraction
            title_node = soup.find(attrs={'data-test': 'text-positionName'})
            title = title_node.get_text(strip=True) if title_node else ''
            record_scanned("Pracuj", title or url)
            
            if not title or title == 'www.pracuj.pl':
                logger.info(f"  SKIPPED (Pracuj): No valid title for {url[:60]}...")
                job_page.close()
                continue
            
            company_node = soup.find(attrs={'data-test': 'text-employerName'})
            company = company_node.get_text(strip=True) if company_node else 'Unknown Company'
            for suffix in ['About the company', 'O firmie']:
                company = company.replace(suffix, '').strip()
            
            text_content = soup.get_text(separator=' ', strip=True)
            
            # Title filter
            if not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (Pracuj) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("Pracuj", title)
                else:
                    record_rejected_other("Pracuj", title, "Title")
                job_page.close()
                continue
            
            # Extract location strictly from offer header & workplace elements (not bottom recommendations)
            loc_node = soup.find(attrs={'data-test': 'text-workplaceAddress'}) or soup.find(attrs={'data-test': 'sections-benefit-workplaces'}) or soup.find(attrs={'data-test': 'section-benefit-workplaces'})
            loc_text = loc_node.get_text(separator=' ') if loc_node else ''
            header_node = soup.find(attrs={'data-test': 'section-offer-header'}) or soup.find(attrs={'data-test': 'section-positionAndCompany'}) or soup.find('h1')
            h_parent = header_node.find_parent('section') or header_node.find_parent('div') if header_node else None
            h_text = h_parent.get_text(separator=' ') if h_parent else ''
            combined_loc_text = f"{loc_text} {h_text}".strip()
            
            is_remote = bool(parsers.REMOTE_REGEX.search(combined_loc_text)) or 'praca zdalna' in combined_loc_text.lower()
            has_tricity = bool(parsers.POMERANIA_REGEX.search(combined_loc_text))
            
            # Location filter
            if not is_remote and not has_tricity:
                logger.info(f"  REJECTED (Pracuj) location: {title}")
                record_rejected_other("Pracuj", title, "Location")
                job_page.close()
                continue
            
            # Contract filter
            if not parsers.CONTRACT_REGEX.search(text_content):
                logger.info(f"  REJECTED (Pracuj) contract: {title}")
                record_rejected_other("Pracuj", title, "Contract")
                job_page.close()
                continue
            
            # Automation tools check — scan tech stack and requirements sections
            rejected_automation = False
            # Check Pracuj data-test attributes for expected technologies
            tech_expected = soup.find(attrs={'data-test': 'section-technologies-expected'}) or soup.find(attrs={'data-test': 'section-requirements-expected'})
            if tech_expected and parsers.AUTOMATION_TOOLS_REGEX.search(tech_expected.get_text(separator=' ')):
                rejected_automation = True
                
            if not rejected_automation:
                for section_kw in ['requirements', 'wymagania', 'oczekujemy', 'our requirements', 'tech stack', 'technology', 'narzędzia', 'tools']:
                    section_el = soup.find(string=lambda s, kw=section_kw: s and kw in s.lower())
                    if section_el:
                        parent = section_el.find_parent('section') or section_el.find_parent('div')
                        if parent:
                            section_text = parent.get_text(separator=' ')
                            if parsers.AUTOMATION_TOOLS_REGEX.search(section_text):
                                rejected_automation = True
                                break
                                
            if rejected_automation:
                logger.info(f"  REJECTED (Pracuj) automation tools: {title}")
                record_rejected_automation("Pracuj", title)
                job_page.close()
                continue
            
            # Clean city display
            m_city = parsers.CITY_REGEX.search(combined_loc_text)
            city_name = m_city.group(0).title() if m_city else ""
            city_display = "Remote" if is_remote and not city_name else (f"{city_name} / Remote" if is_remote and city_name else city_name)
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': 'Pracuj',
                'city': city_display,
                'pay': parsers.extract_pracuj_salary(soup),
                'published_at': parsers.extract_published_date(soup, text_content)
            })
            record_accepted("Pracuj", title)
            logger.info(f"  ACCEPTED (Pracuj): {title} @ {company}")
            
        except Exception as e:
            logger.error(f"Error scraping Pracuj {url[:60]}...: {e}")
        finally:
            job_page.close()
    
    return jobs


def scrape_protocol(browser, deep=False):
    logger.info("Scraping theprotocol.it...")
    update_progress("Protocol", "", "Scanning theprotocol.it listings...")
    jobs = []
    context = create_stealth_context(browser)
    page = context.new_page()
    max_urls = 50 if deep else 15
    all_urls = []
    base = "https://theprotocol.it/filtry"
    
    # 1. Targeted keyword and category searches
    search_queries = [
        f"{base}/testing;t",
        f"{base}/tester;kw",
        f"{base}/qa;kw",
        f"{base}/testing;t/praca-zdalna;wm",
        f"{base}/testing;t/gdansk;wp",
    ]
    if deep:
        search_queries.extend([
            f"{base}/tester%20manualny;kw",
            f"{base}/quality%20assurance;kw",
            f"{base}/testing;t/gdynia;wp",
            f"{base}/testing;t/sopot;wp"
        ])
    for s_url in search_queries:
        all_urls += get_job_urls(page, s_url, "szczegoly", "https://theprotocol.it", max_urls)
        page.wait_for_timeout(1000)
        
    unique_urls = list(dict.fromkeys(all_urls))
    logger.info(f"Protocol total unique URLs to visit: {len(unique_urls)}")
    
    for url in unique_urls:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(1500)
            dismiss_cookie_consent(page)
            
            # Check for Cloudflare / verification screen
            if "just a moment" in page.title().lower() or "are you a human" in page.content().lower():
                logger.info(f"  Cloudflare verification detected on {url[:60]}... waiting up to 6s...")
                page.wait_for_timeout(6000)
            
            # Wait for Protocol to render
            try:
                page.wait_for_selector('h1', timeout=8000)
            except:
                logger.info(f"  SKIPPED (Protocol): Page did not render for {url[:60]}...")
                continue
            
            page.wait_for_timeout(1000)
            soup = BeautifulSoup(page.content(), 'html.parser')
            
            title_node = soup.find('h1')
            title = title_node.get_text(strip=True) if title_node else ''
            record_scanned("Protocol", title or url)
            
            if not title or 'theprotocol' in title.lower():
                logger.info(f"  SKIPPED (Protocol): No valid title for {url[:60]}...")
                continue
            
            # Company: try multiple selectors
            company = 'Unknown Company'
            for sel in ['[data-test="text-companyName"]', '[data-test="text-employer-name"]']:
                node = soup.find(attrs={'data-test': sel.split('"')[1]})
                if node:
                    company = node.get_text(strip=True)
                    break
            
            if company == 'Unknown Company':
                # Fallback: look for company name near title or in specific sections
                # theprotocol often has company name in a specific div or h2 below the title
                employer_section = soup.find(string=lambda s: s and 'pracodawca' in s.lower()) if soup else None
                if employer_section:
                    parent = employer_section.find_parent('div')
                    if parent:
                        links = parent.find_all('a')
                        for link in links:
                            txt = link.get_text(strip=True)
                            if txt and len(txt) > 2:
                                company = txt
                                break
                
                if company == 'Unknown Company':
                    # Try finding company from breadcrumbs or any h2 near top
                    h2s = soup.find_all('h2')
                    for h2 in h2s[:3]:
                        txt = h2.get_text(strip=True)
                        if txt and 'test' not in txt.lower() and 'qa' not in txt.lower() and len(txt) < 60:
                            company = txt
                            break
            
            # Clean up company name
            for prefix in ['Company:', 'Firma:', 'Pracodawca:']:
                if company.startswith(prefix):
                    company = company[len(prefix):].strip()
            
            text_content = soup.get_text(separator=' ', strip=True)
            
            # Title filter
            if not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (Protocol) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("Protocol", title)
                else:
                    record_rejected_other("Protocol", title, "Title")
                continue
            
            # Location filter - use targeted Protocol workModes & location tags
            loc_modes = soup.find(attrs={'data-test': 'text-workModes'})
            loc_place = soup.find(attrs={'data-test': 'text-primaryLocation'}) or soup.find(attrs={'data-test': 'text-workplaceAddress'})
            modes_text = loc_modes.get_text(separator=' ') if loc_modes else ''
            place_text = loc_place.get_text(separator=' ') if loc_place else ''
            loc_combined = f"{modes_text} {place_text}"
            
            is_remote = bool(parsers.REMOTE_REGEX.search(loc_combined)) or 'zdaln' in loc_combined.lower()
            has_tricity = bool(parsers.POMERANIA_REGEX.search(loc_combined))
            
            # If not in specific tags, check offer header near title
            if not is_remote and not has_tricity and title_node:
                h_parent = title_node.find_parent('div')
                if h_parent:
                    hp_text = h_parent.get_text(separator=' ')
                    if parsers.REMOTE_REGEX.search(hp_text) or 'zdaln' in hp_text.lower():
                        is_remote = True
                    if parsers.POMERANIA_REGEX.search(hp_text):
                        has_tricity = True
                        loc_combined += f" {hp_text}"
            
            if not is_remote and not has_tricity:
                logger.info(f"  REJECTED (Protocol) location: {title}")
                record_rejected_other("Protocol", title, "Location")
                continue
            
            # Contract filter
            if not parsers.CONTRACT_REGEX.search(text_content):
                logger.info(f"  REJECTED (Protocol) contract: {title}")
                record_rejected_other("Protocol", title, "Contract")
                continue
            
            # Automation tools in must-have requirements or expected technologies
            tech_expected = soup.find(attrs={'data-test': 'section-technologies-expected'}) or soup.find(attrs={'data-test': 'section-technologies-required'})
            if tech_expected and parsers.AUTOMATION_TOOLS_REGEX.search(tech_expected.get_text(separator=' ')):
                logger.info(f"  REJECTED (Protocol) automation tools: {title}")
                record_rejected_automation("Protocol", title)
                continue
                
            oczekujemy = soup.find(string=lambda s: s and s.strip().lower() in ['oczekujemy', 'wymagania', 'must have', 'requirements'])
            if oczekujemy:
                parent = oczekujemy.find_parent('div') or oczekujemy.find_parent('section')
                if parent:
                    req_text = parent.get_text(separator=' ')
                    if parsers.AUTOMATION_TOOLS_REGEX.search(req_text):
                        logger.info(f"  REJECTED (Protocol) automation tools: {title}")
                        continue
            
            # Clean city
            m_city = parsers.CITY_REGEX.search(loc_combined)
            city_name = m_city.group(0).title() if m_city else ""
            city_display = "Remote" if is_remote and not city_name else (f"{city_name} / Remote" if is_remote and city_name else city_name)
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': 'Protocol',
                'city': city_display,
                'pay': parsers.extract_protocol_salary(soup),
                'published_at': parsers.extract_published_date(soup, text_content)
            })
            logger.info(f"  ACCEPTED (Protocol): {title} @ {company}")
            
        except Exception as e:
            logger.error(f"Error scraping Protocol {url[:60]}...: {e}")
            
    page.close()
    context.close()
    return jobs


def scrape_bulldogjob(browser, deep=False):
    logger.info("Scraping Bulldogjob...")
    update_progress("Bulldog", "", "Scanning Bulldogjob listings...")
    jobs = []
    page = browser.new_page()
    max_pages = 3 if deep else 1
    
    all_urls = []
    base_search_urls = [
        "https://bulldogjob.pl/companies/jobs/s/role,qa",
        "https://bulldogjob.pl/companies/jobs/s/role,qa/city,Trojmiasto",
        "https://bulldogjob.pl/companies/jobs/s/role,qa/remote,true"
    ]
    
    for base in base_search_urls:
        for pg in range(1, max_pages + 1):
            url = f"{base}?page={pg}" if pg > 1 else base
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=25000)
                page.wait_for_timeout(1500)
                dismiss_cookie_consent(page)
                soup = BeautifulSoup(page.content(), 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    if '/companies/jobs/' in href and '/companies/jobs/s/' not in href and any(c.isdigit() for c in href):
                        full = href if href.startswith('http') else f"https://bulldogjob.pl{href}"
                        if full not in all_urls:
                            all_urls.append(full)
            except Exception as e:
                logger.error(f"Error collecting Bulldogjob URLs from {url}: {e}")
                
    page.close()
    logger.info(f"Bulldogjob total unique URLs to visit: {len(all_urls)}")
    
    for url in all_urls:
        job_page = browser.new_page()
        try:
            job_page.goto(url, wait_until="domcontentloaded", timeout=25000)
            job_page.wait_for_timeout(1500)
            dismiss_cookie_consent(job_page)
            
            soup = BeautifulSoup(job_page.content(), 'html.parser')
            
            # Check ld+json
            ld_scripts = soup.find_all('script', type='application/ld+json')
            ld_data = {}
            for s in ld_scripts:
                raw_text = s.get_text().strip()
                if raw_text:
                    try:
                        d = json.loads(raw_text, strict=False)
                        if isinstance(d, dict) and d.get('@type') == 'JobPosting':
                            ld_data = d
                            break
                    except: pass
                    
            title = ld_data.get('title')
            if not title:
                h1 = soup.find('h1')
                title = h1.get_text(strip=True) if h1 else ''
            record_scanned("Bulldog", title or url)
                
            if not title or not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (Bulldog) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("Bulldog", title)
                else:
                    record_rejected_other("Bulldog", title, "Title")
                continue
                
            company = "Unknown"
            if ld_data.get('hiringOrganization'):
                org = ld_data['hiringOrganization']
                company = org.get('name', company) if isinstance(org, dict) else str(org)
                
            # Location check
            is_remote = (ld_data.get('jobLocationType') == 'TELECOMMUTE')
            city = ""
            
            loc = ld_data.get('jobLocation')
            if loc:
                locs = loc if isinstance(loc, list) else [loc]
                for item in locs:
                    if isinstance(item, dict):
                        addr = item.get('address') or {}
                        c_name = (addr.get('addressLocality') or '') if isinstance(addr, dict) else ''
                        if c_name and parsers.POMERANIA_REGEX.search(c_name):
                            city = c_name
                            break
                            
            header_node = soup.find('h1')
            h_parent = header_node.find_parent('div') if header_node else None
            h_text = h_parent.get_text(separator=' ') if h_parent else ''
            
            if not is_remote and (parsers.REMOTE_REGEX.search(h_text) or 'remote' in url.lower()):
                is_remote = True
            if not city and parsers.POMERANIA_REGEX.search(h_text):
                m = parsers.POMERANIA_REGEX.search(h_text)
                city = m.group(0).title()
                
            if not is_remote and not city:
                logger.info(f"  REJECTED (Bulldog) location: {title} @ {company}")
                record_rejected_other("Bulldog", title, "Location")
                continue
                
            # Contract check
            text_content = soup.get_text(separator=' ', strip=True)
            emp_type = str(ld_data.get('employmentType', ''))
            has_contract = bool(parsers.CONTRACT_REGEX.search(emp_type) or parsers.CONTRACT_REGEX.search(text_content))
            if not has_contract:
                logger.info(f"  REJECTED (Bulldog) contract: {title} @ {company}")
                record_rejected_other("Bulldog", title, "Contract")
                continue
                
            # Automation tools check
            skills = ld_data.get('skills') or ''
            if isinstance(skills, list):
                skills = ' '.join(str(s) for s in skills if s)
            else:
                skills = str(skills)
            desc = str(ld_data.get('description') or '')
            
            has_auto = False
            if skills and parsers.AUTOMATION_TOOLS_REGEX.search(skills):
                has_auto = True
            elif desc:
                for req_word in ['wymagania', 'oczekujemy', 'requirements', 'must have', 'required']:
                    if req_word in desc.lower():
                        idx = desc.lower().find(req_word)
                        req_slice = desc[idx:]
                        end_idx = 900
                        for marker in ['mile widziane', 'nice to have', 'dodatkowym atutem', 'oferujemy', 'we offer', 'benefity']:
                            m_idx = req_slice.lower().find(marker)
                            if m_idx != -1 and 0 < m_idx < end_idx:
                                end_idx = m_idx
                        chunk = req_slice[:end_idx]
                        if parsers.AUTOMATION_TOOLS_REGEX.search(chunk):
                            has_auto = True
                            break
                            
            if has_auto:
                logger.info(f"  REJECTED (Bulldog) automation tools: {title} @ {company}")
                record_rejected_automation("Bulldog", title)
                continue
                
            # Salary extraction
            pay = "Not given"
            base_sal = ld_data.get('baseSalary')
            if base_sal and isinstance(base_sal, dict):
                val = base_sal.get('value', {})
                curr = base_sal.get('currency', 'PLN')
                min_v = val.get('minValue')
                max_v = val.get('maxValue')
                if min_v and max_v:
                    pay = f"{min_v:,} - {max_v:,} {curr}".replace(',', ' ')
                elif min_v:
                    pay = f"od {min_v:,} {curr}".replace(',', ' ')
                    
            # Published date
            pub_date = ld_data.get('datePosted', '')
            if pub_date:
                pub_date = parsers.format_date_str(str(pub_date))
                
            city_display = "Remote" if is_remote and not city else (f"{city} / Remote" if is_remote and city else city)
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': 'Bulldog',
                'city': city_display,
                'pay': pay,
                'published_at': pub_date
            })
            record_accepted("Bulldog", title)
            logger.info(f"  ACCEPTED (Bulldog): {title} @ {company} | {city_display} | {pay}")
            
        except Exception as e:
            logger.error(f"Error scraping Bulldog {url[:60]}...: {e}")
        finally:
            job_page.close()
            
    return jobs


def scrape_solidjobs(browser, deep=False):
    logger.info("Scraping Solid.jobs...")
    update_progress("Solid", "", "Scanning Solid.jobs listings...")
    page = browser.new_page()
    jobs = []
    
    search_queries = [
        "https://solid.jobs/offers/it;parsedSearchTerm=qa",
        "https://solid.jobs/offers/it;parsedSearchTerm=tester",
        "https://solid.jobs/offers/it;parsedSearchTerm=testy",
        "https://solid.jobs/offers/it;parsedSearchTerm=testing"
    ]
    if deep:
        search_queries.extend([
            "https://solid.jobs/offers/it;location=Gda%C5%84sk",
            "https://solid.jobs/offers/it;location=Gdynia",
            "https://solid.jobs/offers/it;location=Sopot",
            "https://solid.jobs/offers/it;location=100%25%20zdalnie"
        ])
        
    all_urls = []
    for query_url in search_queries:
        try:
            page.goto(query_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(1000)
            dismiss_cookie_consent(page)
            
            soup = BeautifulSoup(page.content(), 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/offer/' in href:
                    full_url = href if href.startswith('http') else f"https://solid.jobs{href}"
                    if full_url not in all_urls:
                        all_urls.append(full_url)
        except Exception as e:
            logger.error(f"Error collecting Solid.jobs URLs from {query_url}: {e}")
            
    page.close()
    logger.info(f"Solid.jobs total unique URLs to visit: {len(all_urls)}")
    
    for url in all_urls:
        job_page = browser.new_page()
        try:
            job_page.goto(url, wait_until="networkidle", timeout=25000)
            job_page.wait_for_timeout(1000)
            dismiss_cookie_consent(job_page)
            
            soup = BeautifulSoup(job_page.content(), 'html.parser')
            ld_scripts = soup.find_all('script', type='application/ld+json')
            ld_data = {}
            for s in ld_scripts:
                raw_text = s.get_text().strip()
                if raw_text:
                    try:
                        d = json.loads(raw_text, strict=False)
                        if isinstance(d, dict) and d.get('@type') == 'JobPosting':
                            ld_data = d
                            break
                    except: pass
                    
            title = ld_data.get('title') or (soup.find('h1').get_text(strip=True) if soup.find('h1') else '')
            record_scanned("Solid", title or url)
            
            if not title or not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (Solid) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("Solid", title)
                else:
                    record_rejected_other("Solid", title, "Title")
                continue
                
            company = "Unknown"
            if ld_data.get('hiringOrganization'):
                org = ld_data['hiringOrganization']
                company = org.get('name', company) if isinstance(org, dict) else str(org)
                
            # Location check
            is_remote = (ld_data.get('jobLocationType') == 'TELECOMMUTE')
            city = ""
            loc = ld_data.get('jobLocation')
            if loc:
                locs = loc if isinstance(loc, list) else [loc]
                for item in locs:
                    if isinstance(item, dict):
                        addr = item.get('address') or {}
                        c_name = (addr.get('addressLocality') or '') if isinstance(addr, dict) else ''
                        if c_name and parsers.POMERANIA_REGEX.search(c_name):
                            city = c_name
                            break
                            
            text_content = soup.get_text(separator=' ', strip=True)
            if not is_remote and (parsers.REMOTE_REGEX.search(text_content[:1500]) or 'zdalnie' in text_content[:1500].lower()):
                is_remote = True
            if not city and parsers.POMERANIA_REGEX.search(text_content[:1500]):
                m = parsers.POMERANIA_REGEX.search(text_content[:1500])
                city = m.group(0).title()
                
            if not is_remote and not city:
                logger.info(f"  REJECTED (Solid) location: {title} @ {company}")
                record_rejected_other("Solid", title, "Location")
                continue
                
            # Contract check
            emp_type = str(ld_data.get('employmentType') or '')
            has_contract = bool(parsers.CONTRACT_REGEX.search(emp_type) or parsers.CONTRACT_REGEX.search(text_content))
            if not has_contract:
                logger.info(f"  REJECTED (Solid) contract: {title} @ {company}")
                record_rejected_other("Solid", title, "Contract")
                continue
                
            # Automation tools check in requirements (ignoring nice-to-have / mile widziane)
            skills = ld_data.get('skills') or ''
            if isinstance(skills, list):
                skills = ' '.join(str(s) for s in skills if s)
            else:
                skills = str(skills)
            desc = str(ld_data.get('description') or '')
            
            has_auto = False
            if skills and parsers.AUTOMATION_TOOLS_REGEX.search(skills):
                has_auto = True
            elif desc:
                for req_word in ['wymagania', 'oczekujemy', 'requirements', 'must have', 'required']:
                    if req_word in desc.lower():
                        idx = desc.lower().find(req_word)
                        req_slice = desc[idx:]
                        end_idx = 900
                        for marker in ['mile widziane', 'nice to have', 'dodatkowym atutem', 'oferujemy', 'we offer', 'benefity']:
                            m_idx = req_slice.lower().find(marker)
                            if m_idx != -1 and 0 < m_idx < end_idx:
                                end_idx = m_idx
                        chunk = req_slice[:end_idx]
                        if parsers.AUTOMATION_TOOLS_REGEX.search(chunk):
                            has_auto = True
                            break
                            
            if has_auto:
                logger.info(f"  REJECTED (Solid) automation tools: {title} @ {company}")
                record_rejected_automation("Solid", title)
                continue
                
            # Salary extraction
            pay = "Not given"
            base_sal = ld_data.get('baseSalary')
            if base_sal and isinstance(base_sal, dict):
                val = base_sal.get('value', {})
                curr = base_sal.get('currency', 'PLN')
                min_v = val.get('minValue')
                max_v = val.get('maxValue')
                if min_v and max_v:
                    pay = f"{int(min_v):,} - {int(max_v):,} {curr}".replace(',', ' ')
                elif min_v:
                    pay = f"od {int(min_v):,} {curr}".replace(',', ' ')
                    
            pub_date = ld_data.get('datePosted', '')
            if pub_date:
                pub_date = parsers.format_date_str(str(pub_date))
                
            city_display = "Remote" if is_remote and not city else (f"{city} / Remote" if is_remote and city else city)
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': 'Solid',
                'city': city_display,
                'pay': pay,
                'published_at': pub_date
            })
            record_accepted("Solid", title)
            logger.info(f"  ACCEPTED (Solid): {title} @ {company} | {city_display} | {pay}")
            
        except Exception as e:
            logger.error(f"Error scraping Solid {url[:60]}...: {e}")
        finally:
            job_page.close()
            
    return jobs


def scrape_4programmers(browser, deep=False):
    logger.info("Scraping 4programmers...")
    update_progress("4prog", "", "Scanning 4programmers listings...")
    page = browser.new_page()
    jobs = []
    
    search_queries = [
        "https://4programmers.net/Praca?q=tester",
        "https://4programmers.net/Praca?q=qa",
        "https://4programmers.net/Praca?q=test"
    ]
    if deep:
        search_queries.extend([
            "https://4programmers.net/Praca?remote=1",
            "https://4programmers.net/Praca?city=Gda%C5%84sk",
            "https://4programmers.net/Praca?city=Gdynia"
        ])
        
    all_urls = []
    for q_url in search_queries:
        try:
            page.goto(q_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(1200)
            dismiss_cookie_consent(page)
            
            soup = BeautifulSoup(page.content(), 'html.parser')
            for a in soup.find_all('a', href=True):
                href = a['href']
                if '/Praca/' in href and any(c.isdigit() for c in href):
                    full_url = href if href.startswith('http') else f"https://4programmers.net{href}"
                    if full_url not in all_urls:
                        all_urls.append(full_url)
        except Exception as e:
            logger.error(f"Error collecting 4programmers URLs from {q_url}: {e}")
            
    page.close()
    logger.info(f"4programmers total unique URLs to visit: {len(all_urls)}")
    
    for url in all_urls:
        job_page = browser.new_page()
        try:
            job_page.goto(url, wait_until="domcontentloaded", timeout=25000)
            job_page.wait_for_timeout(1000)
            dismiss_cookie_consent(job_page)
            
            soup = BeautifulSoup(job_page.content(), 'html.parser')
            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else ''
            record_scanned("4prog", title or url)
            
            if not title or not parsers.is_title_valid(title):
                logger.info(f"  REJECTED (4programmers) title: {title}")
                if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                    record_rejected_automation("4prog", title)
                else:
                    record_rejected_other("4prog", title, "Title")
                continue
                
            comp_a = soup.find('a', href=lambda h: h and '/Praca/Firma/' in h)
            company = comp_a.get_text(strip=True) if comp_a else "Unknown"
            
            text_content = soup.get_text(separator=' ', strip=True)
            
            # Location check
            is_remote = bool(parsers.REMOTE_REGEX.search(text_content) or 'zdalna' in text_content.lower())
            city = ""
            if parsers.POMERANIA_REGEX.search(text_content):
                m = parsers.POMERANIA_REGEX.search(text_content)
                city = m.group(0).title()
                
            if not is_remote and not city:
                logger.info(f"  REJECTED (4programmers) location: {title} @ {company}")
                record_rejected_other("4prog", title, "Location")
                continue
                
            # Contract check
            has_contract = bool(parsers.CONTRACT_REGEX.search(text_content))
            if not has_contract:
                logger.info(f"  REJECTED (4programmers) contract: {title} @ {company}")
                record_rejected_other("4prog", title, "Contract")
                continue
                
            # Automation tools in requirements
            has_auto = False
            for req_word in ['wymagania', 'oczekujemy', 'requirements', 'must have', 'required']:
                if req_word in text_content.lower():
                    idx = text_content.lower().find(req_word)
                    req_slice = text_content[idx:]
                    end_idx = 900
                    for marker in ['mile widziane', 'nice to have', 'dodatkowym atutem', 'oferujemy', 'we offer']:
                        m_idx = req_slice.lower().find(marker)
                        if m_idx != -1 and 0 < m_idx < end_idx:
                            end_idx = m_idx
                    chunk = req_slice[:end_idx]
                    if parsers.AUTOMATION_TOOLS_REGEX.search(chunk):
                        has_auto = True
                        break
                        
            if has_auto:
                logger.info(f"  REJECTED (4programmers) automation tools: {title} @ {company}")
                record_rejected_automation("4prog", title)
                continue
                
            # Pay
            pay = "Not given"
            m_pay = parsers.PAY_REGEX.search(text_content)
            if m_pay:
                pay = m_pay.group(0).strip()
                
            city_display = "Remote" if is_remote and not city else (f"{city} / Remote" if is_remote and city else city)
            
            jobs.append({
                'title': title,
                'url': url,
                'company': company,
                'source': '4programmers',
                'city': city_display,
                'pay': pay,
                'published_at': ''
            })
            record_accepted("4prog", title)
            logger.info(f"  ACCEPTED (4programmers): {title} @ {company} | {city_display} | {pay}")
        except Exception as e:
            logger.error(f"Error scraping 4programmers {url}: {e}")
        finally:
            job_page.close()
            
    return jobs


def scrape_linkedin(browser, deep=False):
    logger.info("Scraping LinkedIn (guest mode)...")
    update_progress("LinkedIn", "", "Scanning LinkedIn QA listings...")
    page = browser.new_page()
    jobs = []
    
    search_queries = [
        ("https://www.linkedin.com/jobs/search?keywords=Manual%20QA&location=Poland&f_WT=2", True),
        ("https://www.linkedin.com/jobs/search?keywords=Tester%20Manualny&location=Poland&f_WT=2", True)
    ]
    if deep:
        search_queries.extend([
            ("https://www.linkedin.com/jobs/search?keywords=QA%20Tester&location=Poland&f_WT=2", True),
            ("https://www.linkedin.com/jobs/search?keywords=Tester%20Manualny&location=Gda%C5%84sk", False),
            ("https://www.linkedin.com/jobs/search?keywords=QA&location=Gda%C5%84sk", False)
        ])
        
    card_data = {}
    for query_url, default_remote in search_queries:
        try:
            page.goto(query_url, wait_until="domcontentloaded", timeout=30000)
            page.wait_for_timeout(2000)
            dismiss_cookie_consent(page)
            
            # Scroll slightly to load cards
            if deep:
                for _ in range(4):
                    page.mouse.wheel(0, 2000)
                    page.wait_for_timeout(1000)
                    
            soup = BeautifulSoup(page.content(), 'html.parser')
            cards = soup.find_all('div', class_=lambda c: c and 'base-card' in str(c))
            for c in cards:
                t_el = c.find(['h3', 'h4'], class_=lambda cl: cl and 'title' in str(cl))
                cmp_el = c.find(['h4', 'a'], class_=lambda cl: cl and 'subtitle' in str(cl))
                loc_el = c.find('span', class_=lambda cl: cl and 'location' in str(cl))
                time_el = c.find('time')
                link_el = c.find('a', href=True)
                
                title = t_el.get_text(strip=True) if t_el else ''
                company = cmp_el.get_text(strip=True) if cmp_el else 'Unknown'
                loc = loc_el.get_text(strip=True) if loc_el else ''
                pub_date = time_el.get('datetime', '') if time_el else ''
                raw_url = link_el['href'] if link_el else ''
                clean_url = raw_url.split('?')[0] if raw_url else ''
                
                if clean_url and clean_url not in card_data:
                    card_data[clean_url] = {
                        'title': title,
                        'company': company,
                        'location': loc,
                        'pub_date': pub_date,
                        'is_remote': default_remote
                    }
        except Exception as e:
            logger.error(f"Error collecting LinkedIn cards from {query_url}: {e}")
            
    page.close()
    logger.info(f"LinkedIn unique job cards collected: {len(card_data)}")
    
    # Filter candidates by title & location first
    candidates = []
    for url, item in card_data.items():
        title = item['title']
        record_scanned("LinkedIn", title or url)
        if not title or not parsers.is_title_valid(title):
            if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                record_rejected_automation("LinkedIn", title)
            else:
                record_rejected_other("LinkedIn", title, "Title")
            continue
            
        loc = item['location']
        is_pomerania = bool(parsers.POMERANIA_REGEX.search(loc + ' ' + title))
        is_hybrid = bool(re.search(r'(?i)\b(hybrid|hybryd\w*)\b', loc + ' ' + title))
        is_onsite = bool(re.search(r'(?i)\b(on-site|na miejscu|stacjonarn\w*)\b', loc + ' ' + title))
        has_other_city = bool(parsers.NON_POMERANIA_CITIES_REGEX.search(loc + ' ' + title))
        is_explicit_remote = bool(re.search(r'(?i)\b(remote|zdaln\w*)\b', loc + ' ' + title))
        
        # 1. Reject if hybrid or on-site in non-Pomerania city
        if is_hybrid and not is_pomerania:
            logger.info(f"  REJECTED (LinkedIn) non-Pomerania hybrid card: {title} @ {loc}")
            record_rejected_other("LinkedIn", title, "Location")
            continue
            
        if is_onsite and not is_pomerania:
            logger.info(f"  REJECTED (LinkedIn) non-Pomerania on-site card: {title} @ {loc}")
            record_rejected_other("LinkedIn", title, "Location")
            continue
            
        if has_other_city and not is_pomerania and not is_explicit_remote:
            logger.info(f"  REJECTED (LinkedIn) non-Pomerania city without remote card: {title} @ {loc}")
            record_rejected_other("LinkedIn", title, "Location")
            continue
            
        candidates.append((url, item))
        
    logger.info(f"LinkedIn candidate manual QA jobs to visit: {len(candidates)}")
    
    # Inspect up to 25 in normal, 60 in deep
    limit = 60 if deep else 25
    for url, item in candidates[:limit]:
        job_page = browser.new_page()
        try:
            job_page.goto(url, wait_until="domcontentloaded", timeout=25000)
            job_page.wait_for_timeout(1000)
            dismiss_cookie_consent(job_page)
            
            soup = BeautifulSoup(job_page.content(), 'html.parser')
            ld_scripts = soup.find_all('script', type='application/ld+json')
            ld_data = {}
            for s in ld_scripts:
                raw_text = s.get_text().strip()
                if raw_text:
                    try:
                        d = json.loads(raw_text, strict=False)
                        if isinstance(d, dict) and d.get('@type') == 'JobPosting':
                            ld_data = d
                            break
                    except: pass
                    
            desc = str(ld_data.get('description') or soup.get_text(separator=' ', strip=True))
            
            # --- Location & Hybrid Verification ---
            ld_locality = ""
            jl = ld_data.get('jobLocation') or {}
            if isinstance(jl, dict):
                addr = jl.get('address') or {}
                if isinstance(addr, dict):
                    ld_locality = addr.get('addressLocality') or ''
            ld_loc_type = ld_data.get('jobLocationType') or ''
            
            topcard_loc = ""
            for tag in soup.find_all(['span', 'div'], class_=lambda cl: cl and any(x in str(cl) for x in ['topcard__flavor', 'location', 'workplace'])):
                topcard_loc += " " + tag.get_text(strip=True)
                
            combined_loc_text = f"{item['location']} {ld_locality} {topcard_loc} {item['title']}"
            is_pomerania = bool(parsers.POMERANIA_REGEX.search(combined_loc_text))
            
            is_hybrid_desc = bool(re.search(
                r'(?i)\b(hybryd\w*|hybrid|model hybrydowy|praca hybrydowa|system hybrydowy|dni z biura|z biura w\b|z biura we\b)\b',
                desc[:2500] + ' ' + combined_loc_text
            ))
            is_onsite_desc = bool(re.search(
                r'(?i)\b(stacjonarn\w*|on-site|100%\s*stacjonarnie|praca z biura)\b',
                desc[:2500] + ' ' + combined_loc_text
            ))
            has_other_city = bool(parsers.NON_POMERANIA_CITIES_REGEX.search(combined_loc_text))
            
            # REJECT if hybrid outside Pomerania
            if is_hybrid_desc and not is_pomerania:
                logger.info(f"  REJECTED (LinkedIn) non-Pomerania hybrid: {item['title']} @ {combined_loc_text[:60]}")
                record_rejected_other("LinkedIn", item['title'], "Location")
                continue
                
            # REJECT if on-site outside Pomerania
            if is_onsite_desc and not is_pomerania:
                logger.info(f"  REJECTED (LinkedIn) non-Pomerania on-site: {item['title']} @ {combined_loc_text[:60]}")
                record_rejected_other("LinkedIn", item['title'], "Location")
                continue
                
            # REJECT if located in another city and not TELECOMMUTE and not explicitly 100% remote
            is_100_remote = (ld_loc_type == 'TELECOMMUTE') or bool(re.search(r'(?i)\b(100%\s*remote|fully\s*remote|ca[łl]kowicie\s*zdalnie|remote|zdalnie)\b', topcard_loc))
            if has_other_city and not is_pomerania and not is_100_remote:
                logger.info(f"  REJECTED (LinkedIn) other city not 100% remote: {item['title']} @ {combined_loc_text[:60]}")
                record_rejected_other("LinkedIn", item['title'], "Location")
                continue

            # Check automation tools in requirements
            has_auto = False
            for req_word in ['wymagania', 'oczekujemy', 'requirements', 'must have', 'required', 'qualifications']:
                if req_word in desc.lower():
                    idx = desc.lower().find(req_word)
                    req_slice = desc[idx:]
                    end_idx = 900
                    for marker in ['mile widziane', 'nice to have', 'dodatkowym atutem', 'oferujemy', 'we offer', 'benefity']:
                        m_idx = req_slice.lower().find(marker)
                        if m_idx != -1 and 0 < m_idx < end_idx:
                            end_idx = m_idx
                    chunk = req_slice[:end_idx]
                    if parsers.AUTOMATION_TOOLS_REGEX.search(chunk):
                        has_auto = True
                        break
                        
            if has_auto:
                logger.info(f"  REJECTED (LinkedIn) automation tools: {item['title']} @ {item['company']}")
                record_rejected_automation("LinkedIn", item['title'])
                continue
                
            # Salary if in LD+JSON or text
            pay = "Not given"
            base_sal = ld_data.get('baseSalary')
            if base_sal and isinstance(base_sal, dict):
                val = base_sal.get('value', {})
                curr = base_sal.get('currency', 'PLN')
                min_v = val.get('minValue')
                max_v = val.get('maxValue')
                if min_v and max_v:
                    pay = f"{int(min_v):,} - {int(max_v):,} {curr}".replace(',', ' ')
                elif min_v:
                    pay = f"od {int(min_v):,} {curr}".replace(',', ' ')
            else:
                m_pay = parsers.PAY_REGEX.search(desc)
                if m_pay:
                    pay = m_pay.group(0).strip()
                    
            pub_date = parsers.format_date_str(item['pub_date'] or str(ld_data.get('datePosted') or ''))
            
            if is_pomerania and is_hybrid_desc:
                m_pom = parsers.POMERANIA_REGEX.search(combined_loc_text)
                p_city = m_pom.group(0).title() if m_pom else "Gdańsk"
                city_display = f"{p_city} (Hybrid)"
            elif is_pomerania and is_100_remote:
                m_pom = parsers.POMERANIA_REGEX.search(combined_loc_text)
                p_city = m_pom.group(0).title() if m_pom else "Gdańsk"
                city_display = f"{p_city} / Remote"
            elif is_pomerania:
                m_pom = parsers.POMERANIA_REGEX.search(combined_loc_text)
                city_display = m_pom.group(0).title() if m_pom else "Gdańsk"
            else:
                city_display = "Remote"
            
            jobs.append({
                'title': item['title'],
                'url': url,
                'company': item['company'],
                'source': 'LinkedIn',
                'city': city_display,
                'pay': pay,
                'published_at': pub_date
            })
            record_accepted("LinkedIn", item['title'])
            logger.info(f"  ACCEPTED (LinkedIn): {item['title']} @ {item['company']} | {city_display} | {pay}")
            
        except Exception as e:
            logger.error(f"Error scraping LinkedIn {url}: {e}")
        finally:
            job_page.close()
            
    return jobs


def scrape_rocketjobs(browser, deep=False):
    logger.info("Scraping RocketJobs...")
    page = browser.new_page()
    jobs = []
    
    search_queries = [
        "https://rocketjobs.pl/oferty-pracy/wszystkie-lokalizacje?keyword=tester",
        "https://rocketjobs.pl/oferty-pracy/wszystkie-lokalizacje?keyword=qa"
    ]
    if deep:
        search_queries.append("https://rocketjobs.pl/oferty-pracy/wszystkie-lokalizacje?keyword=quality")
        
    seen_urls = set()
    raw_offers = []
    
    for q_url in search_queries:
        try:
            page.goto(q_url, wait_until="networkidle", timeout=30000)
            page.wait_for_timeout(2000)
            dismiss_cookie_consent(page)
            
            # Scroll
            scroll_count = 6 if deep else 3
            for _ in range(scroll_count):
                page.mouse.wheel(0, 1500)
                page.wait_for_timeout(1000)
                
            cards = page.evaluate("""() => {
                const h3s = Array.from(document.querySelectorAll('h3'));
                return h3s.map(h3 => {
                    const title = h3.innerText.trim();
                    let a = h3.closest('a');
                    if (!a) {
                        const parent = h3.closest('li') || h3.closest('div');
                        a = parent ? parent.querySelector('a[href*="/oferta-pracy/"]') : null;
                    }
                    const url = a ? a.href.replace('rocketjobs.pl//', 'rocketjobs.pl/') : '';
                    
                    let card = h3;
                    while (card.parentElement && !card.tagName.match(/LI|ARTICLE/i) && card.parentElement.innerText.length < 500) {
                        card = card.parentElement;
                    }
                    return { title, url, cardText: card.innerText };
                });
            }""")
            
            for c in cards:
                url = c['url']
                if not url:
                    continue
                if url in seen_urls:
                    METRICS["duplicates"] += 1
                    continue
                seen_urls.add(url)
                raw_offers.append(c)
        except Exception as e:
            logger.error(f"Error scraping RocketJobs query {q_url}: {e}")
            
    page.close()
    logger.info(f"RocketJobs unique cards collected: {len(raw_offers)}")
    
    for c in raw_offers:
        title = c['title']
        card_text = c['cardText']
        record_scanned("Rocket", title)
        lines = [l.strip() for l in card_text.split('\n') if l.strip()]
        company = lines[0] if lines else "Unknown"
        
        # 1. Title validation
        if not parsers.is_title_valid(title):
            if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                record_rejected_automation("Rocket", title)
            else:
                record_rejected_other("Rocket", title, "Title")
            continue
            
        # 2. Automation tools in card text
        if parsers.AUTOMATION_TOOLS_REGEX.search(card_text) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', card_text):
            record_rejected_automation("Rocket", title)
            logger.info(f"  REJECTED (RocketJobs) automation: {title} @ {company}")
            continue
            
        # 3. Location filter
        is_remote = bool(re.search(r'(?i)zdalnie|remote', card_text))
        is_tricity = bool(parsers.POMERANIA_REGEX.search(card_text))
        if not is_remote and not is_tricity:
            record_rejected_other("Rocket", title, "Location")
            continue
            
        # 4. Salary
        pay = "Not given"
        m_sal = re.search(r'(\d[\d\s]*\d\s*[-–]\s*\d[\d\s]*\d\s*(?:PLN|zł|EUR)?\s*/?\s*(?:godz|mies|h|month)?)', card_text, re.IGNORECASE)
        if m_sal:
            pay = m_sal.group(0).strip().replace('\xa0', ' ')
        elif parsers.PAY_REGEX.search(card_text):
            pay = parsers.PAY_REGEX.search(card_text).group(0).strip().replace('\xa0', ' ')
            
        city = "Remote" if is_remote and not is_tricity else ("Gdańsk / Remote" if is_remote and is_tricity else "Gdańsk")
        
        pub_date = ""
        m_date = re.search(r'(Wygasa\s+[^\n]+)', card_text)
        if m_date:
            pub_date = m_date.group(1).strip()
            
        job_item = {
            'title': title,
            'company': company,
            'url': c['url'],
            'city': city,
            'pay': pay,
            'published_at': pub_date,
            'source': 'RocketJobs'
        }
        jobs.append(job_item)
        record_accepted("Rocket", title)
        logger.info(f"  ACCEPTED (RocketJobs): {title} @ {company} | {city} | {pay}")
        
    return jobs


def scrape_qaboard(browser, deep=False):
    logger.info("Scraping QA Board (https://qaboard.pl/jobs)...")
    update_progress("QABoard", "", "Scanning QA Board listings...")
    jobs = []
    page = browser.new_page()
    seen_urls = set()
    
    max_pages = 5 if deep else 2
    for page_num in range(1, max_pages + 1):
        list_url = f"https://qaboard.pl/jobs?page={page_num}" if page_num > 1 else "https://qaboard.pl/jobs"
        try:
            page.goto(list_url, wait_until="domcontentloaded", timeout=25000)
            page.wait_for_timeout(2000)
            dismiss_cookie_consent(page)
            
            html = page.content()
            soup = BeautifulSoup(html, 'html.parser')
            articles = soup.find_all('article')
            if not articles:
                break
                
            for art in articles:
                card_text = art.get_text(separator=' | ', strip=True).replace('\u2013', '-').replace('\u2014', '-').replace('–', '-')
                
                job_url = ""
                for a in art.find_all('a', href=True):
                    href = a['href']
                    if '/jobs/' in href or 'solid.jobs' in href:
                        job_url = "https://qaboard.pl" + href if href.startswith('/') else href
                        break
                if not job_url:
                    a_tags = art.find_all('a', href=True)
                    if a_tags:
                        href = a_tags[-1]['href']
                        job_url = "https://qaboard.pl" + href if href.startswith('/') else href
                        
                if not job_url or job_url in seen_urls:
                    continue
                seen_urls.add(job_url)
                
                h_tag = art.find(['h1', 'h2', 'h3', 'h4'])
                raw_title = h_tag.get_text(strip=True) if h_tag else ""
                title = re.sub(r'(?i)(Senior|Mid|Junior|Lead)$', '', raw_title).strip()
                if not title:
                    title = raw_title
                    
                record_scanned("QABoard", title or job_url)
                    
                # 1. Title filter (Strict Manual QA only)
                if not parsers.is_title_valid(title):
                    logger.info(f"  REJECTED (QABoard) title: {title}")
                    if parsers.AUTOMATION_TOOLS_REGEX.search(title) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', title):
                        record_rejected_automation("QABoard", title)
                    else:
                        record_rejected_other("QABoard", title, "Title")
                    continue
                    
                # 2. Automation tools in card text
                if parsers.AUTOMATION_TOOLS_REGEX.search(card_text) or re.search(r'(?i)\b(automation|automatyzacj\w*|automatyzuj\w*|sdet)\b', card_text):
                    logger.info(f"  REJECTED (QABoard) automation: {title}")
                    record_rejected_automation("QABoard", title)
                    continue
                    
                # 3. Location filter: Remote OR Pomerania
                is_remote = bool(re.search(r'(?i)\bzdalnie\b|\bremote\b', card_text))
                is_pomerania = bool(parsers.POMERANIA_REGEX.search(card_text))
                is_other_city = bool(re.search(r'(?i)\b(warszaw\w*|warsaw|krak[óo]w|krakow|wroc[łl]aw|wroclaw|pozna[ńn]|poznan|katowic\w*|silesia|[łl][óo]d[źz]|lodz|szczecin|lublin|bia[łl]ystok|rzesz[óo]w|bydgoszcz|toru[ńn])\b', card_text))
                is_hybrid = bool(re.search(r'(?i)\bhybryd\w*|hybrid\b', card_text))
                
                # Reject if hybrid/onsite in non-Pomerania city
                if is_other_city and (is_hybrid or not is_remote) and not is_pomerania:
                    logger.info(f"  REJECTED (QABoard) non-Pomerania location: {title} @ {card_text[:80]}")
                    record_rejected_other("QABoard", title, "Location")
                    continue
                    
                if not is_remote and not is_pomerania:
                    logger.info(f"  REJECTED (QABoard) location: {title}")
                    record_rejected_other("QABoard", title, "Location")
                    continue
                    
                # City display
                if is_pomerania and is_remote:
                    city_display = "Gdańsk / Remote"
                elif is_pomerania:
                    city_display = "Gdańsk (Hybrid)" if is_hybrid else "Gdańsk"
                else:
                    city_display = "Remote"
                    
                company = "Quality Island"
                if "ITFS" in card_text:
                    company = "ITFS"
                elif "Solid.Jobs" in card_text:
                    company = "Quality Island Partner"
                    
                pay = "Not given"
                m_sal = re.search(r'Wynagrodzenie\s*\|\s*([\d\s,.-]+)\s*\|\s*(PLN/[hm]|zł/[hm]|PLN|EUR|USD)', card_text, re.I)
                if m_sal:
                    pay = parsers.clean_pay(f"{m_sal.group(1).strip()} {m_sal.group(2).strip()}")
                elif parsers.PAY_REGEX.search(card_text):
                    pay = parsers.clean_pay(parsers.PAY_REGEX.search(card_text).group(0))
                    
                pub_date = ""
                m_pub = re.search(r'Opublikowano\s+([^\n|]+)', card_text)
                if m_pub:
                    pub_date = m_pub.group(1).strip()
                    
                job_item = {
                    'title': title,
                    'company': company,
                    'url': job_url,
                    'city': city_display,
                    'pay': pay,
                    'published_at': pub_date,
                    'source': 'QABoard'
                }
                jobs.append(job_item)
                record_accepted("QABoard", title)
                logger.info(f"  ACCEPTED (QABoard): {title} @ {company} | {city_display} | {pay}")
        except Exception as e:
            logger.error(f"Error scraping QABoard page {page_num}: {e}")
            break
            
    page.close()
    return jobs


def run_scraper(portal="ALL", deep=False):
    global SCRAPER_STATE
    reset_metrics()
    SCRAPER_STATE["is_running"] = True
    SCRAPER_STATE["portal"] = portal
    SCRAPER_STATE["deep"] = deep
    SCRAPER_STATE["current_portal"] = portal
    SCRAPER_STATE["current_job"] = "Initializing browser..."
    SCRAPER_STATE["current_status"] = "Launching scraper..."
    
    all_raw_jobs = []
    
    # headless=False with stealth flags to bypass WAF / Cloudflare blocks
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=[
                '--disable-blink-features=AutomationControlled',
                '--no-sandbox',
                '--disable-infobars',
                '--disable-dev-shm-usage',
            ]
        )
        
        if portal in ["ALL", "JJIT"]:
            all_raw_jobs.extend(scrape_jjit(browser, deep))
        if portal in ["ALL", "NFJ"]:
            all_raw_jobs.extend(scrape_nfj(browser, deep))
        if portal in ["ALL", "PRACUJ"]:
            all_raw_jobs.extend(scrape_pracuj(browser, deep))
        if portal in ["ALL", "PROTOCOL"]:
            all_raw_jobs.extend(scrape_protocol(browser, deep))
        if portal in ["ALL", "BULLDOG"]:
            all_raw_jobs.extend(scrape_bulldogjob(browser, deep))
        if portal in ["ALL", "SOLID"]:
            all_raw_jobs.extend(scrape_solidjobs(browser, deep))
        if portal in ["ALL", "4PROGRAMMERS"]:
            all_raw_jobs.extend(scrape_4programmers(browser, deep))
        if portal in ["ALL", "LINKEDIN"]:
            all_raw_jobs.extend(scrape_linkedin(browser, deep))
        if portal in ["ALL", "ROCKET", "ROCKETJOBS"]:
            all_raw_jobs.extend(scrape_rocketjobs(browser, deep))
        if portal in ["ALL", "QABOARD", "QA_BOARD"]:
            all_raw_jobs.extend(scrape_qaboard(browser, deep))
            
        browser.close()
        
    initial_count = len(all_raw_jobs)
    deduplicated = parsers.deduplicate_jobs(all_raw_jobs)
    dedup_diff = initial_count - len(deduplicated)
    METRICS["duplicates"] += dedup_diff
    SCRAPER_STATE["duplicates"] += dedup_diff
    SCRAPER_STATE["is_running"] = False
    SCRAPER_STATE["current_status"] = "Scan complete"
    
    # Build lookup maps for extra fields
    extra_map = {job['url']: job for job in all_raw_jobs}
    
    final_jobs = []
    for job in deduplicated:
        raw = extra_map.get(job['url'], {})
        final_jobs.append({
            'title': job['title'],
            'url': job['url'],
            'company': raw.get('company') or job.get('company', ''),
            'source': raw.get('source', 'Unknown'),
            'city': raw.get('city', ''),
            'pay': raw.get('pay') or 'Not given',
            'published_at': raw.get('published_at', '')
        })
    
    logger.info(f"FINAL: {len(final_jobs)} unique valid jobs from {len(all_raw_jobs)} raw matches")
    return {
        "jobs": final_jobs,
        "metrics": dict(METRICS)
    }

if __name__ == "__main__":
    jobs = run_scraper("ALL")
    for j in jobs:
        logger.info(j)
