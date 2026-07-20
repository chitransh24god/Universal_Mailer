# AI Handoff & Architecture Document
**Project Name**: Universal Mailer v2
**Target Environment**: Standalone Desktop Executable (`.exe`) via local SQLite.

> **ATTENTION AI AGENT**: Read this file to instantly understand the entire architecture, tech stack, and state of this project without needing to waste tokens reading every single source code file. 

## 1. Project Purpose
This is a self-hosted, offline-capable bulk email automation platform. It bypasses restrictive 3rd-party SaaS email APIs by connecting directly to any email provider (Gmail, Outlook, custom domains) using standard **SMTP** (for sending) and **IMAP** (for tracking replies and bounces). It features a built-in tracking pixel for open rates, a dynamic UI dashboard, and smart campaign automation.

## 2. Tech Stack
- **Backend Server**: Python (FastAPI, Uvicorn)
- **Database**: SQLite3 (`universal_mailer.db`)
- **Frontend**: Vanilla HTML, CSS, JavaScript (Single Page Application architecture in `static/index.html`)
- **Core Python Libraries**: `smtplib`, `imaplib`, `pandas`, `jinja2`, `email`

## 3. Core Features & Logic
- **Provider Agnostic**: Users can add unlimited Sender Accounts (SMTP/IMAP credentials) via the UI.
- **Smart Pacing & Limits**: The background sender respects daily limits per sender (e.g., 300/day). If the limit is hit, the campaign *pauses* and goes to sleep. It automatically resumes the next day. It also enforces working hours (10 AM to 7 PM) and automatically sleeps/skips entirely on Sundays.
- **Open Tracking**: Injects a custom 1x1 invisible pixel (hosted on the FastAPI server `/api/track/{token}`) into outgoing HTML emails.
- **Reply & Bounce Tracking**: A background thread (`poll_replies`) logs into the sender's inbox via IMAP every few minutes, scanning for replies or bounce messages linked to the campaign's Message-IDs.
- **48h Alerts**: Flags recipients who have not opened or replied within 48 hours for manual follow-up.

## 4. File Structure
- `app.py`: The monolithic backend. Contains FastAPI routes, SMTP sending loops, IMAP polling threads, campaign automation logic, and time-pacing math.
- `database.py`: Initializes the SQLite schema. Contains tables for `sender_accounts`, `email_templates`, `sent_emails` (tracking), `replies`, and `daily_counter`.
- `static/index.html`: The monolithic frontend. Contains the CSS styling, Dashboard graphs (Chart.js), Settings tab, Tracking tab, and Campaign Upload wizard.
- `requirements.txt`: Python package dependencies.

## 5. Current State / Immediate Next Steps
The user is preparing to migrate the campaign logic from an in-memory loop to a **Persistent Database Queue Architecture**. 
Currently, campaigns run in a Python `BackgroundTasks` thread iterating over a Pandas DataFrame. If the terminal is closed, the campaign dies. 
**The immediate next step** is to refactor `app.py` and `database.py` to:
1. Save uploaded CSV rows directly to a `campaign_queue` SQLite table.
2. Build a cron-style worker that polls the DB for `pending` rows, respecting the existing 10 AM to 7 PM and limit logic, allowing campaigns to safely survive PC restarts and span across months.

After the Queue Architecture is complete, the final step is compiling the app into a `.exe` using PyInstaller.
