/**
 * CropSentinel — Settings  v5.0
 * =========================
 * Polished tabbed settings with SVG icons. Install tab removed.
 * Tabs: general, security, agent, audit (admin), data
 */

import { useState, useEffect, useCallback, useRef } from 'react'
import { useApi, useAuth } from '../hooks/useAuth'
import { invalidateIceServersCache } from '../hooks/useIceServers'
import {
  Toggle,
  Field,
  InfoBox,
  SectionCard,
  SaveBtn,
  PwdStrength,
  Stat,
  UploadButton,
} from './settings/SettingsShared'
import { SettingsIcon } from '../components/ui/OverviewIcons'

/* ── SVG tab icons ──────────────────────────────────────────────────────────── */
const IC = {
  general:  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><rect x="3" y="3" width="18" height="18" rx="2"/><path d="M3 9h18M9 21V9"/></svg>,
  security: <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/></svg>,
  agent:    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 01-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 01-2.83-2.83l.06-.06A1.65 1.65 0 004.68 15a1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 012.83-2.83l.06.06A1.65 1.65 0 009 4.68a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 012.83 2.83l-.06.06A1.65 1.65 0 0019.4 9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/></svg>,
  audit:    <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6M16 13H8M16 17H8M10 9H8"/></svg>,
  data:     <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M21 12c0 1.66-4 3-9 3s-9-1.34-9-3"/><path d="M3 5v14c0 1.66 4 3 9 3s9-1.34 9-3V5"/></svg>,
  key:      <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 11-7.78 7.78 5.5 5.5 0 017.78-7.78zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>,
  stop:     <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><path d="M15 9l-6 6M9 9l6 6"/></svg>,
  timer:    <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg>,
  eye:      <svg width="15" height="15" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M1 12s4-8 11-8 11 8 11 8-4 8-11 8-11-8-11-8z"/><circle cx="12" cy="12" r="3"/></svg>,
  save:     <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><path d="M19 21H5a2 2 0 01-2-2V5a2 2 0 012-2h11l5 5v11a2 2 0 01-2 2z"/><polyline points="17 21 17 13 7 13 7 21"/><polyline points="7 3 7 8 15 8"/></svg>,
  trash:    <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><polyline points="3 6 5 6 21 6"/><path d="M19 6v14a2 2 0 01-2 2H7a2 2 0 01-2-2V6m3 0V4a2 2 0 012-2h4a2 2 0 012 2v2"/></svg>,
  alert:    <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M10.29 3.86L1.82 18a2 2 0 001.71 3h16.94a2 2 0 001.71-3L13.71 3.86a2 2 0 00-3.42 0z"/><path d="M12 9v4M12 17h.01"/></svg>,
  download: <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="7 10 12 15 17 10"/><line x1="12" y1="15" x2="12" y2="3"/></svg>,
  search:   <svg width="13" height="13" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><circle cx="11" cy="11" r="8"/><path d="M21 21l-4.35-4.35"/></svg>,
  webrtc:   <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M5.636 18.364a9 9 0 010-12.728"/><path d="M18.364 5.636a9 9 0 010 12.728"/><path d="M8.464 15.536a5 5 0 010-7.072"/><path d="M15.536 8.464a5 5 0 010 7.072"/><circle cx="12" cy="12" r="1"/></svg>,
  check:    <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><polyline points="20 6 9 17 4 12"/></svg>,
  x:        <svg width="12" height="12" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2.5"><line x1="18" y1="6" x2="6" y2="18"/><line x1="6" y1="6" x2="18" y2="18"/></svg>,
  circle:   <svg width="10" height="10" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="2"><circle cx="12" cy="12" r="9"/></svg>,
  license:  <svg width="16" height="16" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M21 10V8a2 2 0 00-2-2h-5l-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2h7"/><circle cx="17" cy="16" r="3"/><path d="M17 19v3M19 21l-2-2-2 2"/></svg>,
  upload:   <svg width="14" height="14" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth="1.8"><path d="M21 15v4a2 2 0 01-2 2H5a2 2 0 01-2-2v-4"/><polyline points="17 8 12 3 7 8"/><line x1="12" y1="3" x2="12" y2="15"/></svg>,
}

const TAB_LIST = [
  { id:'general',  icon: IC.general,  label:'General'   },
  { id:'security', icon: IC.security, label:'Security'  },
  { id:'agent',    icon: IC.agent,    label:'Agent'     },
  { id:'webrtc',   icon: IC.webrtc,   label:'WebRTC'    },
  { id:'license',  icon: IC.license,  label:'License'   },
  { id:'audit',    icon: IC.audit,    label:'Audit Logs', adminOnly:true },
  { id:'data',     icon: IC.data,     label:'Data'      },
]

/* ── Shared Components ──────────────────────────────────────────────────────── */




/* ══════════════════════════════════════════════════════════════════════════════
   PANELS
   ══════════════════════════════════════════════════════════════════════════════ */

function GeneralPanel({ toast$ }) {
  const { get, put } = useApi()
  const [name, setName] = useState('')
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    get('/api/settings').then(s => setName(s.company_name || '')).catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    try { await put('/api/settings', { company_name: name }); toast$('Company name saved') }
    catch (e) { toast$(e.message, 'red') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth:600, display:'flex', flexDirection:'column', gap:20 }}>
      <SectionCard icon={IC.general} title="Company Information"
        description="This name appears in PDF reports and the sidebar branding.">
        <Field label="Company Name">
          <input className="input-field" value={name}
            onChange={e => setName(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && save()}
            placeholder="e.g. HAAK IT SOLUTIONS" />
        </Field>
        <div style={{ marginTop:18 }}>
          <SaveBtn saving={saving} onClick={save} saveIcon={IC.save} />
        </div>
      </SectionCard>
    </div>
  )
}

function SecurityPanel({ toast$ }) {
  const { post, put } = useApi()
  const [pwd, setPwd]     = useState({ old:'', next:'', confirm:'' })
  const [pwdErr, setPwdErr] = useState('')
  const [savingPwd, setSavingPwd] = useState(false)
  const [stop, setStop]   = useState({ pwd:'', confirm:'' })
  const [stopErr, setStopErr] = useState('')
  const [savingStop, setSavingStop] = useState(false)

  const savePwd = async () => {
    setPwdErr('')
    if (!pwd.old)                { setPwdErr('Enter current password'); return }
    if (pwd.next.length < 8)     { setPwdErr('Minimum 8 characters required'); return }
    if (pwd.next !== pwd.confirm){ setPwdErr('Passwords do not match'); return }
    setSavingPwd(true)
    try {
      await post('/api/auth/change-password', { old_password:pwd.old, new_password:pwd.next })
      setPwd({ old:'', next:'', confirm:'' })
      toast$('Admin password updated')
    } catch (e) { setPwdErr(e.message) }
    finally { setSavingPwd(false) }
  }

  const saveStop = async () => {
    setStopErr('')
    if (stop.pwd !== stop.confirm){ setStopErr('Passwords do not match'); return }
    setSavingStop(true)
    try {
      await put('/api/settings', { agent_stop_password: stop.pwd })
      setStop({ pwd:'', confirm:'' })
      toast$('Agent stop password updated')
    } catch (e) { setStopErr(e.message) }
    finally { setSavingStop(false) }
  }

  return (
    <div style={{ maxWidth:600, display:'flex', flexDirection:'column', gap:20 }}>

      <SectionCard icon={IC.key} title="Admin Password"
        description="Change the password used to log into the CropSentinel dashboard.">
        <div style={{ display:'flex', flexDirection:'column', gap:14 }}>
          <Field label="Current Password">
            <input type="password" className="input-field" value={pwd.old}
              onChange={e => setPwd(p => ({...p, old:e.target.value}))}
              placeholder="Enter current password" />
          </Field>
          <Field label="New Password">
            <input type="password" className="input-field" value={pwd.next}
              onChange={e => setPwd(p => ({...p, next:e.target.value}))}
              placeholder="Minimum 8 characters" />
            <PwdStrength pwd={pwd.next} checkIcon={IC.check} circleIcon={IC.circle} />
          </Field>
          <Field label="Confirm New Password">
            <input type="password" className="input-field" value={pwd.confirm}
              onChange={e => setPwd(p => ({...p, confirm:e.target.value}))}
              placeholder="Repeat new password" />
          </Field>
          {pwdErr && <InfoBox variant="danger" icon={IC.alert}>{pwdErr}</InfoBox>}
          <div><SaveBtn saving={savingPwd} onClick={savePwd} label="Update Password" saveIcon={IC.save} /></div>
        </div>
      </SectionCard>

      <SectionCard icon={IC.stop} title="Agent Stop Password"
        description="Required to stop or uninstall the monitoring agent on any machine.">
        <InfoBox variant="amber" icon={IC.alert}>
          <span>Default: <code style={{ fontFamily:'JetBrains Mono,monospace', fontSize:12, background:'var(--surface-4)', padding:'2px 6px', borderRadius:4 }}>StopAgent@CropPro</code> — change this in production.</span>
        </InfoBox>
        <div style={{ display:'flex', flexDirection:'column', gap:14, marginTop:16 }}>
          <Field label="New Stop Password">
            <input type="password" className="input-field" value={stop.pwd}
              onChange={e => setStop(s => ({...s, pwd:e.target.value}))}
              placeholder="Leave blank to keep current" />
          </Field>
          <Field label="Confirm Stop Password">
            <input type="password" className="input-field" value={stop.confirm}
              onChange={e => setStop(s => ({...s, confirm:e.target.value}))}
              placeholder="Repeat password" />
          </Field>
          {stopErr && <InfoBox variant="danger" icon={IC.alert}>{stopErr}</InfoBox>}
          <div><SaveBtn saving={savingStop} onClick={saveStop} label="Update Stop Password" saveIcon={IC.save} /></div>
        </div>
      </SectionCard>
    </div>
  )
}

