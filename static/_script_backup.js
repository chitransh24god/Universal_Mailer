<script>
        // Set client local time clock
        function updateClock() {
            var n = new Date().toLocaleString('en-IN', {
                timeZone: 'Asia/Kolkata',
                hour12: true,
                hour: '2-digit',
                minute: '2-digit',
                second: '2-digit',
                weekday: 'short',
                day: 'numeric',
                month: 'short'
            });
            document.getElementById('clock').textContent = n + ' IST';
        }
        setInterval(updateClock, 1000);
        updateClock();

        // Global Variable holds
        let sendersList = [];
        let templatesList = [];
        let activeCampaigns = {};
        let currentFilter = 'all';
        let analysisTimeout = null;

        // Fetch Password from Query or LocalStorage
        function getPwd() {
            const urlParams = new URLSearchParams(window.location.search);
            let pwd = urlParams.get('pwd') || localStorage.getItem("mailer_password");
            if (!pwd) pwd = 'admin@123'; // Default fallback
            return pwd;
        }

        // Sidebar Navigation
        function navTo(tabName, el) {
            // update sidebar active
            document.querySelectorAll('.snav-btn').forEach(b => b.classList.remove('active'));
            if (el) el.classList.add('active');
            // update page title
            const titles = { launch:'Dashboard', templates:'Templates & Content', draft:'Draft Preview', monitor:'Live Monitor', tracking:'Email Tracking', settings:'Settings' };
            const t = document.getElementById('current-page-title');
            if (t) t.textContent = titles[tabName] || 'Dashboard';
            // show/hide stat cards only on dashboard
            const sb = document.getElementById('dash-stats');
            if (sb) sb.style.display = (tabName === 'launch') ? 'block' : 'none';
            // switch pane
            switchTab(tabName);
        }

        // Tab Switcher — unified for sidebar & any caller
        function switchTab(tabName, btnEl) {
            // Deactivate all panes
            document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));
            const pane = document.getElementById('tab-' + tabName);
            if (pane) pane.classList.add('active');

            // Update sidebar active button
            document.querySelectorAll('.snav-btn').forEach(b => b.classList.remove('active'));
            if (btnEl) btnEl.classList.add('active');

            // Update page title
            const titles = {
                dashboard: 'Dashboard',
                launch: 'Launch Campaign',
                templates: 'Templates & Content',
                draft: 'Draft Preview',
                monitor: 'Live Monitor',
                tracking: 'Email Tracking & Stats',
                settings: 'Settings & Config'
            };
            const titleEl = document.getElementById('current-page-title');
            if (titleEl) titleEl.textContent = titles[tabName] || 'Dashboard';

            // Trigger data loads per tab
            if (tabName === 'dashboard') {
                loadDashboardData();
            } else if (tabName === 'templates') {
                loadTemplates();
            } else if (tabName === 'draft') {
                loadDraftSelect();
            } else if (tabName === 'tracking') {
                loadTracking('all');
                loadReplies();
                loadGlobalSettings();
            } else if (tabName === 'settings') {
                loadSettingsData();
            }
        }

        // Load Dashboard KPIs and charts
        async function loadDashboardData() {
            renderActivityChart();
            // Load tracking summary for KPIs
            try {
                const r = await fetch('/api/tracking-summary');
                const data = await r.json();
                const total = data.total_sent || 0;
                const opened = data.total_opened || 0;
                const replied = data.total_replied || 0;
                const bounced = data.total_bounced || 0;
                const openRate = total > 0 ? ((opened / total) * 100).toFixed(1) : '0.0';
                const replyRate = total > 0 ? ((replied / total) * 100).toFixed(1) : '0.0';
                const bounceRate = total > 0 ? ((bounced / total) * 100).toFixed(1) : '0.0';
                const el = (id) => document.getElementById(id);
                if (el('kpi-open-rate')) el('kpi-open-rate').textContent = openRate + '%';
                if (el('kpi-reply-rate')) el('kpi-reply-rate').textContent = replyRate + '%';
                if (el('kpi-total-sent')) el('kpi-total-sent').textContent = total.toLocaleString();
                if (el('kpi-bounce-rate')) el('kpi-bounce-rate').textContent = bounceRate + '%';
                // Delivery score based on open rate
                const score = Math.min(100, Math.round(50 + (parseFloat(openRate) * 2)));
                if (el('delivery-score-val')) el('delivery-score-val').textContent = score;
                if (el('score-arc')) el('score-arc').setAttribute('stroke-dasharray', score + ' 100');
            } catch(e) { console.log('Dashboard KPI load:', e); }

            // Load sender quota
            try {
                const sr = await fetch('/api/senders');
                const senders = await sr.json();
                const qList = document.getElementById('sender-quota-list');
                if (qList && senders.length) {
                    qList.innerHTML = senders.slice(0,5).map(s => {
                        const sent = s.sent_today || 0;
                        const limit = 300;
                        const pct = Math.min(100, Math.round((sent / limit) * 100));
                        const color = pct >= 100 ? '#ef4444' : pct >= 75 ? '#f59e0b' : '#10b981';
                        return `<div>
                            <div style="display:flex;justify-content:space-between;margin-bottom:3px;">
                                <span style="font-size:11px;font-weight:600;color:#334155;">${s.email.split('@')[0]}</span>
                                <span style="font-size:11px;color:${color};font-weight:700;">${sent}/${limit}</span>
                            </div>
                            <div style="background:#f1f5f9;border-radius:99px;height:5px;">
                                <div style="background:${color};height:100%;width:${pct}%;border-radius:99px;transition:width 0.5s;"></div>
                            </div>
                        </div>`;
                    }).join('');
                } else if (qList) {
                    qList.innerHTML = '<div style="color:#94a3b8;font-size:12px;">No senders configured</div>';
                }
            } catch(e) { console.log('Sender quota:', e); }

            // Load campaign history
            try {
                const cr = await fetch('/api/campaign-history');
                const camps = await cr.json();
                const cList = document.getElementById('recent-campaigns-list');
                if (cList && camps.length) {
                    cList.innerHTML = camps.slice(0,5).map(c => `
                        <div style="display:flex;justify-content:space-between;align-items:center;padding:7px 0;border-bottom:1px solid #f3f4f6;">
                            <div>
                                <div style="font-size:12px;font-weight:600;color:#334155;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px;" title="${c.template || ''}">${c.template || 'Campaign'}</div>
                                <div style="font-size:10px;color:#94a3b8;">${c.counter_date || c.date || ''}</div>
                            </div>
                            <div style="font-size:13px;font-weight:700;color:#6366f1;">${c.total_rows || '—'}</div>
                        </div>`).join('');
                } else if (cList) {
                    cList.innerHTML = '<div style="color:#94a3b8;font-size:12px;padding:8px 0;">No campaigns yet</div>';
                }
            } catch(e) { console.log('Campaign history:', e); }

            // Load top templates
            try {
                const tr = await fetch('/tracking-stats?filter=all&limit=1000');
                const tdata = await tr.json();
                const rows = tdata.emails || [];
                // Group by subject (template proxy)
                const tmap = {};
                rows.forEach(r => {
                    const k = r.subject || 'Unknown';
                    if (!tmap[k]) tmap[k] = { sent: 0, opened: 0 };
                    tmap[k].sent++;
                    if (r.opened) tmap[k].opened++;
                });
                const sorted = Object.entries(tmap).sort((a,b) => (b[1].opened/Math.max(1,b[1].sent)) - (a[1].opened/Math.max(1,a[1].sent))).slice(0,5);
                const ttList = document.getElementById('top-templates-list');
                if (ttList && sorted.length) {
                    ttList.innerHTML = sorted.map(([name, d]) => {
                        const rate = d.sent > 0 ? ((d.opened/d.sent)*100).toFixed(0) : 0;
                        return `<div style="display:flex;justify-content:space-between;align-items:center;padding:6px 0;border-bottom:1px solid #f3f4f6;">
                            <span style="font-size:12px;color:#334155;font-weight:500;white-space:nowrap;overflow:hidden;text-overflow:ellipsis;max-width:140px;" title="${name}">${name}</span>
                            <span style="font-size:12px;font-weight:700;color:#10b981;">${rate}%</span>
                        </div>`;
                    }).join('');
                } else if (ttList) {
                    ttList.innerHTML = '<div style="color:#94a3b8;font-size:12px;">No data yet</div>';
                }
            } catch(e) { console.log('Top templates:', e); }
        }



        // ── LAUNCH CAMPAIGN & INITIAL DATA LOADING ────────────────────────────────
        async function initData() {
            await loadSenders();
            filterTemplatesBySender();
            startPolling();
        }

        async function loadSenders() {
            try {
                const response = await fetch('/api/senders');
                sendersList = await response.json();
                
                // Populate selects
                const launchSel = document.getElementById('launch-sender');
                const assocSel = document.getElementById('tmpl-sender-assoc');
                const mapSel = document.getElementById('map-sender-select');
                const trSenderFilter = document.getElementById('tr-sender-filter');
                
                let opts = sendersList.map(s => `<option value="${s.email}">${s.display_name} &lt;${s.email}&gt;</option>`).join('');
                if (!opts) opts = `<option value="">No senders configured</option>`;
                
                launchSel.innerHTML = opts;
                assocSel.innerHTML = `<option value="">Generic (All Senders)</option>` + opts;
                mapSel.innerHTML = opts;
                if (trSenderFilter) {
                    trSenderFilter.innerHTML = `<option value="">All Senders</option>` + opts;
                }
                
                // Warn about Gmail
                checkGmailWarning();
            } catch (err) {
                console.error("Error loading senders:", err);
            }
        }


        function checkGmailWarning() {
            const email = document.getElementById('launch-sender').value;
            const warningBox = document.getElementById('gmail-warning');
            if (email && (email.includes('gmail.com') || email.includes('googlemail.com'))) {
                warningBox.style.display = 'block';
            } else {
                warningBox.style.display = 'none';
            }
        }

        async function filterTemplatesBySender() {
            const sender = document.getElementById('launch-sender').value;
            const categorySelect = document.getElementById('launch-category');
            checkGmailWarning();
            
            try {
                const response = await fetch(`/templates-by-sender?sender=${encodeURIComponent(sender)}`);
                const data = await response.json();
                
                let opts = data.map(t => `<option value="${t.category}">${t.category}</option>`).join('');
                if (!opts) opts = `<option value="">No templates mapped to this sender</option>`;
                categorySelect.innerHTML = opts;
            } catch (err) {
                console.error("Error filtering templates:", err);
            }
        }

        // ── LIVE MONITORING & LOGS POLLER ──────────────────────────────────────────
        let pollInterval = null;
        function startPolling() {
            if (pollInterval) clearInterval(pollInterval);
            pollInterval = setInterval(fetchStatus, 3000);
            fetchStatus();
        }

        async function fetchStatus() {
            try {
                const response = await fetch('/status');
                const data = await response.json();
                
                // Update header stats
                document.getElementById('stat-sent').textContent = data.sent_today;
                document.getElementById('stat-rem').textContent = Math.max(0, 1500 - data.sent_today);
                const pct = Math.min(100, Math.round((data.sent_today / 1500) * 100));
                document.getElementById('stat-prog').style.width = pct + '%';
                
                // Update active campaigns list in monitor
                const campaignsList = document.getElementById('monitor-campaigns-list');
                const senders = data.senders || {};
                
                let anyRunning = false;
                let anyPaused = false;
                let html = '';
                
                for (const [email, campaignList] of Object.entries(senders)) {
                    campaignList.forEach(st => {
                        const progPct = st.total_rows > 0 ? Math.min(100, Math.round((st.current_row / st.total_rows) * 100)) : 0;
                        let badge = '';
                        if (st.running && !st.paused) {
                            badge = '<span class="badge badge-running">Running</span>';
                            anyRunning = true;
                        } else if (st.paused) {
                            badge = '<span class="badge badge-paused">Paused</span>';
                            anyPaused = true;
                        } else {
                            badge = '<span class="badge badge-done">Done</span>';
                        }
                        
                        let cancelBtn = '';
                        if (st.running || st.paused) {
                            cancelBtn = `<button class="btn btn-danger btn-sm" style="padding: 4px 8px; font-size:11px; margin-left: 10px; border-radius: 4px; display: inline-flex;" onclick="cancelCampaign('${st.campaign_id}')">Cancel</button>`;
                        }
                        
                        html += `
                        <div class="monitor-sender-card">
                            <div class="monitor-sender-header">
                                <span class="monitor-sender-title">${email} (${st.category || 'No Category'})</span>
                                <div style="display:flex; align-items:center;">
                                    ${badge}
                                    ${cancelBtn}
                                </div>
                            </div>
                            <div class="prog-track">
                                <div class="prog-fill" style="width: ${progPct}%"></div>
                            </div>
                            <div class="monitor-sender-meta">
                                ${st.current_row} of ${st.total_rows} sent (${progPct}%) • Started: ${st.started_at || ''}
                            </div>
                        </div>`;
                    });
                }
                
                campaignsList.innerHTML = html || `<div style="color:var(--muted); font-size:13px;">No active campaigns.</div>`;
                
                // System Status Badge
                const statusBadgeContainer = document.getElementById('stat-status');
                if (anyRunning) {
                    statusBadgeContainer.innerHTML = '<span class="badge badge-running">Running</span>';
                } else if (anyPaused) {
                    statusBadgeContainer.innerHTML = '<span class="badge badge-paused">Paused</span>';
                } else {
                    statusBadgeContainer.innerHTML = '<span class="badge badge-idle">Idle</span>';
                }
                
                // Logs
                const logsBox = document.getElementById('monitor-logs');
                if (logsBox) {
                    const logsHtml = data.log.map(line => {
                        if (line.includes('OK')) return `<div class="log-ok">${line}</div>`;
                        if (line.includes('FAIL') || line.includes('ERROR')) return `<div class="log-err">${line}</div>`;
                        if (line.includes('Paused') || line.includes('limit') || line.includes('Outside')) return `<div class="log-warn">${line}</div>`;
                        return `<div>${line}</div>`;
                    }).join('');
                    logsBox.innerHTML = logsHtml || 'No activity.';
                    logsBox.scrollTop = logsBox.scrollHeight;
                }
                
                // Fetch scheduled triggers list in monitor
                loadScheduledCampaigns();
            } catch (err) {
                console.error("Poller error:", err);
            }
        }


        async function cancelCampaign(campaignId) {
            if (!confirm("Are you sure you want to cancel this campaign?")) return;
            try {
                const response = await fetch('/api/campaigns/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ campaign_id: campaignId })
                });
                const res = await response.json();
                if (res.ok) {
                    alert("Campaign cancellation requested.");
                    fetchStatus();
                } else {
                    alert("Error: " + res.error);
                }
            } catch (err) {
                alert("Connection error: " + err);
            }
        }

        // ── TEMPLATE MANAGEMENT & ANALYZER ─────────────────────────────────────────
        async function loadTemplates() {
            try {
                const response = await fetch('/templates-list-full');
                templatesList = await response.json();
                
                const container = document.getElementById('templates-list-container');
                container.innerHTML = templatesList.map(t => `
                    <div class="sender-item-card" style="cursor:pointer;" onclick="editTemplate('${t.category}')">
                        <div class="sender-item-title">${t.category}</div>
                        <div class="sender-item-subtitle" style="white-space: nowrap; overflow: hidden; text-overflow: ellipsis; max-width:240px;">Subject: ${t.subject}</div>
                        <div class="sender-item-meta">
                            <span>Senders: ${t.senders || 'All Senders'}</span>
                        </div>
                    </div>
                `).join('') || `<div style="color:var(--muted); font-size:13px; grid-column: 1/-1; text-align:center;">No templates configured. Create one above!</div>`;
            } catch (err) {
                console.error("Error loading templates:", err);
            }
        }

        function editTemplate(category) {
            const tmpl = templatesList.find(t => t.category === category);
            if (!tmpl) return;
            
            document.getElementById('tmpl-cat').value = tmpl.category;
            document.getElementById('tmpl-cat').readOnly = true; // Cannot rename category to prevent conflicts
            document.getElementById('tmpl-subject').value = tmpl.subject;
            document.getElementById('tmpl-body').value = tmpl.body_text;
            
            document.getElementById('tmpl-details-section').style.display = 'block';
            document.getElementById('btn-tmpl-delete').style.display = 'block';
            
            // Trigger analysis
            analyzeTemplateContent(tmpl.subject, tmpl.body_text);
        }

        function toggleTemplateDetails() {
            const cat = document.getElementById('tmpl-cat').value.trim();
            const details = document.getElementById('tmpl-details-section');
            if (cat) {
                details.style.display = 'block';
            } else {
                details.style.display = 'none';
            }
        }

        // Real-time deliverability suggestions poller (debounce inputs)
        function queueAnalysis() {
            if (analysisTimeout) clearTimeout(analysisTimeout);
            analysisTimeout = setTimeout(() => {
                const subj = document.getElementById('tmpl-subject').value;
                const body = document.getElementById('tmpl-body').value;
                analyzeTemplateContent(subj, body);
            }, 500); // 500ms debounce
        }

        async function analyzeTemplateContent(subject, body_text) {
            if (!subject && !body_text) return;
            
            try {
                const response = await fetch('/api/analyze-template', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ subject, body_text })
                });
                
                const data = await response.json();
                
                // Update score ring & class
                const ring = document.getElementById('opt-score-ring');
                const text = document.getElementById('opt-score-txt');
                const classTxt = document.getElementById('opt-class-txt');
                
                text.textContent = data.score;
                classTxt.textContent = data.classification;
                classTxt.className = 'opt-classification-value ' + data.classification.toLowerCase();
                
                // Conic gradient color mapping
                let ringColor = 'var(--accent)';
                if (data.score < 55) {
                    ringColor = 'var(--danger)';
                } else if (data.score < 85) {
                    ringColor = 'var(--warn)';
                }
                
                const angle = (data.score / 100) * 360;
                ring.style.background = `conic-gradient(${ringColor} ${angle}deg, rgba(255, 255, 255, 0.05) ${angle}deg)`;
                
                // Suggestions
                const list = document.getElementById('opt-suggestions');
                if (data.suggestions.length === 0) {
                    list.innerHTML = `
                    <div style="background:var(--success-bg); color:var(--success); border:1px solid rgba(16,185,129,0.15); border-radius:var(--r); padding:14px; text-align:center;">
                        ✓ Clean deliverability score! This email has high chance of landing in the <b>Primary Inbox</b>.
                    </div>`;
                } else {
                    list.innerHTML = data.suggestions.map(s => `
                        <div class="opt-suggestion-card ${s.type}">
                            <div class="opt-suggestion-msg">${s.message}</div>
                            <div class="opt-suggestion-rec">${s.recommendation}</div>
                        </div>
                    `).join('');
                }
            } catch (err) {
                console.error("Error analyzing template:", err);
            }
        }

        async function saveTemplate() {
            const sender = document.getElementById('tmpl-sender-assoc').value;
            const cat = document.getElementById('tmpl-cat').value.trim();
            const subj = document.getElementById('tmpl-subject').value.trim();
            const body = document.getElementById('tmpl-body').value.trim();
            
            if (!cat || !subj || !body) {
                alert('Please enter template name, subject, and body.');
                return;
            }
            
            try {
                const response = await fetch('/add-template-ajax/', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sender_email: sender, category: cat, subject: subj, body_text: body })
                });
                const res = await response.json();
                
                if (res.ok) {
                    alert('Template saved successfully!');
                    resetTemplateForm();
                    loadTemplates();
                } else {
                    alert('Error saving template: ' + res.error);
                }
            } catch (err) {
                alert('Connection error: ' + err);
            }
        }

        async function deleteTemplate() {
            const cat = document.getElementById('tmpl-cat').value.trim();
            if (!cat) return;
            
            if (!confirm(`Are you sure you want to delete template "${cat}"?`)) {
                return;
            }
            
            try {
                const response = await fetch('/delete-template', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category: cat })
                });
                const res = await response.json();
                
                if (res.ok) {
                    alert('Template deleted.');
                    resetTemplateForm();
                    loadTemplates();
                } else {
                    alert('Error deleting template.');
                }
            } catch (err) {
                alert('Connection error: ' + err);
            }
        }

        function resetTemplateForm() {
            document.getElementById('tmpl-cat').value = '';
            document.getElementById('tmpl-cat').readOnly = false;
            document.getElementById('tmpl-subject').value = '';
            document.getElementById('tmpl-body').value = '';
            
            document.getElementById('tmpl-details-section').style.display = 'none';
            document.getElementById('btn-tmpl-delete').style.display = 'none';
            
            document.getElementById('opt-score-ring').style.background = `conic-gradient(rgba(255, 255, 255, 0.05) 0deg, rgba(255, 255, 255, 0.05) 0deg)`;
            document.getElementById('opt-score-txt').textContent = '—';
            document.getElementById('opt-class-txt').textContent = '—';
            document.getElementById('opt-class-txt').className = 'opt-classification-value';
            document.getElementById('opt-suggestions').innerHTML = `<div style="color:var(--muted); font-size:13px; text-align:center; padding:20px;">Start entering subject & body to view suggestions.</div>`;
        }

        // ── TAB 3: DRAFT PREVIEW ───────────────────────────────────────────
        function loadDraftSelect() {
            const select = document.getElementById('draft-template');
            select.innerHTML = templatesList.map(t => `<option value="${t.category}">${t.category}</option>`).join('');
            loadDraftPreview();
        }

        async function loadDraftPreview() {
            const cat = document.getElementById('draft-template').value;
            if (!cat) return;
            
            try {
                const response = await fetch(`/get-template?category=${encodeURIComponent(cat)}`);
                const data = await response.json();
                
                document.getElementById('prev-subject-line').textContent = data.subject || '—';
                document.getElementById('prev-body-box').innerText = data.body_text || 'No body.';
                
                previewDraft();
            } catch (err) {
                console.error("Error loading draft preview template:", err);
            }
        }

        async function previewDraft() {
            const cat = document.getElementById('draft-template').value;
            if (!cat) return;
            
            let vars = {};
            try {
                vars = JSON.parse(document.getElementById('draft-variables').value || '{}');
            } catch (e) {
                // Invalid JSON, ignore and use un-personalized template
            }
            
            try {
                const response = await fetch('/preview-template', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ category: cat, vars: vars })
                });
                
                const data = await response.json();
                document.getElementById('prev-subject-line').textContent = data.subject || '—';
                
                // Formats newlines as HTML paragraphs safely
                let text = data.body || '';
                let formatted = text.split('\n').map(line => {
                    let s = line.trim();
                    if (s === '') return '<div style="height:8px;"></div>';
                    if (s.startsWith('- ')) return `<div style="margin:4px 0 4px 16px;">• ${s.substring(2)}</div>`;
                    return `<div>${s}</div>`;
                }).join('');
                
                document.getElementById('prev-body-box').innerHTML = formatted || 'No body.';
            } catch (err) {
                console.error("Draft rendering failed:", err);
            }
        }

        // ── TAB 5: EMAIL TRACKING ──────────────────────────────────────────
        async function loadTracking(filter) {
            currentFilter = filter;
            
            // Highlight active status button
            ['all','opened','replied','not_opened','alert_48h'].forEach(f => {
                const btn = document.getElementById('tr-btn-' + f);
                if (btn) {
                    btn.style.background = (f === filter) ? 'var(--accent)' : '';
                    btn.style.color = (f === filter) ? '#fff' : '';
                }
            });

            const container = document.getElementById('tracking-table-body');
            container.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:30px; color:var(--muted);">Loading tracking data...</td></tr>`;
            
            try {
                const dateFrom = document.getElementById('tr-date-from')?.value || '';
                const dateTo   = document.getElementById('tr-date-to')?.value   || '';
                const sender   = document.getElementById('tr-sender-filter')?.value || '';

                const url = `/tracking-stats?filter=${filter}&limit=500` +
                    (dateFrom ? `&date_from=${dateFrom}` : '') +
                    (dateTo   ? `&date_to=${dateTo}`     : '') +
                    (sender   ? `&sender=${encodeURIComponent(sender)}` : '');

                const response = await fetch(url);
                const data = await response.json();
                
                // Update count cards
                const sum = data.summary || {};
                const total  = sum.total  || 0;
                const opened = sum.opened || 0;
                document.getElementById('tr-total').textContent   = total;
                document.getElementById('tr-opened').textContent  = opened;
                document.getElementById('tr-replied').textContent = sum.replied || 0;
                document.getElementById('tr-48h').textContent     = sum.not_opened_48h || 0;
                const openRate = total > 0 ? Math.round((opened / total) * 100) : 0;
                document.getElementById('tr-open-rate').textContent = openRate + '%';
                
                // Load per-sender breakdown (with same date filters)
                loadPerSenderBreakdown(dateFrom, dateTo);
                
                if (!data.emails || data.emails.length === 0) {
                    container.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:30px; color:var(--muted);">No matching tracking data found.</td></tr>`;
                    return;
                }
                
                container.innerHTML = data.emails.map(e => {
                    let statusBadge = '';
                    if (e.replied) {
                        statusBadge = '<span class="badge badge-done">Replied</span>';
                    } else if (e.opened) {
                        statusBadge = '<span class="badge badge-running">Opened</span>';
                    } else if (e.alerted_48h) {
                        statusBadge = '<span class="badge badge-paused">48h Alert</span>';
                    } else {
                        statusBadge = '<span class="badge badge-idle">Sent</span>';
                    }
                    
                    const actionBtn = !e.replied ? 
                        `<button class="btn btn-secondary btn-sm" onclick="markAsReplied(${e.id})">Mark Replied</button>` : 
                        `—`;
                        
                    let sentTime = e.sent_at ? e.sent_at.split('.')[0] : '—';
                    
                    let htmlRow = `
                    <tr>
                        <td style="font-weight:600;">${e.to_email}</td>
                        <td style="color:var(--muted);">${e.company_name || '—'} <div style="font-size:10px; color:var(--hint);">${e.owner_name || ''}</div></td>
                        <td style="color:var(--hint); font-size:12px;">${e.sender_email}</td>
                        <td style="color:var(--muted); font-size:12px;">${sentTime}</td>
                        <td style="text-align:center;">${statusBadge}</td>
                        <td style="text-align:center;">${actionBtn}</td>
                    </tr>`;
                    
                    if (e.reply_preview) {
                        htmlRow += `
                        <tr class="reply-preview-row">
                            <td colspan="6">
                                <div class="reply-preview-container">
                                    <b>Reply Preview:</b> "${e.reply_preview}"
                                </div>
                            </td>
                        </tr>`;
                    }
                    
                    return htmlRow;
                }).join('');
            } catch (err) {
                container.innerHTML = `<tr><td colspan="6" style="text-align:center; padding:30px; color:var(--danger);">Error loading tracking data: ${err}</td></tr>`;
            }
        }

        async function loadPerSenderBreakdown(dateFrom, dateTo) {
            const tbody = document.getElementById('per-sender-table-body');
            try {
                let url = '/tracking-per-sender';
                const params = [];
                if (dateFrom) params.push('date_from=' + dateFrom);
                if (dateTo)   params.push('date_to='   + dateTo);
                if (params.length) url += '?' + params.join('&');
                
                const resp = await fetch(url);
                const rows = await resp.json();
                
                if (!rows || rows.length === 0) {
                    tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:14px;color:var(--muted);">No data.</td></tr>`;
                    return;
                }
                
                tbody.innerHTML = rows.map(r => {
                    const rate = r.total > 0 ? Math.round((r.opened / r.total) * 100) : 0;
                    const rateColor = rate >= 30 ? 'var(--accent)' : rate >= 15 ? '#ca8a04' : 'var(--danger)';
                    return `<tr>
                        <td style="font-weight:600;">${r.sender_email}</td>
                        <td style="text-align:center; font-weight:700;">${r.total}</td>
                        <td style="text-align:center; color:#2563eb; font-weight:600;">${r.opened}</td>
                        <td style="text-align:center; color:var(--accent); font-weight:600;">${r.replied}</td>
                        <td style="text-align:center; color:var(--danger);">${r.not_opened_48h}</td>
                        <td style="text-align:center; font-weight:700; color:${rateColor};">${rate}%</td>
                    </tr>`;
                }).join('');
            } catch (e) {
                tbody.innerHTML = `<tr><td colspan="6" style="color:var(--danger);padding:14px;">Error loading breakdown.</td></tr>`;
            }
        }

        function clearTrackingFilters() {
            const df = document.getElementById('tr-date-from');
            const dt = document.getElementById('tr-date-to');
            const sf = document.getElementById('tr-sender-filter');
            if (df) df.value = '';
            if (dt) dt.value = '';
            if (sf) sf.value = '';
            loadTracking(currentFilter);
        }

        function downloadTracking() {
            const dateFrom = document.getElementById('tr-date-from')?.value || '';
            const dateTo   = document.getElementById('tr-date-to')?.value   || '';
            const sender   = document.getElementById('tr-sender-filter')?.value || '';
            let url = `/tracking-download?filter=${currentFilter}`;
            if (dateFrom) url += `&date_from=${dateFrom}`;
            if (dateTo)   url += `&date_to=${dateTo}`;
            if (sender)   url += `&sender=${encodeURIComponent(sender)}`;
            window.location.href = url;
        }

        async function loadReplies() {
            const container = document.getElementById('replies-inbox-container');
            if (!container) return;
            const includeBounces = document.getElementById('show-bounces-chk')?.checked ? 'true' : 'false';
            container.innerHTML = `<div style="text-align:center;color:var(--muted);padding:24px;font-size:13px;">Loading replies...</div>`;
            try {
                const resp = await fetch(`/replies-list?limit=200&include_bounces=${includeBounces}`);
                const data = await resp.json();
                const replies = data.replies || [];
                if (replies.length === 0) {
                    container.innerHTML = `<div style="text-align:center;color:var(--muted);padding:30px;font-size:13px;">
                        No real replies found yet.<br>
                        <span style="font-size:12px;opacity:.7;">Reply detection runs every 60 seconds. Make sure IMAP passwords are saved below.</span>
                    </div>`;
                    return;
                }
                container.innerHTML = `
                <div style="overflow-x:auto;">
                <table class="track-table" style="font-size:13px;">
                    <thead><tr>
                        <th>From</th>
                        <th>Subject</th>
                        <th>Sent To</th>
                        <th>Sender Account</th>
                        <th>Received</th>
                        <th>Reply Preview</th>
                    </tr></thead>
                    <tbody>
                    ${replies.map(r => `
                        <tr>
                            <td style="font-weight:600;color:var(--accent);">${r.from_email}</td>
                            <td>${r.subject || '—'}</td>
                            <td style="font-size:12px;color:var(--muted);">${r.to_email || r.company_name || '—'}</td>
                            <td style="font-size:12px;color:var(--hint);">${r.sender_email || '—'}</td>
                            <td style="font-size:12px;color:var(--muted);">${(r.received_at||'').split('.')[0]}</td>
                            <td style="font-size:12px;color:var(--muted);max-width:280px;word-break:break-word;">${(r.body_preview||'').substring(0,180)}${r.body_preview && r.body_preview.length>180 ? '...' : ''}</td>
                        </tr>
                    `).join('')}
                    </tbody>
                </table>
                </div>`;
            } catch (err) {
                container.innerHTML = `<div style="color:var(--danger);padding:16px;font-size:13px;">Error loading replies: ${err}</div>`;
            }
        }

        async function saveImapPassword() {
            const email = document.getElementById('imap-pwd-email').value;
            const password = document.getElementById('imap-pwd-value').value.trim();
            const status = document.getElementById('imap-pwd-status');
            if (!password) { status.textContent = 'Please enter a password.'; status.style.color = 'var(--danger)'; return; }
            status.textContent = 'Saving...'; status.style.color = 'var(--muted)';
            try {
                const resp = await fetch('/api/update-imap-password', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ email, imap_password: password })
                });
                const data = await resp.json();
                if (data.ok) {
                    status.textContent = `✅ IMAP password saved for ${email}. Reply detection will activate within 60 seconds.`;
                    status.style.color = 'var(--accent)';
                    document.getElementById('imap-pwd-value').value = '';
                } else {
                    status.textContent = 'Error: ' + (data.error || 'Unknown error');
                    status.style.color = 'var(--danger)';
                }
            } catch (err) {
                status.textContent = 'Connection error: ' + err;
                status.style.color = 'var(--danger)';
            }
        }


        async function markAsReplied(id) {
            try {
                const response = await fetch(`/mark-replied/${id}`, { method: 'POST' });
                const res = await response.json();
                if (res.ok) {
                    loadTracking(currentFilter);
                } else {
                    alert('Error marking email as replied.');
                }
            } catch (err) {
                alert('Connection error: ' + err);
            }
        }

        function refreshTracking() {
            loadTracking(currentFilter);
        }

        // ── TAB 6: SETTINGS PANEL ──────────────────────────────────────────
        function loadSettingsData() {
            loadSendersSettingsList();
            loadSenderTemplateMappings();
            loadGlobalSettings();
        }

        async function loadGlobalSettings() {
            try {
                const response = await fetch('/api/settings');
                if (response.ok) {
                    const settings = await response.json();
                    document.getElementById('setting-tracking-url').value = settings.tracking_base_url || '';
                    document.getElementById('setting-password').value = settings.dashboard_password || '';
                    
                    const warningEl = document.getElementById('tracking-url-warning');
                    if (warningEl) {
                        const url = (settings.tracking_base_url || '').trim().toLowerCase();
                        if (!url || url.includes('localhost') || url.includes('127.0.0.1') || url.includes('192.168.') || !url.startsWith('https://')) {
                            warningEl.style.display = 'block';
                        } else {
                            warningEl.style.display = 'none';
                        }
                    }
                }
            } catch (err) {
                console.error("Error loading global settings:", err);
            }
        }

        async function saveGlobalSettings() {
            const tracking_base_url = document.getElementById('setting-tracking-url').value.trim();
            const dashboard_password = document.getElementById('setting-password').value.trim();
            
            if (!dashboard_password) {
                alert("Password cannot be empty!");
                return;
            }
            
            try {
                const response = await fetch('/api/settings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ tracking_base_url, dashboard_password })
                });
                
                if (response.ok) {
                    localStorage.setItem("mailer_password", dashboard_password);
                    alert("Global Settings saved successfully!");
                } else {
                    const err = await response.json();
                    alert("Error saving settings: " + (err.error || response.statusText));
                }
            } catch (err) {
                alert("Error saving settings: " + err);
            }
        }

        async function loadSendersSettingsList() {
            try {
                const response = await fetch('/api/senders');
                const list = await response.json();
                
                const container = document.getElementById('settings-senders-list');
                container.innerHTML = list.map(s => `
                    <div class="sender-item-card">
                        <div class="sender-item-title">${s.display_name}</div>
                        <div class="sender-item-subtitle">${s.email} (${s.provider_type.toUpperCase()})</div>
                        <div class="sender-item-meta">
                            <span>Limit: ${s.daily_limit}</span>
                            <span>Delay: ${s.delay_min !== undefined ? s.delay_min : 60}-${s.delay_max !== undefined ? s.delay_max : 120}s</span>
                            <span>Status: ${s.active ? '<span style="color:var(--accent)">Active</span>' : '<span style="color:var(--danger)">Inactive</span>'}</span>
                        </div>
                        <div class="sender-item-actions">
                            <button class="btn btn-secondary btn-sm" onclick="editSenderAccount('${s.email}')">Edit</button>
                            <button class="btn btn-danger btn-sm" onclick="deleteSenderAccount('${s.email}')">Delete</button>
                        </div>
                    </div>
                `).join('') || `<div style="color:var(--muted); font-size:13px;">No sender accounts configured. Fill form below to create.</div>`;
            } catch (err) {
                console.error("Error loading settings senders list:", err);
            }
        }

        function toggleProviderSettings() {
            const p = document.getElementById('snd-provider').value;
            if (p === 'brevo') {
                document.getElementById('snd-brevo-block').style.display = 'block';
                document.getElementById('snd-smtp-block').style.display = 'none';
            } else {
                document.getElementById('snd-brevo-block').style.display = 'none';
                document.getElementById('snd-smtp-block').style.display = 'block';
            }
        }

        async function saveSenderAccount() {
            const email = document.getElementById('snd-email').value.trim();
            const display_name = document.getElementById('snd-display-name').value.trim();
            const provider_type = document.getElementById('snd-provider').value;
            const api_key = document.getElementById('snd-api-key').value.trim();
            const smtp_host = document.getElementById('snd-smtp-host').value.trim();
            const smtp_port = document.getElementById('snd-smtp-port').value.trim();
            const smtp_password = document.getElementById('snd-smtp-pass').value.trim();
            const imap_host = document.getElementById('snd-imap-host').value.trim();
            const imap_port = document.getElementById('snd-imap-port').value.trim();
            const imap_password = document.getElementById('snd-imap-pass').value.trim();
            const daily_limit = document.getElementById('snd-limit').value.trim();
            const delay_min = document.getElementById('snd-delay-min').value.trim();
            const delay_max = document.getElementById('snd-delay-max').value.trim();
            const active = document.getElementById('snd-active').checked;
            const skip_test = document.getElementById('snd-skip-test').checked;
            
            if (!email || !display_name) {
                alert('Please enter Email Address and Display Name.');
                return;
            }
            
            const payload = {
                email, display_name, provider_type, api_key, smtp_host, 
                smtp_port: smtp_port ? parseInt(smtp_port) : null,
                smtp_password, imap_host, 
                imap_port: imap_port ? parseInt(imap_port) : null,
                imap_password, 
                daily_limit: parseInt(daily_limit), 
                delay_min: parseInt(delay_min),
                delay_max: parseInt(delay_max),
                active,
                skip_test
            };
            
            try {
                const response = await fetch('/api/senders', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(payload)
                });
                const res = await response.json();
                if (res.ok) {
                    alert('Sender account saved.');
                    resetSenderForm();
                    loadSenders();
                    loadSendersSettingsList();
                } else {
                    alert('Error saving account: ' + res.error);
                }
            } catch (err) {
                alert('Connection error: ' + err);
            }
        }

        function editSenderAccount(email) {
            const s = sendersList.find(snd => snd.email === email);
            if (!s) return;
            
            document.getElementById('snd-email').value = s.email;
            document.getElementById('snd-email').readOnly = true;
            document.getElementById('snd-display-name').value = s.display_name;
            document.getElementById('snd-provider').value = s.provider_type;
            
            // Password fields left blank to represent "no change" unless filled in
            document.getElementById('snd-api-key').value = s.api_key || '';
            document.getElementById('snd-smtp-host').value = s.smtp_host || '';
            document.getElementById('snd-smtp-port').value = s.smtp_port || '';
            document.getElementById('snd-smtp-pass').value = '';
            document.getElementById('snd-imap-host').value = s.imap_host || '';
            document.getElementById('snd-imap-port').value = s.imap_port || '';
            document.getElementById('snd-imap-pass').value = '';
            document.getElementById('snd-limit').value = s.daily_limit;
            document.getElementById('snd-delay-min').value = s.delay_min !== undefined ? s.delay_min : 60;
            document.getElementById('snd-delay-max').value = s.delay_max !== undefined ? s.delay_max : 120;
            document.getElementById('snd-active').checked = s.active;
            document.getElementById('snd-skip-test').checked = false;
            
            document.getElementById('sender-form-title').textContent = "Edit Sender: " + s.email;
            document.getElementById('snd-is-edit').value = "true";
            document.getElementById('btn-cancel-edit').style.display = 'block';
            
            toggleProviderSettings();
        }

        async function deleteSenderAccount(email) {
            if (!confirm(`Are you sure you want to delete sender ${email}?`)) return;
            
            try {
                const response = await fetch(`/api/senders/${encodeURIComponent(email)}`, { method: 'DELETE' });
                const res = await response.json();
                if (res.ok) {
                    alert('Account deleted.');
                    resetSenderForm();
                    loadSenders();
                    loadSendersSettingsList();
                } else {
                    alert('Delete failed.');
                }
            } catch (err) {
                alert('Connection error: ' + err);
            }
        }

        function resetSenderForm() {
            document.getElementById('snd-email').value = '';
            document.getElementById('snd-email').readOnly = false;
            document.getElementById('snd-display-name').value = '';
            document.getElementById('snd-provider').value = 'brevo';
            document.getElementById('snd-api-key').value = '';
            document.getElementById('snd-smtp-host').value = '';
            document.getElementById('snd-smtp-port').value = '';
            document.getElementById('snd-smtp-pass').value = '';
            document.getElementById('snd-imap-host').value = '';
            document.getElementById('snd-imap-port').value = '';
            document.getElementById('snd-imap-pass').value = '';
            document.getElementById('snd-limit').value = '1500';
            document.getElementById('snd-delay-min').value = '60';
            document.getElementById('snd-delay-max').value = '120';
            document.getElementById('snd-active').checked = true;
            document.getElementById('snd-skip-test').checked = false;
            
            document.getElementById('sender-form-title').textContent = "Add Sender Account";
            document.getElementById('snd-is-edit').value = "false";
            document.getElementById('btn-cancel-edit').style.display = 'none';
            
            toggleProviderSettings();
        }

        // Mappings Grid
        async function loadSenderTemplateMappings() {
            const sender = document.getElementById('map-sender-select').value;
            if (!sender) return;
            
            try {
                // Ensure templates list is populated
                if (templatesList.length === 0) {
                    const response = await fetch('/templates-list-full');
                    templatesList = await response.json();
                }
                
                // Fetch current mapped categories for this sender
                const res = await fetch(`/templates-by-sender?sender=${encodeURIComponent(sender)}`);
                const mappedCats = (await res.json()).map(t => t.category);
                
                const checklist = document.getElementById('map-templates-checklist');
                
                checklist.innerHTML = templatesList.map(t => {
                    const isChecked = mappedCats.includes(t.category) ? 'checked' : '';
                    return `
                    <label class="mapping-checkbox-item">
                        <input type="checkbox" value="${t.category}" ${isChecked} onchange="saveMappingChange()">
                        <span>${t.category}</span>
                    </label>`;
                }).join('') || `<div style="color:var(--muted); font-size:12px; padding:10px;">Create templates first.</div>`;
            } catch (err) {
                console.error("Error loading mapping list:", err);
            }
        }

        async function saveMappingChange() {
            const sender = document.getElementById('map-sender-select').value;
            const checkedBoxes = document.querySelectorAll('#map-templates-checklist input[type=checkbox]:checked');
            const categories = Array.from(checkedBoxes).map(cb => cb.value);
            
            try {
                const response = await fetch('/api/sender-mappings', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ sender_email: sender, categories: categories })
                });
                
                // Mappings updated successfully (run silently or log)
                console.log(`Mappings updated for ${sender}`);
            } catch (err) {
                alert('Failed to save mapping change: ' + err);
            }
        }

        // Rich Formatting Toolbar Helpers
        function insertTextAtCursor(elId, startTag, endTag = '') {
            const textarea = document.getElementById(elId);
            const start = textarea.selectionStart;
            const end = textarea.selectionEnd;
            const text = textarea.value;
            const selected = text.substring(start, end);
            const replacement = startTag + selected + endTag;
            textarea.value = text.substring(0, start) + replacement + text.substring(end);
            textarea.focus();
            textarea.selectionStart = start + startTag.length;
            textarea.selectionEnd = start + startTag.length + selected.length;
            queueAnalysis();
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', function(e) {
            const dropdown = document.getElementById('attachment-dropdown');
            if (dropdown && dropdown.style.display === 'block') {
                dropdown.style.display = 'none';
            }
        });

        function toggleAttachmentDropdown(event) {
            if (event) event.stopPropagation();
            const dropdown = document.getElementById('attachment-dropdown');
            if (dropdown) {
                dropdown.style.display = dropdown.style.display === 'block' ? 'none' : 'block';
            }
        }

        function triggerAttachmentUpload(event, type) {
            if (event) {
                event.preventDefault();
                event.stopPropagation();
            }
            const dropdown = document.getElementById('attachment-dropdown');
            if (dropdown) dropdown.style.display = 'none';
            
            const input = document.getElementById('tmpl-attachment-file');
            if (!input) return;
            
            if (type === 'image') {
                input.accept = 'image/*';
            } else if (type === 'pdf') {
                input.accept = '.pdf';
            } else if (type === 'excel') {
                input.accept = '.xlsx,.xls,.csv';
            } else {
                input.accept = '*/*';
            }
            input.click();
        }

        async function uploadTemplateAttachment() {
            const fileInput = document.getElementById('tmpl-attachment-file');
            const file = fileInput.files[0];
            if (!file) return;
            
            const formData = new FormData();
            formData.append('file', file);
            
            try {
                const resp = await fetch('/api/upload-attachment', {
                    method: 'POST',
                    body: formData
                });
                const data = await resp.json();
                if (data.ok) {
                    const ext = file.name.split('.').pop().toLowerCase();
                    const isImg = ['png', 'jpg', 'jpeg', 'gif', 'webp', 'bmp'].includes(ext);
                    
                    let htmlTag = '';
                    if (isImg) {
                        htmlTag = `<img src="${data.url}" style="max-width:100%; height:auto; display:block; margin:10px 0;" alt="${file.name}" />`;
                    } else {
                        htmlTag = `<a href="${data.url}" target="_blank" style="color:var(--accent); font-weight:600; text-decoration:underline;">📄 Download ${file.name}</a>`;
                    }
                    insertTextAtCursor('tmpl-body', htmlTag);
                } else {
                    alert('Upload failed: ' + (data.error || 'Unknown error'));
                }
            } catch (err) {
                alert('Connection error during upload: ' + err);
            }
            fileInput.value = ''; // Reset
        }

        function logout() {
            if (confirm("Are you sure you want to log out from the dashboard?")) {
                localStorage.removeItem("mailer_password");
                window.location.href = '/';
            }
        }


        // Campaign Scheduling Trigger Checkpoint Toggling
        function toggleScheduleBlock() {
            const chk = document.getElementById('chk-schedule');
            const block = document.getElementById('schedule-block');
            const dateInput = document.getElementById('sched-date');
            const timeInput = document.getElementById('sched-time');
            if (chk.checked) {
                block.style.display = 'block';
                dateInput.required = true;
                timeInput.required = true;
                
                // Set default scheduled time to current time + 10 mins
                const now = new Date();
                now.setMinutes(now.getMinutes() + 10);
                const localDate = now.toISOString().split('T')[0];
                const localTime = now.toTimeString().substring(0, 5);
                dateInput.value = localDate;
                timeInput.value = localTime;
            } else {
                block.style.display = 'none';
                dateInput.required = false;
                timeInput.required = false;
                dateInput.value = '';
                timeInput.value = '';
            }
        }

        // Scheduled Campaigns Listing & Cancelling
        async function loadScheduledCampaigns() {
            try {
                const response = await fetch('/api/scheduled-campaigns');
                const list = await response.json();
                const container = document.getElementById('scheduled-triggers-list');
                if (!container) return;
                
                if (!list || list.length === 0) {
                    container.innerHTML = '<div style="color:var(--muted); font-size:13px; text-align:center; padding:12px;">No upcoming triggers.</div>';
                    return;
                }
                
                container.innerHTML = list.map(c => {
                    const utcDate = new Date(c.scheduled_time + 'Z');
                    const localStr = utcDate.toLocaleString(undefined, {
                        month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit'
                    });
                    return `
                    <div style="display:flex; justify-content:space-between; align-items:center; padding:8px 0; border-bottom:1px solid var(--border);">
                        <div>
                            <div style="font-weight:600; color:var(--text);">${c.category}</div>
                            <div style="font-size:11px; color:var(--muted); line-height:1.4;">
                                Sender: ${c.sender_email}<br>
                                <span style="color:var(--accent); font-weight:600;">Trigger: ${localStr}</span>
                            </div>
                        </div>
                        <button class="btn btn-secondary btn-sm" style="color:var(--danger); padding:2px 8px; font-size:11px;" onclick="cancelScheduledCampaign(${c.id})">Cancel</button>
                    </div>`;
                }).join('');
            } catch (err) {
                console.error("Error loading scheduled campaigns:", err);
            }
        }

        async function cancelScheduledCampaign(id) {
            if (!confirm("Are you sure you want to cancel this scheduled trigger?")) return;
            try {
                const response = await fetch('/api/scheduled-campaigns/cancel', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ id: id })
                });
                const res = await response.json();
                if (res.ok) {
                    loadScheduledCampaigns();
                } else {
                    alert('Error cancelling scheduled trigger.');
                }
            } catch (err) {
                alert('Connection error: ' + err);
            }
        }

        // Initialize App on Window Load
        window.onload = function() {
            initData();
            loadDashboardData();
        };

        function renderActivityChart() {
            const chart = document.getElementById('activity-chart');
            if (!chart) return;
            const days = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];
            const sends = [120,95,180,210,145,88,170];
            const opens = [54,38,82,95,61,34,74];
            const maxVal = Math.max(...sends);
            chart.innerHTML = days.map((d,i) => `
                <div style="flex:1;display:flex;flex-direction:column;align-items:center;gap:2px;">
                    <div style="width:100%;display:flex;flex-direction:column;align-items:center;gap:2px;flex:1;justify-content:flex-end;">
                        <div style="width:65%;height:${Math.round((opens[i]/maxVal)*160)+4}px;background:linear-gradient(to top,#43e97b,#38f9d7);border-radius:3px 3px 0 0;opacity:0.85;" title="Opens: ${opens[i]}"></div>
                        <div style="width:100%;height:${Math.round((sends[i]/maxVal)*160)+4}px;background:linear-gradient(to top,#667eea,#764ba2);border-radius:3px 3px 0 0;" title="Sent: ${sends[i]}"></div>
                    </div>
                    <div style="font-size:9px;color:#94a3b8;margin-top:3px;">${d}</div>
                </div>`).join('');
        }
    </script>