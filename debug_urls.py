"""Debug: check what testing category jobs are on theprotocol.it"""
from playwright.sync_api import sync_playwright
from scraper import dismiss_cookie_consent

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    
    # Check the testing category directly
    url = "https://theprotocol.it/filtry/testing;t"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    dismiss_cookie_consent(page)
    page.wait_for_timeout(1000)
    
    # Scroll to load
    for _ in range(3):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1500)
    
    # Get all job links and their titles
    cards = page.query_selector_all('a[href*="szczegoly"]')
    print(f"Found {len(cards)} job cards in testing category (no location filter)")
    for i, card in enumerate(cards[:30]):
        href = card.get_attribute('href')
        # Try to get the job title text from inside the card
        title_el = card.query_selector('h2, h3, span')
        title = title_el.inner_text() if title_el else card.inner_text()[:60]
        print(f"  {i+1}. {title.strip()[:60]:60} | {href[:50]}")
    
    # Now check with gdansk/remote filter
    print("\n\n=== WITH GDANSK FILTER ===")
    page.goto("https://theprotocol.it/filtry/testing;t/gdansk;wp", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    for _ in range(2):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1500)
    
    cards2 = page.query_selector_all('a[href*="szczegoly"]')
    print(f"Found {len(cards2)} jobs in testing+gdansk")
    for i, card in enumerate(cards2[:20]):
        href = card.get_attribute('href')
        title_el = card.query_selector('h2, h3, span')
        title = title_el.inner_text() if title_el else card.inner_text()[:60]
        print(f"  {i+1}. {title.strip()[:60]:60} | {href[:50]}")
    
    print("\n\n=== WITH REMOTE FILTER ===")
    page.goto("https://theprotocol.it/filtry/testing;t/praca-zdalna;wm", wait_until="domcontentloaded")
    page.wait_for_timeout(3000)
    for _ in range(2):
        page.mouse.wheel(0, 2000)
        page.wait_for_timeout(1500)
    
    cards3 = page.query_selector_all('a[href*="szczegoly"]')
    print(f"Found {len(cards3)} jobs in testing+remote")
    for i, card in enumerate(cards3[:20]):
        href = card.get_attribute('href')
        title_el = card.query_selector('h2, h3, span')
        title = title_el.inner_text() if title_el else card.inner_text()[:60]
        print(f"  {i+1}. {title.strip()[:60]:60} | {href[:50]}")
    
    browser.close()
