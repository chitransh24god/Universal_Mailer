import os
import time
import threading
import random
import re
import smtplib
import socket
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, date, timedelta
import pytz
import pandas as pd
import io
import requests
from fastapi import FastAPI, File, UploadFile, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

from database import init_db, execute_query
from analyzer import analyze_email

app = FastAPI()

IST = pytz.timezone("Asia/Kolkata")
DAILY_LIMIT = 1500  # Default fallback global limit
DELAY_MIN_SECS = 60
DELAY_MAX_SECS = 120
DASHBOARD_PASSWORD = os.environ.get("DASHBOARD_PASSWORD", "Mybankloan.ai")

def get_dashboard_password():
    try:
        row = execute_query("SELECT value FROM global_settings WHERE key='dashboard_password';", fetch="one")
        if row and row["value"]:
            return row["value"]
    except Exception:
        pass
    return DASHBOARD_PASSWORD
BREVO_API_URL = "https://api.brevo.com/v3/smtp/email"

# Active campaigns status dictionary
campaigns = {}
campaigns_lock = threading.Lock()
shared_log = []
log_lock = threading.Lock()

# ── Column alias sets for Excel parsing ────────────────────────────────────────
EMAIL_ALIASES = {
    'email', 'mail', 'e-mail', 'e mail', 'email id', 'email address',
    'emailid', 'email_id', 'emailaddress', 'company email', 'contact email',
    'business email', 'corporate email', 'official email',
    'director email', 'owner email', 'work email', 'email id.',
    'email-id', 'email (id)', 'e-mail id', 'email id (for communication)',
}
NAME_ALIASES = {
    'owner name', 'owner', 'director', 'director name',
    'contact name', 'contact person', 'person name', 'proprietor',
    'partner name', 'authorised person', 'authorised signatory',
    'first name', 'full name', 'applicant name', 'contact',
    'managing director', 'md name', 'ceo', 'ceo name',
    'key person', 'representative', 'signatory name',
}
COMPANY_ALIASES = {
    'company', 'company name', 'firm', 'firm name', 'business',
    'business name', 'organisation', 'organization', 'entity',
    'legal_name', 'legal name', 'trade_name', 'trade name',
    'enterprise', 'establishment',
    'company name (as per gst)', 'company/firm name', 'name of company',
    'name of firm', 'name of business', 'company / firm',
    'business entity', 'entity name', 'registered name', 'gst name',
}
PHONE_ALIASES = {
    'phone', 'mobile', 'contact no', 'phone no', 'mobile no',
    'cell', 'telephone', 'tel', 'contact number', 'mobile number',
    'phone number', 'whatsapp', 'mob', 'mob no', 'ph no',
}
LOCATION_ALIASES = {
    'city', 'district', 'location', 'state', 'address', 'area',
    'pincode', 'pin', 'region', 'zone', 'place', 'taluka',
}
BUSINESS_ALIASES = {
    'business_nature', 'business nature', 'nature of business',
    'industry', 'sector', 'type', 'business type', 'category',
    'activity', 'business activity', 'nature', 'field', 'domain',
}

def _find_col(columns, aliases):
    cols_lower = [c.lower().strip() for c in columns]
    for i, cl in enumerate(cols_lower):
        if cl in aliases:
            return columns[i]
    for i, cl in enumerate(cols_lower):
        for alias in aliases:
            if alias in cl or cl in alias:
                return columns[i]
    return None

def _valid_email_count(series):
    return series.apply(
        lambda v: bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]{2,}$', str(v).strip()))
    ).sum()

def smart_parse_excel(file_bytes):
    best_df = None
    best_email = None
    best_score = 0
    for hrow in range(5):
        try:
            df = pd.read_excel(io.BytesIO(file_bytes), header=hrow, dtype=str)
            df.columns = [str(c).strip() for c in df.columns]
            df = df.dropna(how='all').reset_index(drop=True)
            if df.empty:
                continue
            email_col = _find_col(df.columns.tolist(), EMAIL_ALIASES)
            if not email_col:
                continue
            score = _valid_email_count(df[email_col])
            if score > best_score:
                best_score = score
                best_df = df.copy()
                best_email = email_col
        except Exception:
            continue
    if best_df is None or best_email is None:
        raise ValueError("Excel mein koi Email column nahi mila! Column ka naam Email, Mail, E-mail, Email ID etc. hona chahiye.")
    
    df = best_df
    cols = df.columns.tolist()
    name_col = _find_col(cols, NAME_ALIASES)
    company_col = _find_col(cols, COMPANY_ALIASES)
    phone_col = _find_col(cols, PHONE_ALIASES)
    loc_col = _find_col(cols, LOCATION_ALIASES)
    biz_col = _find_col(cols, BUSINESS_ALIASES)
    generic_name_col = _find_col(cols, {'name'})
    
    out = pd.DataFrame()
    out['Email'] = df[best_email].astype(str).str.strip()
    
    if name_col:
        out['Owner Name'] = df[name_col].astype(str).str.strip()
    elif generic_name_col and not company_col:
        out['Owner Name'] = df[generic_name_col].astype(str).str.strip()
    elif company_col:
        out['Owner Name'] = df[company_col].astype(str).str.strip()
    else:
        out['Owner Name'] = ''
        
    if company_col:
        out['Company Name'] = df[company_col].astype(str).str.strip()
    elif generic_name_col:
        out['Company Name'] = df[generic_name_col].astype(str).str.strip()
    elif name_col:
        out['Company Name'] = df[name_col].astype(str).str.strip()
    else:
        out['Company Name'] = ''
        
    if biz_col:
        raw = df[biz_col].astype(str).str.replace(r"[\[\]']", "", regex=True).str.replace(",", " / ").str.strip()
        out['Business Type'] = raw
    else:
        out['Business Type'] = ''
        
    out['Location'] = df[loc_col].astype(str).str.strip() if loc_col else ''
    out['Phone'] = df[phone_col].astype(str).str.strip() if phone_col else ''
    
    used_cols = {best_email, name_col, company_col, biz_col, loc_col, phone_col, generic_name_col} - {None}
    for col in cols:
        if col not in used_cols and col not in out.columns:
            out[col] = df[col].astype(str).str.strip()
            
    for col in out.columns:
        out[col] = out[col].replace({'nan': '', 'None': '', 'NaN': '', 'none': '', 'NAN': '', 'NONE': ''})
        
    return out, 'Email'

def get_today_sent():
    try:
        row = execute_query("SELECT sent_count FROM daily_counter WHERE counter_date = %s;", [date.today()], fetch="one")
        return row["sent_count"] if row else 0
    except Exception as e:
        print(f"Error reading daily count: {e}")
        return 0

def increment_counter():
    try:
        # Check if date exists
        row = execute_query("SELECT sent_count FROM daily_counter WHERE counter_date = %s;", [date.today()], fetch="one")
        if row:
            execute_query("UPDATE daily_counter SET sent_count = sent_count + 1 WHERE counter_date = %s;", [date.today()])
        else:
            execute_query("INSERT INTO daily_counter (counter_date, sent_count) VALUES (%s, 1);", [date.today()])
    except Exception as e:
        print(f"Counter increment error: {e}")

