const base = {
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 1.8,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
}

function IconShell({ children, size = 20, title }) {
  return (
    <svg width={size} height={size} viewBox="0 0 24 24" role={title ? 'img' : 'presentation'} aria-label={title || undefined} {...base}>
      {title ? <title>{title}</title> : null}
      {children}
    </svg>
  )
}

export function MachinesIcon(props) {
  return (
    <IconShell title="Machines" {...props}>
      <rect x="3.5" y="5" width="17" height="13" rx="2.5" />
      <path d="M8 18v2m8-2v2" />
      <path d="M8 8h.01M11.5 8h.01M15 8h.01" />
      <path d="M3.5 11.5h17" />
    </IconShell>
  )
}

export function OnlineIcon(props) {
  return (
    <IconShell title="Online" {...props}>
      <path d="M4 12a8 8 0 0 1 16 0" />
      <path d="M6.5 12a5.5 5.5 0 0 1 11 0" />
      <circle cx="12" cy="16.75" r="1.25" fill="currentColor" stroke="none" />
    </IconShell>
  )
}

export function OfflineIcon(props) {
  return (
    <IconShell title="Offline" {...props}>
      <path d="M4.5 6.5 19.5 17.5" />
      <path d="M5 12a7 7 0 0 1 10.5-6" />
      <path d="M18.5 12a7 7 0 0 1-1.9 4.9" />
      <path d="M8 18v2m8-2v2" />
    </IconShell>
  )
}

export function TodayIcon(props) {
  return (
    <IconShell title="Active today" {...props}>
      <rect x="4" y="5" width="16" height="15" rx="3" />
      <path d="M4 9h16" />
      <path d="M8 3.5v3m8-3v3" />
      <path d="m9 14 2 2 4-4" />
    </IconShell>
  )
}

export function AppIcon(props) {
  return (
    <IconShell title="Application" {...props}>
      <rect x="4" y="5" width="16" height="14" rx="3" />
      <path d="M4 9h16" />
      <path d="M8 12h2M8 15h2M13 12h3M13 15h3" />
    </IconShell>
  )
}

