/**
 * i18n bootstrap. Runs before React mounts (see main.tsx) so the first
 * render already has the resolved language.
 *
 * Language resolution priority:
 *   1. localStorage key `ev.lang`
 *   2. navigator.language prefix (`zh-*` → zh, else en)
 *   3. fallback `zh`
 *
 * Keep this module tiny and framework-agnostic. Anything React-specific
 * (provider, html[lang] sync) lives in `LanguageProvider.tsx`.
 */

import i18n from 'i18next'
import LanguageDetector from 'i18next-browser-languagedetector'
import { initReactI18next } from 'react-i18next'

import en from './en.json'
import zh from './zh.json'

export const SUPPORTED_LANGUAGES = ['zh', 'en'] as const
export type SupportedLanguage = (typeof SUPPORTED_LANGUAGES)[number]

export const LANGUAGE_STORAGE_KEY = 'ev.lang'

void i18n
  .use(LanguageDetector)
  .use(initReactI18next)
  .init({
    resources: {
      en: { translation: en },
      zh: { translation: zh },
    },
    fallbackLng: 'zh',
    supportedLngs: SUPPORTED_LANGUAGES as unknown as string[],
    nonExplicitSupportedLngs: true,
    detection: {
      // Persisted preference beats browser locale; cookie + URL left off
      // for simplicity (we can add ?lang= later without changing consumers).
      order: ['localStorage', 'navigator'],
      lookupLocalStorage: LANGUAGE_STORAGE_KEY,
      caches: ['localStorage'],
    },
    interpolation: {
      escapeValue: false, // React escapes.
    },
    returnNull: false,
  })

export default i18n