def add_log(msg, campaign_id=""):
    ts = datetime.now(IST).strftime("%H:%M:%S")
    line = f"[{ts}] {msg}"
    print(line)
    with log_lock:
        shared_log.append(line)
        if len(shared_log) > 300:
            shared_log.pop(0)
    if campaign_id:
        with campaigns_lock:
            if campaign_id in campaigns:
                campaigns[campaign_id]["log"].append(line)
                if len(campaigns[campaign_id]["log"]) > 100:
                    campaigns[campaign_id]["log"].pop(0)

def is_working_hours():
    now = datetime.now(IST)
    return 10 <= now.hour < 19  # 10 AM to 7 PM

def secs_until_work():
    now = datetime.now(IST)
    start = now.replace(hour=10, minute=0, second=0, microsecond=0)
    if now >= start:
        start += timedelta(days=1)
    return max(0, int((start - now).total_seconds()))

def interruptible_sleep(secs, campaign_id):
    for _ in range(int(secs)):
        with campaigns_lock:
            if campaign_id in campaigns and campaigns[campaign_id].get("cancelled"):
                return True
        time.sleep(1)
    # Sleep any fractional remainder
    frac = secs - int(secs)
    if frac > 0:
        time.sleep(frac)
    return False

def extract_msg_ids(header_val):
    if not header_val:
        return []
    return [m.strip("<>") for m in re.findall(r'<([^>]+)>', header_val)]

def _clean(val):
    v = str(val).strip()
    return '' if v.lower() in ('nan', 'none', 'null', '') else v

def personalize_body(template_text, email_subject, row_dict):
    body = template_text
    subject = email_subject
    owner_name = _clean(row_dict.get('Owner Name', ''))
    company_name = _clean(row_dict.get('Company Name', ''))
    biz_type = _clean(row_dict.get('Business Type', ''))
    location = _clean(row_dict.get('Location', ''))
    
    if not owner_name:
        for pk in ('Director', 'Owner', 'Contact Person', 'Proprietor', 'Managing Director',
                   'Authorised Person', 'Contact Name', 'Person Name', 'MD Name', 'CEO', 'name'):
            v = _clean(row_dict.get(pk, ''))
            if v:
                owner_name = v
                break
    if not owner_name:
        owner_name = company_name or 'Sir/Madam'
        
    if not company_name:
        for ck in ('Legal Name', 'Trade Name', 'Firm Name', 'Business Name', 'Organisation',
                   'Organization', 'Entity Name', 'Company', 'GST Name', 'Registered Name', 'name'):
            v = _clean(row_dict.get(ck, ''))
            if v:
                company_name = v
                break
    if not company_name:
        company_name = owner_name or 'Your Organisation'
        
    if not biz_type:
        biz_type = 'your business'
        
    replacements = {
        '{Owner Name}': owner_name,   '{owner name}': owner_name,
        '{owner_name}': owner_name,   '[Owner Name]': owner_name,
        '{Company Name}': company_name, '{company name}': company_name,
        '{company_name}': company_name, '[Company Name]': company_name,
        '{Business Type}': biz_type,  '{business_type}': biz_type,
        '{Location}': location,        '{location}': location,
        '{Phone}': _clean(row_dict.get('Phone', '')),
        '{phone}':  _clean(row_dict.get('Phone', '')),
    }
    
    for ph, val in replacements.items():
        body = body.replace(ph, val)
        subject = subject.replace(ph, val)
        
    for k, v in row_dict.items():
        val = _clean(v)
        if val:
            body = body.replace(f"{{{k}}}", val).replace(f"{{{k.lower()}}}", val)
            subject = subject.replace(f"{{{k}}}", val).replace(f"{{{k.lower()}}}", val)
            
    footer = "\n\nPS: If you would prefer not to receive further updates, please reply 'stop' or 'not interested'."
    return body + footer, subject

def make_html_body(plain_text):
    import html as _html
    lines = plain_text.split('\n')
    html_lines = []
    for line in lines:
        s = line.strip()
        e = _html.escape(s)
        if s == '':
            html_lines.append('<div style="height:8px;"></div>')
        elif s.startswith('- '):
            html_lines.append(f"<div style='margin:4px 0 4px 16px;'><span style='color:#444;'>&#8226;</span>&nbsp;{e[2:].strip()}</div>")
        elif all(c == '-' for c in s) and len(s) > 3:
            html_lines.append("<div style='border-top:1px solid #d0d0d0;margin:12px 0;'></div>")
        else:
            html_lines.append(f"<div style='margin:3px 0;'>{e}</div>")
    return (
        '<!DOCTYPE html><html lang="en"><head><meta charset="UTF-8">'
        '<meta name="viewport" content="width=device-width,initial-scale=1.0">'
        '<meta http-equiv="Content-Type" content="text/html;charset=UTF-8"></head>'
        '<body style="margin:0;padding:0;background:#fff;">'
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background:#fff;">'
        '<tr><td align="center" style="padding:24px 12px;">'
        '<table role="presentation" width="600" cellpadding="0" cellspacing="0" style="max-width:600px;width:100%;">'
        '<tr><td style="padding:0;">'
        '<div style="font-family:Arial,Helvetica,sans-serif;font-size:14px;line-height:1.8;color:#1a1a1a;">'
        + "\n".join(html_lines) +
        '</div></td></tr></table></td></tr></table></body></html>'
    )

def make_html_body_tracked(plain_text, track_token, base_url=""):
    if not base_url:
        base_url = os.environ.get("BASE_URL", "https://universal-mailer.onrender.com")
    body = make_html_body(plain_text)
    pixel = (
        f'<img src="{base_url}/track/{track_token}" '
        f'width="1" height="1" style="display:none;" alt="" />'
    )
    return body.replace('</body>', pixel + '</body>')