function AgentPanel({ toast$ }) {
  const { get, put } = useApi()
  const [cfg, setCfg] = useState({
    screenshot_interval: 60, activity_sync_interval: 30, input_bucket_seconds: 30,
    track_screenshots: true, track_browser: true, track_applications: true, track_input_activity: false,
  })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    get('/api/settings').then(s => setCfg(c => ({
      ...c,
      screenshot_interval:    s.screenshot_interval    ?? 60,
      activity_sync_interval: s.activity_sync_interval ?? 30,
      input_bucket_seconds:   s.input_bucket_seconds   ?? 30,
      track_screenshots:      s.track_screenshots      !== false,
      track_browser:          s.track_browser          !== false,
      track_applications:     s.track_applications     !== false,
      track_input_activity:   s.track_input_activity   === true,
    }))).catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await put('/api/settings', {
        screenshot_interval:    Number(cfg.screenshot_interval),
        activity_sync_interval: Number(cfg.activity_sync_interval),
        input_bucket_seconds:   Number(cfg.input_bucket_seconds),
        track_screenshots:      cfg.track_screenshots,
        track_browser:          cfg.track_browser,
        track_applications:     cfg.track_applications,
        track_input_activity:   cfg.track_input_activity,
      })
      toast$('Agent configuration saved')
    } catch (e) { toast$(e.message, 'red') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth:600, display:'flex', flexDirection:'column', gap:20 }}>

      <SectionCard icon={IC.timer} title="Collection Intervals"
        description="Control how frequently the agent captures and syncs data.">
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          <Field label="Screenshot Interval (sec)" hint="How often agent captures a screenshot">
            <input type="number" className="input-field" value={cfg.screenshot_interval}
              min={10} max={3600}
              onChange={e => setCfg(c => ({...c, screenshot_interval:e.target.value}))} />
          </Field>
          <Field label="Activity Sync (sec)" hint="How often agent batches data to server">
            <input type="number" className="input-field" value={cfg.activity_sync_interval}
              min={5} max={300}
              onChange={e => setCfg(c => ({...c, activity_sync_interval:e.target.value}))} />
          </Field>
        </div>
      </SectionCard>

      <SectionCard icon={IC.eye} title="Tracking Features"
        description="Enable or disable specific data collection modules on all agents.">
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          <Toggle on={cfg.track_applications}
            onChange={v => setCfg(c => ({...c, track_applications:v}))}
            label="Application usage (app names, window titles, duration)" />
          <Toggle on={cfg.track_browser}
            onChange={v => setCfg(c => ({...c, track_browser:v}))}
            label="Browser history (URLs, domains, page titles)" />
          <Toggle on={cfg.track_screenshots}
            onChange={v => setCfg(c => ({...c, track_screenshots:v}))}
            label="Periodic screenshots" />
          <Toggle on={cfg.track_input_activity}
            onChange={v => setCfg(c => ({...c, track_input_activity:v}))}
            label="Keyboard & mouse activity (Tier B — hashed keycode n-grams, no raw text)" />
          {cfg.track_input_activity && (
            <div style={{ marginLeft:54 }}>
              <Field label="Input bucket (seconds)" hint="Aggregation interval (10–300)">
                <input type="number" className="input-field" style={{ maxWidth:130 }}
                  min={10} max={300} value={cfg.input_bucket_seconds}
                  onChange={e => setCfg(c => ({...c, input_bucket_seconds:e.target.value}))} />
              </Field>
            </div>
          )}
        </div>
      </SectionCard>

      <div><SaveBtn saving={saving} onClick={save} label="Save Agent Config" saveIcon={IC.save} /></div>
    </div>
  )
}

