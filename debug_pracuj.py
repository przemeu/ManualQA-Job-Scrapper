from playwright.sync_api import sync_playwright

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    page = browser.new_page()
    url = "https://www.pracuj.pl/praca/manual-tester-financial-services-testing-warszawa,oferta,1005055256"
    page.goto(url, wait_until="domcontentloaded")
    page.wait_for_timeout(2000)
    
    # Check for cookie/consent overlays
    btns = page.query_selector_all("button")
    print("=== ALL BUTTONS ===")
    for b in btns:
        try:
            txt = b.inner_text().strip()
            if txt:
                print(f"  Button: [{txt[:60]}]")
        except:
            pass
    
    # Try clicking common cookie consent patterns
    for selector in [
        "button:has-text('Akceptuję')",
        "button:has-text('Akceptuj')",
        "button:has-text('Accept')",
        "button:has-text('Zgadzam')",
        "button:has-text('OK')",
        "#onetrust-accept-btn-handler",
        ".cookie-accept",
    ]:
        try:
            btn = page.query_selector(selector)
            if btn and btn.is_visible():
                print(f"FOUND consent button: {selector}")
                btn.click()
                page.wait_for_timeout(2000)
                break
        except:
            pass
    
    # Now check content
    page.wait_for_timeout(3000)
    h1 = page.query_selector("h1")
    if h1:
        print(f"H1: {h1.inner_text()}")
    
    title_dt = page.query_selector('[data-test="text-positionName"]')
    if title_dt:
        print(f"TITLE (data-test): {title_dt.inner_text()}")
    else:
        print("data-test title NOT found")
    
    # Print page title
    print(f"Page title: {page.title()}")
    
    # Check if there's an iframe or shadow DOM
    frames = page.frames
    print(f"Number of frames: {len(frames)}")
    for f in frames:
        print(f"  Frame: {f.url[:80]}")
    
    browser.close()
