import { useCallback, useEffect, useMemo, useState } from 'react'
import { useApi, useWsListener } from '../hooks/useAuth'
import { PageStateView } from '../components/ui/PageState'
import { usePageContext } from '../hooks/usePageContext'
import { ChoiceGrid, SimpleBadge, SimpleKeyValue, SimpleSection } from '../features/security/simpleUi'
import { PhishingIcon } from '../components/ui/OverviewIcons'

const PROTECTION_LEVELS = [
  {
    value: 'off',
    label: 'Off',
    description: 'Disable tenant phishing detections and do not warn users.',
  },
  {
    value: 'detect_only',
    label: 'Detect only',
    description: 'Record suspicious sites for analysts without warning the user.',
  },
  {
    value: 'warn_only',
    label: 'Warn users',
    description: 'Show a warning when a site looks suspicious. Best default for most tenants.',
  },
  {
    value: 'soft_block',
    label: 'Soft block',
    description: 'Backend returns block guidance, but the agent still runs in post-navigation detect mode.',
  },
  {
    value: 'hard_block',
    label: 'Hard block',
    description: 'Use the highest policy severity even though the current agent cannot pre-block navigation.',
  },
]

const INCIDENT_STATES = ['open', 'in_review', 'resolved', 'false_positive']

function friendlyDate(value) {
  if (!value) return '-'
  try {
    return new Date(value).toLocaleString()
  } catch {
    return String(value)
  }
}

function severityTone(value) {
  if (value === 'critical' || value === 'high') return 'danger'
  if (value === 'medium') return 'warning'
  if (value === 'low') return 'info'
  return 'default'
}

function parseCommaList(value) {
  return value
    .split(',')
    .map((item) => item.trim().toLowerCase())
    .filter(Boolean)
}

function formatList(items) {
  if (!items?.length) return 'None'
  return items.join(', ')
}

function StatCard({ label, value, sub, tone = 'brand' }) {
  return (
    <div className={`stat-card machine-calm-card machine-calm-stat control-stat phishing-stat phishing-tone-${tone}`}>
      <div className="stat-label">{label}</div>
      <div className="stat-value">{value}</div>
      <div className="stat-sub">{sub}</div>
    </div>
  )
}

function ListManager({
  title,
  subtitle,
  value,
  onChange,
  onAdd,
  items,
  onRemove,
  placeholder,
  emptyText,
  buttonLabel,
}) {
  return (
    <SimpleSection title={title} subtitle={subtitle}>
      <div className="phishing-list-manager">
        <div className="phishing-input-row">
          <input
            className="input-field machine-calm-search control-field"
            placeholder={placeholder}
            value={value}
            onChange={(e) => onChange(e.target.value)}
            onKeyDown={(e) => {
              if (e.key === 'Enter') {
                e.preventDefault()
                onAdd()
              }
            }}
          />
          <button className="btn btn-outline machine-calm-btn" type="button" onClick={onAdd}>
            {buttonLabel}
          </button>
        </div>
        <div className="phishing-chip-wrap">
          {items.map((item) => (
            <button
              key={item.id || item.domain || item.url_pattern}
              type="button"
              className="control-chip phishing-chip-button"
              onClick={() => onRemove(item)}
              title="Remove"
            >
              {item.domain || item.url_pattern}
            </button>
          ))}
          {!items.length && <div className="phishing-empty-copy">{emptyText}</div>}
        </div>
      </div>
    </SimpleSection>
  )
}

function TokenEditor({ label, subtitle, value, onChange, placeholder }) {
  return (
    <SimpleSection title={label} subtitle={subtitle}>
      <div className="phishing-token-editor">
        <textarea
          className="input-field control-field phishing-textarea"
          placeholder={placeholder}
          value={value}
          onChange={(e) => onChange(e.target.value)}
        />
      </div>
    </SimpleSection>
  )
}