# ── Custom SMTP Sending ────────────────────────────────────────────────────────
def send_via_custom_smtp(to_email, subject, html_body, plain_body, sender_email, sender_name, config, retries=2):
    import secrets
    # Extract domain dynamically for Message-ID domain alignment
    domain = sender_email.split('@')[-1].lower() if '@' in sender_email else "vsdgroup.com"
    msg_id = f"<smtp-{secrets.token_hex(12)}@{domain}>"
    smtp_host = config.get("smtp_host")
    smtp_port = config.get("smtp_port") or 587
    smtp_user = config.get("smtp_username") or sender_email
    smtp_pass = config.get("smtp_password")
    
    if not smtp_pass:
        return False, "SMTP password / Gmail App password is not configured."
        
    def _build_mime():
        msg = MIMEMultipart('alternative')
        msg['Subject'] = subject
        msg['From'] = f"{sender_name} <{sender_email}>"
        msg['To'] = to_email
        # Centralize replies only for mybankloan.ai domains. For others, keep sender's own email to avoid DMARC mismatch.
        reply_email = "admin@mybankloan.ai" if "mybankloan.ai" in sender_email.lower() else sender_email
        msg['Reply-To'] = f"{sender_name} <{reply_email}>"
        msg['Message-ID'] = msg_id
        msg.attach(MIMEText(plain_body, 'plain', 'utf-8'))
        msg.attach(MIMEText(html_body, 'html', 'utf-8'))
        return msg

    last_err = "No attempt made"
    for attempt in range(1, retries + 2):
        # Try STARTTLS on 587 first (or configured port)
        try:
            msg = _build_mime()
            # If port is 465, use SMTP_SSL
            if int(smtp_port) == 465:
                with smtplib.SMTP_SSL(smtp_host, int(smtp_port), timeout=30) as srv:
                    srv.ehlo()
                    srv.login(smtp_user, smtp_pass)
                    srv.sendmail(sender_email, [to_email], msg.as_string())
            else:
                try:
                    with smtplib.SMTP(smtp_host, int(smtp_port), timeout=30) as srv:
                        srv.ehlo()
                        srv.starttls()
                        srv.ehlo()
                        srv.login(smtp_user, smtp_pass)
                        srv.sendmail(sender_email, [to_email], msg.as_string())
                except Exception as starttls_err:
                    # Fallback to SSL port 465 if configured port was 587 and failed
                    if int(smtp_port) == 587:
                        with smtplib.SMTP_SSL(smtp_host, 465, timeout=30) as srv:
                            srv.ehlo()
                            srv.login(smtp_user, smtp_pass)
                            srv.sendmail(sender_email, [to_email], msg.as_string())
                    else:
                        raise starttls_err
            return True, msg_id
        except smtplib.SMTPAuthenticationError as e:
            return False, f"SMTP auth failed. ({e})"
        except smtplib.SMTPRecipientsRefused as e:
            return False, f"Recipient refused: {e}"
        except Exception as e:
            last_err = f"Attempt {attempt}: {e}"
            
        if attempt <= retries:
            time.sleep(10 * attempt)
            
    return False, f"SMTP send failed. Last error: {last_err}"

# ── Campaign Runner Thread Loop ────────────────────────────────────────────────
def make_campaign_state(sender_email="", category=""):
    return {
        "running": False,
        "paused": False,
        "cancelled": False,
        "current_row": 0,
        "total_rows": 0,
        "category": category,
        "sender_email": sender_email,
        "log": [],
        "started_at": datetime.now(IST).strftime("%H:%M:%S")
    }

def run_campaign(df_dict, email_subject, template_text, email_col, sender_email, sender_name, campaign_id, category, base_url=""):
    import secrets
    df = pd.DataFrame(df_dict)
    if 'Email' in df.columns:
        email_col = 'Email'
    total = len(df)
    
    with campaigns_lock:
        campaigns[campaign_id] = make_campaign_state(sender_email=sender_email, category=category)
        campaigns[campaign_id]["running"] = True
        campaigns[campaign_id]["total_rows"] = total
        
    add_log(f"Campaign started | Sender: {sender_email} | Category: {category} | Rows: {total}", campaign_id)
    
    try:
        execute_query(
            "INSERT INTO campaign_history (counter_date, sender_email, template, total_rows) VALUES (%s,%s,%s,%s);",
            [date.today(), sender_email, email_subject, total]
        )
    except Exception as e:
        print(f"History logging error: {e}")
        
    # Load sender configurations from DB
    sender_config = execute_query("SELECT * FROM sender_accounts WHERE email = %s;", [sender_email], fetch="one")
    if not sender_config:
        add_log(f"ERROR: Sender configuration for {sender_email} not found in database!", campaign_id)
        with campaigns_lock:
            campaigns[campaign_id]["running"] = False
        return
        
    provider_type = sender_config.get("provider_type", "brevo").lower()
    api_key = sender_config.get("api_key")
    daily_limit = sender_config.get("daily_limit") or DAILY_LIMIT
    delay_min = sender_config.get("delay_min") if sender_config.get("delay_min") is not None else DELAY_MIN_SECS
    delay_max = sender_config.get("delay_max") if sender_config.get("delay_max") is not None else DELAY_MAX_SECS
    
    for index, row in df.iterrows():
        # Check if campaign was cancelled
        with campaigns_lock:
            if campaign_id in campaigns and campaigns[campaign_id].get("cancelled"):
                add_log(f"Campaign cancelled/stopped by user.", campaign_id)
                break

        # Check global/daily limit
        if get_today_sent() >= daily_limit:
            add_log(f"Daily limit reached ({category}). Resuming tomorrow 10 AM.", campaign_id)
            with campaigns_lock:
                campaigns[campaign_id]["paused"] = True
            if interruptible_sleep(secs_until_work() + 5, campaign_id):
                break
            with campaigns_lock:
                campaigns[campaign_id]["paused"] = False
            add_log(f"Resuming campaign ({category}) for {sender_email}", campaign_id)
            
        # Working hours check
        if not is_working_hours():
            secs = secs_until_work()
            add_log(f"Outside working hours ({category}). Sleeping {secs//3600}h {(secs%3600)//60}m.", campaign_id)
            with campaigns_lock:
                campaigns[campaign_id]["paused"] = True
            if interruptible_sleep(secs + 5, campaign_id):
                break
            with campaigns_lock:
                campaigns[campaign_id]["paused"] = False
            add_log(f"Resuming (10 AM IST reached) for {sender_email} ({category})", campaign_id)
            
        customer_email = str(row.get(email_col, row.get('Email', ''))).strip()
        if not customer_email or customer_email.lower() in ('nan', 'none', ''):
            continue
            
        row_dict = {str(k).strip(): str(v).strip() for k, v in row.to_dict().items()}
        body, subject = personalize_body(template_text, email_subject, row_dict)
        track_token = secrets.token_urlsafe(16)
        html_body = make_html_body_tracked(body, track_token, base_url=base_url)
        success = False
        msg_id = ""
        
        if provider_type == "smtp":
            success, result = send_via_custom_smtp(
                to_email=customer_email, subject=subject,
                html_body=html_body, plain_body=body,
                sender_email=sender_email, sender_name=sender_name,
                config=sender_config
            )
            if success:
                msg_id = result
            else:
                add_log(f"[{index+1}/{total}] FAIL SMTP {customer_email} ({category}): {result}", campaign_id)
        else:
            # Centralize replies only for mybankloan.ai domains. For others, keep sender's own email to avoid DMARC mismatch.
            reply_email = "admin@mybankloan.ai" if "mybankloan.ai" in sender_email.lower() else sender_email
            payload = {
                "sender": {"name": sender_name, "email": sender_email},
                "to": [{"email": customer_email}],
                "subject": subject,
                "htmlContent": html_body,
                "textContent": body,
                "replyTo": {"email": reply_email, "name": sender_name},
            }
            try:
                resp = requests.post(
                    BREVO_API_URL, json=payload,
                    headers={"accept": "application/json", "content-type": "application/json", "api-key": api_key},
                    timeout=30
                )
                if resp.status_code in (200, 201):
                    success = True
                    msg_id = resp.json().get("messageId", "")
                else:
                    try:
                        err = resp.json().get("message", resp.text[:100])
                    except Exception:
                        err = resp.text[:100]
                    add_log(f"[{index+1}/{total}] FAIL {customer_email} ({category}): {resp.status_code} {err}", campaign_id)
            except Exception as e:
                add_log(f"[{index+1}/{total}] ERROR {customer_email} ({category}): {e}", campaign_id)
                
        if success:
            increment_counter()
            new_sent = get_today_sent()
            with campaigns_lock:
                campaigns[campaign_id]["current_row"] = index + 1
            owner = row_dict.get('Owner Name', row_dict.get('Company Name', ''))
            add_log(f"[{index+1}/{total}] OK {customer_email} ({owner}) [{category}] | Today: {new_sent}/{daily_limit}", campaign_id)
            try:
                execute_query(
                    """INSERT INTO sent_emails
                       (track_token, sender_email, to_email, company_name, owner_name, subject, message_id)
                       VALUES (%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING;""",
                    [track_token, sender_email, customer_email,
                     row_dict.get('Company Name', ''), row_dict.get('Owner Name', ''), subject, msg_id]
                )
            except Exception as te:
                print(f"Track save error: {te}")
                
        if index < total - 1:
            delay = random.randint(int(delay_min), int(delay_max))
            if interruptible_sleep(delay, campaign_id):
                break
            
    with campaigns_lock:
        was_cancelled = campaign_id in campaigns and campaigns[campaign_id].get("cancelled")
        
    if was_cancelled:
        add_log(f"Campaign stopped/cancelled for {sender_email} ({category})!", campaign_id)
    else:
        add_log(f"Campaign completed for {sender_email} ({category})!", campaign_id)
        
    with campaigns_lock:
        campaigns[campaign_id]["running"] = False

