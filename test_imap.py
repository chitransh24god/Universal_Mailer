"""
Test IMAP connection for mybankloan.ai accounts.
Run this interactively to find the correct password.
"""
import imaplib, socket, sys

accounts_to_test = [
    ("admin@mybankloan.ai",   "mail.mybankloan.ai", 993),
    ("cayagya@mybankloan.ai", "mail.mybankloan.ai", 993),
    ("bl@mybankloan.ai",      "mail.mybankloan.ai", 993),
    ("invest@mybankloan.ai",  "mail.mybankloan.ai", 993),
]

password = sys.argv[1] if len(sys.argv) > 1 else input("Enter password to test: ")

for email, host, port in accounts_to_test:
    try:
        socket.setdefaulttimeout(10)
        mail = imaplib.IMAP4_SSL(host, port)
        status, resp = mail.login(email, password)
        print(f"  OK: {email} — {status}")
        mail.logout()
    except Exception as e:
        print(f"  FAIL: {email} — {e}")
