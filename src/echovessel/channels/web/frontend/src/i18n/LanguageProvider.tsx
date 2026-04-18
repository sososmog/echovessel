/**
 * Syncs <html lang> with the active i18n language and persists
 * explicit user choices to localStorage. The i18n init in `./index.ts`
 * already wires a localStorage-backed LanguageDetector, so this
 * provider's job is the DOM side of the story only.
 *
 * Place near the root of the component tree (inside I18nextProvider).
 */

import { useEffect, type ReactNode } from 'react'
import { useTranslation } from 'react-i18next'

export function LanguageProvider({ children }: { children: ReactNode }) {
  const { i18n } = useTranslation()

  useEffect(() => {
    const apply = (lang: string) => {
      const short = lang.split('-')[0]
      if (typeof document !== 'undefined') {
        document.documentElement.setAttribute('lang', short === 'en' ? 'en' : 'zh-CN')
      }
    }

    apply(i18n.language || 'zh')
    i18n.on('languageChanged', apply)
    return () => {
      i18n.off('languageChanged', apply)
    }
  }, [i18n])

  return <>{children}</>
}
