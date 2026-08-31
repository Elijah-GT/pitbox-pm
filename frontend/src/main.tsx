import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import { Root } from './Root.tsx'
import './styles.css'
import './site.css'

const container = document.getElementById('root')
if (!container) throw new Error('Missing #root element')

createRoot(container).render(
  <StrictMode>
    <Root />
  </StrictMode>,
)
