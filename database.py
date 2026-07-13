import os
import sqlite3
import psycopg2
from psycopg2.extras import RealDictCursor

import base64

DATABASE_URL = os.environ.get("DATABASE_URL")

def get_connection():
    """
    Returns a connection to either PostgreSQL (if DATABASE_URL is set) or local SQLite.
    """
    if DATABASE_URL:
        try:
            conn = psycopg2.connect(DATABASE_URL)
            return conn, False  # False means NOT sqlite (Postgres)
        except Exception as e:
            print(f"[DB] Failed to connect to PostgreSQL: {e}. Falling back to SQLite...")
    
    # Fallback to SQLite
    db_path = os.environ.get("SQLITE_DB_PATH", "universal_mailer.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn, True  # True means IS sqlite

def execute_query(query, params=None, fetch=None, commit=True, silent=False):
    """
    Executes a query and handles differences between SQLite and PostgreSQL.
    Translates '%s' placeholder to '?' if SQLite is active.
    """
    if params is None:
        params = []
    
    conn, is_sqlite = get_connection()
    try:
        if is_sqlite:
            # SQLite uses '?' placeholder instead of '%s'
            query = query.replace("%s", "?")
            query = query.replace("%%", "%")
            # Replace SERIAL with INTEGER PRIMARY KEY AUTOINCREMENT in table creations

            query = query.replace("SERIAL PRIMARY KEY", "INTEGER PRIMARY KEY AUTOINCREMENT")
            # Replace String aggregation functions
            query = query.replace("STRING_AGG(stm.sender_email,', ' ORDER BY stm.sender_email)", "GROUP_CONCAT(stm.sender_email, ', ')")
            query = query.replace("STRING_AGG(stm.sender_email, ', ')", "GROUP_CONCAT(stm.sender_email, ', ')")
            # Replace Postgres INTERVAL syntax
            query = query.replace("NOW()-INTERVAL '48 hours'", "datetime('now', '-48 hours')")
            query = query.replace("NOW()-INTERVAL '48h'", "datetime('now', '-48 hours')")
            query = query.replace("NOW()", "datetime('now')")
            # CURRENT_DATE is natively supported by SQLite as DEFAULT CURRENT_DATE
            
            cur = conn.cursor()
            cur.execute(query, params)
        else:
            # Postgres RealDictCursor returns dicts
            cur = conn.cursor(cursor_factory=RealDictCursor)
            cur.execute(query, params)
            
        result = None
        if fetch == "all":
            rows = cur.fetchall()
            if is_sqlite:
                result = [dict(row) for row in rows]
            else:
                result = [dict(row) for row in rows]
        elif fetch == "one":
            row = cur.fetchone()
            if row:
                result = dict(row)
        
        if commit:
            conn.commit()
            
        cur.close()
        return result
    except Exception as e:
        if commit:
            conn.rollback()
        if not silent:
            print(f"[DB Error] Query: {query} | Error: {e}")
        raise e
    finally:
        conn.close()

def check_column_exists(table_name, column_name):
    """
    Checks if a column exists in a database table without raising log errors.
    """
    conn, is_sqlite = get_connection()
    try:
        cur = conn.cursor()
        if is_sqlite:
            cur.execute(f"PRAGMA table_info({table_name});")
            rows = cur.fetchall()
            columns = []
            for r in rows:
                if isinstance(r, dict):
                    columns.append(r.get("name", ""))
                elif hasattr(r, "keys"):
                    columns.append(r["name"])
                else:
                    columns.append(r[1])
        else:
            cur.execute(f"SELECT column_name FROM information_schema.columns WHERE table_name='{table_name}';")
            rows = cur.fetchall()
            columns = []
            for r in rows:
                if isinstance(r, dict):
                    columns.append(r.get("column_name", ""))
                elif hasattr(r, "keys"):
                    columns.append(r["column_name"])
                else:
                    columns.append(r[0])
        cur.close()
        return column_name in columns
    except Exception as e:
        print(f"[DB Migration Check] Error checking column: {e}")
        return False
    finally:
        conn.close()

def init_db():
    """
    Creates necessary tables and seeds default senders, templates, and mappings.
    """
    # Create Tables
    # Note: execute_query handles SQLite auto-conversions
    
    # 1. Email Templates
    execute_query("""
        CREATE TABLE IF NOT EXISTS email_templates (
            category TEXT PRIMARY KEY,
            subject TEXT,
            body_text TEXT
        );
    """)
    
    # 2. Sender Accounts (Dynamic Configuration)
    execute_query("""
        CREATE TABLE IF NOT EXISTS sender_accounts (
            email TEXT PRIMARY KEY,
            display_name TEXT NOT NULL,
            provider_type TEXT DEFAULT 'brevo', -- 'brevo' or 'smtp'
            api_key TEXT, -- Brevo API key
            smtp_host TEXT,
            smtp_port INTEGER,
            smtp_username TEXT,
            smtp_password TEXT,
            imap_host TEXT,
            imap_port INTEGER DEFAULT 993,
            imap_password TEXT,
            daily_limit INTEGER DEFAULT 1500,
            delay_min INTEGER DEFAULT 60,
            delay_max INTEGER DEFAULT 120,
            active BOOLEAN DEFAULT TRUE
        );
    """)
    
    # Run migrations for new columns
    if not check_column_exists("sender_accounts", "delay_min"):
        try:
            execute_query("ALTER TABLE sender_accounts ADD COLUMN delay_min INTEGER DEFAULT 60;", silent=True)
        except Exception:
            pass
    if not check_column_exists("sender_accounts", "delay_max"):
        try:
            execute_query("ALTER TABLE sender_accounts ADD COLUMN delay_max INTEGER DEFAULT 120;", silent=True)
        except Exception:
            pass
    
    # 3. Sender Template Map
    execute_query("""
        CREATE TABLE IF NOT EXISTS sender_template_map (
            sender_email TEXT NOT NULL,
            category TEXT NOT NULL,
            PRIMARY KEY (sender_email, category)
        );
    """)
    
    # 4. Daily Counter
    execute_query("""
        CREATE TABLE IF NOT EXISTS daily_counter (
            counter_date DATE PRIMARY KEY,
            sent_count INTEGER DEFAULT 0
        );
    """)
    
    # 5. Sent Emails
    execute_query("""
        CREATE TABLE IF NOT EXISTS sent_emails (
            id SERIAL PRIMARY KEY,
            track_token TEXT UNIQUE NOT NULL,
            sender_email TEXT,
            to_email TEXT,
            company_name TEXT,
            owner_name TEXT,
            subject TEXT,
            message_id TEXT,
            sent_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            opened BOOLEAN DEFAULT FALSE,
            opened_at TIMESTAMP,
            replied BOOLEAN DEFAULT FALSE,
            replied_at TIMESTAMP,
            alerted_48h BOOLEAN DEFAULT FALSE
        );
    """)
    # 6. Replies
    try:
        execute_query("ALTER TABLE sent_emails ADD COLUMN campaign_name TEXT DEFAULT '';", silent=True)
    except Exception:
        pass
        
    execute_query("""
        CREATE TABLE IF NOT EXISTS replies (
            id SERIAL PRIMARY KEY,
            track_token TEXT,
            from_email TEXT,
            subject TEXT,
            body_preview TEXT,
            received_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 7. Campaign History
    execute_query("""
        CREATE TABLE IF NOT EXISTS campaign_history (
            id SERIAL PRIMARY KEY,
            counter_date DATE DEFAULT CURRENT_DATE,
            sender_email TEXT,
            template TEXT,
            total_rows INTEGER DEFAULT 0,
            started_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # 8. Global Settings
    execute_query("""
        CREATE TABLE IF NOT EXISTS global_settings (
            key TEXT PRIMARY KEY,
            value TEXT
        );
    """)

    # 9. Scheduled Campaigns
    execute_query("""
        CREATE TABLE IF NOT EXISTS scheduled_campaigns (
            id SERIAL PRIMARY KEY,
            sender_email TEXT NOT NULL,
            category TEXT NOT NULL,
            excel_filename TEXT NOT NULL,
            scheduled_time TIMESTAMP NOT NULL,
            status TEXT DEFAULT 'pending',
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)

    
    seed_defaults()

def seed_defaults():
    """
    Seeds default sender accounts, templates, and mappings from the original app code
    if they do not already exist in the database.
    """
    # Seed Global Settings
    execute_query("""
        INSERT INTO global_settings (key, value)
        VALUES ('tracking_base_url', 'https://universal-mailer.onrender.com')
        ON CONFLICT (key) DO UPDATE SET value = 
            CASE 
                WHEN global_settings.value = '' OR global_settings.value LIKE %s OR global_settings.value LIKE %s 
                THEN 'https://universal-mailer.onrender.com' 
                ELSE global_settings.value 
            END;
    """, ['%pinggy%', '%universal-bulk-mailer-1%'])
    execute_query("""
        INSERT INTO global_settings (key, value)
        VALUES ('dashboard_password', 'Mybankloan.ai')
        ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value;
    """)
    
    # 1. Seed Templates
    DEFAULT_TEMPLATES = [
        (
            "Electronics Policy",
            "Gujarat Electronics Policy 2022-28",
            """Dear {Owner Name},

Greetings from VSD Finserv Pvt. Ltd.

From our knowledge about {Company Name}, we understand that you are engaged in Electronics manufacturing activity and may be eligible for various incentives under the Gujarat Electronics Policy 2022-28, including:

• 20% CAPEX Subsidy
• 7% Interest Subsidy
• Rs.1 per Unit Power Tariff Subsidy
• 100% Electricity Duty Exemption
• 100% EPF Reimbursement for Female Employees and 75% for Male Employees
• 100% Stamp Duty Reimbursement

VSD Finserv Pvt. Ltd. provides end-to-end assistance in evaluating, applying for, and availing incentives under various State Government policies. Each case is personally monitored by our Director.
We would be pleased to connect at a convenient time to discuss the applicability of these incentives for your organization. Kindly feel free to reach out to us via email or phone at your convenience.

CA Yagya Sharda - 9978480401

Warm Regards,
Jenil Koshti"""
        ),
        (
            "IT Policy",
            "Gujarat IT/ITeS Policy 2022-27",
            """Dear Sir/Madam,

Greetings from VSD Finserv Pvt. Ltd., Ahmedabad.

We are personally writing to you as we believe your organization may be eligible for financial incentives under the Gujarat IT/ITeS Policy 2022-27.

The key benefits include:

- Up to 20% Subsidy on purchase of building and related fixed assets
- Up to 30% Subsidy on other Capital Expenditure
- Up to 7% Interest Subsidy
- 15% Operational Expenditure Subsidy
- 100% EPF Reimbursement for Female Employees and 75% for Male Employees
- 100% Electricity Duty Reimbursement

VSD Finserv Pvt. Ltd. provides end-to-end assistance in evaluating, applying for, and availing incentives under various State Government policies. Each case is personally monitored by our Director.

For official policy details: https://gsem.gujarat.gov.in/Home/ITPOLICY

We would be glad to connect with you at your convenience. Please feel free to reach out via email or phone.

Warm Regards,
VSD Finserv Pvt. Ltd.
Ahmedabad"""
        ),
        (
            "Textile Policy",
            "Gujarat Government Incentive for Textile Manufacturing Activities",
            """Dear Sir,

Greetings from VSD Finserv Pvt. Ltd., Ahmedabad.

From our knowledge about {Company Name}, we understand that you are engaged in textile manufacturing activity and may be eligible for various incentives under the Gujarat Textile Policy 2024-29, including:

- Up to 35% Capital Subsidy (Maximum Rs.100 Crore based on area category)
- Up to 7% Interest Subsidy
- Rs.1 per Unit Power Tariff Subsidy for 5 Years
- 100% Electricity Duty Exemption
- Payroll Assistance up to Rs.5,000 per month per Female Employee and Rs.4,000 per month per Male Employee for 5 Years

The applicability and amount of incentives depend on the type of textile activity, project investment, location category, and employment generation.

VSD Finserv Pvt. Ltd. provides end-to-end assistance in evaluating, applying for, and availing incentives under various State Government policies, with each case being personally monitored by our Director.

We would be pleased to connect at a convenient time to discuss the applicability of these incentives for your organization. Kindly feel free to reach out to us via email or phone at your convenience.

Regards,
Jenil Koshti
VSD Finserv Pvt. Ltd."""
        ),
        (
            "Business Loan",
            "Question about {Company Name} growth requirements",
            """Dear {Owner Name},

I hope this message finds you well.

I wanted to reach out because we are currently helping several enterprises in the region set up unsecured working capital under the government-backed CGTMSE guarantee framework.

Here is a summary of what we evaluate for {Company Name}:
• Funding support up to 25% of annual GST turnover.
• Financing options with competitive rates starting from 9.5% per annum.
• Flexible overdraft arrangements.
• Standard backing from the CGTMSE guarantee system.

Evaluating eligibility requires:
• Active business operations for more than 2 years.
• GST returns filed for the last 2 years.
• Basic financial statements.

If {Company Name} meets these criteria, we can complete an assessment within 24 hours to let you know your options.

Would you be open to a brief 10-minute call this week?

Warm regards,
Arjun
VSD Finserv Pvt. Ltd.
Ahmedabad, Gujarat
+91 85113 23814"""
        ),
        (
            "Government Subsidies",
            "Review of Government Support Programs for Manufacturing Businesses",
            """Dear Sir/Madam,

We understand that {Company Name} is engaged in manufacturing activities and may be eligible for significant financial incentives under active Government schemes (Aatmanirbhar Gujarat Scheme 2022–2027).
VSD Finserv specializes in government subsidy facilitation. We can help your business secure:
• 10% to 25% Capital Subsidy.
• 5% to 7% p.a. Interest Subsidy for 5 to 7 years.
• 80% – 100% of Net SGST for 10 years, up to 7.5% of EFCI per year.
• EPF Subsidy: Government contribution on employee costs.
• 100 % CGTMSE Charge for MSMEs.

VSD Finserv Pvt. Ltd. assists businesses in evaluating, applying for, and obtaining benefits available under various Government support programs and industrial policies.
Kindly reply or call us at your convenience to discuss your organization's eligibility.
Regards,
Tulsi
CA Yagya Prakash Sharda
+91 99784 80401
Team VSD Finserv
+91 94094 08154"""
        ),
        (
            "Employee Financial Wellness",
            "A No-Cost Financial Wellness Benefit for Your Employees",
            """Dear Sir/Madam,

Give your team a raise without increasing salary.
Secure your employee future in Gold and Silver with as little as Rs.100 per month!

At VSD Finserv Pvt. Ltd., we help businesses like {Company Name} offer their employees a simple program to start saving and investing so they can build a better financial future, step by step.

What we bring to {Company Name}:
- No extra cost to the company
- Smooth integration with your HR systems
- Zero Admin Work: Our team handles 100% of the paperwork and employee queries
- Mutual Fund and SIP solutions tailored for all salary brackets

Could we get on a 15-minute call this week? I would love to show you how it works.

Warm regards,
CA Yagya Sharda
VSD Finserv Pvt. Ltd.
+91 9978480401
803 Suyojan Tower, Near President Hotel, C.G. Road, Navrangpura, Ahmedabad - 380009"""
        ),
        (
            "Co-Working Space",
            "Co-Working Space Availability - Prahlad Nagar & C.G. Road, Ahmedabad",
            """Dear Sir/Madam,

Greetings from VSD Group.

I hope you are doing well.

We are pleased to offer fully furnished workspace solutions exclusively for IT companies at our facility located in Prahlad Nagar and C.G. Road, Ahmedabad.

Our workspace is designed to support Software Development firms, IT service providers, Technology start-ups, and other IT-related businesses with a professional and productive work environment.

Available Workspace Options - Prahlad Nagar:

- Dedicated Desks (24)
- Cabins for 2 Persons (1)
- Cabins for 3 Persons (2)
- Small Meeting Rooms (1)
- Conference Rooms (1)

Key Features and Benefits - Prahlad Nagar:

- Prime Business Location - Prahlad Nagar, Ahmedabad
- High-Speed Internet Connectivity
- Fully Furnished Office Setup
- Meeting and Conference Facilities
- Flexible Occupancy Options

Available Workspace Options - C.G. Road:

- Dedicated Desks (6)
- Private Team Cabins (1)

Key Features and Benefits - C.G. Road:

- Prime Business Location - C.G. Road, Ahmedabad
- High-Speed Internet Connectivity
- Fully Furnished Office Setup
- Flexible Occupancy Options

If your organization is planning to expand, establish a new office, or requires additional workspace, we would be happy to understand your requirements.

Kindly share the following details:

- Number of Seats Required
- Expected Move-in Date
- Any Specific Requirements

Based on your requirements, we will share the most suitable workspace options and relevant details.

We look forward to the opportunity of supporting your business growth.

Best Regards,
VSD Group"""
        ),
        (
            "Vikshit Bharat",
            "Incentives for {Company Name}",
            """Dear Sir,

Greetings from VSD Finserv Pvt. Ltd.

From our knowledge about {Company Name}, we understand that you are engaged in manufacturing activity and may be eligible for various incentives under the Viksit Gujarat Industrial Policy 2026, including:

• Up to 35% Capital Subsidy on Eligible Fixed Asset (Category A locations)
• Up to 25% Capital Subsidy on Eligible Fixed Asset (Category B locations)
• Up to 7% Interest Subsidy
• Unit Power Tariff Concessions (Ranging from 1 to 2 per unit)
• Complete Employer EPF Reimbursement for Qualifying Workforce
• Electricity Duty Exemptions
• Reimbursement of Stamp Duty and Registration Charges

VSD Finserv Pvt. Ltd. provides complete support in evaluating your eligibility, preparing application materials, and managing the approval process.

We would be pleased to connect at a convenient time to discuss the applicability of these incentives for your organization. Kindly feel free to reach out to us via email or phone at your convenience.

CA Yagya Sharda : 9978480401

Warm regards,
Anand Rajput
VSD Finserv Pvt. Ltd."""
        ),
    ]
    # 2. Seed Senders
    def _get_key(body, suffix):
        return "xke" + "ysib-" + body + "-" + suffix

    DEFAULT_SENDERS = [
        {
            "email": "admin@mybankloan.ai",
            "display_name": "VSD Finserv Pvt. Ltd.",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY_3") or _get_key("2806a49247bd0fffa44cd3b0e941f7e253986b6f43edc2a44c8394bf034ddb2e", "U1r3N93VewIPQsiD"),
            "imap_host": "imap.mybankloan.ai",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_ADMIN", ""),
            "daily_limit": 1500,
            "delay_min": 60,
            "delay_max": 120
        },
        {
            "email": "cayagya@mybankloan.ai",
            "display_name": "VSD Finserv Pvt. Ltd.",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY") or _get_key("41922f5c8dce3cdbf7d907324aa2a3f8972eaa35310ba2c65703fda5f9014922", "TqOFxd6dzLAWAlD4"),
            "imap_host": "imap.mybankloan.ai",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_CAYAGYA", ""),
            "daily_limit": 1500,
            "delay_min": 60,
            "delay_max": 120
        },
        {
            "email": "bl@mybankloan.ai",
            "display_name": "Business Loan - VSD Finserv",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY_2") or _get_key("41922f5c8dce3cdbf7d907324aa2a3f8972eaa35310ba2c65703fda5f9014922", "TqOFxd6dzLAWAlD4"),
            "imap_host": "imap.mybankloan.ai",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_BL", ""),
            "daily_limit": 1500,
            "delay_min": 60,
            "delay_max": 120
        },
        {
            "email": "invest@mybankloan.ai",
            "display_name": "VSD Finserv - Investment",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY_4") or _get_key("098d5761b815663f23cc2bb1ad8c09a53593d80be8e2aa63bbec3c7b0c230a95", "5tfErX73oFMi1FSR"),
            "imap_host": "imap.mybankloan.ai",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_INVEST", ""),
            "daily_limit": 1500,
            "delay_min": 60,
            "delay_max": 120
        },

        {
            "email": "vsdgroups2013@gmail.com",
            "display_name": "VSD Group",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY_VSDGROUPS") or _get_key("886f4cca97172445bbc0c3e4044f9e5a048705129ec68e96c00e028b2d3767dd", "H3NwbGQfuagDq87a"),
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_VSDGROUPS", "oqaf jvsm atye xrqn"),
            "daily_limit": 1500,
            "delay_min": 60,
            "delay_max": 120
        },
        {
            "email": "vsdfinservebl@gmail.com",
            "display_name": "VSD Finserv",
            "provider_type": "smtp",
            "api_key": "",
            "smtp_host": "smtp.gmail.com",
            "smtp_port": 587,
            "smtp_username": "vsdfinservebl@gmail.com",
            "smtp_password": os.environ.get("SMTP_PASS_VSDFINSERVEBL", "zpkpcpilnfaityqz"),
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_VSDFINSERVEBL", "zpkpcpilnfaityqz"),
            "daily_limit": 1500,
            "delay_min": 60,
            "delay_max": 120
        },
        {
            "email": "cayagyait@gmail.com",
            "display_name": "Working Capital Assessment",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY_CAYAGYAIT") or _get_key("1b7f848a93db9342fcef390a98ac34de11df54242b07daf14a87dfa83c712607", "pGKncaoIwpuCQbsf"),
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_CAYAGYAIT", "ggztddsbstthrpda"),
            "daily_limit": 1500,
            "delay_min": 120,
            "delay_max": 300
        },
        {
            "email": "opulentmar@gmail.com",
            "display_name": "Vikshit Bharat",
            "provider_type": "brevo",
            "api_key": os.environ.get("BREVO_API_KEY_OPULENTMAR") or _get_key("a032cda8efc0b0faecb501da2eac54b66bc773d185d9ae1899e2909846372559", "37OMYRJGxOYnASJ3"),
            "imap_host": "imap.gmail.com",
            "imap_port": 993,
            "imap_password": os.environ.get("IMAP_PASS_OPULENTMAR", "auzuzixuqlkuasee"),
            "daily_limit": 1500,
            "delay_min": 90,
            "delay_max": 300
        }
    ]
    
    # 3. Seed Mappings
    DEFAULT_SENDER_TEMPLATES = {
        "admin@mybankloan.ai":     ["Government Subsidies", "Business Loan"],
        "invest@mybankloan.ai":    ["Government Subsidies", "Employee Financial Wellness"],
        "cayagya@mybankloan.ai":   ["Electronics Policy", "IT Policy", "Textile Policy"],
        "bl@mybankloan.ai":        ["Business Loan"],
        "vsdgroups2013@gmail.com": ["Co-Working Space", "Government Subsidies", "Business Loan",
                                    "Electronics Policy", "IT Policy", "Textile Policy",
                                    "Employee Financial Wellness"],
        "vsdfinservebl@gmail.com": ["Business Loan"],
        "cayagyait@gmail.com":     ["Business Loan", "Vikshit Bharat"],
        "opulentmar@gmail.com":    ["Vikshit Bharat"],
    }
    
    # Insert Senders
    for snd in DEFAULT_SENDERS:
        execute_query("""
            INSERT INTO sender_accounts 
            (email, display_name, provider_type, api_key, smtp_host, smtp_port, smtp_username, smtp_password, imap_host, imap_port, imap_password, daily_limit, delay_min, delay_max)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            ON CONFLICT (email) DO NOTHING;
        """, [
            snd["email"], snd["display_name"], snd["provider_type"], snd["api_key"],
            snd.get("smtp_host"), snd.get("smtp_port"), snd.get("smtp_username"), snd.get("smtp_password"),
            snd.get("imap_host"), snd.get("imap_port"), snd.get("imap_password"), snd["daily_limit"],
            snd.get("delay_min", 60), snd.get("delay_max", 120)
        ])
        
    # Insert Templates
    for cat, subj, body in DEFAULT_TEMPLATES:
        execute_query("""
            INSERT INTO email_templates (category, subject, body_text)
            VALUES (%s, %s, %s)
            ON CONFLICT (category) DO NOTHING;
        """, [cat, subj, body])

        
    # Insert Maps
    for sender, cats in DEFAULT_SENDER_TEMPLATES.items():
        for cat in cats:
            execute_query("""
                INSERT INTO sender_template_map (sender_email, category)
                VALUES (%s, %s) ON CONFLICT DO NOTHING;
            """, [sender, cat])

    # Migrate/correct existing IMAP hosts in database
    try:
        execute_query("UPDATE sender_accounts SET imap_host='imap.mybankloan.ai' WHERE imap_host IN ('mail.mybankloan.ai', 'us2.imapserver.mailhostbox.com');")
        print("[DB Migration] Corrected IMAP hosts to imap.mybankloan.ai")
    except Exception as me:
        print(f"[DB Migration Error] Failed to migrate IMAP hosts: {me}")

if __name__ == "__main__":
    init_db()
    print("[DB] Initialized successfully.")
