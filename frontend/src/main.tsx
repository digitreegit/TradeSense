import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/index.css'
import { applyThemeToDocument, readStoredTheme } from './theme/theme'

applyThemeToDocument(readStoredTheme())
try {
  document.documentElement.lang = localStorage.getItem('tradesense-language') === 'ko' ? 'ko' : 'en'
} catch {
  document.documentElement.lang = 'en'
}

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
