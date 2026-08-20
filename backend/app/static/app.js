// AEGIS Dashboard Client Orchestration
class AegisDashboard {
    constructor() {
        this.currentTab = 'tab-dashboard';
        this.selectedHitlId = null;
        this.allEvents = []; // Cache all loaded events for detail retrieval
        this.init();
    }

    init() {
        // Tab switching setup
        document.querySelectorAll('.nav-item').forEach(item => {
            item.addEventListener('click', (e) => {
                e.preventDefault();
                const tabId = item.getAttribute('data-tab');
                this.switchTab(tabId);
            });
        });

        // Simulator form setup
        const simForm = document.getElementById('sim-form');
        if (simForm) {
            simForm.addEventListener('submit', (e) => {
                e.preventDefault();
                this.runSimulation();
            });
        }

        // Initial fetch
        this.refreshAll();

        // Start dynamic polling intervals
        setInterval(() => this.pollStatus(), 5000);
        setInterval(() => this.pollMetricsAndBadge(), 10000);
    }

    switchTab(tabId) {
        this.currentTab = tabId;
        
        // Update nav active states
        document.querySelectorAll('.nav-item').forEach(item => {
            if (item.getAttribute('data-tab') === tabId) {
                item.classList.add('active');
            } else {
                item.classList.remove('active');
            }
        });

        // Update pane active states
        document.querySelectorAll('.tab-pane').forEach(pane => {
            if (pane.id === tabId) {
                pane.classList.add('active');
            } else {
                pane.classList.remove('active');
            }
        });

        // Tab-specific loads
        if (tabId === 'tab-dashboard') {
            this.refreshMetrics();
            this.loadRecentEvents();
        } else if (tabId === 'tab-events') {
            this.loadEvents();
        } else if (tabId === 'tab-hitl') {
            this.loadHitlQueue();
        } else if (tabId === 'tab-policies') {
            this.loadPolicies();
        } else if (tabId === 'tab-sessions') {
            this.loadSessions();
        }
    }

    refreshAll() {
        this.pollStatus();
        this.refreshMetrics();
        this.loadRecentEvents();
        this.loadHitlQueue();
        this.loadPolicies();
        this.loadSessions();
    }

    // Health indicator check
    async pollStatus() {
        try {
            const res = await fetch('/health');
            const data = await res.json();
            const statusIndicator = document.getElementById('system-status');
            if (res.ok && data.status === 'healthy') {
                statusIndicator.className = 'status-indicator';
                statusIndicator.querySelector('.status-dot').style.backgroundColor = '#00875a';
                statusIndicator.querySelector('.status-text').textContent = 'Operational';
            } else {
                statusIndicator.className = 'status-indicator text-danger';
                statusIndicator.querySelector('.status-dot').style.backgroundColor = '#bf2600';
                statusIndicator.querySelector('.status-text').textContent = 'Degraded';
            }
        } catch (e) {
            const statusIndicator = document.getElementById('system-status');
            statusIndicator.className = 'status-indicator text-danger';
            statusIndicator.querySelector('.status-dot').style.backgroundColor = '#bf2600';
            statusIndicator.querySelector('.status-text').textContent = 'Offline';
        }
    }

    async pollMetricsAndBadge() {
        try {
            const res = await fetch('/api/v1/governance/metrics');
            if (res.ok) {
                const metrics = await res.json();
                
                // Fetch real hitl pending list size to be absolutely accurate
                const hitlRes = await fetch('/api/v1/hitl/pending');
                if (hitlRes.ok) {
                    const hitlList = await hitlRes.json();
                    const realPendingCount = hitlList.length;
                    
                    const badge = document.getElementById('hitl-badge');
                    if (badge) {
                        if (realPendingCount > 0) {
                            badge.textContent = realPendingCount;
                            badge.style.display = 'inline-block';
                        } else {
                            badge.style.display = 'none';
                        }
                    }
                    
                    const hitlMetric = document.getElementById('metric-hitl');
                    if (hitlMetric) {
                        hitlMetric.textContent = realPendingCount;
                    }
                }
            }
        } catch (e) {
            console.error("Metrics polling failed: ", e);
        }
    }

    async refreshMetrics() {
        try {
            const res = await fetch('/api/v1/governance/metrics');
            if (!res.ok) return;
            const metrics = await res.json();

            document.getElementById('metric-total').textContent = metrics.total_requests;
            document.getElementById('metric-allow').textContent = metrics.decision_counts.ALLOW || 0;
            document.getElementById('metric-block').textContent = metrics.decision_counts.BLOCK || 0;
            document.getElementById('metric-suspend').textContent = metrics.decision_counts.SUSPEND_SESSION || 0;
            
            // Poll for pending HITL count
            this.pollMetricsAndBadge();
        } catch (e) {
            console.error("Failed to load metrics: ", e);
        }
    }

