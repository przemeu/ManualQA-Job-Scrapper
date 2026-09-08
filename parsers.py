import re
import json
from bs4 import BeautifulSoup
from typing import List, Dict, Optional, Any

# --- Regex Patterns ---
AUTOMATION_TOOLS_REGEX = re.compile(r'(?i)\b(selenium|cypress|playwright|appium|restassured|puppeteer)\b')
POMERANIA_REGEX = re.compile(r'(?i)\b(pomorsk\w*|tr[óo]jmiasto|gda[ńn]sk|gdynia|sopot|rumia|reda|wejherow\w*|tczew\w*|s[łl]upsk\w*|starogard\w*|malbork\w*|kwidzyn\w*|l[ęe]bork\w*|pruszcz\s*gda[ńn]sk\w*)\b')
TRICITY_REGEX = POMERANIA_REGEX
REMOTE_REGEX = re.compile(r'(?i)\b(remote|praca\s*zdalna|100%\s*remote|fully\s*remote|zdalnie)\b')
CONTRACT_REGEX = re.compile(r'(?i)\b(uop|umow[ae]\s*o\s*prac[eę]|b2b)\b')
SUFFIX_STRIP_REGEX = re.compile(r'(?i)(\s*\(remote\)|\s*\(b2b\)|\s*sp\.\s*z\s*o\.\s*o\.?|\s*inc\.?|\s*llc\.?)')

# Title filters to ensure it's ONLY a manual QA role
TITLE_REQUIRED_REGEX = re.compile(r'(?i)\b(qa|test|tester|quality\s*assurance)\b')
TITLE_REJECT_REGEX = re.compile(
    r'(?i)\b(automation|automatyzuj\w*|automatyzacj\w*|automatyzacja|'
    r'sdet|engineer\s+in\s+test|developer|programmer|programista|architect\w*|'
    r'python|staff|support|manager|lead|director|head|pm|project\s*manager|product\s*manager|release\s*manager|product\s*owner|scrum\s*master|'
    r'data\s*engineer|data\s*qa|ai|machine\s*learning|'
    r'c#|java|kotlin|golang|rust|c\+\+|embedded|administrator|devops|sysadmin|'
    r'security|penetration|pentest\w*|fullstack|full\s*stack|performance|wydajno[śs]ciow\w*|'
    r'intern|sta[żz]|sta[żz]ysta|praktyk\w*|trener|trainer|szkoleniow\w*|wyk[łl]adowc\w*|'
    r'koordynator|coordinator)\b'
)

def is_title_valid(title: str) -> bool:
    """Ensures the job title is strictly for Manual QA/Testing, rejecting automation and dev roles."""
    if not title: 
        return False
    if not TITLE_REQUIRED_REGEX.search(title): 
        return False
    if TITLE_REJECT_REGEX.search(title): 
        return False
    return True

def is_location_valid(is_remote: bool, is_hybrid: bool, location_strings: List[str]) -> bool:
    if is_remote:
        return True
    if is_hybrid:
        for loc in location_strings:
            if POMERANIA_REGEX.search(loc):
                return True
    return False

# City names we care about, in priority order
CITY_NAMES = ['Gdańsk', 'Gdynia', 'Sopot', 'Rumia', 'Reda', 'Wejherowo', 'Tczew', 'Słupsk', 'Malbork', 'Starogard Gdański', 'Kwidzyn', 'Lębork', 'Pruszcz Gdański']
CITY_REGEX = re.compile(r'(?i)\b(gda[ńn]sk|gdynia|sopot|rumia|reda|wejherow\w*|tczew\w*|s[łl]upsk\w*|starogard\w*|malbork\w*|kwidzyn\w*|l[ęe]bork\w*|pruszcz\s*gda[ńn]sk\w*)\b')

