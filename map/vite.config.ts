import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  base: '/wm/map-demo/',
  build: {
    rollupOptions: {
      input: {
        map: 'index.html',
      },
    },
  },
})
