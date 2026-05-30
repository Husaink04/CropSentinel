import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePlatformApi } from './PlatformLayout'
import { ChoiceGrid, SimpleBadge, SimpleKeyValue, SimpleSection } from '../features/security/simpleUi'

const PROTECTION_LEVELS = [
  {
    value: 'off',
    label: 'Off',
    description: 'Disable the global phishing baseline for newly inherited tenants.',
  },
  {
    value: 'detect_only',
    label: 'Detect only',
    description: 'Record suspicious activity without warning users in inherited tenants.',
  },
  {
    value: 'warn_only',
    label: 'Warn users',
    description: 'Recommended baseline for most tenants.',
  },
  {
    value: 'soft_block',
    label: 'Soft block',
    description: 'Raise the backend decision to block guidance while the agent remains detect-after-navigation.',
  },
  {
    value: 'hard_block',
    label: 'Hard block',
    description: 'Strongest inherited policy, still subject to current agent enforcement limits.',
  },
]

const CHANNEL_OPTIONS = ['browser', 'download', 'desktop_link_open', 'email_client_open']

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

function BaselineListEditor({ title, subtitle, value, onChange, placeholder }) {
  return (
    <SimpleSection title={title} subtitle={subtitle}>
      <textarea
        className="input-field control-field phishing-textarea"
        value={value}
        onChange={(e) => onChange(e.target.value)}
        placeholder={placeholder}
      />
    </SimpleSection>
  )
}

