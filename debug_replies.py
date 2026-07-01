import sys, os
sys.path.insert(0, '.')
from database import execute_query

print("=== IMAP Credentials Check ===")
accounts = execute_query(
    "SELECT email, imap_host, imap_port, imap_password FROM sender_accounts WHERE active=TRUE;",
    fetch="all"
)
for a in accounts:
    d = dict(a)
    print(f"  {d['email']} | imap_host: {d['imap_host']} | imap_port: {d['imap_port']} | has_pass: {bool(d['imap_password'])}")

print()
print("=== Sent emails with message_id ===")
rows = execute_query(
    "SELECT COUNT(*) as total FROM sent_emails;",
    fetch="one"
)
print(f"  Total sent_emails: {rows['total']}")

rows = execute_query(
    "SELECT COUNT(*) as c FROM sent_emails WHERE message_id IS NOT NULL AND message_id != '';",
    fetch="one"
)
print(f"  With message_id: {rows['c']}")

print()
print("=== Last 5 sent emails ===")
rows = execute_query(
    "SELECT to_email, sender_email, sent_at, replied, message_id FROM sent_emails ORDER BY sent_at DESC LIMIT 5;",
    fetch="all"
)
for r in rows:
    d = dict(r)
    print(f"  {d['to_email']} | replied={d['replied']} | has_msgid={bool(d['message_id'])}")

print()
print("=== Replies table ===")
rows = execute_query("SELECT COUNT(*) as c FROM replies;", fetch="one")
print(f"  Total replies stored: {rows['c']}")

rows = execute_query(
    "SELECT from_email, subject, received_at FROM replies ORDER BY received_at DESC LIMIT 5;",
    fetch="all"
)
for r in rows:
    d = dict(r)
    print(f"  FROM: {d['from_email']} | {d['subject'][:40]} | {d['received_at']}")