function EnhancedAgentPanel({ toast$ }) {
  const { get, put } = useApi()
  const [cfg, setCfg] = useState({
    screenshot_interval: 180,
    activity_sync_interval: 60,
    heartbeat_interval_seconds: 30,
    app_tracker_interval_seconds: 10,
    network_interval_seconds: 60,
    usb_interval_seconds: 10,
    print_interval_seconds: 20,
    file_cache_fast_sweep_seconds: 10,
    file_cache_recursive_sweep_seconds: 120,
    file_cache_sweeper_enabled: true,
    agent_self_throttle_enabled: true,
    agent_self_throttle_cpu_percent: 85,
    agent_self_throttle_memory_percent: 80,
    agent_self_throttle_queue_depth: 500,
    agent_self_throttle_multiplier: 2,
    agent_self_throttle_cooldown_seconds: 300,
    input_bucket_seconds: 30,
    track_screenshots: true,
    track_browser: true,
    track_applications: true,
    track_input_activity: false,
  })
  const [saving, setSaving] = useState(false)

  const updateCfg = (key, value) => setCfg(current => ({ ...current, [key]: value }))

  const presets = [
    {
      id: 'balanced',
      label: 'Balanced',
      description: 'Good default for most desktops.',
      values: {
        screenshot_interval: 180,
        activity_sync_interval: 60,
        heartbeat_interval_seconds: 30,
        app_tracker_interval_seconds: 10,
        network_interval_seconds: 60,
        usb_interval_seconds: 10,
        print_interval_seconds: 20,
        file_cache_fast_sweep_seconds: 10,
        file_cache_recursive_sweep_seconds: 120,
        file_cache_sweeper_enabled: true,
      },
    },
    {
      id: 'low_impact',
      label: 'Low Impact',
      description: 'Use on weaker endpoints and VMs.',
      values: {
        screenshot_interval: 300,
        activity_sync_interval: 90,
        heartbeat_interval_seconds: 45,
        app_tracker_interval_seconds: 15,
        network_interval_seconds: 90,
        usb_interval_seconds: 15,
        print_interval_seconds: 30,
        file_cache_fast_sweep_seconds: 15,
        file_cache_recursive_sweep_seconds: 180,
        file_cache_sweeper_enabled: true,
      },
    },
    {
      id: 'high_visibility',
      label: 'High Visibility',
      description: 'Tighter collection with higher endpoint cost.',
      values: {
        screenshot_interval: 90,
        activity_sync_interval: 30,
        heartbeat_interval_seconds: 20,
        app_tracker_interval_seconds: 5,
        network_interval_seconds: 30,
        usb_interval_seconds: 5,
        print_interval_seconds: 10,
        file_cache_fast_sweep_seconds: 5,
        file_cache_recursive_sweep_seconds: 60,
        file_cache_sweeper_enabled: true,
      },
    },
  ]

  useEffect(() => {
    get('/api/settings').then(settings => setCfg(current => ({
      ...current,
      screenshot_interval: settings.screenshot_interval ?? 180,
      activity_sync_interval: settings.activity_sync_interval ?? 60,
      heartbeat_interval_seconds: settings.heartbeat_interval_seconds ?? 30,
      app_tracker_interval_seconds: settings.app_tracker_interval_seconds ?? 10,
      network_interval_seconds: settings.network_interval_seconds ?? 60,
      usb_interval_seconds: settings.usb_interval_seconds ?? 10,
      print_interval_seconds: settings.print_interval_seconds ?? 20,
      file_cache_fast_sweep_seconds: settings.file_cache_fast_sweep_seconds ?? 10,
      file_cache_recursive_sweep_seconds: settings.file_cache_recursive_sweep_seconds ?? 120,
      file_cache_sweeper_enabled: settings.file_cache_sweeper_enabled !== false,
      agent_self_throttle_enabled: settings.agent_self_throttle_enabled !== false,
      agent_self_throttle_cpu_percent: settings.agent_self_throttle_cpu_percent ?? 85,
      agent_self_throttle_memory_percent: settings.agent_self_throttle_memory_percent ?? 80,
      agent_self_throttle_queue_depth: settings.agent_self_throttle_queue_depth ?? 500,
      agent_self_throttle_multiplier: settings.agent_self_throttle_multiplier ?? 2,
      agent_self_throttle_cooldown_seconds: settings.agent_self_throttle_cooldown_seconds ?? 300,
      input_bucket_seconds: settings.input_bucket_seconds ?? 30,
      track_screenshots: settings.track_screenshots !== false,
      track_browser: settings.track_browser !== false,
      track_applications: settings.track_applications !== false,
      track_input_activity: settings.track_input_activity === true,
    }))).catch(() => {})
  }, [get])

  const save = async () => {
    setSaving(true)
    try {
      await put('/api/settings', {
        screenshot_interval: Number(cfg.screenshot_interval),
        activity_sync_interval: Number(cfg.activity_sync_interval),
        heartbeat_interval_seconds: Number(cfg.heartbeat_interval_seconds),
        app_tracker_interval_seconds: Number(cfg.app_tracker_interval_seconds),
        network_interval_seconds: Number(cfg.network_interval_seconds),
        usb_interval_seconds: Number(cfg.usb_interval_seconds),
        print_interval_seconds: Number(cfg.print_interval_seconds),
        file_cache_fast_sweep_seconds: Number(cfg.file_cache_fast_sweep_seconds),
        file_cache_recursive_sweep_seconds: Number(cfg.file_cache_recursive_sweep_seconds),
        file_cache_sweeper_enabled: cfg.file_cache_sweeper_enabled,
        agent_self_throttle_enabled: cfg.agent_self_throttle_enabled,
        agent_self_throttle_cpu_percent: Number(cfg.agent_self_throttle_cpu_percent),
        agent_self_throttle_memory_percent: Number(cfg.agent_self_throttle_memory_percent),
        agent_self_throttle_queue_depth: Number(cfg.agent_self_throttle_queue_depth),
        agent_self_throttle_multiplier: Number(cfg.agent_self_throttle_multiplier),
        agent_self_throttle_cooldown_seconds: Number(cfg.agent_self_throttle_cooldown_seconds),
        input_bucket_seconds: Number(cfg.input_bucket_seconds),
        track_screenshots: cfg.track_screenshots,
        track_browser: cfg.track_browser,
        track_applications: cfg.track_applications,
        track_input_activity: cfg.track_input_activity,
      })
      toast$('Agent configuration saved')
    } catch (e) {
      toast$(e.message, 'red')
    } finally {
      setSaving(false)
    }
  }

  return (
    <div style={{ maxWidth:760, display:'flex', flexDirection:'column', gap:20 }}>
      <SectionCard
        icon={IC.agent}
        title="Performance Profile"
        description="Choose a safe operating mode, then tune individual collectors only where needed."
      >
        <div style={{ display:'grid', gap:12 }}>
          {presets.map(preset => (
            <button
              key={preset.id}
              type="button"
              className="btn btn-ghost"
              onClick={() => setCfg(current => ({ ...current, ...preset.values }))}
              style={{
                justifyContent:'space-between',
                alignItems:'center',
                padding:'14px 16px',
                border:'1px solid var(--border-0)',
                background:'var(--surface-3)',
              }}
            >
              <span style={{ display:'flex', flexDirection:'column', alignItems:'flex-start', gap:4 }}>
                <span style={{ fontWeight:700, color:'var(--text-1)' }}>{preset.label}</span>
                <span style={{ fontSize:12, color:'var(--text-3)' }}>{preset.description}</span>
              </span>
              <span className="badge badge-gray" style={{ fontSize:10 }}>Apply</span>
            </button>
          ))}
        </div>
        <InfoBox variant="amber" icon={IC.alert} style={{ marginTop:16 }}>
          Start with <strong>Balanced</strong>. If machines still run hot, increase screenshot and recursive file sweep intervals before disabling features.
        </InfoBox>
      </SectionCard>

      <SectionCard
        icon={IC.timer}
        title="Collection Cadence"
        description="These intervals control how often expensive subsystems sample state or push updates."
      >
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
          <Field label="Screenshot Interval (sec)" hint="Periodic screenshot capture cadence">
            <input type="number" className="input-field" value={cfg.screenshot_interval} min={10} max={3600}
              onChange={e => updateCfg('screenshot_interval', e.target.value)} />
          </Field>
          <Field label="Browser Sync (sec)" hint="Browser activity batching and polling cadence">
            <input type="number" className="input-field" value={cfg.activity_sync_interval} min={10} max={600}
              onChange={e => updateCfg('activity_sync_interval', e.target.value)} />
          </Field>
          <Field label="Heartbeat (sec)" hint="Machine health heartbeat cadence">
            <input type="number" className="input-field" value={cfg.heartbeat_interval_seconds} min={10} max={600}
              onChange={e => updateCfg('heartbeat_interval_seconds', e.target.value)} />
          </Field>
          <Field label="App Tracker (sec)" hint="Foreground app sampling cadence">
            <input type="number" className="input-field" value={cfg.app_tracker_interval_seconds} min={3} max={300}
              onChange={e => updateCfg('app_tracker_interval_seconds', e.target.value)} />
          </Field>
          <Field label="Network Tracker (sec)" hint="Connection inventory cadence">
            <input type="number" className="input-field" value={cfg.network_interval_seconds} min={10} max={600}
              onChange={e => updateCfg('network_interval_seconds', e.target.value)} />
          </Field>
          <Field label="USB Tracker (sec)" hint="Removable media detection cadence">
            <input type="number" className="input-field" value={cfg.usb_interval_seconds} min={5} max={300}
              onChange={e => updateCfg('usb_interval_seconds', e.target.value)} />
          </Field>
          <Field label="Print Tracker (sec)" hint="Print queue polling cadence">
            <input type="number" className="input-field" value={cfg.print_interval_seconds} min={5} max={300}
              onChange={e => updateCfg('print_interval_seconds', e.target.value)} />
          </Field>
        </div>
      </SectionCard>

      <SectionCard
        icon={IC.audit}
        title="File Cache Sweeper"
        description="Controls the cleanup work used by watched-folder DLP backup caching."
      >
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          <Toggle
            on={cfg.file_cache_sweeper_enabled}
            onChange={value => updateCfg('file_cache_sweeper_enabled', value)}
            label="Enable file cache sweeper"
          />
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Field label="Fast Sweep (sec)" hint="Short pass over recent cache entries">
              <input type="number" className="input-field" value={cfg.file_cache_fast_sweep_seconds} min={1} max={300} step="0.5"
                onChange={e => updateCfg('file_cache_fast_sweep_seconds', e.target.value)} />
            </Field>
            <Field label="Recursive Sweep (sec)" hint="Deeper cleanup over watched-folder cache">
              <input type="number" className="input-field" value={cfg.file_cache_recursive_sweep_seconds} min={10} max={1800}
                onChange={e => updateCfg('file_cache_recursive_sweep_seconds', e.target.value)} />
            </Field>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        icon={IC.alert}
        title="Adaptive Self-Throttle"
        description="When a machine stays hot or its offline queue starts backing up, the agent can temporarily stretch expensive collection intervals."
      >
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          <Toggle
            on={cfg.agent_self_throttle_enabled}
            onChange={value => updateCfg('agent_self_throttle_enabled', value)}
            label="Enable adaptive self-throttle"
          />
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:16 }}>
            <Field label="CPU Threshold (%)" hint="Trigger when CPU stays at or above this level">
              <input type="number" className="input-field" value={cfg.agent_self_throttle_cpu_percent} min={50} max={99}
                onChange={e => updateCfg('agent_self_throttle_cpu_percent', e.target.value)} />
            </Field>
            <Field label="Memory Threshold (%)" hint="Trigger when RAM stays at or above this level">
              <input type="number" className="input-field" value={cfg.agent_self_throttle_memory_percent} min={50} max={99}
                onChange={e => updateCfg('agent_self_throttle_memory_percent', e.target.value)} />
            </Field>
            <Field label="Queue Depth Threshold" hint="Trigger when offline queue exceeds this many events">
              <input type="number" className="input-field" value={cfg.agent_self_throttle_queue_depth} min={50} max={50000}
                onChange={e => updateCfg('agent_self_throttle_queue_depth', e.target.value)} />
            </Field>
            <Field label="Interval Multiplier" hint="How much to stretch heavy polling intervals during throttle">
              <input type="number" className="input-field" value={cfg.agent_self_throttle_multiplier} min={1.2} max={5} step="0.1"
                onChange={e => updateCfg('agent_self_throttle_multiplier', e.target.value)} />
            </Field>
            <Field label="Cooldown (sec)" hint="How long the lighter mode stays active after a trigger">
              <input type="number" className="input-field" value={cfg.agent_self_throttle_cooldown_seconds} min={30} max={3600}
                onChange={e => updateCfg('agent_self_throttle_cooldown_seconds', e.target.value)} />
            </Field>
          </div>
        </div>
      </SectionCard>

      <SectionCard
        icon={IC.eye}
        title="Tracking Features"
        description="Enable or disable specific data collection modules on all agents."
      >
        <div style={{ display:'flex', flexDirection:'column', gap:16 }}>
          <Toggle
            on={cfg.track_applications}
            onChange={value => updateCfg('track_applications', value)}
            label="Application usage (app names, window titles, duration)"
          />
          <Toggle
            on={cfg.track_browser}
            onChange={value => updateCfg('track_browser', value)}
            label="Browser history (URLs, domains, page titles)"
          />
          <Toggle
            on={cfg.track_screenshots}
            onChange={value => updateCfg('track_screenshots', value)}
            label="Periodic screenshots"
          />
          <Toggle
            on={cfg.track_input_activity}
            onChange={value => updateCfg('track_input_activity', value)}
            label="Keyboard and mouse activity (Tier B - hashed keycode n-grams, no raw text)"
          />
          {cfg.track_input_activity && (
            <div style={{ marginLeft:54 }}>
              <Field label="Input bucket (seconds)" hint="Aggregation interval (10-300)">
                <input type="number" className="input-field" style={{ maxWidth:130 }} min={10} max={300} value={cfg.input_bucket_seconds}
                  onChange={e => updateCfg('input_bucket_seconds', e.target.value)} />
              </Field>
            </div>
          )}
        </div>
      </SectionCard>

      <div><SaveBtn saving={saving} onClick={save} label="Save Agent Config" saveIcon={IC.save} /></div>
    </div>
  )
}