export default function PlatformPhishing() {
  const api = usePlatformApi()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [baseline, setBaseline] = useState(null)
  const [selectedLevel, setSelectedLevel] = useState('warn_only')
  const [saving, setSaving] = useState(false)
  const [suspiciousTldsInput, setSuspiciousTldsInput] = useState('')
  const [brandWatchlistInput, setBrandWatchlistInput] = useState('')
  const [baselineAllowlistInput, setBaselineAllowlistInput] = useState('')
  const [protectedChannels, setProtectedChannels] = useState(['browser', 'download'])

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await api.get('/api/platform/phishing/baseline')
      const policy = (data?.policies || []).find((item) => item.scope === 'platform_baseline') || data?.policies?.[0] || null
      setBaseline(policy)
      setSelectedLevel(policy?.rollout_mode || 'warn_only')
      setSuspiciousTldsInput((policy?.suspicious_tlds || []).join(', '))
      setBrandWatchlistInput((policy?.brand_watchlist || []).join(', '))
      setBaselineAllowlistInput((policy?.allowlists?.domains || []).join(', '))
      setProtectedChannels(policy?.protected_channels || ['browser', 'download'])
    } catch (err) {
      setError(err?.message || 'Failed to load platform phishing baseline')
      setBaseline(null)
    } finally {
      setLoading(false)
    }
  }, [api])

  useEffect(() => { load() }, [load])

  const toggleChannel = (channel) => {
    setProtectedChannels((prev) => (
      prev.includes(channel)
        ? prev.filter((item) => item !== channel)
        : [...prev, channel]
    ))
  }

  const summary = useMemo(() => [
    { label: 'Baseline mode', value: PROTECTION_LEVELS.find((item) => item.value === selectedLevel)?.label || 'Warn users' },
    { label: 'Protected channels', value: formatList(protectedChannels) },
    { label: 'Suspicious TLDs', value: formatList(parseCommaList(suspiciousTldsInput)) },
    { label: 'Brand watchlist', value: formatList(parseCommaList(brandWatchlistInput)) },
    { label: 'Inherited trusted domains', value: formatList(parseCommaList(baselineAllowlistInput)) },
    { label: 'Policy version', value: String(baseline?.version || 1) },
  ], [selectedLevel, protectedChannels, suspiciousTldsInput, brandWatchlistInput, baselineAllowlistInput, baseline?.version])

  const save = async () => {
    setSaving(true)
    try {
      await api.put('/api/platform/phishing/policy', {
        name: 'Platform Baseline Phishing Policy',
        description: `Guide-aligned platform baseline in ${selectedLevel} mode.`,
        scope: 'platform_baseline',
        status: 'published',
        priority: 1000,
        rollout_mode: selectedLevel,
        intel_mode: baseline?.intel_mode || 'intel_plus_heuristics',
        phishing_enabled: selectedLevel !== 'off',
        protected_channels: protectedChannels,
        severity_thresholds: baseline?.severity_thresholds || { medium: 55, high: 75, critical: 90 },
        suspicious_tlds: parseCommaList(suspiciousTldsInput),
        brand_watchlist: parseCommaList(brandWatchlistInput),
        allowlists: {
          domains: parseCommaList(baselineAllowlistInput),
          apps: baseline?.allowlists?.apps || [],
          users: baseline?.allowlists?.users || [],
          paths: baseline?.allowlists?.paths || [],
        },
        download_risk_rules: baseline?.download_risk_rules || { dangerous_extensions: ['exe', 'msi', 'bat'], warn_unknown_downloads: true },
        evidence_controls: baseline?.evidence_controls || { capture_title: true, store_masked_indicators: true, store_url: true },
        config: baseline?.config || {},
      })
      await load()
    } finally {
      setSaving(false)
    }
  }

  if (loading) {
    return (
      <div className="loading-center" style={{ minHeight: 320 }}>
        <div className="spinner" style={{ width: 28, height: 28 }} />
      </div>
    )
  }

  if (error) {
    return (
      <div className="empty-state">
        <div className="empty-state-title">Unable to load platform phishing</div>
        <div className="empty-state-sub">{error}</div>
        <button className="btn btn-outline btn-sm" onClick={load}>Retry</button>
      </div>
    )
  }

  return (
    <div className="control-shell">
      <div className="platform-hero machine-calm-header control-hero">
        <div>
          <h1>Platform Phishing Baseline</h1>
          <p>Set the inherited phishing posture for every tenant before tenant-level overrides apply.</p>
        </div>
        <SimpleBadge tone="info">Baseline</SimpleBadge>
      </div>

      <div className="control-banner">
        This baseline controls inherited phishing behavior, suspicious TLDs, and brand lookalike detection. Tenant-specific whitelist and blacklist exceptions are still managed inside each tenant workspace.
      </div>

      <SimpleSection
        title="Inherited response mode"
        subtitle="Choose how the global phishing baseline should classify and respond to suspicious sites"
        action={<button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving...' : 'Save baseline'}</button>}
      >
        <ChoiceGrid value={selectedLevel} onChange={setSelectedLevel} options={PROTECTION_LEVELS} />
      </SimpleSection>

      <SimpleSection title="Protected channels" subtitle="Channels that every tenant inherits unless they override locally">
        <div className="phishing-chip-wrap">
          {CHANNEL_OPTIONS.map((channel) => {
            const active = protectedChannels.includes(channel)
            return (
              <button
                key={channel}
                type="button"
                className={`control-chip phishing-chip-button${active ? ' phishing-chip-active' : ''}`}
                onClick={() => toggleChannel(channel)}
              >
                {channel}
              </button>
            )
          })}
        </div>
      </SimpleSection>

      <div className="grid-2">
        <BaselineListEditor
          title="Suspicious TLD watchlist"
          subtitle="Comma-separated TLDs that should increase inherited phishing risk."
          value={suspiciousTldsInput}
          onChange={setSuspiciousTldsInput}
          placeholder="zip, click, work, top"
        />
        <BaselineListEditor
          title="Brand watchlist"
          subtitle="Brands that should trigger lookalike detection across tenants."
          value={brandWatchlistInput}
          onChange={setBrandWatchlistInput}
          placeholder="microsoft, google, okta, adobe"
        />
      </div>

      <BaselineListEditor
        title="Inherited trusted domains"
        subtitle="Domains that should be trusted by default before tenant-specific exceptions are added."
        value={baselineAllowlistInput}
        onChange={setBaselineAllowlistInput}
        placeholder="login.microsoftonline.com, accounts.google.com"
      />

      <div className="grid-2">
        <SimpleSection title="Baseline summary" subtitle="What every tenant inherits from the platform">
          <SimpleKeyValue items={summary} />
        </SimpleSection>

        <SimpleSection title="Current limitation" subtitle="Important implementation note">
          <div className="phishing-guide-steps">
            <div>1. Platform baseline can raise phishing verdicts and warning behavior for all tenants.</div>
            <div>2. The current agent still detects after browser activity instead of blocking navigation before page load.</div>
            <div>3. Tenant pages handle domain-specific whitelist and blacklist exceptions on top of this baseline.</div>
          </div>
        </SimpleSection>
      </div>
    </div>
  )
}
