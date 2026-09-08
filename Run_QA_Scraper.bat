@echo off
echo Starting QA Job Scraper...
cd /d "%~dp0"
start "QA Scraper Backend" python app.py
timeout /t 3 >nul
start http://localhost:8000