function LicensePanel({ toast$ }) {
  const { get } = useApi()

  // This page shows the CUSTOMER'S subscription lease, not the platform's
  // license. `/api/my-tenant/license` resolves the caller's tenant and
  // returns its own tier/seats/expiry. The platform license (vendor-level)
  // is completely hidden from customers.
  const [info, setInfo]       = useState(null)
  const [loading, setLoading] = useState(true)

  const refresh = useCallback(() => {
    setLoading(true)
    get('/api/my-tenant/license')
      .then(setInfo)
      .catch(e => toast$(e.message, 'red'))
      .finally(() => setLoading(false))
  }, [get, toast$])

  useEffect(() => { refresh() }, [refresh])

  if (loading && !info) {
    return (
      <div style={{ maxWidth:760, padding:'40px 0', textAlign:'center', color:'var(--text-3)', fontSize:13 }}>
        Loading subscription information...
      </div>
    )
  }
  if (!info) return null

  const maxSeats = info.max_seats || 0
  const used     = info.seats_used || 0
  const pct      = maxSeats > 0 ? Math.round((used / maxSeats) * 100) : 0
  const gaugeColor =
    (maxSeats > 0 && used >= maxSeats) ? 'var(--red)' :
    pct >= 80                           ? 'var(--amber)' :
                                          'var(--green)'

  const daysLeft = info.days_remaining ?? null
  const expiryColor =
    info.is_past_grace ? 'var(--red)' :
    info.is_in_grace   ? 'var(--amber)' :
    (daysLeft !== null && daysLeft <= 14) ? 'var(--amber)' :
                                             'var(--green)'

  return (
    <div style={{ maxWidth:760, display:'flex', flexDirection:'column', gap:20 }}>

      {/* Grace / expiry warnings */}
      {info.is_in_grace && !info.is_past_grace && (
        <InfoBox variant="amber" icon={IC.alert}>
          <strong>Your subscription is in grace period.</strong> It expired on{' '}
          {info.valid_until ? new Date(info.valid_until).toLocaleDateString() : 'an earlier date'},
          but you have {info.grace_days_remaining} day(s) left before access is blocked.
          Please contact your administrator to renew.
        </InfoBox>
      )}
      {info.is_past_grace && (
        <InfoBox variant="danger" icon={IC.alert}>
          <strong>Your subscription has expired.</strong> Login will be blocked
          after your next sign-out. Please contact your administrator to renew.
        </InfoBox>
      )}
      {maxSeats > 0 && used >= maxSeats && (
        <InfoBox variant="danger" icon={IC.alert}>
          <strong>Seat limit reached.</strong> {used}/{maxSeats} seats used.
          New agents will be denied registration until you remove machines or
          ask your administrator to raise the limit.
        </InfoBox>
      )}

      {/* Subscription details */}
      <SectionCard icon={IC.license} title="Subscription Details"
        description="Your current plan and billing contact.">
        <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:'14px 24px', fontSize:13 }}>
          <Stat label="Customer"  value={info.customer_name || info.tenant_name || '—'} />
          <Stat label="Tier"      value={<span style={{ textTransform:'capitalize' }}>{info.tier || '—'}</span>} />
          <Stat label="Status"    value={<span style={{ color: expiryColor, fontWeight:600 }}>{info.status_label || '—'}</span>} />
          <Stat label="Started"   value={info.subscription_started ? new Date(info.subscription_started).toLocaleDateString() : '—'} />
          <Stat label="Expires"
            value={
              info.valid_until ? (
                <span style={{ color: expiryColor, fontWeight:600 }}>
                  {new Date(info.valid_until).toLocaleDateString()}
                  {daysLeft !== null ? ` (${daysLeft} day${daysLeft === 1 ? '' : 's'})` : ''}
                </span>
              ) : <span style={{ color:'var(--text-3)' }}>Perpetual</span>
            } />
          <Stat label="Grace Period" value={`${info.grace_days ?? 0} days`} />
        </div>
      </SectionCard>

      {/* Seat usage gauge */}
      <SectionCard icon={IC.eye} title="Seat Usage"
        description="A seat is one registered machine on your account.">
        <div style={{ display:'flex', alignItems:'baseline', gap:10, marginBottom:10 }}>
          <span style={{ fontSize:28, fontWeight:700, color:'var(--text-1)' }}>
            {used}
          </span>
          <span style={{ fontSize:14, color:'var(--text-3)' }}>
            {maxSeats > 0 ? `/ ${maxSeats} seats` : '(no cap)'}
          </span>
          {maxSeats > 0 && (
            <span style={{ marginLeft:'auto', fontSize:13, fontWeight:600, color:gaugeColor }}>
              {pct}%
            </span>
          )}
        </div>
        {maxSeats > 0 && (
          <div style={{ width:'100%', height:10, borderRadius:6,
            background:'var(--border-1)', overflow:'hidden' }}>
            <div style={{
              width: `${Math.min(100, pct)}%`,
              height:'100%',
              background: gaugeColor,
              transition:'width .3s ease',
            }}/>
          </div>
        )}
        {maxSeats > 0 && (
          <div style={{ marginTop:14, display:'grid', gridTemplateColumns:'1fr 1fr', gap:14, fontSize:12.5 }}>
            <Stat label="Seats Remaining" value={Math.max(0, info.seats_remaining ?? 0)} />
            <Stat label="Seats Used"      value={used} />
          </div>
        )}
      </SectionCard>

      <div style={{
        padding:'12px 16px', borderRadius:'var(--r-md)',
        background:'var(--surface-4)', border:'1px solid var(--border-0)',
        fontSize:12, color:'var(--text-3)', lineHeight:1.6,
      }}>
        Need to change your plan, add seats, or renew? Contact your platform
        administrator — they manage your subscription lease.
      </div>
    </div>
  )
}