    async loadRecentEvents() {
        try {
            const res = await fetch('/api/v1/governance/audit_events?limit=5');
            const tbody = document.querySelector('#dashboard-recent-table tbody');
            if (!res.ok) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Failed to load recent events.</td></tr>`;
                return;
            }
            const events = await res.json();
            this.cacheEvents(events);
            if (events.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No decisions logged yet.</td></tr>`;
                return;
            }

            tbody.innerHTML = events.map(e => {
                const rc = typeof e.runtime_context === 'string' ? JSON.parse(e.runtime_context) : (e.runtime_context || {});
                // Never fabricate risk: if risk was not calculated, show N/A explicitly
                const riskVal = (rc.risk_score !== undefined && rc.risk_score !== null)
                    ? `${rc.risk_score} (${rc.risk_level || 'N/A'})`
                    : (rc.risk_calculated === false ? 'N/A (Not Calculated)' : 'N/A');
                const anomalyVal = (rc.anomaly_score !== undefined && rc.anomaly_score !== null) ? `${rc.anomaly_score}` : 'N/A';
                
                const badgeClass = this.getBadgeClass(e.decision);
                const time = new Date(e.created_at).toLocaleTimeString();
                const toolName = e.tool_name || 'N/A';
                return `
                    <tr>
                        <td>${time}</td>
                        <td><code>${e.session_id}</code></td>
                        <td>${toolName}</td>
                        <td><span class="badge-decision" style="background:#f4f5f7; color:var(--text-color); font-weight:600; border:1px solid var(--border-color);">${riskVal}</span></td>
                        <td><code>${anomalyVal}</code></td>
                        <td><span class="badge-decision ${badgeClass}">${e.decision}</span></td>
                        <td>
                            <button class="btn btn-secondary" style="padding:4px 8px; font-size:11px;" onclick="window.app.viewEventDetail('${e.id}')">Inspect</button>
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (e) {
            console.error(e);
        }
    }

    cacheEvents(events) {
        events.forEach(e => {
            if (!this.allEvents.some(cached => cached.id === e.id)) {
                this.allEvents.push(e);
            }
        });
    }

    async loadEvents() {
        try {
            const res = await fetch('/api/v1/governance/audit_events?limit=50');
            const tbody = document.querySelector('#audit-table tbody');
            tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">Loading logs...</td></tr>`;
            
            if (!res.ok) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-danger">Failed to fetch logs.</td></tr>`;
                return;
            }
            const events = await res.json();
            this.cacheEvents(events);
            if (events.length === 0) {
                tbody.innerHTML = `<tr><td colspan="8" class="text-center text-muted">No governance logs.</td></tr>`;
                return;
            }

            tbody.innerHTML = events.map(e => {
                const rc = typeof e.runtime_context === 'string' ? JSON.parse(e.runtime_context) : (e.runtime_context || {});
                // Never fabricate risk: if risk was not calculated, show N/A explicitly
                const riskVal = (rc.risk_score !== undefined && rc.risk_score !== null)
                    ? `${rc.risk_score} (${rc.risk_level || 'N/A'})`
                    : (rc.risk_calculated === false ? 'N/A (Not Calculated)' : 'N/A');
                const anomalyVal = (rc.anomaly_score !== undefined && rc.anomaly_score !== null) ? `${rc.anomaly_score}` : 'N/A';

                const badgeClass = this.getBadgeClass(e.decision);
                const time = new Date(e.created_at).toLocaleString();
                const actionType = e.action_type || 'N/A';
                const toolName = e.tool_name || 'N/A';
                return `
                    <tr>
                        <td>${time}</td>
                        <td><code>${e.session_id}</code></td>
                        <td>${actionType}</td>
                        <td>${toolName}</td>
                        <td><span class="badge-decision" style="background:#f4f5f7; color:var(--text-color); font-weight:600; border:1px solid var(--border-color);">${riskVal}</span></td>
                        <td><code>${anomalyVal}</code></td>
                        <td><span class="badge-decision ${badgeClass}">${e.decision}</span></td>
                        <td>
                            <button class="btn btn-secondary" onclick="window.app.viewEventDetail('${e.id}')">Inspect</button>
                        </td>
                    </tr>
                `;
            }).join('');
        } catch (e) {
            console.error(e);
        }
    }