export function DomainIcon(props) {
  return (
    <IconShell title="Domain" {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M4 12h16" />
      <path d="M12 4c2.5 2 3.5 4.8 3.5 8s-1 6-3.5 8c-2.5-2-3.5-4.8-3.5-8s1-6 3.5-8Z" />
      <path d="M7 7c1.4.9 3 .4 5 .4s3.6.5 5-.4" />
      <path d="M7 17c1.4-.9 3-.4 5-.4s3.6-.5 5 .4" />
    </IconShell>
  )
}

export function TimeIcon(props) {
  return (
    <IconShell title="Time" {...props}>
      <circle cx="12" cy="12" r="8" />
      <path d="M12 8v4l3 2" />
      <path d="M9 3.5h6" />
    </IconShell>
  )
}

export function VisitsIcon(props) {
  return (
    <IconShell title="Productive visits" {...props}>
      <path d="M5 16.5v-3" />
      <path d="M9 16.5V9.5" />
      <path d="M13 16.5v-5" />
      <path d="M17 16.5V7.5" />
      <path d="m7 11 1.5 1.5L12 9" />
      <path d="M4 19h16" />
    </IconShell>
  )
}

export function AverageHoursIcon(props) {
  return (
    <IconShell title="Average daily hours" {...props}>
      <path d="M6 17h12" />
      <path d="M7.5 13.5 11 10l2.5 2.5L17 9" />
      <path d="M17 9h-3m3 0v3" />
      <circle cx="18" cy="6" r="1.2" fill="currentColor" stroke="none" />
    </IconShell>
  )
}

export function ChartBarIcon(props) {
  return (
    <IconShell title="Bar chart" {...props}>
      <path d="M5 19h14" />
      <rect x="7" y="11" width="2.8" height="6" rx="1" />
      <rect x="11" y="8" width="2.8" height="9" rx="1" />
      <rect x="15" y="5" width="2.8" height="12" rx="1" />
    </IconShell>
  )
}

export function ChartPieIcon(props) {
  return (
    <IconShell title="Pie chart" {...props}>
      <path d="M12 4a8 8 0 1 0 8 8h-8z" />
      <path d="M12 4v8h8" />
    </IconShell>
  )
}

export function ChartLineIcon(props) {
  return (
    <IconShell title="Line chart" {...props}>
      <path d="M5 18h14" />
      <path d="M6.5 14.5 10 11l2.5 2.5L17 8" />
      <circle cx="10" cy="11" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="12.5" cy="13.5" r="1.1" fill="currentColor" stroke="none" />
      <circle cx="17" cy="8" r="1.1" fill="currentColor" stroke="none" />
    </IconShell>
  )
}

export function AlertsIcon(props) {
  return (
    <IconShell title="Alerts" {...props}>
      <path d="M12 4.5 20 18H4z" />
      <path d="M12 9v4" />
      <circle cx="12" cy="15.6" r="1" fill="currentColor" stroke="none" />
    </IconShell>
  )
}

export function ReportsIcon(props) {
  return (
    <IconShell title="Reports" {...props}>
      <path d="M7 4.5h6l4 4V19H7z" />
      <path d="M13 4.5V9h4.5" />
      <path d="M9 13h6" />
      <path d="M9 16h4" />
      <path d="M9 10h2" />
    </IconShell>
  )
}

export function UsersIcon(props) {
  return (
    <IconShell title="Users" {...props}>
      <circle cx="9" cy="9" r="2.5" />
      <circle cx="16.5" cy="10.5" r="2" />
      <path d="M4.5 18c.8-2.5 2.5-4 4.8-4s4 1.5 4.8 4" />
      <path d="M14 17c.5-1.5 1.6-2.5 3.3-2.5 1.1 0 2.1.4 2.9 1.3" />
    </IconShell>
  )
}

export function SettingsIcon(props) {
  return (
    <IconShell title="Settings" {...props}>
      <circle cx="12" cy="12" r="2.4" />
      <path d="M19.4 15a1.6 1.6 0 0 0 .3 1.8l.1.1a2 2 0 0 1-2.8 2.8l-.1-.1a1.6 1.6 0 0 0-1.8-.3 1.6 1.6 0 0 0-1 1.5V21a2 2 0 0 1-4 0v-.1a1.6 1.6 0 0 0-1-1.5 1.6 1.6 0 0 0-1.8.3l-.1.1a2 2 0 0 1-2.8-2.8l.1-.1a1.6 1.6 0 0 0 .3-1.8 1.6 1.6 0 0 0-1.5-1H3a2 2 0 0 1 0-4h.1a1.6 1.6 0 0 0 1.5-1 1.6 1.6 0 0 0-.3-1.8l-.1-.1a2 2 0 0 1 2.8-2.8l.1.1a1.6 1.6 0 0 0 1.8.3h.1a1.6 1.6 0 0 0 1-1.5V3a2 2 0 0 1 4 0v.1a1.6 1.6 0 0 0 1 1.5h.1a1.6 1.6 0 0 0 1.8-.3l.1-.1a2 2 0 0 1 2.8 2.8l-.1.1a1.6 1.6 0 0 0-.3 1.8v.1a1.6 1.6 0 0 0 1.5 1H21a2 2 0 0 1 0 4h-.1a1.6 1.6 0 0 0-1.5 1z" />
    </IconShell>
  )
}

export function DlpIcon(props) {
  return (
    <IconShell title="DLP" {...props}>
      <path d="M12 4.5 18 7v5.5c0 3.7-2.5 6.8-6 7.9-3.5-1.1-6-4.2-6-7.9V7z" />
      <path d="M9.2 12.1 11 14l3.8-4" />
    </IconShell>
  )
}

export function PhishingIcon(props) {
  return (
    <IconShell title="Phishing" {...props}>
      <path d="M6 18c2-6 4-9 6-9s4 3 6 9" />
      <path d="M9 11c1.2-2.8 2.2-4 3-4s1.8 1.2 3 4" />
      <path d="M12 14v.01" />
      <path d="M12 8.5V7" />
    </IconShell>
  )
}

export function InputIcon(props) {
  return (
    <IconShell title="Input activity" {...props}>
      <rect x="4.5" y="6" width="15" height="12" rx="2.5" />
      <path d="M7 10h10" />
      <path d="M7 13h6" />
      <path d="M17.5 14.5 20 17" />
      <circle cx="17.8" cy="14.8" r="1" fill="currentColor" stroke="none" />
    </IconShell>
  )
}

export function FileIcon(props) {
  return (
    <IconShell title="File logs" {...props}>
      <path d="M7 4.5h6l4 4V19H7z" />
      <path d="M13 4.5V9h4.5" />
      <path d="M9 12h6M9 15h4" />
    </IconShell>
  )
}

export function NetworkIcon(props) {
  return (
    <IconShell title="Network logs" {...props}>
      <circle cx="8" cy="8" r="1.5" />
      <circle cx="16" cy="8" r="1.5" />
      <circle cx="12" cy="16" r="1.5" />
      <path d="M9.2 8h5.6M9 9.2l2.1 5.1M15 9.2 12.9 14.3" />
    </IconShell>
  )
}