function WebRTCPanel({ toast$ }) {
  const { get, put } = useApi()
  const [turn, setTurn] = useState({ url:'', username:'', password:'' })
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    get('/api/settings').then(s => setTurn({
      url:      s.webrtc_turn_url      || '',
      username: s.webrtc_turn_username || '',
      password: s.webrtc_turn_password || '',
    })).catch(() => {})
  }, [])

  const save = async () => {
    setSaving(true)
    try {
      await put('/api/settings', {
        webrtc_turn_url:      turn.url.trim(),
        webrtc_turn_username: turn.username.trim(),
        webrtc_turn_password: turn.password,
      })
      // New LiveView / RemoteAccess peer connections will pick up the change
      // on their next open — no backend restart required.
      invalidateIceServersCache()
      toast$('TURN settings saved — applied to new sessions')
    } catch (e) { toast$(e.message, 'red') }
    finally { setSaving(false) }
  }

  return (
    <div style={{ maxWidth:600, display:'flex', flexDirection:'column', gap:20 }}>

      <SectionCard icon={IC.webrtc} title="TURN Server Configuration"
        description="Required for remote desktop streaming across different networks.">
        <InfoBox variant="brand" icon={IC.webrtc}>
          <div>
            <strong>Without TURN:</strong> Works on LAN / same network only.<br/>
            <strong>With TURN:</strong> Works across any network, VPN, hotspot, strict NAT.<br/>
            <span style={{ fontSize:11, color:'var(--text-3)' }}>
              Free option: openrelay.metered.ca &middot; Self-host: coturn
            </span>
          </div>
        </InfoBox>

        <div style={{ display:'flex', flexDirection:'column', gap:14, marginTop:16 }}>
          <Field label="TURN Server URL" hint="Leave blank to use STUN only (Google)">
            <input className="input-field" value={turn.url}
              onChange={e => setTurn(t => ({...t, url:e.target.value}))}
              placeholder="turn:your-server.com:3478  or  turns:..." />
          </Field>
          <div style={{ display:'grid', gridTemplateColumns:'1fr 1fr', gap:14 }}>
            <Field label="Username">
              <input className="input-field" value={turn.username}
                onChange={e => setTurn(t => ({...t, username:e.target.value}))}
                placeholder="TURN username" />
            </Field>
            <Field label="Credential">
              <input type="password" className="input-field" value={turn.password}
                onChange={e => setTurn(t => ({...t, password:e.target.value}))}
                placeholder="TURN credential" />
            </Field>
          </div>
        </div>

        <div style={{ display:'flex', alignItems:'center', gap:14, marginTop:18 }}>
          <SaveBtn saving={saving} onClick={save} label="Save TURN Config" saveIcon={IC.save} />
          <span style={{ fontSize:12, color: turn.url ? 'var(--green)' : 'var(--text-3)',
            display:'inline-flex', alignItems:'center', gap:4 }}>
            {turn.url ? <>{IC.check} TURN configured</> : <>{IC.circle} Using STUN only</>}
          </span>
        </div>
      </SectionCard>

      <SectionCard icon={IC.agent} title="Environment Variables (Alternative)"
        description="Set these on the backend instead of using the form above.">
        <div style={{ display:'flex', flexDirection:'column', gap:6 }}>
          {['WEBRTC_TURN_URL=turn:your-server:3478',
            'WEBRTC_TURN_USER=username',
            'WEBRTC_TURN_PASS=password'
          ].map(v => (
            <div key={v} style={{ fontFamily:'JetBrains Mono,monospace',
              fontSize:11.5, color:'var(--text-code)', padding:'6px 10px',
              background:'var(--surface-4)', borderRadius:'var(--r-sm)',
              border:'1px solid var(--border-0)' }}>{v}</div>
          ))}
        </div>
      </SectionCard>
    </div>
  )
}