# Pay regex: matches patterns like "10 000 - 15 000 PLN", "8000-12000 zł", "5k-8k", etc.
PAY_REGEX = re.compile(
    r'(\d[\d\s]*[\d]\s*[-–]\s*\d[\d\s]*[\d]\s*(?:PLN|pln|zł|z[lł]|EUR|eur|USD|usd|gross|netto|brutto|net))'
    r'|(\d[\d\s,.]*\s*(?:PLN|pln|zł|z[lł]|EUR|eur|USD|usd)\s*[-–]\s*\d[\d\s,.]*\s*(?:PLN|pln|zł|z[lł]|EUR|eur|USD|usd))',
    re.IGNORECASE
)

def extract_city(text: str) -> str:
    """Extract the most specific city name from text, or 'Remote' if remote."""
    if REMOTE_REGEX.search(text):
        # Check if also has a city (hybrid)
        match = CITY_REGEX.search(text)
        if match:
            city_raw = match.group(1).lower()
            for name in CITY_NAMES:
                if name.lower().replace('ń', 'n') == city_raw.replace('ń', 'n'):
                    return f"{name} / Remote"
            return f"{match.group(1).title()} / Remote"
        return "Remote"
    
    match = CITY_REGEX.search(text)
    if match:
        city_raw = match.group(1).lower()
        for name in CITY_NAMES:
            if name.lower().replace('ń', 'n') == city_raw.replace('ń', 'n'):
                return name
        return match.group(1).title()
    return ""

def clean_pay(val: str) -> str:
    if not val or val.strip() in ['Not given', 'brak widełek', 'brak widelek', 'None', '-']:
        return "Not given"
        
    s = val.replace('\xa0', ' ').replace('\u202f', ' ').strip()
    lower = s.lower()
    
    # 1. Detect period / time unit
    period = ''
    if any(k in lower for k in ['godzinow', '/ hour', '/ h', '/h', 'godz', 'per hour']):
        period = '/ h'
    elif any(k in lower for k in ['dziennie', 'dzień', 'dzien', '/ day', '/ d', '/d', 'per day']):
        period = '/ d'
    elif any(k in lower for k in ['rocznie', 'rok', '/ year', '/ y', '/y', 'per year']):
        period = '/ y'
    elif any(k in lower for k in ['miesi', '/ month', '/ m', '/m', 'per month']):
        period = '/ m'
        
    # 2. Detect currency
    curr = 'PLN'
    if 'EUR' in s or '€' in s:
        curr = 'EUR'
    elif 'USD' in s or '$' in s:
        curr = 'USD'
    elif 'GBP' in s or '£' in s:
        curr = 'GBP'
    elif 'zł' in lower or 'zl' in lower:
        curr = 'PLN'
        
    # 3. Clean clutter
    s = re.sub(r'(?i)\+\s*vat', '', s)
    s = re.sub(r'(?i)\(b2b\)|\(uop\)|b2b|uop', '', s)
    s = re.sub(r'(?i)brutto|netto', '', s)
    s = re.sub(r'(?i)oblicz\s*[\"\']?na\s*r[eę]k[eę][\"\']?', '', s)
    s = re.sub(r'(?i)oblicz\s*netto', '', s)
    s = re.sub(r'(?i)miesięcznie|miesiecznie|godzinowo|dziennie|rocznie|month|hour|year|day', '', s)
    s = re.sub(r'(?i)pln|eur|usd|gbp|zł|zl', '', s)
    s = re.sub(r'[/\\()]', '', s)
    s = s.replace('"', '').replace("'", '')
    
    # Normalize decimals e.g. 50,00 -> 50 or 50.00 -> 50
    s = re.sub(r'(\d+)[,.]00\b', r'\1', s)
    
    # Normalize dashes
    s = re.sub(r'\s*[-–—~to]+\s*', ' – ', s)
    s = re.sub(r'\s+', ' ', s).strip()
    
    # Find numbers and range
    nums_match = re.search(r'([\d\s]+(?:\s*–\s*[\d\s]+)?)', s)
    if not nums_match:
        return "Not given"
        
    num_part = nums_match.group(1).strip()
    if '–' in num_part:
        parts = [p.strip() for p in num_part.split('–')]
        if len(parts) == 2 and parts[0] and parts[1]:
            num_part = f"{parts[0]} – {parts[1]}"
        elif len(parts) == 2 and parts[0]:
            num_part = parts[0]
            
    res = f"{num_part} {curr}"
    if period:
        res += f" {period}"
    return res

