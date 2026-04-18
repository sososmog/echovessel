import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { App } from './App'
import './i18n' // initialises i18next before first render
import { LanguageProvider } from './i18n/LanguageProvider'
import './styles.css'

const root = document.getElementById('root')
if (!root) throw new Error('root element missing')

createRoot(root).render(
  <StrictMode>
    <LanguageProvider>
      <App />
    </LanguageProvider>
  </StrictMode>,
)
