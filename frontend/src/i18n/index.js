/**
 * CropSentinel — i18n initialisation
 * ══════════════════════════════════
 *
 * Skeleton using `react-i18next`. All strings live under src/i18n/locales/<lang>.json.
 * A single `en` locale ships today; adding a new language is a three-step job:
 *
 *   1. Create src/i18n/locales/<lang>.json with the same keys as en.json
 *   2. Import it below and add it to the `resources` object
 *   3. Add the code to SUPPORTED_LANGUAGES in ./languages.js
 *
 * The detected language is persisted to localStorage under 'croppro_lang'
 * so the selection survives reloads.
 *
 * Usage in a component:
 *
 *   import { useTranslation } from 'react-i18next'
 *   const { t } = useTranslation()
 *   return <h1>{t('dashboard.title')}</h1>
 *
 * `t('x.y.z')` falls back to the key itself if a string is missing — safe
 * to roll out page-by-page without breaking anything.
 */

import i18n from 'i18next'
import { initReactI18next } from 'react-i18next'

import en from './locales/en.json'
import es from './locales/es.json'
import fr from './locales/fr.json'
import de from './locales/de.json'

const STORAGE_KEY = 'croppro_lang'

const savedLang =
  typeof window !== 'undefined'
    ? window.localStorage.getItem(STORAGE_KEY)
    : null

i18n
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      es: { translation: es },
      fr: { translation: fr },
      de: { translation: de },
    },
    lng:          savedLang ?? 'en',
    fallbackLng:  'en',
    interpolation: { escapeValue: false },   // React already escapes
    returnEmptyString: false,                 // fall back to key on empty
    react:         { useSuspense: false },    // we handle loading manually
  })

// Persist on change so the next reload keeps the selection.
i18n.on('languageChanged', (lng) => {
  try { window.localStorage.setItem(STORAGE_KEY, lng) } catch { /* ignore */ }
  if (typeof document !== 'undefined') document.documentElement.lang = lng
})

export default i18n
