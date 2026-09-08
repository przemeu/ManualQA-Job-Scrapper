# Manual QA Job Hunter & Application Tracker

An automated job scraping, filtering, and application management dashboard tailored for **Manual QA / QA Engineers** in Poland (Remote & Tricity / Trójmiasto).

![Python](https://img.shields.io/badge/Python-3.10%2B-blue?logo=python)
![FastAPI](https://img.shields.io/badge/FastAPI-0.100%2B-009688?logo=fastapi)
![SQLite](https://img.shields.io/badge/SQLite-Database-003B57?logo=sqlite)
![TailwindCSS](https://img.shields.io/badge/Tailwind-CSS-38B2AC?logo=tailwind-css)

---

## Key Features

### 1. Multi-Portal Scraper
Scrapes Polish and international tech job portals for QA opportunities:
- **Pracuj.pl**
- **NoFluffJobs (NFJ)**
- **JustJoinIT (JJIT)**
- **RocketJobs**
- **BulldogJob**
- **LinkedIn**
- **TheProtocol**

### 2. Intelligent Filtering & Quality Control
- **Manual QA Focus**: Automatically weeds out developer/SDET automation-heavy listings while capturing genuine manual & exploratory QA roles.
- **Location Filters**: Quick chips for **Remote** and **Tricity** (Gdańsk, Gdynia, Sopot).
- **Duplicate Detection**: Filters out already seen and processed URLs across refresh cycles.

### 3. Application Pipeline & Mini-CRM
- **Stage Management**: Track progress for every job in APPLIED (Applied 🟣, Recruiter Screen 🔵, Tech Interview 🟡, Offer 🟢, Rejected 🔴).
- **Application Notes & Salary Tracker**: Store recruiter notes, technical test tasks, asked salary, and upcoming interview dates.
- **Tab Views**: Organized by ALL, NEW, APPLIED, IGNORED, and WRONG OFFERS.

### 4. Market & Salary Insights Dashboard
- Live salary statistics: median and range benchmarks.
- Salary transparency percentage.
- Remote work distribution and top in-demand QA skills.

### 5. Automation & Notifications
- **Background Auto-Scan**: Configurable interval scanner (e.g., every 30 or 60 minutes).
- **Desktop Toast Notifications**: Native Windows 10/11 alerts.
- **Telegram Bot Alerts**: Instant push notifications to your phone whenever new matching offers appear.

### 6. CSV Export & Sorting
- **1-Click Excel CSV Export**: UTF-8 BOM encoding with semicolon delimiters for Excel.
- **Multi-Key Sorting**: Sort by Newest, Company (A-Z / Z-A), Highest Salary, or Title.

---

## Installation & Setup

### 1. Clone the Repository
`ash
git clone https://github.com/przemeu/ManualQA-Job-Scrapper.git
cd ManualQA-Job-Scrapper
`

### 2. Install Dependencies
`ash
pip install -r requirements.txt
`

### 3. Run the Application
You can run it directly:
`ash
python app.py
`
Or use the Windows launcher batch file:
`cmd
Run_QA_Scraper.bat
`

Open your browser and navigate to:
`
http://127.0.0.1:8000
`

---

## Telegram Bot Notifications (Optional)

1. Open the **Settings** modal in the web dashboard.
2. Enter your **Telegram Bot Token** (from @BotFather) and **Chat ID** (from @userinfobot).
3. Click **Test Alert** to verify, then enable **Telegram Notifications**.
