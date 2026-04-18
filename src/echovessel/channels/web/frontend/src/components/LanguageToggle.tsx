/**
 * Two-button segmented chip for EN ↔ 中. Lives in the TopBar.
 * Keeps its own styling inline to avoid bloating styles.css; adjust
 * once if the TopBar gets a design pass.
 */

import { useTranslation } from 'react-i18next'

export function LanguageToggle() {
  const { i18n, t } = useTranslation()
  const current = i18n.language?.split('-')[0] ?? 'zh'

  const switchTo = (lang: 'en' | 'zh') => {
    if (current === lang) return
    void i18n.changeLanguage(lang)
  }

  const activeBg = 'rgba(255,255,255,0.18)'
  const idleBg = 'transparent'
  const baseBtn: React.CSSProperties = {
    background: 'transparent',
    border: 'none',
    color: 'rgba(255,255,255,0.72)',
    fontSize: 11,
    letterSpacing: '0.08em',
    padding: '4px 10px',
    cursor: 'pointer',
    borderRadius: 999,
    transition: 'background 0.12s ease',
  }

  return (
    <div
      role="group"
      aria-label="Language"
      style={{
        display: 'inline-flex',
        alignItems: 'center',
        gap: 2,
        marginRight: 10,
        padding: 2,
        border: '1px solid rgba(255,255,255,0.12)',
        borderRadius: 999,
      }}
    >
      <button
        type="button"
        onClick={() => switchTo('zh')}
        aria-pressed={current === 'zh'}
        aria-label={t('language.switch_to_zh_aria')}
        style={{
          ...baseBtn,
          background: current === 'zh' ? activeBg : idleBg,
          color:
            current === 'zh'
              ? 'rgba(255,255,255,0.95)'
              : 'rgba(255,255,255,0.6)',
        }}
      >
        中
      </button>
      <button
        type="button"
        onClick={() => switchTo('en')}
        aria-pressed={current === 'en'}
        aria-label={t('language.switch_to_en_aria')}
        style={{
          ...baseBtn,
          background: current === 'en' ? activeBg : idleBg,
          color:
            current === 'en'
              ? 'rgba(255,255,255,0.95)'
              : 'rgba(255,255,255,0.6)',
        }}
      >
        EN
      </button>
    </div>
  )
}