function DataPanel({ toast$, isAdmin = false }) {
  const { get, del, post } = useApi()
  const [machines, setMachines] = useState([])
  const [selId, setSelId]       = useState('')
  const [confirm, setConfirm]   = useState('')
  const [loading, setLoading]   = useState(false)
  const [dbOverview, setDbOverview] = useState(null)
  const [retentionPreview, setRetentionPreview] = useState(null)
  const [historyLoading, setHistoryLoading] = useState(false)

  useEffect(() => { get('/api/machines').then(setMachines).catch(() => {}) }, [])
  useEffect(() => {
    if (!isAdmin) return
    get('/api/admin/database/overview').then(setDbOverview).catch(() => {})
    get('/api/admin/database/retention').then(setRetentionPreview).catch(() => {})
  }, [get, isAdmin])

  const sel = machines.find(m => m.machine_id === selId)

  const deleteActivity = async () => {
    if (!selId) return
    setLoading(true)
    try {
      await del(`/api/machines/${selId}/activity`)
      toast$('Activity data deleted for ' + sel?.hostname)
      setConfirm('')
    } catch (e) { toast$(e.message, 'red') }
    finally { setLoading(false) }
  }

  const deleteMachine = async () => {
    if (!selId || confirm !== sel?.hostname) return
    setLoading(true)
    try {
      await del(`/api/machines/${selId}`)
      toast$('Machine ' + sel?.hostname + ' deleted')
      setSelId(''); setConfirm('')
      get('/api/machines').then(setMachines).catch(() => {})
    } catch (e) { toast$(e.message, 'red') }
      finally { setLoading(false) }
    }

  const runHistoryImpactPreview = async () => {
    if (!isAdmin) return
    setHistoryLoading(true)
    try {
      const result = await post('/api/admin/database/retention/run?dry_run=true', {})
      setRetentionPreview(result)
      toast$('Retention impact preview refreshed')
    } catch (e) { toast$(e.message, 'red') }
    finally { setHistoryLoading(false) }
  }

  return (
    <div style={{ maxWidth:600, display:'flex', flexDirection:'column', gap:20 }}>

      <InfoBox variant="amber" icon={IC.alert}>
        Data management operations are <strong>irreversible</strong>. Activity data is permanently
        deleted from PostgreSQL. Machine deletion also removes all cascaded data.
      </InfoBox>

      <SectionCard icon={IC.data} title="Select Machine"
        description="Choose a machine to manage its data.">
        <select className="input-field" value={selId}
          onChange={e => { setSelId(e.target.value); setConfirm('') }}
          style={{ maxWidth:400 }}>
          <option value="">Choose a machine...</option>
          {machines.map(m => (
            <option key={m.machine_id} value={m.machine_id}>
              {m.hostname}  ({m.username || m.ip_address || m.machine_id.slice(0,8)})
            </option>
          ))}
        </select>
      </SectionCard>

        {selId && (
          <>
          <SectionCard icon={IC.trash} title="Delete Activity Data"
            description={<>Removes all app usage, browser history, screenshots, and input data for <strong style={{ color:'var(--text-1)' }}>{sel?.hostname}</strong>. The machine record is kept.</>}>
            <button className="btn btn-danger" onClick={deleteActivity} disabled={loading}
              style={{ display:'inline-flex', alignItems:'center', gap:7 }}>
              {loading ? <><span className="spinner" style={{ width:13, height:13 }} /> Deleting...</>
                : <>{IC.trash} Delete All Activity</>}
            </button>
          </SectionCard>

          <div style={{ background:'var(--red-dim)', border:'1px solid var(--red-glow)',
            borderRadius:'var(--r-lg)', padding:'20px 22px' }}>
            <div style={{ display:'flex', alignItems:'center', gap:10, marginBottom:6 }}>
              <span style={{ color:'var(--red)', display:'flex' }}>{IC.alert}</span>
              <span style={{ fontSize:14, fontWeight:700, color:'var(--red)' }}>Delete Machine Permanently</span>
            </div>
            <div style={{ fontSize:12.5, color:'var(--text-2)', marginBottom:16, lineHeight:1.5 }}>
              Deletes the machine record and <strong>all associated data</strong> (activity,
              screenshots, alert logs). This cannot be undone.
            </div>
            <Field label={<>Type <code style={{ fontFamily:'JetBrains Mono,monospace', fontSize:12, background:'var(--surface-4)', padding:'1px 6px', borderRadius:4 }}>{sel?.hostname}</code> to confirm</>}>
              <input className="input-field" value={confirm}
                onChange={e => setConfirm(e.target.value)}
                placeholder={sel?.hostname}
                style={{ maxWidth:300 }} />
            </Field>
            <div style={{ marginTop:14 }}>
              <button className="btn btn-danger"
                onClick={deleteMachine}
                disabled={loading || confirm !== sel?.hostname}
                style={{ display:'inline-flex', alignItems:'center', gap:7 }}>
                {loading ? <><span className="spinner" style={{ width:13, height:13 }} /> Deleting...</>
                  : <>{IC.alert} Delete Machine</>}
              </button>
            </div>
          </div>
          </>
        )}

        {isAdmin && (
          <>
            <SectionCard icon={IC.audit} title="DLP History Health"
              description="A quick admin view of how much recent DLP investigation history is available and what may age out soon.">
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(150px, 1fr))', gap:12 }}>
                <Stat label="Recent DLP incidents" value={dbOverview?.dlp_history_health?.dlp_recent_incident_count ?? '--'} />
                <Stat label="Recent notes" value={dbOverview?.dlp_history_health?.dlp_recent_note_count ?? '--'} />
                <Stat label="Recent timeline entries" value={dbOverview?.dlp_history_health?.dlp_recent_timeline_count ?? '--'} />
                <Stat label="Recent DLP artifacts" value={dbOverview?.dlp_history_health?.dlp_recent_artifact_count ?? '--'} />
                <Stat label="Upcoming expiry" value={dbOverview?.dlp_history_health?.upcoming_expiry_count ?? '--'} />
              </div>
              <div style={{ marginTop:14, fontSize:12, color:'var(--text-3)', lineHeight:1.6 }}>
                This helps admins judge whether recent DLP cases still have enough notes, timeline depth, and stored evidence to support analyst investigations.
              </div>
            </SectionCard>

            <SectionCard icon={IC.timer} title="Retention Impact Preview"
              description="Dry-run what would age out before running cleanup, with a DLP-specific history impact summary.">
              <div style={{ display:'flex', gap:10, flexWrap:'wrap', marginBottom:16 }}>
                <button className="btn btn-outline machine-calm-btn btn-sm" onClick={runHistoryImpactPreview} disabled={historyLoading}>
                  {historyLoading ? 'Refreshing...' : 'Preview retention impact'}
                </button>
              </div>
              <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fit, minmax(180px, 1fr))', gap:12 }}>
                <Stat label="Old DLP incidents" value={retentionPreview?.history_impact?.incidents_before_window ?? '--'} />
                <Stat label="Old DLP events" value={retentionPreview?.history_impact?.events_before_window ?? '--'} />
                <Stat label="Notes on old cases" value={retentionPreview?.history_impact?.notes_linked_to_old_incidents ?? '--'} />
                <Stat label="Timeline on old cases" value={retentionPreview?.history_impact?.timeline_entries_linked_to_old_incidents ?? '--'} />
                <Stat label="Evidence near expiry" value={retentionPreview?.history_impact?.evidence_objects_near_expiry ?? '--'} />
              </div>
              <div style={{ marginTop:16, fontSize:12, color:'var(--text-3)', lineHeight:1.6 }}>
                Preview mode does not delete anything. It estimates how much DLP investigation depth would be harder to recover after retention cleanup.
              </div>
            </SectionCard>
          </>
        )}
      </div>
    )
  }

/* ══════════════════════════════════════════════════════════════════════════════
   AUDIT LOGS
   ══════════════════════════════════════════════════════════════════════════════ */

const ACTION_COLORS = {
  login_success:           { bg:'var(--green-dim)',  color:'var(--green)'  },
  login_failed:            { bg:'var(--red-dim)',    color:'var(--red)'    },
  password_changed:        { bg:'var(--brand-dim)',  color:'var(--brand)'  },
  password_change_failed:  { bg:'var(--red-dim)',    color:'var(--red)'    },
  user_created:            { bg:'var(--green-dim)',  color:'var(--green)'  },
  user_updated:            { bg:'var(--brand-dim)',  color:'var(--brand)'  },
  user_deleted:            { bg:'var(--red-dim)',    color:'var(--red)'    },
  machine_updated:         { bg:'var(--brand-dim)',  color:'var(--brand)'  },
  machine_deleted:         { bg:'var(--red-dim)',    color:'var(--red)'    },
  machine_activity_deleted:{ bg:'var(--red-dim)',    color:'var(--red)'    },
  settings_updated:        { bg:'var(--amber-dim)',  color:'var(--amber)'  },
  alert_rule_created:      { bg:'var(--green-dim)',  color:'var(--green)'  },
  alert_rule_updated:      { bg:'var(--brand-dim)',  color:'var(--brand)'  },
  alert_rule_toggled:      { bg:'var(--amber-dim)',  color:'var(--amber)'  },
  alert_rule_deleted:      { bg:'var(--red-dim)',    color:'var(--red)'    },
  remote_command:          { bg:'var(--purple-dim)', color:'var(--purple)' },
}
const DEFAULT_AC = { bg:'var(--surface-4)', color:'var(--text-2)' }

const fmtTs = ts => {
  if (!ts) return '--'
  const d = new Date(ts)
  return d.toLocaleDateString('en-US', { month:'short', day:'numeric' }) + ' ' +
         d.toLocaleTimeString('en-US', { hour12:false, hour:'2-digit', minute:'2-digit', second:'2-digit' })
}

const PAGE_SIZE = 25