# ── IMAP Poller Background Tracker ─────────────────────────────────────────────
def poll_replies():
    import imaplib
    import email as _email_lib
    from email.header import decode_header
    from email.parser import BytesHeaderParser
    
    def decode_hdr(h):
        if not h:
            return ""
        parts = decode_header(h)
        result = []
        for b, enc in parts:
            if isinstance(b, bytes):
                result.append(b.decode(enc or "utf-8", errors="replace"))
            else:
                result.append(str(b))
        return " ".join(result).strip()
        
    def get_body_preview(msg):
        body = ""
        if msg.is_multipart():
            for part in msg.walk():
                if part.get_content_type() == "text/plain":
                    try:
                        body = part.get_payload(decode=True).decode("utf-8", errors="replace")
                        break
                    except Exception:
                        pass
        else:
            try:
                body = msg.get_payload(decode=True).decode("utf-8", errors="replace")
            except Exception:
                body = ""
        return body[:500]

    # Fetch active senders with IMAP credentials
    accounts = execute_query("SELECT email, imap_host, imap_port, imap_password FROM sender_accounts WHERE active=TRUE AND imap_password != '';", fetch="all")
    if not accounts:
        return
        
    for acc in accounts:
        sender_email = acc["email"]
        imap_host = acc["imap_host"]
        imap_port = acc["imap_port"] or 993
        imap_pass = acc["imap_password"]
        
        if not imap_host or not imap_pass:
            continue
            
        try:
            old_to = socket.getdefaulttimeout()
            socket.setdefaulttimeout(15)
            print(f"[IMAP] Connecting {sender_email} -> {imap_host}:{imap_port}")
            
            mail = imaplib.IMAP4_SSL(imap_host, int(imap_port))
            mail.login(sender_email, imap_pass)
            socket.setdefaulttimeout(old_to)
            
            mail.select("INBOX")
            
            # Fetch recently sent emails to match replies against
            sent_rows = execute_query("SELECT message_id, track_token FROM sent_emails WHERE message_id IS NOT NULL AND message_id != '';", fetch="all")
            our_msgs = {r["message_id"].strip("<>"): r["track_token"] for r in sent_rows if r["message_id"]} if sent_rows else {}
            
            if not our_msgs:
                mail.logout()
                continue
                
            _, select_data = mail.select("INBOX")
            total_emails = int(select_data[0])
            print(f"[IMAP] {sender_email} — Total emails: {total_emails}")
            
            if total_emails > 0:
                start_seq = max(1, total_emails - 100)
                _, header_data = mail.fetch(f"{start_seq}:{total_emails}", "(BODY[HEADER.FIELDS (IN-REPLY-TO REFERENCES FROM SUBJECT)])")
                
                parser = BytesHeaderParser()
                for part in header_data:
                    if isinstance(part, tuple):
                        msg_bytes = part[1]
                        msg = parser.parsebytes(msg_bytes)
                        
                        in_reply_to_raw = decode_hdr(msg.get("In-Reply-To", ""))
                        references_raw = decode_hdr(msg.get("References", ""))
                        from_email = decode_hdr(msg.get("From", ""))
                        subject = decode_hdr(msg.get("Subject", ""))
                        
                        seq_match = re.match(br'^(\d+)', part[0])
                        msg_seq = int(seq_match.group(1)) if seq_match else None
                        
                        if not msg_seq:
                            continue
                            
                        in_reply_to_ids = extract_msg_ids(in_reply_to_raw)
                        references_ids = extract_msg_ids(references_raw)
                        all_reply_ids = in_reply_to_ids + references_ids
                        
                        matched_token = None
                        for rid in all_reply_ids:
                            if rid in our_msgs:
                                matched_token = our_msgs[rid]
                                break
                                    
                        if matched_token:
                            # Verify if we already have this reply saved
                            dup = execute_query("SELECT COUNT(*) as c FROM replies WHERE track_token = %s AND from_email = %s AND subject = %s;", [matched_token, from_email, subject], fetch="one")
                            if dup and dup["c"] > 0:
                                continue
                                
                            # Fetch full message body for matched sequence number
                            print(f"[IMAP] Matched sequence {msg_seq}. Fetching full content...")
                            _, body_data = mail.fetch(str(msg_seq), "(RFC822)")
                            full_msg = _email_lib.message_from_bytes(body_data[0][1])
                            body_prev = get_body_preview(full_msg)
                            
                            execute_query(
                                "INSERT INTO replies (track_token, from_email, subject, body_preview) VALUES (%s,%s,%s,%s);",
                                [matched_token, from_email, subject, body_prev]
                            )
                            execute_query(
                                "UPDATE sent_emails SET replied=TRUE, replied_at=NOW(), opened=TRUE, opened_at=COALESCE(opened_at, NOW()) WHERE track_token=%s;",
                                [matched_token]
                            )
                            print(f"[IMAP] Reply recorded: {from_email} -> {sender_email}")
            mail.logout()
        except Exception as e:
            print(f"[IMAP error] {sender_email} ({imap_host}): {e}")

def check_48hr_alerts():
    try:
        execute_query("""UPDATE sent_emails SET alerted_48h=TRUE
            WHERE opened=FALSE AND alerted_48h=FALSE AND sent_at < NOW()-INTERVAL '48 hours';""")
    except Exception as e:
        print(f"[48hr error] {e}")