function IncidentListCard({ item, onOpen }) {
  return (
    <button type="button" className="phishing-incident-card" onClick={() => onOpen(item)}>
      <div className="phishing-incident-card-head">
        <div>
          <div className="phishing-incident-title">{item.title || item.domain || 'Suspicious site'}</div>
          <div className="phishing-incident-sub">{item.summary || item.url || 'Phishing activity detected.'}</div>
        </div>
        <div className="phishing-incident-badges">
          <SimpleBadge tone={severityTone(item.severity)}>{item.severity || 'medium'}</SimpleBadge>
          <SimpleBadge tone={item.warning_shown ? 'warning' : 'info'}>{item.warning_shown ? 'warned' : 'logged'}</SimpleBadge>
        </div>
      </div>
      <div className="phishing-incident-meta">
        <span><strong>Domain:</strong> {item.domain || '-'}</span>
        <span><strong>User:</strong> {item.actor_username || '-'}</span>
        <span><strong>Last seen:</strong> {friendlyDate(item.last_seen || item.timestamp)}</span>
      </div>
    </button>
  )
}

function DetailSection({ title, children }) {
  return (
    <div className="phishing-detail-section">
      <div className="phishing-detail-section-title">{title}</div>
      {children}
    </div>
  )
}

function IncidentDrawer({
  item,
  loading,
  detailState,
  setDetailState,
  onSave,
  onWhitelist,
  onClose,
  saving,
}) {
  if (!item) return null
  const metadata = item.metadata || {}
  const features = metadata.features || metadata.local_features || {}
  const reasonCodes = metadata.reason_codes || []

  return (
    <div className="activity-drawer-overlay" onClick={onClose}>
      <div className="activity-drawer phishing-drawer" onClick={(e) => e.stopPropagation()}>
        <div className="activity-drawer-header">
          <div>
            <div className="activity-drawer-title">{item.title || item.domain || 'Phishing incident'}</div>
            <div className="activity-drawer-subtitle">{item.url || item.summary || 'Detailed phishing incident context.'}</div>
          </div>
          <button type="button" className="btn btn-outline btn-sm" onClick={onClose}>Close</button>
        </div>

        <div className="activity-drawer-badges">
          <SimpleBadge tone={severityTone(item.severity)}>{item.severity || 'medium'}</SimpleBadge>
          <SimpleBadge tone="info">{item.state || 'open'}</SimpleBadge>
          <SimpleBadge tone={item.warning_shown ? 'warning' : 'default'}>{item.warning_shown ? 'warning shown' : 'logged only'}</SimpleBadge>
        </div>

        <div className="activity-drawer-body">
          {loading ? (
            <div className="control-empty">Loading incident details...</div>
          ) : (
            <div className="phishing-detail-grid">
              <DetailSection title="Incident overview">
                <SimpleKeyValue
                  items={[
                    { label: 'Domain', value: item.domain || '-' },
                    { label: 'URL', value: item.url || '-' },
                    { label: 'User', value: item.actor_username || '-' },
                    { label: 'Machine', value: item.machine_name || item.hostname || item.machine_id || '-' },
                    { label: 'Channel', value: item.channel || 'browser' },
                    { label: 'First seen', value: friendlyDate(item.first_seen || item.created_at) },
                    { label: 'Last seen', value: friendlyDate(item.last_seen || item.updated_at) },
                  ]}
                />
              </DetailSection>

              <DetailSection title="Response">
                <div className="phishing-form-grid">
                  <label className="phishing-field">
                    <span>State</span>
                    <select
                      className="input-field control-field"
                      value={detailState.state}
                      onChange={(e) => setDetailState((prev) => ({ ...prev, state: e.target.value }))}
                    >
                      {INCIDENT_STATES.map((option) => (
                        <option key={option} value={option}>{option}</option>
                      ))}
                    </select>
                  </label>
                  <label className="phishing-field">
                    <span>Assignee</span>
                    <input
                      className="input-field control-field"
                      value={detailState.assignee}
                      onChange={(e) => setDetailState((prev) => ({ ...prev, assignee: e.target.value }))}
                      placeholder="SOC analyst"
                    />
                  </label>
                  <label className="phishing-field phishing-field-wide">
                    <span>Analyst note</span>
                    <textarea
                      className="input-field control-field phishing-textarea"
                      value={detailState.note}
                      onChange={(e) => setDetailState((prev) => ({ ...prev, note: e.target.value }))}
                      placeholder="Document what happened or mark a false positive."
                    />
                  </label>
                </div>
              </DetailSection>

              <DetailSection title="Detection evidence">
                <div className="phishing-chip-wrap">
                  {reasonCodes.length
                    ? reasonCodes.map((code) => <span key={code} className="control-chip">{code}</span>)
                    : <span className="phishing-empty-copy">No reason codes were stored for this incident.</span>}
                </div>
                {!!Object.keys(features).length && (
                  <div className="phishing-feature-grid">
                    {Object.entries(features).map(([key, value]) => (
                      <div key={key} className="machine-calm-detail-item">
                        <div className="machine-calm-detail-label">{key.replaceAll('_', ' ')}</div>
                        <div className="machine-calm-detail-value">
                          {Array.isArray(value) ? value.join(', ') : typeof value === 'boolean' ? (value ? 'Yes' : 'No') : String(value)}
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </DetailSection>

              <DetailSection title="Timeline">
                <div className="phishing-timeline">
                  {(item.timeline || []).map((entry) => (
                    <div key={entry.id || `${entry.action}-${entry.created_at}`} className="phishing-timeline-item">
                      <div className="phishing-timeline-title">{entry.action}</div>
                      <div className="phishing-timeline-sub">{entry.actor || 'system'} · {friendlyDate(entry.created_at)}</div>
                    </div>
                  ))}
                  {!item.timeline?.length && <div className="phishing-empty-copy">No incident timeline yet.</div>}
                </div>
              </DetailSection>

              <DetailSection title="Notes">
                <div className="phishing-timeline">
                  {(item.notes || []).map((entry) => (
                    <div key={entry.id || `${entry.author}-${entry.created_at}`} className="phishing-timeline-item">
                      <div className="phishing-timeline-title">{entry.author || 'analyst'}</div>
                      <div className="phishing-timeline-copy">{entry.note || entry.content || '-'}</div>
                      <div className="phishing-timeline-sub">{friendlyDate(entry.created_at)}</div>
                    </div>
                  ))}
                  {!item.notes?.length && <div className="phishing-empty-copy">No analyst notes yet.</div>}
                </div>
              </DetailSection>
            </div>
          )}
        </div>

        <div className="activity-drawer-footer">
          <button type="button" className="btn btn-outline btn-sm" onClick={onWhitelist} disabled={!item.domain}>
            Whitelist domain
          </button>
          <button type="button" className="btn btn-primary btn-sm" onClick={onSave} disabled={saving}>
            {saving ? 'Saving...' : 'Save incident'}
          </button>
        </div>
      </div>
    </div>
  )
}

export default function Phishing() {
  const { get, put, post, del } = useApi()
  const { setPageContext, clearPageContext } = usePageContext()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [partialError, setPartialError] = useState('')
  const [policy, setPolicy] = useState(null)
  const [policies, setPolicies] = useState([])
  const [incidents, setIncidents] = useState([])
  const [events, setEvents] = useState([])
  const [stats, setStats] = useState({})
  const [trustedSites, setTrustedSites] = useState([])
  const [blockedSites, setBlockedSites] = useState([])
  const [savingPolicy, setSavingPolicy] = useState(false)
  const [selectedLevel, setSelectedLevel] = useState('warn_only')
  const [trustedSite, setTrustedSite] = useState('')
  const [blockedSite, setBlockedSite] = useState('')
  const [suspiciousTldsInput, setSuspiciousTldsInput] = useState('')
  const [brandWatchlistInput, setBrandWatchlistInput] = useState('')
  const [selectedIncidentId, setSelectedIncidentId] = useState(null)
  const [incidentDetail, setIncidentDetail] = useState(null)
  const [incidentLoading, setIncidentLoading] = useState(false)
  const [incidentSaving, setIncidentSaving] = useState(false)
  const [detailState, setDetailState] = useState({ state: 'open', assignee: '', note: '' })

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    setPartialError('')
    try {
      const [policyRes, policiesRes, incidentsRes, eventsRes, whitelistRes, blacklistRes] = await Promise.allSettled([
        get('/api/phishing/policy/effective'),
        get('/api/phishing/policies'),
        get('/api/phishing/incidents?limit=12'),
        get('/api/phishing/events?limit=12'),
        get('/api/phishing/whitelists'),
        get('/api/phishing/blacklists'),
      ])

      const failures = []
      let loadedSections = 0

      if (policyRes.status === 'fulfilled') {
        loadedSections += 1
        const nextPolicy = policyRes.value || {}
        setPolicy(nextPolicy)
        setSelectedLevel(nextPolicy.rollout_mode || 'warn_only')
        setSuspiciousTldsInput((nextPolicy.suspicious_tlds || []).join(', '))
        setBrandWatchlistInput((nextPolicy.brand_watchlist || []).join(', '))
      } else {
        failures.push('policy')
      }

      if (policiesRes.status === 'fulfilled') {
        loadedSections += 1
        setPolicies(policiesRes.value?.policies || [])
      } else {
        setPolicies([])
        failures.push('policy history')
      }

      if (incidentsRes.status === 'fulfilled') {
        loadedSections += 1
        setIncidents(incidentsRes.value?.items || [])
        setStats(incidentsRes.value?.stats || {})
      } else {
        setIncidents([])
        setStats({})
        failures.push('incidents')
      }

      if (eventsRes.status === 'fulfilled') {
        loadedSections += 1
        setEvents(eventsRes.value?.events || [])
      } else {
        setEvents([])
        failures.push('event feed')
      }

      if (whitelistRes.status === 'fulfilled') {
        setTrustedSites(whitelistRes.value?.items || [])
      } else {
        setTrustedSites([])
        failures.push('whitelist')
      }

      if (blacklistRes.status === 'fulfilled') {
        setBlockedSites(blacklistRes.value?.items || [])
      } else {
        setBlockedSites([])
        failures.push('blacklist')
      }

      if (!loadedSections) {
        throw new Error('Failed to load phishing protection')
      }
      if (failures.length) {
        setPartialError(`Some phishing sections could not load: ${failures.join(', ')}`)
      }
    } catch (err) {
      setError(err?.message || 'Failed to load phishing protection')
    } finally {
      setLoading(false)
    }
  }, [get])

  useEffect(() => { load() }, [load])

  useEffect(() => {
    setPageContext('Tenant Scope', 'Phishing Protection')
    return () => clearPageContext()
  }, [setPageContext, clearPageContext])

  const openIncident = useCallback(async (incident) => {
    if (!incident?.id) return
    setSelectedIncidentId(incident.id)
    setIncidentLoading(true)
    setDetailState({
      state: incident.state || 'open',
      assignee: incident.assignee || '',
      note: '',
    })
    try {
      const detail = await get(`/api/phishing/incidents/${incident.id}`)
      setIncidentDetail(detail)
      setDetailState({
        state: detail.state || 'open',
        assignee: detail.assignee || '',
        note: '',
      })
    } catch {
      setIncidentDetail(incident)
    } finally {
      setIncidentLoading(false)
    }
  }, [get])

  useWsListener(useCallback((msg) => {
    if (msg.type === 'phishing_update' && msg.data) {
      setEvents((prev) => [msg.data, ...prev.filter((item) => item.id !== msg.data.id)].slice(0, 12))
    }
    if (msg.type === 'phishing_incident_update' && msg.data) {
      setIncidents((prev) => [msg.data, ...prev.filter((item) => item.id !== msg.data.id)].slice(0, 12))
      if (selectedIncidentId && msg.data.id === selectedIncidentId) {
        setIncidentDetail((prev) => ({ ...(prev || {}), ...msg.data }))
      }
    }
  }, [selectedIncidentId]))

  const savePolicy = async () => {
    setSavingPolicy(true)
    try {
      await put('/api/phishing/policy', {
        name: 'Tenant Phishing Protection',
        description: `Guide-aligned phishing policy in ${selectedLevel} mode.`,
        scope: 'tenant_override',
        status: 'published',
        priority: 100,
        rollout_mode: selectedLevel,
        intel_mode: policy?.intel_mode || 'intel_plus_heuristics',
        phishing_enabled: selectedLevel !== 'off',
        protected_channels: policy?.protected_channels || ['browser', 'download'],
        severity_thresholds: policy?.severity_thresholds || { medium: 55, high: 75, critical: 90 },
        suspicious_tlds: parseCommaList(suspiciousTldsInput),
        brand_watchlist: parseCommaList(brandWatchlistInput),
        allowlists: {
          domains: trustedSites.map((item) => item.domain).filter(Boolean),
          apps: policy?.allowlists?.apps || [],
          users: policy?.allowlists?.users || [],
          paths: policy?.allowlists?.paths || [],
        },
        download_risk_rules: policy?.download_risk_rules || { dangerous_extensions: ['exe', 'msi', 'bat'], warn_unknown_downloads: true },
        evidence_controls: policy?.evidence_controls || { capture_title: true, store_masked_indicators: true, store_url: true },
        config: policy?.config || {},
      })
      await load()
    } finally {
      setSavingPolicy(false)
    }
  }

  const addTrustedSite = async () => {
    const domain = trustedSite.trim().toLowerCase()
    if (!domain || trustedSites.some((item) => item.domain === domain)) {
      setTrustedSite('')
      return
    }
    setTrustedSite('')
    await post('/api/phishing/whitelists', { domain, reason: 'Trusted tenant destination' })
    await load()
  }

  const removeTrustedSite = async (item) => {
    if (!item?.id) return
    await del(`/api/phishing/whitelists/${item.id}`)
    await load()
  }

  const addBlockedSite = async () => {
    const domain = blockedSite.trim().toLowerCase()
    if (!domain || blockedSites.some((item) => item.domain === domain || item.url_pattern === domain)) {
      setBlockedSite('')
      return
    }
    setBlockedSite('')
    const payload = domain.includes('/') ? { url_pattern: domain, reason: 'Known phishing destination' } : { domain, reason: 'Known phishing destination' }
    await post('/api/phishing/blacklists', payload)
    await load()
  }

  const removeBlockedSite = async (item) => {
    if (!item?.id) return
    await del(`/api/phishing/blacklists/${item.id}`)
    await load()
  }

  const saveIncident = async () => {
    if (!selectedIncidentId) return
    setIncidentSaving(true)
    try {
      const updated = await put(`/api/phishing/incidents/${selectedIncidentId}`, {
        state: detailState.state,
        assignee: detailState.assignee,
        note: detailState.note,
      })
      setIncidentDetail(updated)
      setDetailState((prev) => ({ ...prev, note: '' }))
      await load()
    } finally {
      setIncidentSaving(false)
    }
  }

  const whitelistIncident = async () => {
    const domain = incidentDetail?.domain?.trim().toLowerCase()
    if (!domain) return
    await post('/api/phishing/whitelists', { domain, reason: `Added from incident ${incidentDetail.id}` })
    await load()
  }

  const topDomain = stats?.top_domains?.[0]?.domain || 'No active campaigns'
  const warnedCount = stats?.warned_users || 0
  const incidentsOpen = stats?.by_state?.open || 0
  const policyMode = PROTECTION_LEVELS.find((item) => item.value === selectedLevel)?.label || 'Warn users'
  const pageState = loading ? 'loading' : error ? 'error' : partialError ? 'partial' : 'ready'
  const hasData = incidents.length > 0 || events.length > 0 || trustedSites.length > 0 || blockedSites.length > 0

  const summaryItems = useMemo(() => [
    { label: 'Mode', value: policyMode },
    { label: 'Coverage', value: formatList(policy?.protected_channels || ['browser']) },
    { label: 'Suspicious TLDs', value: formatList(parseCommaList(suspiciousTldsInput)) },
    { label: 'Brand watchlist', value: formatList(parseCommaList(brandWatchlistInput)) },
    { label: 'Policy versions', value: String(policies.length || 1) },
  ], [policyMode, policy?.protected_channels, suspiciousTldsInput, brandWatchlistInput, policies.length])

  return (
    <div className="fade-in control-shell">
      <div className="page-header machine-calm-header analytics-hero control-hero">
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <PhishingIcon size={24} />
          </div>
          <div>
            <div className="page-title">Phishing Protection</div>
            <div className="page-subtitle">Guide-aligned phishing policy, incident review, and trust controls for this tenant.</div>
          </div>
        </div>
        <div className="control-actions">
          <button className="btn btn-outline machine-calm-btn btn-sm" onClick={load}>Refresh</button>
          <SimpleBadge tone="info">{policyMode}</SimpleBadge>
        </div>
      </div>

      <PageStateView
        state={pageState}
        title={error ? 'Unable to load phishing protection' : partialError ? 'Phishing loaded with missing sections' : 'No phishing activity yet'}
        message={error || partialError || 'This tenant has no recent phishing detections yet.'}
        onRetry={load}
      >
        <div className="control-grid">
          <div className="control-banner">
            The backend can return `soft_block` or `hard_block` decisions, but the current agent still detects after navigation. Use these modes to raise analyst urgency, not to promise pre-navigation blocking.
          </div>

          {!hasData && (
            <div className="control-empty">
              No phishing activity yet. Start with policy mode, suspicious TLDs, and trust lists below.
            </div>
          )}

          <div className="stats-grid phishing-stats-grid">
            <StatCard label="Open incidents" value={incidentsOpen} sub="Incidents waiting for analyst action" tone="danger" />
            <StatCard label="Warnings shown" value={warnedCount} sub="Users who saw a phishing warning" tone="brand" />
            <StatCard label="Top domain" value={topDomain} sub="Most common suspicious destination" tone="sand" />
            <StatCard label="Blocked destinations" value={blockedSites.length} sub="Known bad domains or URL patterns" tone="slate" />
          </div>

          <SimpleSection
            title="Response mode"
            subtitle="Choose how the tenant policy should react when the phishing engine escalates a site"
            action={<button className="btn btn-primary btn-sm" onClick={savePolicy} disabled={savingPolicy}>{savingPolicy ? 'Saving...' : 'Save policy'}</button>}
          >
            <ChoiceGrid value={selectedLevel} onChange={setSelectedLevel} options={PROTECTION_LEVELS} />
          </SimpleSection>

          <div className="grid-2">
            <TokenEditor
              label="Suspicious TLD watchlist"
              subtitle="Comma-separated TLDs that should increase phishing suspicion."
              value={suspiciousTldsInput}
              onChange={setSuspiciousTldsInput}
              placeholder="zip, click, work, top"
            />
            <TokenEditor
              label="Brand watchlist"
              subtitle="Comma-separated brands that should trigger lookalike checks."
              value={brandWatchlistInput}
              onChange={setBrandWatchlistInput}
              placeholder="microsoft, google, okta, adobe"
            />
          </div>

          <div className="grid-2">
            <ListManager
              title="Whitelist"
              subtitle="Domains that should not trigger tenant phishing warnings."
              value={trustedSite}
              onChange={setTrustedSite}
              onAdd={addTrustedSite}
              items={trustedSites}
              onRemove={removeTrustedSite}
              placeholder="login.company.com"
              emptyText="No trusted domains added yet."
              buttonLabel="Add domain"
            />
            <ListManager
              title="Blacklist"
              subtitle="Known bad domains or URL patterns to force a malicious decision."
              value={blockedSite}
              onChange={setBlockedSite}
              onAdd={addBlockedSite}
              items={blockedSites}
              onRemove={removeBlockedSite}
              placeholder="phish.bad or https://bad.example/login"
              emptyText="No blocked destinations added yet."
              buttonLabel="Add block"
            />
          </div>

          <div className="grid-2">
            <SimpleSection title="Policy summary" subtitle="Plain-English view of the current tenant phishing posture">
              <SimpleKeyValue items={summaryItems} />
            </SimpleSection>

            <SimpleSection title="Guide flow now active" subtitle="How the upgraded frontend maps to the phishing workflow">
              <div className="phishing-guide-steps">
                <div>1. Agent does first-pass URL heuristics and asks the backend for a final verdict when risk is high.</div>
                <div>2. Analysts tune suspicious TLDs, watch brands, and trust lists here.</div>
                <div>3. Incidents open below with evidence, notes, and timeline so the SOC can close or whitelist quickly.</div>
              </div>
            </SimpleSection>
          </div>

          <SimpleSection title="Recent incidents" subtitle="Open the drawer to review evidence, notes, and timeline">
            <div className="phishing-incident-list">
              {incidents.map((item) => (
                <IncidentListCard key={item.id || `${item.domain}-${item.last_seen}`} item={item} onOpen={openIncident} />
              ))}
              {!incidents.length && <div className="phishing-empty-copy">No recent phishing incidents.</div>}
            </div>
          </SimpleSection>

          <SimpleSection title="Detection feed" subtitle="Latest phishing detections from the tenant event stream">
            <div style={{ overflowX: 'auto' }}>
              <table className="data-table machine-calm-table">
                <thead>
                  <tr>
                    <th>Time</th>
                    <th>Site</th>
                    <th>Verdict</th>
                    <th>Warning</th>
                    <th>User</th>
                    <th>Machine</th>
                  </tr>
                </thead>
                <tbody>
                  {events.map((item) => {
                    const metadata = item.metadata || {}
                    const verdict = metadata.verdict || item.verdict || 'suspicious'
                    return (
                      <tr key={item.id || `${item.timestamp}-${item.domain}`} onClick={() => item.incident_id && openIncident({ id: item.incident_id, ...item })} className="phishing-table-row">
                        <td>{friendlyDate(item.timestamp)}</td>
                        <td>{item.domain || item.url || '-'}</td>
                        <td><SimpleBadge tone={verdict === 'malicious' ? 'danger' : 'warning'}>{verdict}</SimpleBadge></td>
                        <td><SimpleBadge tone={item.warning_shown ? 'warning' : 'info'}>{item.warning_shown ? 'shown' : 'logged'}</SimpleBadge></td>
                        <td>{item.actor_username || '-'}</td>
                        <td>{item.machine_name || item.hostname || item.machine_id || '-'}</td>
                      </tr>
                    )
                  })}
                  {!events.length && (
                    <tr>
                      <td colSpan={6} style={{ textAlign: 'center', color: 'var(--text-3)' }}>No phishing detections yet.</td>
                    </tr>
                  )}
                </tbody>
              </table>
            </div>
          </SimpleSection>
        </div>
      </PageStateView>

      <IncidentDrawer
        item={incidentDetail}
        loading={incidentLoading}
        detailState={detailState}
        setDetailState={setDetailState}
        onSave={saveIncident}
        onWhitelist={whitelistIncident}
        onClose={() => {
          setSelectedIncidentId(null)
          setIncidentDetail(null)
        }}
        saving={incidentSaving}
      />
    </div>
  )
}
