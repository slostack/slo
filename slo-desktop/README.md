# Slo Desktop

A minimal TypeScript + Electron shell. It does not connect to the Slo engine yet.

## Requirements

Node.js 22.12+ (or 20.19+) and npm. A graphical desktop session is required to open the window.

## Run

From `slo-desktop/`:

```bash
npm ci
npm run dev
```

The Electron development renderer is served on `0.0.0.0:9911`. **Electron still needs a graphical desktop session**; if it exits, its development server stops too. To test just the page from a remote machine without launching Electron, run `npm run dev:web` instead and visit `http://<server-ip>:9911/`. This previews the UI only, not native Electron functionality. Prefer an SSH tunnel (`ssh -L 9911:127.0.0.1:9911 user@server`) rather than exposing the dev server to an untrusted network.

If you see `Error: Electron uninstall`, the Electron binary is missing even though its npm package is present. Reinstall it with:

```bash
node node_modules/electron/install.js
npm run dev
```

If the rebuild cannot download Electron, check your network/proxy and Electron download mirror settings, then retry. Running Electron as root on Linux may require a sandbox configuration; use a normal desktop user rather than disabling the sandbox by default.

## Other commands

```bash
npm run typecheck  # Check TypeScript
npm run build      # Build Electron main and renderer
npm start          # Preview the built application
```

The renderer has no Node.js access. There is no preload bridge or Slo backend connection yet; those will be added when needed.
