import re
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
from scraper import dismiss_cookie_consent
import parsers

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    # Let's check theprotocol.it testing category and keyword searches
    search_urls = [
        "https://theprotocol.it/filtry/tester;kw",
        "https://theprotocol.it/filtry/qa;kw",
        "https://theprotocol.it/filtry/testing;t"
    ]
    
    all_links = []
    for s_url in search_urls:
        page.goto(s_url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        dismiss_cookie_consent(page)
        for a in page.query_selector_all('a[href*="szczegoly"]'):
            href = a.get_attribute('href')
            if href:
                full = 'https://theprotocol.it' + href if href.startswith('/') else href
                if full not in all_links:
                    all_links.append(full)
                    
    print(f"Total unique protocol links found across search URLs: {len(all_links)}")
    
    for url in all_links[:25]:
        p2 = browser.new_page()
        try:
            p2.goto(url, wait_until="domcontentloaded", timeout=20000)
            p2.wait_for_timeout(2000)
            dismiss_cookie_consent(p2)
            try:
                p2.wait_for_selector('h1', timeout=4000)
            except:
                pass
            p2.wait_for_timeout(1000)
            
            soup = BeautifulSoup(p2.content(), 'html.parser')
            h1 = soup.find('h1')
            title = h1.get_text(strip=True) if h1 else 'No H1'
            
            # Check title
            title_ok = parsers.is_title_valid(title)
            
            # Check location
            full_text = soup.get_text(separator=' ')
            is_remote = bool(parsers.REMOTE_REGEX.search(full_text))
            has_tricity = bool(parsers.TRICITY_REGEX.search(full_text))
            loc_ok = is_remote or has_tricity
            
            # Check contract
            contract_ok = bool(parsers.CONTRACT_REGEX.search(full_text))
            
            # Check automation tools
            # Let's find exactly where automation tools appear if any!
            auto_in_req = False
            auto_snippets = []
            
            # Find Requirements vs Optional sections on theprotocol.it
            # Look for specific section headers on Protocol
            sections = soup.find_all(lambda tag: tag.name in ['h2', 'h3', 'h4', 'div', 'span'] and any(w in tag.get_text(strip=True).lower() for w in ['oczekujemy', 'wymagania', 'must have', 'mile widziane', 'nice to have', 'technologie']))
            
            for s in sections:
                header_text = s.get_text(strip=True).lower()
                parent = s.find_parent('div') or s.find_parent('section')
                if parent:
                    p_text = parent.get_text(separator=' ')
                    if parsers.AUTOMATION_TOOLS_REGEX.search(p_text):
                        auto_snippets.append(f"Header: [{header_text}] -> Match in section: {p_text[:120]}")
                        if any(w in header_text for w in ['oczekujemy', 'wymagania', 'must have']):
                            # Is it in optional part of this section?
                            auto_in_req = True
            
            print(f"\n--- Offer: {title} ---")
            print(f"  URL: {url[:70]}")
            print(f"  Title Valid? {title_ok}")
            print(f"  Loc Valid? {loc_ok} (remote={is_remote}, tricity={has_tricity})")
            print(f"  Contract Valid? {contract_ok}")
            print(f"  Auto in Req? {auto_in_req}")
            if auto_snippets:
                for snip in auto_snippets:
                    print(f"    {snip}")
                    
        except Exception as e:
            print(f"Error checking {url}: {e}")
        finally:
            p2.close()
            
    browser.close()