def extract_pracuj_salary(soup: BeautifulSoup) -> str:
    """Extract salary from Pracuj offer header only, ignoring recommended offers."""
    if not soup:
        return "Not given"
    node = soup.find(attrs={'data-test': 'text-earningAmount'})
    if not node:
        node = soup.find(attrs={'data-test': 'section-salary'})
    if node:
        return clean_pay(node.get_text(strip=True))
    return "Not given"

def extract_protocol_salary(soup: BeautifulSoup) -> str:
    """Extract salary from Protocol offer header section."""
    if not soup:
        return "Not given"
    node = soup.find(attrs={'data-test': 'text-salary-value'})
    if not node:
        node = soup.find(attrs={'data-test': 'text-contractSalary'})
    if node:
        txt = node.get_text(strip=True)
        unit_node = soup.find(attrs={'data-test': 'text-contractTimeUnits'})
        if unit_node:
            txt += " " + unit_node.get_text(strip=True)
        return clean_pay(txt)
    return "Not given"

def extract_jjit_salary(soup: BeautifulSoup) -> str:
    """Extract salary from JJIT metadata or header."""
    if not soup:
        return "Not given"
    for s in soup.find_all('script', type='application/ld+json'):
        if not s.string: continue
        try:
            d = json.loads(s.string)
            if 'baseSalary' in d and isinstance(d['baseSalary'], dict):
                bs = d['baseSalary']
                curr = bs.get('currency', 'PLN')
                val = bs.get('value', {})
                min_v = val.get('minValue')
                max_v = val.get('maxValue')
                unit = val.get('unitText', '')
                if min_v and max_v:
                    u_str = f" / {unit.lower()}" if unit else ""
                    return f"{min_v:,} - {max_v:,} {curr}{u_str}".replace(',', ' ')
                elif min_v:
                    return f"{min_v:,} {curr}".replace(',', ' ')
        except:
            pass
    h1 = soup.find('h1')
    if h1:
        parent = h1.find_parent('div')
        if parent:
            for span in parent.find_all(['span', 'div']):
                t = span.get_text(strip=True)
                if any(c in t for c in ['PLN', 'EUR', 'USD', 'zł']) and re.search(r'\d', t):
                    return clean_pay(t)
    return "Not given"

def extract_nfj_salary(soup: BeautifulSoup) -> str:
    """Extract salary from NFJ metadata or salary badge."""
    if not soup:
        return "Not given"
    for s in soup.find_all('script', type='application/ld+json'):
        if not s.string: continue
        try:
            d = json.loads(s.string)
            items = d.get('@graph', [d]) if isinstance(d, dict) else []
            for item in items:
                if isinstance(item, dict) and 'baseSalary' in item:
                    bs = item['baseSalary']
                    if isinstance(bs, dict):
                        curr = bs.get('currency', 'PLN')
                        val = bs.get('value', {})
                        min_v = val.get('minValue')
                        max_v = val.get('maxValue')
                        if min_v and max_v:
                            return f"{min_v:,} - {max_v:,} {curr}".replace(',', ' ')
        except:
            pass
    for el in soup.find_all(['h4', 'span', 'div'], class_=lambda c: c and 'salary' in str(c).lower()):
        t = el.get_text(strip=True)
        if any(c in t for c in ['PLN', 'EUR', 'USD', 'zł']) and re.search(r'\d', t):
            return clean_pay(t)
    return "Not given"

def extract_pay(text: str) -> str:
    """Legacy helper fallback."""
    return "Not given"

