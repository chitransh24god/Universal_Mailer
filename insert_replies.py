"""Insert the Replies Inbox and IMAP setup sections into index.html."""

REPLIES_HTML = '''
            <!-- ── REPLIES INBOX ── -->
            <div class="card" style="margin-top:20px;">
                <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;">
                    <div class="card-title" style="margin-bottom:0;">&#128236; Replies Inbox</div>
                    <div style="display:flex;gap:8px;align-items:center;">
                        <label style="font-size:12px;color:var(--muted);display:flex;align-items:center;gap:5px;cursor:pointer;">
                            <input type="checkbox" id="show-bounces-chk" onchange="loadReplies()">
                            Show bounces
                        </label>
                        <button class="btn btn-secondary btn-sm" onclick="loadReplies()">&#8635; Refresh</button>
                    </div>
                </div>
                <div id="replies-inbox-container">
                    <div style="text-align:center;color:var(--muted);padding:24px;font-size:13px;">Loading replies...</div>
                </div>
            </div>

            <!-- ── IMAP PASSWORD SETUP ── -->
            <div class="card" style="margin-top:20px;">
                <div class="card-title">&#128295; Enable Reply Detection for @mybankloan.ai Accounts</div>
                <div style="background:rgba(234,179,8,0.07);border:1px solid rgba(234,179,8,0.25);border-radius:var(--r);padding:14px;font-size:13px;color:#92400e;margin-bottom:16px;line-height:1.6;">
                    &#9888; <strong>IMAP password is required</strong> for admin@, cayagya@, bl@, invest@mybankloan.ai to detect replies.
                    Enter the same password you use to log in at <strong>mail.mybankloan.ai</strong> webmail.
                </div>
                <div style="display:grid;grid-template-columns:1fr 1fr;gap:12px;align-items:end;">
                    <div class="field" style="margin-bottom:0;">
                        <label>Sender Account</label>
                        <select id="imap-pwd-email">
                            <option value="admin@mybankloan.ai">admin@mybankloan.ai</option>
                            <option value="cayagya@mybankloan.ai">cayagya@mybankloan.ai</option>
                            <option value="bl@mybankloan.ai">bl@mybankloan.ai</option>
                            <option value="invest@mybankloan.ai">invest@mybankloan.ai</option>
                        </select>
                    </div>
                    <div class="field" style="margin-bottom:0;">
                        <label>Email Hosting Password (IMAP)</label>
                        <input type="password" id="imap-pwd-value" placeholder="Your webmail password">
                    </div>
                </div>
                <button class="btn" style="margin-top:12px;" onclick="saveImapPassword()">&#128190; Save IMAP Password</button>
                <div id="imap-pwd-status" style="margin-top:10px;font-size:13px;"></div>
            </div>

'''

with open('static/index.html', 'r', encoding='utf-8') as f:
    content = f.read()

# Find the closing of the tracking tab (the </div></div></div> after tracking-table-body)
MARKER = '                </div>\n            </div>\n        </div>\n\n        <!-- \u2500\u2500 TAB 6: SETTINGS PANEL'
REPLACEMENT = '                </div>\n            </div>\n' + REPLIES_HTML + '        </div>\n\n        <!-- \u2500\u2500 TAB 6: SETTINGS PANEL'

if MARKER in content:
    content = content.replace(MARKER, REPLACEMENT, 1)
    with open('static/index.html', 'w', encoding='utf-8') as f:
        f.write(content)
    print("SUCCESS: Replies inbox inserted.")
else:
    print("MARKER NOT FOUND - searching nearby...")
    idx = content.find('TAB 6: SETTINGS PANEL')
    print("Chars before TAB 6:", repr(content[idx-120:idx]))