def background_tracker():
    while True:
        try:
            poll_replies()
        except Exception as e:
            print(f"[Poller error] {e}")
        try:
            check_48hr_alerts()
        except Exception as e:
            print(f"[48hr alert error] {e}")
        time.sleep(60)

@app.on_event("startup")
async def startup():
    init_db()
    threading.Thread(target=background_tracker, daemon=True).start()
    print("[Tracker] Background thread started")

# ── API ROUTES ────────────────────────────────────────────────────────────────
@app.get("/track/{token}")
async def track_open(token: str):
    try:
        execute_query("UPDATE sent_emails SET opened=TRUE, opened_at=NOW() WHERE track_token=%s AND opened=FALSE;", [token])
    except Exception as e:
        print(f"Track error: {e}")
    import base64
    from fastapi.responses import Response
    pixel = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
    return Response(content=pixel, media_type="image/gif", headers={"Cache-Control": "no-cache,no-store"})

@app.post("/api/webhooks/brevo")
async def brevo_webhook(request: Request):
    try:
        body = await request.json()
        event = body.get("event")
        msg_id = body.get("message-id") or body.get("messageId")
        
        if event == "opened" and msg_id:
            # Mark email as opened in database
            execute_query("""
                UPDATE sent_emails 
                SET opened=TRUE, opened_at=NOW() 
                WHERE message_id=%s AND opened=FALSE;
            """, [msg_id])
            print(f"[Webhook] Email opened via Brevo webhook: message_id={msg_id}")
            
        return {"status": "success"}
    except Exception as e:
        print(f"[Webhook Error] {e}")
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/status")
async def get_status():
    with campaigns_lock:
        senders_status = {}
        for cid, st in campaigns.items():
            s = st["sender_email"]
            entry = {
                "campaign_id": cid, "category": st["category"],
                "running": st["running"], "paused": st["paused"],
                "current_row": st["current_row"], "total_rows": st["total_rows"],
                "started_at": st.get("started_at", ""), "log": list(st["log"]),
            }
            senders_status.setdefault(s, []).append(entry)
    with log_lock:
        logs = list(shared_log)
    return {"sent_today": get_today_sent(), "senders": senders_status, "log": logs}

# Global Settings API
@app.get("/api/settings")
async def get_settings():
    try:
        rows = execute_query("SELECT key, value FROM global_settings;", fetch="all")
        settings_d = {r["key"]: r["value"] for r in rows} if rows else {}
        return JSONResponse(settings_d)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/settings")
async def save_settings(request: Request):
    try:
        body = await request.json()
        for k, v in body.items():
            val = str(v).strip()
            # Sanitize tracking URL: strip query parameters and trailing slashes
            if k == "tracking_base_url" and "?" in val:
                val = val.split("?")[0].rstrip("/")
            execute_query("""
                INSERT INTO global_settings (key, value) VALUES (%s, %s)
                ON CONFLICT (key) DO UPDATE SET value=EXCLUDED.value;
            """, [k, val])
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Senders API (Dynamic Configuration)
@app.get("/api/senders")
async def get_senders():
    try:
        rows = execute_query("SELECT email, display_name, provider_type, api_key, smtp_host, smtp_port, smtp_username, imap_host, imap_port, daily_limit, delay_min, delay_max, active FROM sender_accounts ORDER BY email;", fetch="all")
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/senders")
async def save_sender(request: Request):
    try:
        body = await request.json()
        email = body.get("email", "").strip()
        display_name = body.get("display_name", "").strip()
        provider_type = body.get("provider_type", "brevo").strip()
        api_key = body.get("api_key", "").strip()
        smtp_host = body.get("smtp_host", "").strip()
        smtp_port = int(body.get("smtp_port", 587)) if body.get("smtp_port") else None
        smtp_username = body.get("smtp_username", "").strip()
        smtp_password = body.get("smtp_password", "").strip()
        imap_host = body.get("imap_host", "").strip()
        imap_port = int(body.get("imap_port", 993)) if body.get("imap_port") else None
        imap_password = body.get("imap_password", "").strip()
        daily_limit = int(body.get("daily_limit", 1500))
        delay_min = int(body.get("delay_min", 60))
        delay_max = int(body.get("delay_max", 120))
        active = bool(body.get("active", True))
        skip_test = bool(body.get("skip_test", False))
        
        if not email or not display_name:
            return JSONResponse(status_code=400, content={"error": "Email and Display Name are required."})
            
        # Check if exists
        row = execute_query("SELECT email, smtp_password, imap_password, api_key FROM sender_accounts WHERE email = %s;", [email], fetch="one")
        
        # Test connection if active and not skip_test
        if active and not skip_test:
            test_smtp_pass = smtp_password
            test_imap_pass = imap_password
            test_api_key = api_key
            
            if row:
                if not test_smtp_pass:
                    test_smtp_pass = row.get("smtp_password", "")
                if not test_imap_pass:
                    test_imap_pass = row.get("imap_password", "")
                if not test_api_key:
                    test_api_key = row.get("api_key", "")
            
            if provider_type == "smtp":
                # Verify SMTP Connection
                if smtp_host:
                    try:
                        import smtplib
                        smtp_user = smtp_username or email
                        port = smtp_port or 587
                        if int(port) == 465:
                            with smtplib.SMTP_SSL(smtp_host, int(port), timeout=10) as srv:
                                srv.login(smtp_user, test_smtp_pass)
                        else:
                            try:
                                with smtplib.SMTP(smtp_host, int(port), timeout=10) as srv:
                                    srv.ehlo()
                                    srv.starttls()
                                    srv.ehlo()
                                    srv.login(smtp_user, test_smtp_pass)
                            except Exception as e:
                                # Fallback to port 465 if port 587 fails
                                if int(port) == 587:
                                    with smtplib.SMTP_SSL(smtp_host, 465, timeout=10) as srv:
                                        srv.ehlo()
                                        srv.login(smtp_user, test_smtp_pass)
                                else:
                                    raise e
                    except Exception as e:
                        return JSONResponse(status_code=400, content={"error": f"SMTP Connection failed: {e}"})
                
                # Verify IMAP Connection
                if imap_host:
                    try:
                        import imaplib
                        port = imap_port or 993
                        with imaplib.IMAP4_SSL(imap_host, int(port), timeout=10) as srv:
                            srv.login(email, test_imap_pass)
                    except Exception as e:
                        return JSONResponse(status_code=400, content={"error": f"IMAP Connection failed: {e}"})
                        
            elif provider_type == "brevo":
                # Verify Brevo API Key
                if test_api_key:
                    try:
                        import requests
                        headers = {
                            "accept": "application/json",
                            "api-key": test_api_key
                        }
                        resp = requests.get("https://api.brevo.com/v3/smtp/statistics/events", headers=headers, timeout=10)
                        if resp.status_code == 401:
                            return JSONResponse(status_code=400, content={"error": "Brevo API Key is invalid (Unauthorized)"})
                    except Exception as e:
                        return JSONResponse(status_code=400, content={"error": f"Brevo API verification failed: {e}"})
                        
        if row:
            # Maintain passwords if not updated in request (for security/blank inputs)
            final_smtp_pass = smtp_password if smtp_password else row.get("smtp_password", "")
            final_imap_pass = imap_password if imap_password else row.get("imap_password", "")
            
            execute_query("""
                UPDATE sender_accounts SET
                    display_name=%s, provider_type=%s, api_key=%s, smtp_host=%s, smtp_port=%s,
                    smtp_username=%s, smtp_password=%s, imap_host=%s, imap_port=%s, imap_password=%s,
                    daily_limit=%s, delay_min=%s, delay_max=%s, active=%s
                WHERE email=%s;
            """, [display_name, provider_type, api_key, smtp_host, smtp_port, smtp_username, final_smtp_pass, imap_host, imap_port, final_imap_pass, daily_limit, delay_min, delay_max, active, email])
        else:
            execute_query("""
                INSERT INTO sender_accounts 
                (email, display_name, provider_type, api_key, smtp_host, smtp_port, smtp_username, smtp_password, imap_host, imap_port, imap_password, daily_limit, delay_min, delay_max, active)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s);
            """, [email, display_name, provider_type, api_key, smtp_host, smtp_port, smtp_username, smtp_password, imap_host, imap_port, imap_password, daily_limit, delay_min, delay_max, active])
            
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.delete("/api/senders/{email}")
async def delete_sender(email: str):
    try:
        execute_query("DELETE FROM sender_template_map WHERE sender_email = %s;", [email])
        execute_query("DELETE FROM sender_accounts WHERE email = %s;", [email])
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Sender Template Mappings API
@app.get("/api/sender-mappings")
async def get_sender_mappings():
    try:
        rows = execute_query("SELECT sender_email, category FROM sender_template_map;", fetch="all")
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/api/sender-mappings")
async def update_sender_mappings(request: Request):
    try:
        body = await request.json()
        sender_email = body.get("sender_email", "").strip()
        categories = body.get("categories", [])  # list of template names
        
        if not sender_email:
            return JSONResponse(status_code=400, content={"error": "Sender email is required"})
            
        # Delete existing mappings
        execute_query("DELETE FROM sender_template_map WHERE sender_email = %s;", [sender_email])
        
        # Insert new mappings
        for cat in categories:
            execute_query("INSERT INTO sender_template_map (sender_email, category) VALUES (%s, %s) ON CONFLICT DO NOTHING;", [sender_email, cat])
            
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Templates API
@app.get("/templates-list-full")
async def templates_list_full():
    try:
        rows = execute_query("""
            SELECT et.category, et.subject, et.body_text,
                   STRING_AGG(stm.sender_email, ', ') AS senders
            FROM email_templates et
            LEFT JOIN sender_template_map stm ON et.category=stm.category
            GROUP BY et.category, et.subject, et.body_text
            ORDER BY et.category;
        """, fetch="all")
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/templates-by-sender")
async def templates_by_sender(sender: str = ""):
    try:
        if sender:
            rows = execute_query("""
                SELECT et.category FROM email_templates et
                INNER JOIN sender_template_map stm ON et.category=stm.category AND stm.sender_email=%s
                ORDER BY et.category ASC;
            """, [sender], fetch="all")
        else:
            rows = execute_query("SELECT category FROM email_templates ORDER BY category ASC;", fetch="all")
        return JSONResponse(rows)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/get-template")
