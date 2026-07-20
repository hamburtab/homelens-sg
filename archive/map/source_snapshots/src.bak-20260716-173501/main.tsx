import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';

// Leaflet CSS — required for map tiles and controls to render correctly
import 'leaflet/dist/leaflet.css';

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
