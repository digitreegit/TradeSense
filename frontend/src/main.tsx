import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/index.css'
import { applyLocaleToDocument, readStoredLocale } from './locale/locale'
import { applyThemeToDocument, readStoredTheme } from './theme/theme'

applyThemeToDocument(readStoredTheme())
applyLocaleToDocument(readStoredLocale())

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
