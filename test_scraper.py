"""Full Pracuj test with fresh pages."""
from scraper import scrape_pracuj
from playwright.sync_api import sync_playwright
import logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s', handlers=[logging.StreamHandler()])

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)
    pracuj_jobs = scrape_pracuj(browser)
    print(f"\n===== Pracuj results: {len(pracuj_jobs)} =====")
    for j in pracuj_jobs:
        print(f"  {j['title']} @ {j['company']}")
    browser.close()
