import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

// Leaflet CSS loaded via CDN in index.html (avoids slow Vite CSS pipeline)

import App from './App';

const rootEl = document.getElementById('root');
if (!rootEl) {
  throw new Error('Root element #root not found in index.html');
}

createRoot(rootEl).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
