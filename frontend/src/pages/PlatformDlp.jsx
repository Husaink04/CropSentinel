import { useCallback, useEffect, useMemo, useState } from 'react'
import { usePlatformApi } from './PlatformLayout'
import { ChoiceGrid, SimpleBadge, SimpleKeyValue, SimpleSection } from '../features/security/simpleUi'

const PROTECTION_LEVELS = [
  {
    value: 'monitor_only',
    label: 'Watch only',
    description: 'Keep the baseline quiet and only record sensitive activity.',
  },
  {
    value: 'soft_block',
    label: 'Recommended',
    description: 'Warn users for risky file movement. Safe default for most tenants.',
  },
  {
    value: 'hard_block',
    label: 'Strict',
    description: 'Use stronger blocking on the most risky data transfer actions.',
  },
]

const BASELINE_TARGETS = [
  'Sensitive files',
  'Passwords and keys',
  'Personal data',
  'Financial data',
  'USB transfers',
]

export default function PlatformDlp() {
  const { get, put } = usePlatformApi()
  const [loading, setLoading] = useState(true)
  const [error, setError] = useState('')
  const [baseline, setBaseline] = useState(null)
  const [selectedLevel, setSelectedLevel] = useState('soft_block')
  const [saving, setSaving] = useState(false)

  const load = useCallback(async () => {
    setLoading(true)
    setError('')
    try {
      const data = await get('/api/platform/dlp/baseline')
      const policy = (data?.policies || []).find(item => item.scope === 'platform_baseline') || data?.policies?.[0] || null
      setBaseline(policy)
      setSelectedLevel(policy?.rollout_mode || 'soft_block')
    } catch (err) {
      setError(err?.message || 'Failed to load platform baseline')
      setBaseline(null)
    } finally {
      setLoading(false)
    }
  }, [get])

  useEffect(() => { load() }, [load])

  const summary = useMemo(() => [
    { label: 'Baseline mode', value: PROTECTION_LEVELS.find(item => item.value === selectedLevel)?.label || 'Recommended' },
    { label: 'Tenants inherit', value: 'Yes' },
    { label: 'Protected areas', value: BASELINE_TARGETS.join(', ') },
    { label: 'Baseline rules', value: String((baseline?.rules || []).length) },
  ], [selectedLevel, baseline])

  const save = async () => {
    setSaving(true)
    try {
      await put('/api/platform/dlp/policy', {
        name: 'Platform Baseline DLP Policy',
        description: `Platform baseline set to ${selectedLevel}`,
        scope: 'platform_baseline',
        mode: 'detect_then_block',
        status: 'published',
        priority: 1000,
        rollout_mode: selectedLevel,
        is_baseline: true,
        is_mandatory: true,
        config: {
          simple_mode: selectedLevel,
          protected_targets: BASELINE_TARGETS,
        },
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
        <div className="empty-state-title">Unable to load platform DLP</div>
        <div className="empty-state-sub">{error}</div>
        <button className="btn btn-outline btn-sm" onClick={load}>Retry</button>
      </div>
    )
  }

  return (
    <div style={{ display: 'grid', gap: 18 }}>
      <div className="platform-hero">
        <div>
          <h1>Platform DLP Baseline</h1>
          <p>One simple baseline that every tenant inherits.</p>
        </div>
        <SimpleBadge tone="info">Baseline</SimpleBadge>
      </div>

      <SimpleSection
        title="Protection level"
        subtitle="Choose the default DLP posture for all tenants"
        action={<button className="btn btn-primary btn-sm" onClick={save} disabled={saving}>{saving ? 'Saving...' : 'Save baseline'}</button>}
      >
        <ChoiceGrid value={selectedLevel} onChange={setSelectedLevel} options={PROTECTION_LEVELS} />
      </SimpleSection>

      <div className="grid-2">
        <SimpleSection title="What all tenants inherit" subtitle="This stays simple so it is easy to understand">
          <SimpleKeyValue items={summary} />
        </SimpleSection>

        <SimpleSection title="Plain-English reminder" subtitle="What this baseline does">
          <div style={{ display: 'grid', gap: 10, color: 'var(--text-2)', fontSize: 13, lineHeight: 1.6 }}>
            <div>Tenant teams will see warnings when they move sensitive files in risky ways.</div>
            <div>The baseline keeps the same rule set across all tenants so behavior is predictable.</div>
            <div>Strict mode should only be used if you want stronger blocking by default.</div>
          </div>
        </SimpleSection>
      </div>
    </div>
  )
}
