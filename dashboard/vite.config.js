import { defineConfig } from 'vite'
import react from '@vitejs/plugin-react'
import tailwindcss from '@tailwindcss/vite'

// https://vite.dev/config/
export default defineConfig({
  // GitHub Pages σερβίρει το site από /travel-tracker/, όχι από τη ρίζα
  base: '/travel-tracker/',
  plugins: [react(), tailwindcss()],
})
