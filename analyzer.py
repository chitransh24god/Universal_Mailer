import re

# Lists of words that trigger spam filters or promotions tabs
SPAM_TRIGGER_WORDS = [
    r"\bfree\b", r"\bguaranteed\b", r"\bprize\b", r"\blottery\b", r"\bwinner\b", r"\bcongratulations\b",
    r"\bearn money\b", r"\bmake money\b", r"\brisk[ -]free\b", r"\b100% free\b", r"\bclaim\b",
    r"\bact now\b", r"\burgent\b", r"\bclick here\b", r"\bbuy now\b", r"\border now\b", r"\bcash\b",
    r"\bsave big\b", r"\bcheap\b", r"\blowest price\b", r"\bwinner\b", r"\bselected\b"
]

PROMO_TRIGGER_WORDS = [
    r"\bloan\b", r"\bloans\b", r"\bsubsidy\b", r"\bsubsidies\b", r"\bdiscount\b", r"\bdiscounts\b",
    r"\boffer\b", r"\boffers\b", r"\bpromotion\b", r"\bpromotional\b", r"\bsolar policy\b",
    r"\btextile policy\b", r"\bco-working\b", r"\bwellness benefit\b", r"\bgold and silver\b",
    r"\bmutual fund\b", r"\bsip\b", r"\bfinancial wellness\b", r"\binterest subsidy\b",
    r"\bapply now\b", r"\bclick below\b", r"\bsubscribe\b", r"\bunsubscribe\b"
]

# Mapping of spam/promo words to softer alternatives that improve primary placement
SUGGESTED_ALTERNATIVES = {
    "loan": "funding arrangement / financial assistance",
    "loans": "funding programs",
    "subsidy": "support incentive / government program",
    "subsidies": "incentives / government support",
    "free": "complimentary / zero-cost",
    "buy now": "explore options",
    "click here": "read more / access details",
    "discount": "concession / price benefit",
    "offer": "availability / option",
    "urgent": "important / timely",
    "apply now": "register interest / evaluate eligibility",
    "save big": "optimize costs",
    "earn money": "generate revenue",
    "make money": "enhance earnings",
    "guaranteed": "assured / confirmed",
}