async def get_template(category: str):
    try:
        row = execute_query("SELECT subject, body_text FROM email_templates WHERE category=%s;", [category], fetch="one")
        if row:
            return JSONResponse(row)
        return JSONResponse(status_code=404, content={"error": "Not found"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/add-template-ajax/")
async def add_template_ajax(request: Request):
    try:
        body = await request.json()
        sender_email = body.get("sender_email", "").strip()
        category = body.get("category", "").strip()
        subject = body.get("subject", "").strip()
        body_text = body.get("body_text", "").strip()
        
        if not all([category, subject, body_text]):
            return JSONResponse({"ok": False, "error": "Sabhi fields required hain"})
            
        execute_query("""
            INSERT INTO email_templates (category, subject, body_text) VALUES (%s, %s, %s)
            ON CONFLICT (category) DO UPDATE SET subject=EXCLUDED.subject, body_text=EXCLUDED.body_text;
        """, [category, subject, body_text])
        
        if sender_email:
            execute_query("INSERT INTO sender_template_map (sender_email, category) VALUES (%s, %s) ON CONFLICT DO NOTHING;", [sender_email, category])
            
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse({"ok": False, "error": str(e)})

@app.post("/delete-template")
async def delete_template(request: Request):
    try:
        body = await request.json()
        category = body.get("category", "").strip()
        if not category:
            return JSONResponse(status_code=400, content={"error": "Category is required"})
        execute_query("DELETE FROM sender_template_map WHERE category = %s;", [category])
        execute_query("DELETE FROM email_templates WHERE category = %s;", [category])
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/preview-template")
async def preview_template(request: Request):
    try:
        body = await request.json()
        category = body.get("category", "")
        vars_d = body.get("vars", {})
        
        row = execute_query("SELECT subject, body_text FROM email_templates WHERE category=%s;", [category], fetch="one")
        if not row:
            return JSONResponse(status_code=404, content={"error": "Not found"})
            
        subj = row["subject"]
        body_txt = row["body_text"]
        
        for k, v in vars_d.items():
            body_txt = body_txt.replace(f"{{{k}}}", str(v)).replace(f"{{{k.lower()}}}", str(v))
            subj = subj.replace(f"{{{k}}}", str(v)).replace(f"{{{k.lower()}}}", str(v))
            
        return JSONResponse({"subject": subj, "body": body_txt})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Deliverability Analyzer API
@app.post("/api/analyze-template")
async def api_analyze_template(request: Request):
    try:
        body = await request.json()
        subject = body.get("subject", "")
        body_text = body.get("body_text", "")
        analysis = analyze_email(subject, body_text)
        return JSONResponse(analysis)
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

# Tracking & Logs Stats API
@app.get("/tracking-stats")
async def tracking_stats(filter: str = "all", sender: str = "", limit: int = 200,
                         date_from: str = "", date_to: str = ""):
    try:
        where = []
        params = []
        if sender:
            where.append("se.sender_email=%s")
            params.append(sender)
        if filter == "opened":
            where.append("se.opened=TRUE AND se.replied=FALSE")
        elif filter == "replied":
            where.append("se.replied=TRUE")
        elif filter == "not_opened":
            where.append("se.opened=FALSE")
        elif filter == "alert_48h":
            where.append("se.alerted_48h=TRUE AND se.replied=FALSE")
        if date_from:
            where.append("DATE(se.sent_at) >= %s")
            params.append(date_from)
        if date_to:
            where.append("DATE(se.sent_at) <= %s")
            params.append(date_to)
            
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        params.append(limit)
        
        rows = execute_query(f"""
            SELECT se.id, se.track_token, se.sender_email, se.to_email,
                   se.company_name, se.owner_name, se.subject, se.sent_at, se.opened, se.opened_at,
                   se.replied, se.replied_at, se.alerted_48h,
                   (SELECT r.body_preview FROM replies r WHERE r.track_token=se.track_token
                    ORDER BY r.received_at DESC LIMIT 1) AS reply_preview
            FROM sent_emails se {where_clause} ORDER BY se.sent_at DESC LIMIT %s;
        """, params, fetch="all")
        
        # Summary with same date/sender filters but ignoring status filter
        sum_where = []
        sum_params = []
        if sender:
            sum_where.append("sender_email=%s")
            sum_params.append(sender)
        if date_from:
            sum_where.append("DATE(sent_at) >= %s")
            sum_params.append(date_from)
        if date_to:
            sum_where.append("DATE(sent_at) <= %s")
            sum_params.append(date_to)
        sum_where_clause = ("WHERE " + " AND ".join(sum_where)) if sum_where else ""
        
        summary = execute_query(f"""
            SELECT COUNT(*) AS total,
                   SUM(CASE WHEN opened = TRUE THEN 1 ELSE 0 END) AS opened,
                   SUM(CASE WHEN replied = TRUE THEN 1 ELSE 0 END) AS replied,
                   SUM(CASE WHEN opened = FALSE AND alerted_48h = TRUE THEN 1 ELSE 0 END) AS not_opened_48h,
                   SUM(CASE WHEN opened = FALSE AND sent_at > NOW()-INTERVAL '48h' THEN 1 ELSE 0 END) AS pending
            FROM sent_emails {sum_where_clause};
        """, sum_params, fetch="one")
        
        # Handle SQLite aggregate queries returning None for SUM when no records exist
        if summary:
            summary = {
                "total": summary.get("total") or 0,
                "opened": summary.get("opened") or 0,
                "replied": summary.get("replied") or 0,
                "not_opened_48h": summary.get("not_opened_48h") or 0,
                "pending": summary.get("pending") or 0
            }
        else:
            summary = {"total": 0, "opened": 0, "replied": 0, "not_opened_48h": 0, "pending": 0}
            
        result = []
        for r in rows:
            d = dict(r)
            d["sent_at"] = str(d["sent_at"]) if d["sent_at"] else ""
            d["opened_at"] = str(d["opened_at"]) if d["opened_at"] else ""
            d["replied_at"] = str(d["replied_at"]) if d["replied_at"] else ""
            result.append(d)
            
        return JSONResponse({"summary": summary, "emails": result})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/tracking-per-sender")
async def tracking_per_sender(date_from: str = "", date_to: str = ""):
    """Returns per-sender breakdown of sent/opened/replied counts."""
    try:
        where = []
        params = []
        if date_from:
            where.append("DATE(sent_at) >= %s")
            params.append(date_from)
        if date_to:
            where.append("DATE(sent_at) <= %s")
            params.append(date_to)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""
        rows = execute_query(f"""
            SELECT sender_email,
                   COUNT(*) AS total,
                   SUM(CASE WHEN opened=TRUE THEN 1 ELSE 0 END) AS opened,
                   SUM(CASE WHEN replied=TRUE THEN 1 ELSE 0 END) AS replied,
                   SUM(CASE WHEN opened=FALSE AND alerted_48h=TRUE THEN 1 ELSE 0 END) AS not_opened_48h
            FROM sent_emails {where_clause}
            GROUP BY sender_email ORDER BY total DESC;
        """, params, fetch="all")
        return JSONResponse(rows or [])
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/tracking-download")
async def tracking_download(filter: str = "all", sender: str = "", date_from: str = "", date_to: str = ""):
    """Download tracking data as a CSV file."""
    import csv, io
    from fastapi.responses import StreamingResponse
    try:
        where = []
        params = []
        if sender:
            where.append("se.sender_email=%s")
            params.append(sender)
        if filter == "opened":
            where.append("se.opened=TRUE AND se.replied=FALSE")
        elif filter == "replied":
            where.append("se.replied=TRUE")
        elif filter == "not_opened":
            where.append("se.opened=FALSE")
        elif filter == "alert_48h":
            where.append("se.alerted_48h=TRUE AND se.replied=FALSE")
        if date_from:
            where.append("DATE(se.sent_at) >= %s")
            params.append(date_from)
        if date_to:
            where.append("DATE(se.sent_at) <= %s")
            params.append(date_to)
        where_clause = ("WHERE " + " AND ".join(where)) if where else ""

        rows = execute_query(f"""
            SELECT se.sender_email, se.to_email, se.company_name, se.owner_name,
                   se.subject, se.sent_at, se.opened, se.opened_at, se.replied, se.replied_at,
                   se.alerted_48h,
                   (SELECT r.body_preview FROM replies r WHERE r.track_token=se.track_token
                    ORDER BY r.received_at DESC LIMIT 1) AS reply_preview
            FROM sent_emails se {where_clause} ORDER BY se.sent_at DESC LIMIT 10000;
        """, params, fetch="all")

        output = io.StringIO()
        writer = csv.writer(output)
        writer.writerow(["Sender", "Recipient", "Company", "Owner", "Subject", "Sent At",
                         "Opened", "Opened At", "Replied", "Replied At", "48h Alert", "Reply Preview"])
        for r in (rows or []):
            d = dict(r)
            writer.writerow([
                d.get("sender_email", ""), d.get("to_email", ""), d.get("company_name", ""),
                d.get("owner_name", ""), d.get("subject", ""), d.get("sent_at", ""),
                "Yes" if d.get("opened") else "No", d.get("opened_at", "") or "",
                "Yes" if d.get("replied") else "No", d.get("replied_at", "") or "",
                "Yes" if d.get("alerted_48h") else "No", d.get("reply_preview", "") or ""
            ])

        output.seek(0)
        filename = f"email_tracking_{date_from or 'all'}_{date_to or 'all'}.csv"
        return StreamingResponse(
            io.BytesIO(output.getvalue().encode("utf-8-sig")),
            media_type="text/csv",
            headers={"Content-Disposition": f"attachment; filename={filename}"}
        )
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})



