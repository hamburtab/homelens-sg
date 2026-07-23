import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/wm/map-demo/',
  publicDir: false, // skip copying public/ → dist/ on every build (GeoJSON never changes)
  build: {
    rollupOptions: {
      input: {
        map: 'index.html',
      },
    },
  },
})