def analyze_email(subject, body):
    """
    Analyzes the subject and body of an email template.
    Returns a score (0-100), classification (Primary, Promotions, Spam), and lists of suggestions.
    """
    score = 100
    suggestions = []
    
    subject = subject.strip()
    body = body.strip()
    
    # ── 1. PERSONALIZATION CHECK (CRITICAL FOR PRIMARY INBOX) ───────────────────
    has_owner = "{Owner Name}" in subject or "{Owner Name}" in body or "{owner name}" in subject or "{owner name}" in body
    has_company = "{Company Name}" in subject or "{Company Name}" in body or "{company name}" in subject or "{company name}" in body
    
    if not (has_owner or has_company):
        score -= 25
        suggestions.append({
            "type": "warning",
            "field": "body",
            "message": "No personalization tokens found. Emails without recipient names or company names are usually marked as Promotions or Spam.",
            "recommendation": "Add '{Owner Name}' or '{Company Name}' in the salutation (e.g., 'Dear {Owner Name},')."
        })
    elif not has_owner:
        suggestions.append({
            "type": "suggestion",
            "field": "body",
            "message": "Adding a person's name makes the email feel more personal.",
            "recommendation": "Use '{Owner Name}' to directly address the recipient."
        })
        
    # ── 2. SUBJECT LENGTH CHECK ────────────────────────────────────────────────
    subject_len = len(subject)
    if subject_len < 10:
        score -= 5
        suggestions.append({
            "type": "warning",
            "field": "subject",
            "message": f"Subject line is very short ({subject_len} characters). Short subjects can look suspicious.",
            "recommendation": "Lengthen the subject to describe the email value (optimal: 20-50 characters)."
        })
    elif subject_len > 60:
        score -= 5
        suggestions.append({
            "type": "suggestion",
            "field": "subject",
            "message": f"Subject line is long ({subject_len} characters). It may be truncated on mobile devices.",
            "recommendation": "Shorten the subject line to under 50 characters."
        })
        
    # ── 3. SUBJECT CAPITALIZATION CHECK ────────────────────────────────────────
    # Check if subject is mostly uppercase
    letters = re.sub(r'[^a-zA-Z]', '', subject)
    if len(letters) > 4:
        uppercase_ratio = sum(1 for c in letters if c.isupper()) / len(letters)
        if uppercase_ratio > 0.6:
            score -= 15
            suggestions.append({
                "type": "warning",
                "field": "subject",
                "message": "Subject has a high percentage of capital letters. This triggers spam filters.",
                "recommendation": "Change the subject to Sentence Case or Title Case."
            })
            
    # ── 4. PUNCTUATION & SPECIAL CHARACTERS CHECK ─────────────────────────────
    if "!" in subject:
        excl_count = subject.count("!")
        deduction = min(20, excl_count * 10)
        score -= deduction
        suggestions.append({
            "type": "warning",
            "field": "subject",
            "message": "Subject contains exclamation marks ('!'). Exclamation marks in subjects trigger promotions/spam filters.",
            "recommendation": "Remove exclamation marks from the subject line."
        })
        
    if "!!!" in body:
        score -= 10
        suggestions.append({
            "type": "warning",
            "field": "body",
            "message": "Body contains consecutive exclamation marks ('!!!'). This looks unprofessional and spammy.",
            "recommendation": "Replace '!!!' with a single period or exclamation mark."
        })
        
    # ── 5. LINK COUNT CHECK ────────────────────────────────────────────────────
    # Regex to find links
    links = re.findall(r'https?://[^\s<>"]+|www\.[^\s<>"]+', body)
    if len(links) > 2:
        score -= 15
        suggestions.append({
            "type": "warning",
            "field": "body",
            "message": f"Found {len(links)} links in the body. Multiple links flag emails as promotional.",
            "recommendation": "Reduce links to 1 or 2. Use reply-backs instead of asking users to click multiple links."
        })
        
    # ── 6. BODY LENGTH CHECK ───────────────────────────────────────────────────
    if len(body) < 150:
        score -= 10
        suggestions.append({
            "type": "warning",
            "field": "body",
            "message": "Email body is too short. Short emails with links are often classified as spam.",
            "recommendation": "Add a brief explanation of your business or offer to provide more context."
        })
        
    # ── 7. SPAM & PROMO KEYWORD ANALYSIS ──────────────────────────────────────
    found_spam = []
    found_promo = []
    
    # Analyze Subject
    for pattern in SPAM_TRIGGER_WORDS:
        if re.search(pattern, subject, re.IGNORECASE):
            match = re.search(pattern, subject, re.IGNORECASE).group()
            found_spam.append((match, "subject"))
            score -= 15
            
    for pattern in PROMO_TRIGGER_WORDS:
        if re.search(pattern, subject, re.IGNORECASE):
            match = re.search(pattern, subject, re.IGNORECASE).group()
            found_promo.append((match, "subject"))
            score -= 10
            
    # Analyze Body
    body_spam_deductions = 0
    for pattern in SPAM_TRIGGER_WORDS:
        matches = re.findall(pattern, body, re.IGNORECASE)
        if matches:
            found_spam.append((matches[0], "body"))
            # Limit deductions for body words
            if body_spam_deductions < 20:
                score -= 5
                body_spam_deductions += 5
                
    body_promo_deductions = 0
    for pattern in PROMO_TRIGGER_WORDS:
        matches = re.findall(pattern, body, re.IGNORECASE)
        if matches:
            found_promo.append((matches[0], "body"))
            if body_promo_deductions < 15:
                score -= 3
                body_promo_deductions += 3

    # Add recommendations for spam/promo words
    reported = set()
    for word, field in found_spam + found_promo:
        word_lower = word.lower()
        if word_lower in reported:
            continue
        reported.add(word_lower)
        
        alt = SUGGESTED_ALTERNATIVES.get(word_lower)
        if alt:
            suggestions.append({
                "type": "warning" if word_lower in SUGGESTED_ALTERNATIVES else "suggestion",
                "field": field,
                "message": f"Avoid using the word '{word}' in the {field}.",
                "recommendation": f"Replace '{word}' with '{alt}' to avoid Promotions/Spam classification."
            })
        else:
            suggestions.append({
                "type": "suggestion",
                "field": field,
                "message": f"The term '{word}' in the {field} is commonly associated with promotional emails.",
                "recommendation": f"Try rephrasing or removing '{word}' if it's not strictly necessary."
            })
            
    # Ensure score stays in bounds
    score = max(0, min(100, score))
    
    # Classification logic based on score
    if score >= 85:
        classification = "Primary"
    elif score >= 55:
        classification = "Promotions"
    else:
        classification = "Spam"
        
    return {
        "score": score,
        "classification": classification,
        "suggestions": suggestions
    }