def format_date_str(raw_date: str) -> str:
    if not raw_date:
        return ""
    raw_date = raw_date.strip()
    # Strip prefixes like "od:", "Published:", "Opublikowano:"
    raw_date = re.sub(r'(?i)^(od:|published:\s*|opublikowan[oay]:\s*|dodano:\s*)', '', raw_date).strip()
    # If ISO date e.g. 2026-08-27T13:00:37.283Z -> 2026-08-27
    iso_match = re.match(r'(\d{4}-\d{2}-\d{2})', raw_date)
    if iso_match:
        return iso_match.group(1)
    # If DD.MM.YYYY e.g. 28.08.2026
    dot_match = re.match(r'(\d{1,2}\.\d{1,2}\.\d{4})', raw_date)
    if dot_match:
        return dot_match.group(1)
    return raw_date

def extract_published_date(soup: BeautifulSoup, text: str = "") -> str:
    """Extract publication date using ld+json metadata, data-test attributes, and text regexes."""
    if not soup:
        return ""
    
    # 1. Try ld+json schema metadata (Pracuj, NFJ, JJIT)
    for s in soup.find_all('script', type='application/ld+json'):
        if not s.string:
            continue
        try:
            data = json.loads(s.string)
            if isinstance(data, dict):
                if 'datePosted' in data:
                    return format_date_str(str(data['datePosted']))
                if '@graph' in data and isinstance(data['@graph'], list):
                    for item in data['@graph']:
                        if isinstance(item, dict) and 'datePosted' in item:
                            return format_date_str(str(item['datePosted']))
        except:
            pass

    # 2. Try specific data-test attributes (Protocol, Pracuj)
    for attr in ['text-fromDate', 'text-publicationDate', 'text-publication-date', 'offer-published-date']:
        node = soup.find(attrs={'data-test': attr})
        if node:
            txt = node.get_text(strip=True)
            if txt:
                return format_date_str(txt)

    # 3. Try text regexes (e.g. Published: 28.08.2026 or Opublikowano: 28.08.2026)
    if text:
        match = re.search(r'(?i)(?:published|opublikowan[oay]|dodano)[:\s]+(\d{1,2}\.\d{1,2}\.\d{4}|\d{4}-\d{2}-\d{2}|\d{1,2}\s+[a-ząćęłńóśźż]+\s+\d{4})', text)
        if match:
            return format_date_str(match.group(1))

    return ""

# ==========================================
# 1. Portal-Specific Parsing & Filtering
# ==========================================