    async viewEventDetail(eventId) {
        try {
            // Always fetch the exact event by its primary key — never use in-memory cache as authoritative source.
            // The cache (allEvents) is only used for list rendering; the inspector must always call the API.
            const apiRes = await fetch(`/api/v1/governance/audit_events/${eventId}`);
            if (!apiRes.ok) {
                console.error(`[viewEventDetail] Failed to fetch event ${eventId}: HTTP ${apiRes.status}`);
                return;
            }
            const event = await apiRes.json();

            const modal = document.getElementById('audit-detail-modal');
            const body = document.getElementById('modal-body-content');
            
            const rc = typeof event.runtime_context === 'string' ? JSON.parse(event.runtime_context) : (event.runtime_context || {});
            
            // Risk display: never fabricate a value. Use N/A for uncalculated risk.
            const riskScore = (rc.risk_score !== undefined && rc.risk_score !== null)
                ? rc.risk_score
                : (rc.risk_calculated === false ? null : null);
            const riskLevel = rc.risk_level || null;
            const riskScoreDisplay = riskScore !== null ? `${riskScore} / 100` : 'N/A (Not Calculated)';
            const riskLevelDisplay = riskLevel || (rc.risk_calculated === false ? 'Not Calculated' : 'N/A');
            const riskBarWidth = riskScore !== null ? `${riskScore}%` : '0%';
            const riskColor = riskScore !== null
                ? (riskScore >= 70 ? 'var(--state-block-text)' : riskScore >= 40 ? '#ff8b00' : 'var(--state-allow-text)')
                : '#aaa';
            const anomalyScore = (rc.anomaly_score !== undefined && rc.anomaly_score !== null) ? rc.anomaly_score : null;
            const anomalyDisplay = anomalyScore !== null ? `${anomalyScore} / 100` : 'N/A';
            const anomalyBarWidth = anomalyScore !== null ? `${anomalyScore}%` : '0%';
            
            // Build risk factors
            let factorsHtml = '';
            if (rc.risk_factors && rc.risk_factors.length > 0) {
                factorsHtml = rc.risk_factors.map(f => `<li style="margin-bottom:4px; font-size:12px;">• ${f}</li>`).join('');
            } else if (rc.risk_calculated === false) {
                factorsHtml = '<li style="font-size:12px; color:var(--text-muted);">• Risk calculation was skipped (session suspended)</li>';
            } else {
                factorsHtml = '<li style="font-size:12px; color:var(--text-muted);">• No risk factors identified</li>';
            }

            // Build matched rules
            let rulesMatchedHtml = '';
            if (event.deciding_rule_id) {
                rulesMatchedHtml = `
                    <div style="background:#f4f5f7; border:1px solid #dfe1e6; padding:12px; border-radius:4px; margin-bottom:12px;">
                        <div style="display:flex; justify-content:space-between; font-weight:600; margin-bottom:4px;">
                            <span>Deciding Rule: <code>${event.deciding_rule_id}</code></span>
                            <span class="badge-decision ${this.getBadgeClass(event.decision)}">${event.decision}</span>
                        </div>
                        <p style="font-size:12px; color:var(--text-muted); margin:0;">${event.explanation || 'Rule condition matched runtime context parameters.'}</p>
                    </div>
                `;
            } else {
                rulesMatchedHtml = '<p style="font-size:12px; color:var(--text-muted);">No specific rule matched. Fallback default evaluation applied.</p>';
            }

            // Build behavioral analysis signals from server data
            let anomalySignalsHtml = '';
            const signals = rc.anomaly_signals || [];
            if (signals.length > 0) {
                anomalySignalsHtml = signals.map(s => `<li style="margin-bottom:4px; font-size:12px;">• ${s}</li>`).join('');
            } else {
                anomalySignalsHtml = '<li style="font-size:12px; color:var(--text-muted);">• No behavioral signals identified</li>';
            }

            const histCountDisplay = rc.historical_events_count !== undefined ? rc.historical_events_count : 'N/A';

            const behavioralHtml = `
                <div style="margin-top:10px; font-size:12px;">
                    <div><strong>Historical Events Analyzed:</strong> <code>${histCountDisplay}</code></div>
                    <div style="margin-top:8px;"><strong>Behavioral Signals:</strong></div>
                    <ul style="list-style:none; padding-left:0; margin-top:4px;">
                        ${anomalySignalsHtml}
                    </ul>
                </div>
            `;

            // Security trace flow items
            const dec = event.decision;
            const flowAllow = dec === 'ALLOW';
            const flowHitl = dec === 'REQUIRE_HITL';
            const flowBlock = dec === 'BLOCK' || dec === 'SUSPEND_SESSION';

            const traceProgressHtml = `
                <div style="display:flex; justify-content:space-between; align-items:center; background:#fafbfc; border:1px solid #dfe1e6; padding:12px 20px; border-radius:4px; margin-top:12px; font-size:11px; text-align:center;">
                    <div>
                        <div style="font-weight:600; color:#0052cc;">LLM Proposal</div>
                        <div style="color:var(--text-muted); font-size:9px; margin-top:2px;">Proposed Action</div>
                    </div>
                    <div style="color:var(--border-color); font-weight:bold;">&rarr;</div>
                    <div>
                        <div style="font-weight:600; color:#0052cc;">AEGIS Engine</div>
                        <div style="color:var(--text-muted); font-size:9px; margin-top:2px;">Context &amp; Score</div>
                    </div>
                    <div style="color:var(--border-color); font-weight:bold;">&rarr;</div>
                    <div>
                        <div style="font-weight:600; color:#0052cc;">Policy Engine</div>
                        <div style="color:${flowAllow ? '#006644' : flowHitl ? '#ff8b00' : '#bf2600'}; font-weight:700;">${dec}</div>
                    </div>
                    <div style="color:var(--border-color); font-weight:bold;">&rarr;</div>
                    <div>
                        <div style="font-weight:600; color:${flowAllow ? '#006644' : '#bf2600'};">${flowAllow ? 'Executed' : 'BLOCKED'}</div>
                        <div style="color:var(--text-muted); font-size:9px; margin-top:2px;">ToolGateway</div>
                    </div>
                </div>
            `;

            body.innerHTML = `
                <div style="font-size:11px; color:var(--text-muted); margin-bottom:10px;">
                    Request ID: <code>${event.request_id || 'N/A'}</code> &nbsp;|&nbsp; Event ID: <code>${event.id}</code>
                </div>
                <div style="display:grid; grid-template-columns:1fr 1fr; gap:20px; margin-bottom:20px;">
                    <!-- LEFT COLUMN -->
                    <div>
                        <div class="trace-card">
                            <span class="trace-card-title">1. Proposed Action <span class="trace-badge">LLM PROPOSAL</span></span>
                            <div style="font-size:13px; line-height:1.6;">
                                <div><strong>Tool:</strong> <code>${event.tool_name || 'N/A'}</code></div>
                                <div><strong>Action Type:</strong> <code>${event.action_type || 'N/A'}</code></div>
                                <div style="margin-top:6px;"><strong>Arguments:</strong></div>
                                <pre style="background:#f4f5f7; border:1px solid #dfe1e6; padding:6px; border-radius:4px; font-size:10px; font-family:monospace; margin-top:4px; max-height:80px; overflow-y:auto;">${JSON.stringify(event.proposed_action || {}, null, 2)}</pre>
                            </div>
                        </div>

                        <div class="trace-card">
                            <span class="trace-card-title">2. Runtime Context <span class="trace-badge">SERVER CALCULATED</span></span>
                            <div style="font-size:13px; line-height:1.6; display:grid; grid-template-columns:1fr 1fr; gap:6px;">
                                <div><strong>User Role:</strong> <code>${rc.user_role || 'N/A'}</code></div>
                                <div><strong>Data Classification:</strong> <code>${rc.session_data_classification || 'N/A'}</code></div>
                                <div><strong>Business Hours:</strong> <code>${rc.is_business_hours !== undefined ? (rc.is_business_hours ? 'YES' : 'NO') : 'N/A'}</code></div>
                                <div><strong>Previous Session Violations:</strong> <code>${rc.previous_violations_in_session !== undefined ? rc.previous_violations_in_session : 'N/A'}</code></div>
                            </div>
                        </div>

                        <div class="trace-card">
                            <span class="trace-card-title">3. Policy Evaluation <span class="trace-badge">POLICY DECISION</span></span>
                            ${rulesMatchedHtml}
                        </div>
                    </div>

                    <!-- RIGHT COLUMN -->
                    <div>
                        <div class="trace-card">
                            <span class="trace-card-title">4. Dynamic Risk Analysis <span class="trace-badge">SERVER CALCULATED</span></span>
                            <div>
                                <div style="display:flex; justify-content:space-between; font-weight:700;">
                                    <span>Risk Score: ${riskScoreDisplay}</span>
                                    <span style="color:${riskColor};">${riskLevelDisplay}</span>
                                </div>
                                <div class="progress-bar-container">
                                    <div class="progress-bar-fill" style="width:${riskBarWidth}; background-color:${riskColor}"></div>
                                </div>
                                <div style="margin-top:10px;"><strong>Explainable Risk Factors:</strong></div>
                                <ul style="list-style:none; padding-left:0; margin-top:4px;">
                                    ${factorsHtml}
                                </ul>
                            </div>
                        </div>

                        <div class="trace-card">
                            <span class="trace-card-title">5. Behavioral Analysis <span class="trace-badge">SERVER CALCULATED</span></span>
                            <div>
                                <div style="display:flex; justify-content:space-between; font-weight:700;">
                                    <span>Anomaly Score: ${anomalyDisplay}</span>
                                </div>
                                <div class="progress-bar-container">
                                    <div class="progress-bar-fill" style="width:${anomalyBarWidth}; background-color:${anomalyScore !== null && anomalyScore > 50 ? 'var(--state-block-text)' : 'var(--state-allow-text)'}"></div>
                                </div>
                                ${behavioralHtml}
                            </div>
                        </div>
                    </div>
                </div>

                <div style="border-top:1px solid #dfe1e6; padding-top:16px;">
                    <span class="metric-label" style="margin-bottom:6px;">6. Final Governance Result &amp; Execution Trail</span>
                    <div style="display:flex; align-items:center; justify-content:space-between; padding:12px 16px; border-radius:4px; background:${flowAllow ? 'var(--state-allow-bg)' : flowHitl ? 'var(--state-hitl-bg)' : 'var(--state-block-bg)'}; color:${flowAllow ? 'var(--state-allow-text)' : flowHitl ? 'var(--state-hitl-text)' : 'var(--state-block-text)'}; border:1px solid #dfe1e6;">
                        <div>
                            <strong style="font-size:14px; text-transform:uppercase;">${dec.replace('_', ' ')}</strong>
                            <p style="font-size:11px; margin:2px 0 0 0; color:var(--text-muted);">Deciding Rule ID: <code>${event.deciding_rule_id || 'default_allow'}</code></p>
                        </div>
                        <div style="text-align:right;">
                            <strong style="font-size:12px;">Tool Execution: ${flowAllow ? 'ALLOWED &amp; COMMITTED' : 'BLOCKED'}</strong>
                        </div>
                    </div>
                    ${traceProgressHtml}
                </div>
            `;
            
            modal.style.display = 'flex';
        } catch (e) {
            console.error('[viewEventDetail] Error:', e);
        }
    }

