/**
 * Dropdown language switcher — drop into the topbar when ready.
 * Hidden automatically when only one language is registered.
 */
import { useTranslation } from 'react-i18next'
import { SUPPORTED_LANGUAGES } from './languages'

export default function LanguageSwitcher({ className = '' }) {
  const { i18n, t } = useTranslation()

  if (SUPPORTED_LANGUAGES.length <= 1) return null

  return (
    <label className={className} style={{ display: 'inline-flex', alignItems: 'center', gap: 6 }}>
      <span className="visually-hidden">{t('common.language', 'Language')}</span>
      <select
        value={i18n.language}
        onChange={(e) => i18n.changeLanguage(e.target.value)}
        style={{
          background:  'var(--bg-3)',
          color:       'var(--text-1)',
          border:      '1px solid var(--border-2)',
          borderRadius:'var(--r-sm)',
          padding:     '4px 8px',
          fontSize:    13,
        }}
      >
        {SUPPORTED_LANGUAGES.map((l) => (
          <option key={l.code} value={l.code}>{l.nativeLabel}</option>
        ))}
      </select>
    </label>
  )
}