def parse_jjit(job_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    title = job_data.get('title', '')
    if not is_title_valid(title):
        return None

    workplace_type = job_data.get('workplace_type', '').lower()
    city = job_data.get('city', '')
    is_remote = workplace_type == 'remote'
    is_hybrid = workplace_type == 'partly_remote'
    
    if not is_location_valid(is_remote, is_hybrid, [city]):
        return None

    employment_types = job_data.get('employment_types', [])
    valid_contract = False
    for emp in employment_types:
        emp_type = emp.get('type', '').lower()
        if emp_type in ['b2b', 'permanent']:
            valid_contract = True
            break
    
    if not valid_contract:
        return None

    must_have_skills = job_data.get('must_have', []) 
    for skill in must_have_skills:
        if AUTOMATION_TOOLS_REGEX.search(skill):
            return None 

    return {
        'title': title,
        'url': job_data.get('url', ''),
        'company': job_data.get('company_name', '')
    }

def parse_nfj(job_data: Dict[str, Any]) -> Optional[Dict[str, str]]:
    title = job_data.get('title', '')
    if not is_title_valid(title):
        return None

    location = job_data.get('location', {})
    is_remote = location.get('fullyRemote', False)
    
    is_hybrid = False
    places = location.get('places', [])
    city_names = [place.get('city', '') for place in places]
    
    if not is_remote and places:
        is_hybrid = True
        
    if not is_location_valid(is_remote, is_hybrid, city_names):
        return None

    postings = job_data.get('postings', {})
    valid_contract = False
    if 'b2b' in postings or 'uop' in postings:
        valid_contract = True
        
    if not valid_contract:
        return None

    requirements = job_data.get('requirements', [])
    for req in requirements:
        if AUTOMATION_TOOLS_REGEX.search(req):
            return None 

    return {
        'title': title,
        'url': job_data.get('url', ''),
        'company': job_data.get('company', {}).get('name', '')
    }

def parse_pracuj(html_node: BeautifulSoup, url: str) -> Optional[Dict[str, str]]:
    title_node = html_node.find(['h1', 'h2'])
    title = title_node.get_text(strip=True) if title_node else 'Unknown Title'
    
    if not is_title_valid(title):
        return None

    text_content = html_node.get_text(separator=' ', strip=True)
    
    is_remote = bool(REMOTE_REGEX.search(text_content))
    is_hybrid = "hybrydow" in text_content.lower() or "hybrid" in text_content.lower()
    
    if not is_remote and not (is_hybrid and TRICITY_REGEX.search(text_content)):
        return None
        
    if not CONTRACT_REGEX.search(text_content):
        return None

    wymagania_section = html_node.find(lambda tag: tag.name in ['h2', 'h3', 'div'] and 'wymagania' in tag.get_text(strip=True).lower())
    if wymagania_section:
        requirements_list = wymagania_section.find_next(['ul', 'div'])
        if requirements_list:
            requirements_text = requirements_list.get_text(separator=' ')
            if AUTOMATION_TOOLS_REGEX.search(requirements_text):
                return None 

    company_node = html_node.find(lambda tag: tag.name in ['h2', 'h3', 'div'] and tag.has_attr('data-test') and 'company-name' in tag['data-test'])
    company = company_node.get_text(strip=True) if company_node else 'Unknown Company'

    return {
        'title': title,
        'url': url,
        'company': company
    }

def parse_protocol(html_node: BeautifulSoup, url: str) -> Optional[Dict[str, str]]:
    title_node = html_node.find('h1')
    title = title_node.get_text(strip=True) if title_node else 'Unknown Title'
    
    if not is_title_valid(title):
        return None

    text_content = html_node.get_text(separator=' ', strip=True)
    
    is_remote = bool(REMOTE_REGEX.search(text_content))
    is_hybrid = "hybryd" in text_content.lower()
    
    if not is_remote and not (is_hybrid and TRICITY_REGEX.search(text_content)):
        return None

    if not CONTRACT_REGEX.search(text_content):
        return None

    oczekujemy_section = html_node.find(lambda tag: tag.name in ['h2', 'h3', 'span'] and tag.get_text(strip=True).lower() in ['oczekujemy', 'wymagania'])
    if oczekujemy_section:
        requirements_container = oczekujemy_section.find_parent('div').find_next_sibling('div')
        if requirements_container:
            requirements_text = requirements_container.get_text(separator=' ')
            if AUTOMATION_TOOLS_REGEX.search(requirements_text):
                return None 

    company_node = html_node.find(lambda t: t.has_attr('data-test') and t['data-test'] == 'text-companyName')
    company = company_node.get_text(strip=True) if company_node else 'Unknown Company'

    return {
        'title': title,
        'url': url,
        'company': company
    }


# ==========================================
# 2. Deduplication Logic
# ==========================================

def normalize(text: str) -> str:
    if not text:
        return ""
    t = text.lower()
    t = SUFFIX_STRIP_REGEX.sub('', t)
    t = re.sub(r'[^\w\s]', '', t)
    t = re.sub(r'\s+', ' ', t).strip()
    return t

def deduplicate_jobs(jobs: List[Dict[str, str]]) -> List[Dict[str, str]]:
    seen_keys = set()
    unique_jobs = []
    
    for job in jobs:
        company_norm = normalize(job.get('company', ''))
        title_norm = normalize(job.get('title', ''))
        
        dedup_key = f"{company_norm}_{title_norm}"
        
        if dedup_key not in seen_keys:
            seen_keys.add(dedup_key)
            unique_jobs.append(job)
            
    return unique_jobs