    closeModal() {
        document.getElementById('audit-detail-modal').style.display = 'none';
    }

    // HITL Queue Panel logic
    async loadHitlQueue() {
        try {
            const res = await fetch('/api/v1/hitl/pending');
            const container = document.getElementById('hitl-queue-container');
            container.innerHTML = `<div class="text-center text-muted p-20">Loading queue...</div>`;
            
            if (!res.ok) {
                container.innerHTML = `<div class="text-center text-danger p-20">Failed to load queue.</div>`;
                return;
            }
            const queue = await res.json();
            if (queue.length === 0) {
                container.innerHTML = `<div class="text-center text-muted p-20">No pending requests in queue.</div>`;
                this.resetHitlDetail();
                return;
            }

            container.innerHTML = queue.map(item => {
                const selectedClass = this.selectedHitlId === item.hitl_request_id ? 'selected' : '';
                const time = new Date(item.created_at).toLocaleTimeString();
                // tool is Optional[str] from backend — show 'Unknown tool' when null/empty
                const toolDisplay = (item.tool && item.tool.trim()) ? item.tool : 'Unknown tool';
                
                return `
                    <div class="hitl-item ${selectedClass}" onclick="window.app.selectHitlItem('${item.hitl_request_id}')">
                        <div class="hitl-item-header">
                            <span class="hitl-item-title">${toolDisplay}</span>
                            <span class="hitl-item-time">${time}</span>
                        </div>
                        <div class="text-muted" style="font-size:12px;">Session: <code>${item.session_id}</code></div>
                        <div style="display:flex; justify-content:space-between; margin-top:6px; align-items:center;">
                            <span class="badge-decision" style="background:#fffae6; color:#ff8b00; font-size:10px; font-weight:700;">PENDING HUMAN APPROVAL</span>
                            <span style="font-size:11px; font-weight:600; color:var(--text-muted);">Action: ${item.action_type || 'N/A'}</span>
                        </div>
                    </div>
                `;
            }).join('');

            // Automatically select item if selected
            if (this.selectedHitlId) {
                const exists = queue.some(i => i.hitl_request_id === this.selectedHitlId);
                if (exists) {
                    this.loadHitlDetail(this.selectedHitlId);
                } else {
                    this.resetHitlDetail();
                }
            }
        } catch (e) {
            console.error(e);
        }
    }

    async selectHitlItem(hitlId) {
        this.selectedHitlId = hitlId;
        // Rerender list to show selected state
        this.loadHitlQueue();
        this.loadHitlDetail(hitlId);
    }

    resetHitlDetail() {
        this.selectedHitlId = null;
        const detailPanel = document.getElementById('hitl-detail-container');
        detailPanel.style.opacity = '0.5';
        detailPanel.style.pointerEvents = 'none';
        document.getElementById('hitl-detail-content').innerHTML = `
            <p class="text-muted text-center p-20">Select an item from the queue to review.</p>
        `;
    }