function AuditPanel({ toast$ }) {
  const { get } = useApi()
  const [logs, setLogs]         = useState([])
  const [total, setTotal]       = useState(0)
  const [page, setPage]         = useState(0)
  const [loading, setLoading]   = useState(true)
  const [stats, setStats]       = useState(null)
  const [actions, setActions]   = useState([])
  const [search, setSearch]     = useState('')
  const [fAction, setFAction]   = useState('')
  const [fResource, setFResource] = useState('')
  const [fUser, setFUser]       = useState('')
  const [startDate, setStartDate] = useState('')
  const [endDate, setEndDate]   = useState('')
  const [expanded, setExpanded] = useState(null)
  const searchTimer = useRef(null)

  const loadLogs = useCallback((pg = 0) => {
    setLoading(true)
    const params = new URLSearchParams({ limit: PAGE_SIZE, offset: pg * PAGE_SIZE })
    if (search)    params.set('search', search)
    if (fAction)   params.set('action', fAction)
    if (fResource) params.set('resource_type', fResource)
    if (fUser)     params.set('username', fUser)
    if (startDate) params.set('start_date', startDate)
    if (endDate)   params.set('end_date', endDate)
    get(`/api/audit-logs?${params}`)
      .then(r => { setLogs(r.logs || []); setTotal(r.total || 0) })
      .catch(() => {})
      .finally(() => setLoading(false))
  }, [get, search, fAction, fResource, fUser, startDate, endDate])

  useEffect(() => { loadLogs(page) }, [page, fAction, fResource, fUser, startDate, endDate])
  useEffect(() => {
    clearTimeout(searchTimer.current)
    searchTimer.current = setTimeout(() => { setPage(0); loadLogs(0) }, 350)
    return () => clearTimeout(searchTimer.current)
  }, [search])
  useEffect(() => {
    get('/api/audit-logs/stats').then(setStats).catch(() => {})
    get('/api/audit-logs/actions').then(setActions).catch(() => {})
  }, [])

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE))

  const exportCsv = () => {
    const params = new URLSearchParams()
    if (search) params.set('search', search)
    if (fAction) params.set('action', fAction)
    if (fResource) params.set('resource_type', fResource)
    if (fUser) params.set('username', fUser)
    if (startDate) params.set('start_date', startDate)
    if (endDate) params.set('end_date', endDate)
    const token = localStorage.getItem('croppro_token')
    const base = (import.meta.env.VITE_API_URL || '').replace(/\/$/, '')
    fetch(`${base}/api/audit-logs/export?${params}`, {
      headers: { Authorization: `Bearer ${token}` },
    })
      .then(r => r.blob())
      .then(blob => {
        const a = document.createElement('a')
        a.href = URL.createObjectURL(blob)
        a.download = `audit_logs_${new Date().toISOString().slice(0,10)}.csv`
        a.click()
        URL.revokeObjectURL(a.href)
        toast$('CSV exported')
      })
      .catch(() => toast$('Export failed', 'red'))
  }

  const clearFilters = () => {
    setSearch(''); setFAction(''); setFResource(''); setFUser('')
    setStartDate(''); setEndDate(''); setPage(0)
  }
  const hasFilters = search || fAction || fResource || fUser || startDate || endDate

  return (
    <div style={{ display:'flex', flexDirection:'column', gap:18 }}>

      {/* Stat cards */}
      {stats && (
        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(175px,1fr))', gap:12 }}>
          {[
            { label: 'Total Events',  value: stats.total,   color: 'var(--brand)' },
            { label: 'Last 24 Hours', value: stats.last_24h, color: 'var(--green)' },
            ...(stats.top_actions || []).slice(0,3).map(a => ({
              label: a.action.replace(/_/g, ' '), value: a.cnt, color: 'var(--text-2)',
            })),
          ].map((s,i) => (
            <div key={i} style={{ background:'var(--surface-3)', border:'1px solid var(--border-0)',
              borderRadius:'var(--r-md)', padding:'14px 18px' }}>
              <div style={{ fontSize:11, fontWeight:600, color:'var(--text-3)', textTransform:'capitalize',
                marginBottom:4 }}>{s.label}</div>
              <div style={{ fontSize:22, fontWeight:800, color:s.color }}>
                {typeof s.value === 'number' ? s.value.toLocaleString() : s.value}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* Filter bar */}
      <div style={{
        display:'flex', flexWrap:'wrap', gap:8, alignItems:'center',
        background:'var(--surface-3)', border:'1px solid var(--border-0)',
        borderRadius:'var(--r-md)', padding:'10px 14px',
      }}>
        <div style={{ position:'relative', flex:'1 1 200px', minWidth:160 }}>
          <span style={{ position:'absolute', left:10, top:'50%', transform:'translateY(-50%)',
            color:'var(--text-3)', pointerEvents:'none', display:'flex' }}>{IC.search}</span>
          <input className="input-field" placeholder="Search logs..."
            value={search} onChange={e => setSearch(e.target.value)}
            style={{ paddingLeft:32, height:34, fontSize:12 }} />
        </div>

        <select className="input-field" value={fAction}
          onChange={e => { setFAction(e.target.value); setPage(0) }}
          style={{ height:34, fontSize:12, minWidth:140 }}>
          <option value="">All actions</option>
          {actions.map(a => <option key={a} value={a}>{a.replace(/_/g, ' ')}</option>)}
        </select>

        <select className="input-field" value={fResource}
          onChange={e => { setFResource(e.target.value); setPage(0) }}
          style={{ height:34, fontSize:12, minWidth:130 }}>
          <option value="">All resources</option>
          {['auth','user','machine','settings','alert_rule'].map(r =>
            <option key={r} value={r}>{r.replace(/_/g,' ')}</option>)}
        </select>

        <input type="date" className="input-field" value={startDate}
          onChange={e => { setStartDate(e.target.value); setPage(0) }}
          style={{ height:34, fontSize:11, width:130 }} title="Start date" />
        <input type="date" className="input-field" value={endDate}
          onChange={e => { setEndDate(e.target.value); setPage(0) }}
          style={{ height:34, fontSize:11, width:130 }} title="End date" />

        {hasFilters && (
          <button className="btn btn-ghost btn-sm" onClick={clearFilters}
            style={{ fontSize:11, whiteSpace:'nowrap' }}>Clear</button>
        )}

        <button className="btn btn-outline btn-sm" onClick={exportCsv}
          style={{ fontSize:11, whiteSpace:'nowrap', marginLeft:'auto',
            display:'inline-flex', alignItems:'center', gap:5 }}>
          {IC.download} Export CSV
        </button>
      </div>

      {/* Results */}
      <div style={{ display:'flex', justifyContent:'space-between', alignItems:'center', fontSize:12, color:'var(--text-3)' }}>
        <span>{total.toLocaleString()} event{total !== 1 ? 's' : ''} found</span>
        <span>Page {page + 1} of {totalPages}</span>
      </div>

      {/* Table */}
      {loading ? (
        <div className="loading-center" style={{ padding:40 }}>
          <div className="spinner" style={{ width:22, height:22, borderWidth:2.5 }} />
        </div>
      ) : logs.length === 0 ? (
        <div className="empty-state" style={{ padding:40 }}>
          <div style={{ color:'var(--text-3)', marginBottom:8 }}>{IC.search}</div>
          <div className="empty-state-title">
            {hasFilters ? 'No events match your filters' : 'No audit events yet'}
          </div>
          <div className="empty-state-sub">
            {hasFilters ? 'Try adjusting your search or date range' : 'Events will appear here as users perform actions'}
          </div>
        </div>
      ) : (
        <div className="card" style={{ padding:0, overflow:'hidden' }}>
          <table className="data-table" style={{ fontSize:12 }}>
            <thead>
              <tr>
                <th style={{ width:140 }}>Timestamp</th>
                <th style={{ width:110 }}>User</th>
                <th style={{ width:150 }}>Action</th>
                <th style={{ width:100 }}>Resource</th>
                <th>Details</th>
                <th style={{ width:110 }}>IP</th>
              </tr>
            </thead>
            <tbody>
              {logs.map(l => {
                const ac = ACTION_COLORS[l.action] || DEFAULT_AC
                let meta = {}
                try { meta = typeof l.metadata === 'string' ? JSON.parse(l.metadata) : (l.metadata || {}) } catch {}
                const metaEntries = Object.entries(meta)
                const isExpanded = expanded === l.id

                return [
                  <tr key={l.id}
                    onClick={() => setExpanded(isExpanded ? null : l.id)}
                    style={{ cursor: metaEntries.length ? 'pointer' : 'default' }}>
                    <td className="mono" style={{ fontSize:11, color:'var(--text-3)', whiteSpace:'nowrap' }}>
                      {fmtTs(l.timestamp)}
                    </td>
                    <td>
                      <div style={{ display:'flex', flexDirection:'column' }}>
                        <span style={{ fontWeight:600, color:'var(--text-1)', fontSize:12 }}>
                          {l.username || 'system'}
                        </span>
                        <span style={{ fontSize:10, color:'var(--text-3)' }}>{l.role}</span>
                      </div>
                    </td>
                    <td>
                      <span style={{
                        display:'inline-block', fontSize:10, fontWeight:700,
                        padding:'2px 9px', borderRadius:100,
                        background:ac.bg, color:ac.color, whiteSpace:'nowrap',
                      }}>
                        {l.action.replace(/_/g, ' ')}
                      </span>
                    </td>
                    <td>
                      <span style={{ fontSize:11, color:'var(--text-2)' }}>
                        {l.resource_type}
                        {l.resource_id && (
                          <span className="mono" style={{ fontSize:10, color:'var(--text-3)', marginLeft:4 }}>
                            #{l.resource_id.length > 12 ? l.resource_id.slice(0,12)+'...' : l.resource_id}
                          </span>
                        )}
                      </span>
                    </td>
                    <td style={{ fontSize:11, color:'var(--text-3)' }}>
                      {metaEntries.length > 0 ? (
                        <span style={{ display:'flex', alignItems:'center', gap:4, flexWrap:'wrap' }}>
                          {metaEntries.slice(0,2).map(([k,v]) =>
                            <span key={k} className="badge badge-gray" style={{ fontSize:9 }}>
                              {k}: {String(v).slice(0,20)}
                            </span>
                          )}
                          {metaEntries.length > 2 && (
                            <span style={{ fontSize:10, color:'var(--text-3)' }}>+{metaEntries.length - 2}</span>
                          )}
                        </span>
                      ) : '--'}
                    </td>
                    <td className="mono" style={{ fontSize:10, color:'var(--text-3)' }}>
                      {l.ip_address || '--'}
                    </td>
                  </tr>,
                  isExpanded && metaEntries.length > 0 && (
                    <tr key={`${l.id}-meta`}>
                      <td colSpan={6} style={{ background:'var(--bg-3)', padding:'12px 18px', borderTop:'none' }}>
                        <div style={{ fontSize:11, fontWeight:700, color:'var(--text-2)', marginBottom:8 }}>Metadata</div>
                        <div style={{ display:'grid', gridTemplateColumns:'repeat(auto-fill,minmax(200px,1fr))', gap:'4px 20px' }}>
                          {metaEntries.map(([k,v]) => (
                            <div key={k} style={{ fontSize:11.5 }}>
                              <span style={{ color:'var(--text-3)' }}>{k}: </span>
                              <span className="mono" style={{ color:'var(--text-code)' }}>
                                {typeof v === 'object' ? JSON.stringify(v) : String(v)}
                              </span>
                            </div>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ),
                ]
              })}
            </tbody>
          </table>
        </div>
      )}

      {/* Pagination */}
      {totalPages > 1 && (
        <div style={{ display:'flex', justifyContent:'center', gap:4, marginTop:4 }}>
          <button className="btn btn-ghost btn-sm" disabled={page === 0}
            onClick={() => setPage(0)} style={{ fontSize:11 }}>&laquo;</button>
          <button className="btn btn-ghost btn-sm" disabled={page === 0}
            onClick={() => setPage(p => p - 1)} style={{ fontSize:11 }}>&lsaquo; Prev</button>
          {Array.from({ length: Math.min(7, totalPages) }, (_, i) => {
            let p
            if (totalPages <= 7) p = i
            else if (page < 4) p = i
            else if (page > totalPages - 5) p = totalPages - 7 + i
            else p = page - 3 + i
            return (
              <button key={p} className={`btn btn-sm ${page === p ? 'btn-primary' : 'btn-ghost'}`}
                onClick={() => setPage(p)} style={{ fontSize:11, minWidth:32 }}>{p + 1}</button>
            )
          })}
          <button className="btn btn-ghost btn-sm" disabled={page >= totalPages - 1}
            onClick={() => setPage(p => p + 1)} style={{ fontSize:11 }}>Next &rsaquo;</button>
          <button className="btn btn-ghost btn-sm" disabled={page >= totalPages - 1}
            onClick={() => setPage(totalPages - 1)} style={{ fontSize:11 }}>&raquo;</button>
        </div>
      )}
    </div>
  )
}


/* ══════════════════════════════════════════════════════════════════════════════
   MAIN SETTINGS PAGE
   ══════════════════════════════════════════════════════════════════════════════ */

export default function Settings() {
  const [tab, setTab]     = useState('general')
  const [toast, setToast] = useState(null)
  const { user: authUser } = useAuth()
  const userRole = authUser?.role || 'viewer'

  const toast$ = (msg, type = 'green') => {
    setToast({ msg, type })
    setTimeout(() => setToast(null), 3200)
  }

  const visibleTabs = TAB_LIST.filter(t => !t.adminOnly || userRole === 'admin')

  return (
    <div className="fade-in settings-shell">

      {/* Page header */}
      <div className="page-header machine-calm-header analytics-hero control-hero" style={{ marginBottom:20, flexShrink:0 }}>
        <div className="machine-calm-title-wrap">
          <div className="machine-calm-avatar">
            <SettingsIcon size={24} />
          </div>
          <div>
            <div className="page-title">Settings</div>
            <div className="page-subtitle">System configuration, security policy, agent behavior, and data management.</div>
          </div>
        </div>
      </div>

      {/* Tab bar */}
      <div className="settings-tabs" style={{ flexShrink:0 }}>
        {visibleTabs.map(t => (
          <button key={t.id}
            className={`tab-btn ${tab === t.id ? 'active' : ''}`}
            onClick={() => setTab(t.id)}
            style={{ display:'inline-flex', alignItems:'center', gap:7 }}>
            <span style={{ display:'flex', opacity: tab === t.id ? 1 : 0.6 }}>{t.icon}</span>
            {t.label}
          </button>
        ))}
      </div>

      {/* Active panel */}
      <div className="settings-panel">
        {tab === 'general'  && <GeneralPanel toast$={toast$} />}
        {tab === 'security' && <SecurityPanel toast$={toast$} />}
        {tab === 'agent'    && <EnhancedAgentPanel toast$={toast$} />}
        {tab === 'webrtc'   && <WebRTCPanel toast$={toast$} />}
        {tab === 'license'  && <LicensePanel toast$={toast$} />}
        {tab === 'audit'    && <AuditPanel toast$={toast$} />}
        {tab === 'data'     && <DataPanel toast$={toast$} isAdmin={userRole === 'admin'} />}
      </div>

      {/* Toast notification */}
      {toast && (
        <div style={{
          position:'fixed', bottom:24, right:24, zIndex:9999,
          background:'var(--surface-3)',
          border:`1px solid ${toast.type === 'red' ? 'var(--red-glow)' : 'var(--green-glow)'}`,
          color: toast.type === 'red' ? 'var(--red)' : 'var(--green)',
          padding:'12px 18px', borderRadius:'var(--r-md)', fontSize:13, fontWeight:600,
          animation:'fadeIn .25s ease', boxShadow:'var(--shadow-lg)',
          display:'flex', alignItems:'center', gap:8,
        }}>
          {toast.type === 'red' ? IC.x : IC.check} {toast.msg}
        </div>
      )}
    </div>
  )
}
