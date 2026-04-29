import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App'
import './styles/index.css'
import { readStoredColorMode, applyColorMode } from './theme'
import { useAppStore } from './stores/useAppStore'

const initialMode = readStoredColorMode()
applyColorMode(initialMode)
useAppStore.setState({ colorMode: initialMode })

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