    async loadHitlDetail(hitlId) {
        try {
            const res = await fetch(`/api/v1/hitl/${hitlId}`);
            if (!res.ok) return;
            const r = await res.json();

            const detailPanel = document.getElementById('hitl-detail-container');
            detailPanel.style.opacity = '1';
            detailPanel.style.pointerEvents = 'auto';

            const content = document.getElementById('hitl-detail-content');
            
            const proposedActionStr = JSON.stringify(r.proposed_action, null, 2);
            const rc = typeof r.runtime_context === 'string' ? JSON.parse(r.runtime_context) : (r.runtime_context || {});
            
            let factorsListHtml = '';
            if (rc.risk_factors && rc.risk_factors.length > 0) {
                factorsListHtml = rc.risk_factors.map(f => `<li>• ${f}</li>`).join('');
            } else {
                factorsListHtml = '<li>• No risk factors logged</li>';
            }

            content.innerHTML = `
                <div class="mb-16">
                    <span class="metric-label">Request ID</span>
                    <p style="font-family:monospace; font-size:12px;">${r.id}</p>
                </div>
                <div class="form-row mb-16">
                    <div>
                        <span class="metric-label">Session ID</span>
                        <p style="font-family:monospace;">${r.session_id}</p>
                    </div>
                    <div>
                        <span class="metric-label">Agent ID</span>
                        <p style="font-family:monospace;">${r.agent_id || 'N/A'}</p>
                    </div>
                </div>

                <div style="display:grid; grid-template-columns:1fr 1fr; gap:16px; margin-bottom:16px;">
                    <div style="border:1px solid var(--border-color); padding:12px; border-radius:4px; background:#fff;">
                        <span class="metric-label">Proposed Action <span class="trace-badge">LLM PROPOSAL</span></span>
                        <div style="font-size:12px; line-height:1.5;">
                            <div><strong>Tool:</strong> <code>${r.proposed_action ? r.proposed_action.tool : 'N/A'}</code></div>
                            <pre style="background:#fafbfc; border:1px solid #dfe1e6; padding:6px; border-radius:4px; font-size:10px; font-family:monospace; margin-top:6px; max-height:80px; overflow-y:auto;">${proposedActionStr}</pre>
                        </div>
                    </div>
                    
                    <div style="border:1px solid var(--border-color); padding:12px; border-radius:4px; background:#fff;">
                        <span class="metric-label">Risk &amp; Anomaly <span class="trace-badge">SERVER CALCULATED</span></span>
                        <div style="font-size:12px; line-height:1.5;">
                            <div><strong>Risk Score:</strong> <code>${rc.risk_score !== undefined ? rc.risk_score : 'N/A'} (${rc.risk_level || 'N/A'})</code></div>
                            <div><strong>Anomaly Score:</strong> <code>${rc.anomaly_score !== undefined ? rc.anomaly_score : 'N/A'}</code></div>
                            <div style="margin-top:6px; font-weight:600;">Factors:</div>
                            <ul style="list-style:none; padding-left:0; font-size:11px; color:var(--text-muted);">
                                ${factorsListHtml}
                            </ul>
                        </div>
                    </div>
                </div>
                
                <div class="mb-16">
                    <span class="metric-label">Revalidation Requirement</span>
                    <p style="font-size:12px; color:var(--text-muted); margin:0;">
                        This operation requires human review because of matching policy rule: <code>${r.policy_version_id || 'high_anomaly_write_hitl'}</code>.<br>
                        <strong>Secure Invariant:</strong> Revalidation will recalculate context and risk parameters at approval time.
                    </p>
                </div>
                
                <div class="mb-16" style="border-top:1px solid #dfe1e6; padding-top:16px;">
                    <span class="metric-label">Review Operator Action</span>
                    <div class="sim-form" style="margin-top:10px;">
                        <div class="form-group">
                            <label for="hitl-reviewer">Reviewer Name/ID</label>
                            <input type="text" id="hitl-reviewer" placeholder="Operator Name" value="SecOps Reviewer">
                        </div>
                        <div class="form-group">
                            <label for="hitl-reason">Review Notes / Reason</label>
                            <textarea id="hitl-reason" rows="2" placeholder="Approval/Denial justification notes..."></textarea>
                        </div>
                    </div>
                    <div class="form-buttons">
                        <button class="btn btn-primary" onclick="window.app.resolveHitl('${r.id}', 'approve')">Approve Request</button>
                        <button class="btn btn-danger" onclick="window.app.resolveHitl('${r.id}', 'deny')">Deny Request</button>
                    </div>
                </div>

                <!-- Revalidation Progression Tracker Area -->
                <div id="progression-tracker-area" style="display:none;"></div>
            `;
        } catch (e) {
            console.error(e);
        }
    }

