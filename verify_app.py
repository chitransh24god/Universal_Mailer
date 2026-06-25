import os
import sys

# Ensure local directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from database import init_db, execute_query
from analyzer import analyze_email
from fastapi.testclient import TestClient

def test_database():
    print("== Testing Database Module ==")
    try:
        # Initialize
        init_db()
        print("[OK] Database initialized and tables created.")
        
        # Test query
        senders = execute_query("SELECT COUNT(*) as cnt FROM sender_accounts;", fetch="one")
        templates = execute_query("SELECT COUNT(*) as cnt FROM email_templates;", fetch="one")
        mappings = execute_query("SELECT COUNT(*) as cnt FROM sender_template_map;", fetch="one")
        
        print(f"[OK] Seed Count - Senders: {senders['cnt']}, Templates: {templates['cnt']}, Mappings: {mappings['cnt']}")
        assert senders['cnt'] > 0, "No senders seeded"
        assert templates['cnt'] > 0, "No templates seeded"
        assert mappings['cnt'] > 0, "No mappings seeded"
        print("[OK] Database seeding verification passed!")
        return True
    except Exception as e:
        print(f"[FAIL] Database verification failed: {e}")
        return False

def test_analyzer():
    print("\n== Testing Deliverability Analyzer ==")
    try:
        # Test case 1: Bad promotional text
        spam_subj = "GET A BUSINESS LOAN NOW!!!"
        spam_body = "Apply now for 100% free guaranteed loan options. Click here now to save big cash!"
        res_spam = analyze_email(spam_subj, spam_body)
        print(f"Promotional Test - Score: {res_spam['score']}, Classification: {res_spam['classification']}")
        print(f"Suggestions count: {len(res_spam['suggestions'])}")
        for s in res_spam['suggestions'][:3]:
            print(f"  - [{s['type']}] {s['message']} -> Rec: {s['recommendation']}")
            
        assert res_spam['score'] < 60, "Promotional text score should be low"
        assert res_spam['classification'] in ('Promotions', 'Spam'), "Should be classified as Promotions or Spam"
        
        # Test case 2: Clean personalized text
        clean_subj = "Review of Government Support Programs for Manufacturing"
        clean_body = "Dear {Owner Name},\n\nWe understand {Company Name} is engaged in manufacturing. We would love to evaluate your eligibility for government support incentives. Please let us know a convenient time to discuss.\n\nWarm regards,\nCA Yagya Sharda"
        res_clean = analyze_email(clean_subj, clean_body)
        print(f"Clean Test - Score: {res_clean['score']}, Classification: {res_clean['classification']}")
        print(f"Suggestions count: {len(res_clean['suggestions'])}")
        
        assert res_clean['score'] >= 85, "Personalized text score should be high"
        assert res_clean['classification'] == 'Primary', "Should be classified as Primary"
        print("[OK] Deliverability analyzer verification passed!")
        return True
    except Exception as e:
        print(f"[FAIL] Analyzer verification failed: {e}")
        return False

def test_api():
    print("\n== Testing FastAPI API Endpoints ==")
    try:
        from app import app
        client = TestClient(app)
        
        # Test 1: Senders list
        resp = client.get("/api/senders")
        assert resp.status_code == 200, "Senders API failed"
        senders = resp.json()
        print(f"[OK] Senders list retrieved: {len(senders)} accounts found.")
        
        # Test 2: Full templates list
        resp = client.get("/templates-list-full")
        assert resp.status_code == 200, "Templates API failed"
        templates = resp.json()
        print(f"[OK] Full templates list retrieved: {len(templates)} templates found.")
        
        # Test 3: Status check
        resp = client.get("/status")
        assert resp.status_code == 200, "Status API failed"
        status = resp.json()
        print(f"[OK] Status check passed. Sent today: {status.get('sent_today')}")
        
        # Test 3b: Tracking stats check
        resp = client.get("/tracking-stats")
        assert resp.status_code == 200, "Tracking stats API failed"
        tracking = resp.json()
        assert "summary" in tracking, "Tracking response missing summary"
        assert "emails" in tracking, "Tracking response missing emails list"
        print(f"[OK] Tracking stats check passed. Total tracking rows: {len(tracking.get('emails', []))}")
        
        # Test 4: Analyzer API
        resp = client.post("/api/analyze-template", json={
            "subject": "Greetings from VSD Group",
            "body_text": "Hello {Owner Name}, please reply to unsubscribe."
        })
        assert resp.status_code == 200, "Analyzer API failed"
        analysis = resp.json()
        print(f"[OK] Analyzer API passed. Score: {analysis.get('score')}")
        
        print("[OK] FastAPI endpoints verification passed!")
        return True
    except Exception as e:
        print(f"[FAIL] API verification failed: {e}")
        return False

if __name__ == "__main__":
    db_ok = test_database()
    analyzer_ok = test_analyzer()
    api_ok = test_api()
    
    if db_ok and analyzer_ok and api_ok:
        print("\n==============================")
        print("ALL VERIFICATION TESTS PASSED!")
        print("==============================")
        sys.exit(0)
    else:
        print("\n==============================")
        print("SOME VERIFICATION TESTS FAILED!")
        print("==============================")
        sys.exit(1)
