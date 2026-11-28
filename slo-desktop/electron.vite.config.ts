import { defineConfig } from 'electron-vite'

export default defineConfig({
  main: {},
  renderer: {
    server: {
      host: '0.0.0.0',
      port: 9911,
      strictPort: true
    }
  }
})