    async resolveHitl(hitlId, action) {
        const reviewer = document.getElementById('hitl-reviewer').value.trim();
        const reason = document.getElementById('hitl-reason').value.trim();

        if (!reviewer) {
            alert("Reviewer Name is required.");
            return;
        }

        // Show progression tracker container
        const progressionArea = document.getElementById('progression-tracker-area');
        progressionArea.style.display = 'block';
        progressionArea.innerHTML = `
            <div class="revalidation-progression">
                <div style="font-weight:700; margin-bottom:12px; color:var(--primary-color);">Secure Revalidation Pipeline</div>
                <div class="progression-step active" id="step-lock">
                    <span class="progression-icon">1</span>
                    <span>PENDING RESOLUTION</span>
                </div>
                <div class="progression-step" id="step-query">
                    <span class="progression-icon">2</span>
                    <span>CURRENT CONTEXT CHECK</span>
                </div>
                <div class="progression-step" id="step-risk">
                    <span class="progression-icon">3</span>
                    <span>CURRENT RISK RE-CALCULATION</span>
                </div>
                <div class="progression-step" id="step-policy">
                    <span class="progression-icon">4</span>
                    <span>CURRENT POLICY RE-EVALUATION</span>
                </div>
                <div class="progression-step" id="step-gateway">
                    <span class="progression-icon">5</span>
                    <span>TOOLGATEWAY EXECUTION TRACE</span>
                </div>
            </div>
        `;

        const sleep = (ms) => new Promise(resolve => setTimeout(resolve, ms));

        try {
            // STEP 1
            await sleep(400);
            document.getElementById('step-lock').className = 'progression-step completed';
            document.getElementById('step-query').className = 'progression-step active';
            
            // STEP 2
            await sleep(400);
            document.getElementById('step-query').className = 'progression-step completed';
            document.getElementById('step-risk').className = 'progression-step active';
            
            // STEP 3
            await sleep(400);
            document.getElementById('step-risk').className = 'progression-step completed';
            document.getElementById('step-policy').className = 'progression-step active';
            
            // STEP 4
            await sleep(400);
            document.getElementById('step-policy').className = 'progression-step completed';
            document.getElementById('step-gateway').className = 'progression-step active';

            // Now perform actual request
            const endpoint = `/api/v1/hitl/${hitlId}/${action}`;
            const res = await fetch(endpoint, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ reviewer, reason })
            });
            let data = {};
            try {
                const text = await res.text();
                data = JSON.parse(text);
            } catch (e) {
                data = { detail: res.statusText || 'Server returned non-JSON response.' };
            }
            
            await sleep(400);
            if (res.ok && data.status === 'APPROVED') {
                document.getElementById('step-gateway').className = 'progression-step completed';
                alert(`Request successfully APPROVED. Tool executed: ${data.tool_execution?.tool || 'N/A'}`);
            } else if (res.ok && data.status === 'DENIED') {
                document.getElementById('step-gateway').className = 'progression-step failed';
                const govDecision = data.governance?.decision || 'N/A';
                alert(`Request resolved as DENIED.\nRevalidation decision: ${govDecision}\n${data.governance?.explanation || ''}`);
            } else {
                document.getElementById('step-gateway').className = 'progression-step failed';
                // Structured diagnostic logging — no PHI or credentials logged
                console.error('[resolveHitl] Resolution failed:', {
                    endpoint,
                    method: 'POST',
                    httpStatus: res.status,
                    hitlId,
                    action,
                    responseBody: data
                });
                const errMsg = data.detail || `HTTP ${res.status} — unexpected server error`;
                alert(`Resolution failed: ${errMsg}\n\nCheck browser console for details.`);
            }
            
            this.selectedHitlId = null;
            this.refreshAll();
        } catch (e) {
            console.error('[resolveHitl] Network error:', e);
            alert(`Network error: ${e.message}`);
        }
    }

    // Tab 4: Policies loading
    async loadPolicies() {
        try {
            const res = await fetch('/api/v1/governance/policies');
            const container = document.getElementById('policies-container');
            container.innerHTML = `<p class="text-muted">Loading active policies...</p>`;
            
            if (!res.ok) {
                container.innerHTML = `<p class="text-danger">Failed to load policies.</p>`;
                return;
            }
            const policies = await res.json();
            if (policies.length === 0) {
                container.innerHTML = `<p class="text-muted">No policy versions active in database.</p>`;
                return;
            }

            container.innerHTML = policies.map(p => {
                const rules = p.parsed_rules || {};
                const rulesCount = Object.keys(rules).length;
                
                // Construct rule list html
                let rulesHtml = '';
                for (const ruleId in rules) {
                    const rule = rules[ruleId];
                    
                    // Format conditions beautifully
                    let condStr = '';
                    if (rule.condition) {
                        if (rule.condition.all) {
                            condStr = rule.condition.all.map(c => `<code>${c.field} ${c.operator} ${JSON.stringify(c.value)}</code>`).join(' <strong style="color:#0052cc;">AND</strong> ');
                        } else if (rule.condition.any) {
                            condStr = rule.condition.any.map(c => `<code>${c.field} ${c.operator} ${JSON.stringify(c.value)}</code>`).join(' <strong style="color:#ff8b00;">OR</strong> ');
                        } else {
                            condStr = `<code>${rule.condition.field} ${rule.condition.operator} ${JSON.stringify(rule.condition.value)}</code>`;
                        }
                    } else {
                        condStr = '<span class="text-muted">Always matches</span>';
                    }

                    // Check overrides
                    let overrideBadge = '';
                    if (p.policy_id === 'hospital_policy' && ruleId === 'phi_high_risk_write_block') {
                        overrideBadge = '<span class="badge-decision badge-allow" style="font-size:9px; padding:2px 4px; margin-left:8px;">Overridden (doctor exempt)</span>';
                    } else if (p.policy_id === 'hospital_policy' && ruleId === 'phi_write_hitl') {
                        overrideBadge = '<span class="badge-decision badge-allow" style="font-size:9px; padding:2px 4px; margin-left:8px;">Overridden (doctor exempt)</span>';
                    }

                    rulesHtml += `
                        <div style="border-bottom:1px solid #dfe1e6; padding:12px 0; font-size:13px;">
                            <div style="display:flex; justify-content:space-between; align-items:center; font-weight:600; margin-bottom:4px;">
                                <span>Rule ID: <code>${ruleId}</code> ${overrideBadge}</span>
                                <span class="badge-decision ${this.getBadgeClass(rule.decision)}">${rule.decision}</span>
                            </div>
                            <div class="text-muted" style="font-size:12px; margin-bottom:6px;">${rule.description || 'No description.'} | Priority: <code>${rule.priority}</code></div>
                            <div style="background:#fafbfc; border:1px solid #dfe1e6; border-radius:4px; padding:6px 10px;">
                                <strong>Conditions:</strong> ${condStr}
                            </div>
                        </div>
                    `;
                }

                return `
                    <div class="policy-card">
                        <div class="policy-card-header">
                            <div>
                                <h3 style="font-size:16px; font-weight:600; color:var(--primary-color);">${p.policy_id.toUpperCase().replace('_', ' ')}</h3>
                                <span class="text-muted" style="font-size:11px;">Active Version: ${p.version} | Parent Policy: <code>${p.extends_id || 'None (Base)'}</code> | Rules: ${rulesCount}</span>
                            </div>
                        </div>
                        <div class="mb-16">
                            <span class="metric-label">Parsed Policy Rules</span>
                            <div style="max-height: 400px; overflow-y:auto; padding-right:8px;">
                                ${rulesHtml}
                            </div>
                        </div>
                        <details style="margin-top:12px; border-top:1px solid #dfe1e6; padding-top:12px;">
                            <summary style="cursor:pointer; font-size:12px; font-weight:600; color:var(--text-muted);">View Raw Policy YAML Definition</summary>
                            <pre class="policy-yaml-code" style="margin-top:8px;">${p.yaml_content}</pre>
                        </details>
                    </div>
                `;
            }).join('');
        } catch (e) {
            console.error(e);
        }
    }

    // Tab 5: Scenario presets loading
    async loadScenario(type) {
        const sessInput = document.getElementById('sim-session');
        const roleSelect = document.getElementById('sim-role');
        const classSelect = document.getElementById('sim-class');
        const violationSelect = document.getElementById('sim-violations');
        const bhSelect = document.getElementById('sim-hours');
        const messageText = document.getElementById('sim-message');
        const providerSelect = document.getElementById('sim-provider');

        // Generate a unique session ID per run to prevent state contamination between scenario executions.
        // Each click creates a completely fresh isolated session — no inherited violations or suspended status.
        const runUuid = crypto.randomUUID();
        sessInput.value = `sim-scenario-${type.toLowerCase()}-${runUuid}`;
        providerSelect.value = 'mock'; // Default offline keywords for simulator predictability

        if (type === 'A') {
            roleSelect.value = 'doctor';
            classSelect.value = 'internal';
            violationSelect.value = '0';
            if (bhSelect) bhSelect.value = 'true';
            messageText.value = 'Show client profiles in records';
        } else if (type === 'B') {
            roleSelect.value = 'nurse';
            classSelect.value = 'PHI';
            violationSelect.value = '0';
            if (bhSelect) bhSelect.value = 'false';
            messageText.value = 'Update patient diagnosis record P101';
        } else if (type === 'C') {
            roleSelect.value = 'nurse';
            classSelect.value = 'PHI';
            violationSelect.value = '2'; // High violations
            if (bhSelect) bhSelect.value = 'false';
            messageText.value = 'Delete patient record P101'; // Destructive deletion
        }

        // Auto trigger submit
        this.runSimulation();
    }

    // Tab 5: Simulator execution
    async runSimulation() {
        const sessionId = document.getElementById('sim-session').value.trim();
        const role = document.getElementById('sim-role').value;
        const classification = document.getElementById('sim-class').value;
        const violations = parseInt(document.getElementById('sim-violations').value, 10);
        const bhEl = document.getElementById('sim-hours');
        const bhVal = bhEl ? bhEl.value : 'auto';
        const isBh = bhVal === 'true' ? true : (bhVal === 'false' ? false : null);
        const message = document.getElementById('sim-message').value.trim();
        
        const output = document.getElementById('sim-results-output');
        output.innerHTML = `<div class="text-center text-muted p-20">Provisioning session and running governance engine...</div>`;

        if (!sessionId) {
            output.textContent = "Error: Session ID is required.";
            return;
        }

        try {
            // 1. Provision session with the exact configuration for this scenario
            const sessRes = await fetch('/api/v1/governance/sessions', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    session_id: sessionId,
                    user_role: role,
                    data_classification: classification,
                    previous_violations: violations,
                    is_business_hours: isBh
                })
            });
            
            if (!sessRes.ok) {
                let errDetail = 'Internal error';
                try {
                    const errData = await sessRes.json();
                    errDetail = errData.detail || errDetail;
                } catch (e) {
                    errDetail = sessRes.statusText || errDetail;
                }
                output.textContent = `Session provision failed: ${errDetail}`;
                return;
            }

            const providerEl = document.getElementById('sim-provider');
            const provider = providerEl ? providerEl.value : 'mock';

            let traceData = {};
            let chatOk = true;
            // 2. Execute agent loop or evaluation
            if (message) {
                // Execute real Agent Service chat endpoint
                const chatRes = await fetch('/api/v1/agent/chat', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: sessionId,
                        message: message,
                        llm_provider: provider
                    })
                });
                chatOk = chatRes.ok;
                try {
                    const text = await chatRes.text();
                    traceData = JSON.parse(text);
                } catch (e) {
                    traceData = { detail: chatRes.statusText || 'Server returned non-JSON response.' };
                }
            } else {
                // If no user message provided, run evaluate directly with a default read action
                const evalRes = await fetch('/api/v1/governance/evaluate', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({
                        session_id: sessionId,
                        action: {
                            tool: "read_patient",
                            arguments: { "patient_id": "P101" },
                            action_type: "read",
                            data_scope_size: 1
                        }
                    })
                });
                chatOk = evalRes.ok;
                try {
                    const text = await evalRes.text();
                    traceData = JSON.parse(text);
                } catch (e) {
                    traceData = { detail: evalRes.statusText || 'Server returned non-JSON response.' };
                }
            }

            if (!chatOk) {
                output.textContent = `Governance evaluation failed: ${traceData.detail || 'Internal error'}`;
                return;
            }

            // 3. Determine governance decision from response
            // Chat response nests governance under .governance; evaluate response has .decision at top level
            const isChat = !!traceData.governance;
            const dec = isChat ? (traceData.governance.decision || 'N/A') : (traceData.decision || 'N/A');
            const badgeClass = this.getBadgeClass(dec);
            
            // 4. Fetch the EXACT audit event by audit_event_id returned by the API.
            // This guarantees we display data from THIS SPECIFIC request — not a different event
            // for the same session_id, not a cached stale event.
            const auditEventId = traceData.audit_event_id || null;
            let riskScore = 'N/A';
            let riskLevel = 'N/A';
            let anomalyScore = 'N/A';
            
            if (auditEventId) {
                try {
                    const exactAuditRes = await fetch(`/api/v1/governance/audit_events/${auditEventId}`);
                    if (exactAuditRes.ok) {
                        const exactEvent = await exactAuditRes.json();
                        if (exactEvent.runtime_context) {
                            const rc = typeof exactEvent.runtime_context === 'string'
                                ? JSON.parse(exactEvent.runtime_context)
                                : exactEvent.runtime_context;
                            // Only display values that actually exist — never fallback to invented numbers
                            riskScore = (rc.risk_score !== undefined && rc.risk_score !== null)
                                ? rc.risk_score
                                : (rc.risk_calculated === false ? 'N/A (Not Calculated)' : 'N/A');
                            riskLevel = rc.risk_level || (rc.risk_calculated === false ? 'Not Calculated' : 'N/A');
                            anomalyScore = (rc.anomaly_score !== undefined && rc.anomaly_score !== null)
                                ? rc.anomaly_score
                                : 'N/A';
                        }
                    }
                } catch (auditErr) {
                    console.warn('[runSimulation] Could not fetch exact audit event:', auditErr);
                }
            } else {
                console.warn('[runSimulation] No audit_event_id in response — cannot fetch exact event for risk display.');
            }

            const toolName = traceData.proposed_action ? traceData.proposed_action.tool : 'N/A';
            const actionType = traceData.proposed_action ? traceData.proposed_action.action_type : 'N/A';
            const matchedRule = isChat
                ? (traceData.governance.matched_rules ? traceData.governance.matched_rules[0] : 'default_allow')
                : (traceData.deciding_rule_id || 'default_allow');
            const explanation = isChat
                ? (traceData.governance.explanation || 'Allowed to execute.')
                : (traceData.explanation || 'Allowed to execute.');
            const executed = isChat ? (traceData.tool_execution?.executed || false) : (dec === 'ALLOW');

            const riskScoreDisplay = riskScore === 'N/A' || riskScore === 'N/A (Not Calculated)' ? riskScore : `${riskScore} (${riskLevel})`;

            output.innerHTML = `
                <div style="font-family: inherit; font-size:13px; line-height:1.6;">
                    <div style="display:flex; justify-content:space-between; align-items:center; border-bottom:1px solid var(--border-color); padding-bottom:10px; margin-bottom:12px;">
                        <strong>Governance Response Result</strong>
                        <span class="badge-decision ${badgeClass}">${dec}</span>
                    </div>

                    <div style="margin-bottom:12px;">
                        <strong>1. AGENT INTERCEPTION TRACE</strong>
                        <div style="background:#fff; border:1px solid #dfe1e6; padding:10px; border-radius:4px; margin-top:4px;">
                            <strong>Tool:</strong> <code>${toolName}</code><br>
                            <strong>Action Type:</strong> <code>${actionType}</code>
                        </div>
                    </div>

                    <div style="margin-bottom:12px;">
                        <strong>2. SERVER-DERIVED CONTEXT &amp; METRICS</strong>
                        <div style="display:grid; grid-template-columns:1fr 1fr; gap:6px; background:#fff; border:1px solid #dfe1e6; padding:10px; border-radius:4px; margin-top:4px;">
                            <div>Risk Score: <code>${riskScoreDisplay}</code></div>
                            <div>Anomaly Score: <code>${anomalyScore}</code></div>
                            <div>Role: <code>${role}</code></div>
                            <div>Classification: <code>${classification}</code></div>
                        </div>
                    </div>

                    <div style="margin-bottom:12px;">
                        <strong>3. DECIDING ENGINE RESOLUTION</strong>
                        <div style="background:#fff; border:1px solid #dfe1e6; padding:10px; border-radius:4px; margin-top:4px;">
                            <div>Matched Rule: <code>${matchedRule}</code></div>
                            <div>Explanation: <span class="text-muted">${explanation}</span></div>
                        </div>
                    </div>

                    <div style="margin-bottom:12px;">
                        <strong>4. SECURE EXECUTION GATEWAY BOUNDARY</strong>
                        <div style="background:${dec === 'ALLOW' ? 'var(--state-allow-bg)' : dec === 'REQUIRE_HITL' ? 'var(--state-hitl-bg)' : '#ffebe6'}; color:${dec === 'ALLOW' ? 'var(--state-allow-text)' : dec === 'REQUIRE_HITL' ? 'var(--state-hitl-text)' : 'var(--state-block-text)'}; border:1px solid #dfe1e6; padding:10px; border-radius:4px; margin-top:4px; font-weight:600; text-align:center;">
                            ToolGateway Execution State: ${dec === 'ALLOW' && executed ? 'SUCCESS / EXECUTED' : dec === 'REQUIRE_HITL' ? 'HALTED — AWAITING HITL APPROVAL' : 'INTERCEPTED &amp; BLOCKED'}
                        </div>
                    </div>

                    ${auditEventId ? `
                    <div style="margin-bottom:12px; display:flex; gap:8px; align-items:center;">
                        <strong>Audit Event:</strong>
                        <code style="font-size:11px;">${auditEventId}</code>
                        <button class="btn btn-secondary" style="font-size:11px; padding:4px 10px;" onclick="window.app.viewEventDetail('${auditEventId}')">Inspect Event</button>
                    </div>` : ''}

                    <details style="margin-top:12px; border-top:1px solid #dfe1e6; padding-top:8px;">
                        <summary style="cursor:pointer; font-weight:600; color:var(--text-muted); font-size:11px;">View Full Raw JSON Intercept Payload</summary>
                        <pre style="background:#fafbfc; border:1px solid #dfe1e6; padding:8px; border-radius:4px; font-size:10px; font-family:monospace; margin-top:6px; max-height:180px; overflow-y:auto;">${JSON.stringify(traceData, null, 2)}</pre>
                    </details>
                </div>
            `;
            
            // Refresh database values on dashboard
            this.refreshAll();
        } catch (e) {
            output.textContent = `Network error: ${e.message}`;
        }
    }


    // Tab 6: Session list loading
    async loadSessions() {
        try {
            const res = await fetch('/api/v1/governance/sessions');
            const tbody = document.querySelector('#sessions-table tbody');
            tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">Loading sessions...</td></tr>`;
            
            if (!res.ok) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-danger">Failed to load sessions.</td></tr>`;
                return;
            }
            const sessions = await res.json();
            if (sessions.length === 0) {
                tbody.innerHTML = `<tr><td colspan="7" class="text-center text-muted">No session logs.</td></tr>`;
                return;
            }

            tbody.innerHTML = sessions.map(s => {
                const time = new Date(s.created_at).toLocaleString();
                const statusClass = s.status === 'suspended' ? 'badge-block' : 'badge-allow';
                return `
                    <tr style="cursor:pointer;" onclick="window.app.viewSessionDetails('${s.id}')">
                        <td><code>${s.id}</code></td>
                        <td>${s.agent_id}</td>
                        <td>${s.user_role}</td>
                        <td>${s.data_classification}</td>
                        <td>${s.previous_violations}</td>
                        <td><span class="badge-decision ${statusClass}">${s.status.toUpperCase()}</span></td>
                        <td>${time}</td>
                    </tr>
                `;
            }).join('');
        } catch (e) {
            console.error(e);
        }
    }

    async viewSessionDetails(sessionId) {
        try {
            const res = await fetch(`/api/v1/governance/sessions`);
            if (!res.ok) return;
            const sessions = await res.json();
            const session = sessions.find(s => s.id === sessionId);
            if (!session) return;

            const modal = document.getElementById('audit-detail-modal');
            const body = document.getElementById('modal-body-content');
            
            body.innerHTML = `
                <div class="trace-card">
                    <span class="trace-card-title">Session Overview <span class="trace-badge">DATABASE STATE</span></span>
                    <div style="display:grid; grid-template-columns:1fr 1fr; gap:10px; font-size:13px; line-height:1.6;">
                        <div><strong>Session ID:</strong> <code>${session.id}</code></div>
                        <div><strong>Agent ID:</strong> <code>${session.agent_id}</code></div>
                        <div><strong>User Role:</strong> <code>${session.user_role}</code></div>
                        <div><strong>Classification:</strong> <code>${session.data_classification}</code></div>
                        <div><strong>Violation Count:</strong> <code>${session.previous_violations} / 3</code></div>
                        <div><strong>Status:</strong> <span class="badge-decision ${session.status === 'suspended' ? 'badge-block' : 'badge-allow'}">${session.status.toUpperCase()}</span></div>
                    </div>
                </div>

                <div class="trace-card">
                    <span class="trace-card-title">Session Governance Logs <span class="trace-badge">AUDIT logs</span></span>
                    <p style="font-size:12px; color:var(--text-muted);">
                        To inspect specific decisions and risk scores of this session, close this view and use the <strong>Live Events</strong> table filter.
                    </p>
                </div>
            `;
            
            modal.style.display = 'flex';
        } catch (e) {
            console.error(e);
        }
    }

    getBadgeClass(decision) {
        switch (decision) {
            case 'ALLOW': return 'badge-allow';
            case 'BLOCK': return 'badge-block';
            case 'REQUIRE_HITL': return 'badge-hitl';
            case 'SUSPEND_SESSION': return 'badge-suspend';
            default: return '';
        }
    }
}

// Instantiate dashboard globally
window.app = new AegisDashboard();