@app.get("/replies-list")
async def replies_list(limit: int = 50):
    try:
        rows = execute_query("""
            SELECT r.id, r.from_email, r.subject, r.body_preview, r.received_at,
                   se.sender_email, se.to_email, se.company_name, se.owner_name, se.subject AS original_subject
            FROM replies r JOIN sent_emails se ON r.track_token=se.track_token
            ORDER BY r.received_at DESC LIMIT %s;
        """, [limit], fetch="all")
        result = [dict(r) for r in rows]
        for d in result:
            d["received_at"] = str(d["received_at"])
        return JSONResponse({"replies": result, "count": len(result)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.post("/mark-replied/{email_id}")
async def mark_replied(email_id: int):
    try:
        execute_query("UPDATE sent_emails SET replied=TRUE, replied_at=NOW(), opened=TRUE, opened_at=COALESCE(opened_at, NOW()) WHERE id=%s;", [email_id])
        return JSONResponse({"ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/history")
async def get_history():
    try:
        rows = execute_query("""
            SELECT counter_date, SUM(sent_count) as total_sent FROM daily_counter
            GROUP BY counter_date ORDER BY counter_date DESC LIMIT 30;
        """, fetch="all")
        return JSONResponse([{"date": str(r["counter_date"]), "sent": r["total_sent"]} for r in rows])
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/diagnose-gmail")
async def diagnose_gmail():
    results = {}
    for host, port, label in [
        ("smtp.gmail.com", 587, "STARTTLS"),
        ("smtp.gmail.com", 465, "SSL"),
        ("smtp.gmail.com", 25, "Plain-25"),
    ]:
        try:
            s = socket.create_connection((host, port), timeout=10)
            s.close()
            results[f"{host}:{port} ({label})"] = "REACHABLE"
        except Exception as e:
            results[f"{host}:{port} ({label})"] = f"BLOCKED — {e}"
    return JSONResponse(results)

async def _launch_campaign(sender_email, category, file, base_url=""):
    try:
        row = execute_query("SELECT value FROM global_settings WHERE key='tracking_base_url';", fetch="one")
        if row and row["value"]:
            base_url = row["value"].strip().rstrip('/')
        else:
            tracking_base = os.environ.get("TRACKING_BASE_URL", "").rstrip('/')
            if tracking_base:
                base_url = tracking_base
    except Exception as e:
        print(f"Error reading tracking_base_url settings: {e}")
    
    # Sanitize: strip any query parameters from the base URL
    if '?' in base_url:
        base_url = base_url.split('?')[0].rstrip('/')
    print(f"[Campaign] Using tracking base URL: {base_url}")
        
    campaign_id = f"{sender_email}::{category}::{int(time.time())}"
    with campaigns_lock:
        for cid, st in campaigns.items():
            if st["sender_email"] == sender_email and st["category"] == category and st["running"]:
                return None, f"Campaign already running for {sender_email} with template '{category}'! Wait for it to finish."
                
    try:
        file_bytes = await file.read()
        df, email_col = smart_parse_excel(file_bytes)
        df = df[df["Email"].notna() & (df["Email"] != "") & (df["Email"].str.lower() != "nan")]
        df = df[df["Email"].str.contains("@", na=False)].reset_index(drop=True)
        
        if df.empty:
            return None, "Koi valid email nahi mila Excel mein!"
            
        result = execute_query("SELECT subject, body_text FROM email_templates WHERE category=%s;", [category], fetch="one")
        if not result:
            return None, "Template not found!"
            
        email_subject, template_text = result["subject"], result["body_text"]
        
        sender_details = execute_query("SELECT display_name FROM sender_accounts WHERE email = %s;", [sender_email], fetch="one")
        sender_name = sender_details["display_name"] if sender_details else "VSD Finserv"
        
        t = threading.Thread(
            target=run_campaign,
            args=(df.to_dict(orient="list"), email_subject, template_text, "Email", sender_email, sender_name, campaign_id, category, base_url),
            daemon=True
        )
        t.start()
        return len(df), None
    except Exception as e:
        return None, str(e)

@app.post("/send-emails-public/")
async def send_emails_public(request: Request, pwd: str = Form(...), sender_email: str = Form(...),
                             category: str = Form(...), file: UploadFile = File(...)):
    if pwd != get_dashboard_password():
        return JSONResponse(status_code=403, content={"error": "Unauthorized"})
    base_url = str(request.base_url).rstrip('/')
    count, err = await _launch_campaign(sender_email, category, file, base_url)
    if err:
        return HTMLResponse(f'<html><head><meta http-equiv="refresh" content="3;url=/?pwd={pwd}"></head>'
                            f'<body style="font-family:sans-serif;background:#f8f9fb;color:#b42318;padding:48px;text-align:center;font-size:15px;">'
                            f'{err} Redirecting...</body></html>')
    return HTMLResponse(f'<html><head><meta http-equiv="refresh" content="3;url=/?pwd={pwd}"></head>'
                        f'<body style="font-family:sans-serif;background:#f8f9fb;color:#027a48;padding:48px;text-align:center;font-size:15px;">'
                        f'Campaign launched from <strong>{sender_email}</strong> — {count} emails! Redirecting...</body></html>')

@app.post("/send-emails/")
async def send_emails(request: Request, sender_email: str = Form(...), category: str = Form(...), file: UploadFile = File(...)):
    base_url = str(request.base_url).rstrip('/')
    count, err = await _launch_campaign(sender_email, category, file, base_url)
    if err:
        return JSONResponse(status_code=400, content={"status": "error", "message": err})
    return HTMLResponse(f'<html><head><meta http-equiv="refresh" content="3;url=/"></head>'
                        f'<body style="font-family:sans-serif;background:#f5f4f0;color:#4a6741;padding:40px;text-align:center;font-size:16px;">'
                        f'Campaign launched from <b>{sender_email}</b> — {count} emails!</body></html>')

@app.post("/api/campaigns/cancel")
async def cancel_campaign(request: Request):
    try:
        body = await request.json()
        campaign_id = body.get("campaign_id")
        if not campaign_id:
            return JSONResponse(status_code=400, content={"error": "campaign_id is required"})
            
        with campaigns_lock:
            if campaign_id in campaigns:
                campaigns[campaign_id]["cancelled"] = True
                add_log(f"Cancellation requested for campaign {campaign_id}")
                return JSONResponse({"ok": True})
            else:
                return JSONResponse(status_code=404, content={"error": "Campaign not found or not active"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"error": str(e)})

@app.get("/public", response_class=HTMLResponse)
async def public_dashboard(pwd: str = ""):
    if pwd != get_dashboard_password():
        return FileResponse("static/login.html")
    return FileResponse("static/index.html")

@app.get("/", response_class=HTMLResponse)
async def root(pwd: str = ""):
    # Fix: Catch malformed tracking pixel URLs like /?pwd=Mybankloan.ai/track/TOKEN
    if "/track/" in pwd:
        token = pwd.split("/track/", 1)[1].split("?")[0].split("&")[0]
        if token:
            try:
                execute_query("UPDATE sent_emails SET opened=TRUE, opened_at=NOW() WHERE track_token=%s AND opened=FALSE;", [token])
                print(f"[Track] Open recorded from malformed URL: token={token}")
            except Exception as e:
                print(f"[Track Error] {e}")
            import base64
            pixel = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
            return Response(content=pixel, media_type="image/gif", headers={"Cache-Control": "no-cache,no-store"})
    if pwd != get_dashboard_password():
        return FileResponse("static/login.html")
    return FileResponse("static/index.html")

# Serve the static folder containing HTML, CSS, JS
app.mount("/static", StaticFiles(directory="static"), name="static")

def get_local_ip():
    import socket
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "127.0.0.1"

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    local_ip = get_local_ip()
    print("\n" + "=" * 60)
    print(" UNIVERSAL MAILER v2 IS ACTIVE!")
    print(f"  - Local Dashboard:   http://localhost:{port}")
    print(f"  - Local Wifi Share:  http://{local_ip}:{port}")
    print(f"  Use 'Local Wifi Share' link to access from other computers on the same network.")
    print("=" * 60 + "\n")
    uvicorn.run(app, host="0.0.0.0", port=port)
