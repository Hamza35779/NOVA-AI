# NOVA AI Browser Extension

Bring NOVA AI to every webpage.

## Prerequisites

- NOVA AI backend running locally: `nova serve` (the extension talks to `http://127.0.0.1:8000`)
- Chrome/Edge 88+ to load it unpacked
- Node.js (any recent version) only if you want to package it — no build step is required for development:

  ```bash
  cd browser-extension
  npm install        # dev tooling only; the extension itself is plain JS/CSS
  ```

## Install (Developer Mode)

1. Open Chrome/Edge and go to `chrome://extensions`
2. Enable **Developer mode** (top right toggle)
3. Click **Load unpacked**
4. Select the `browser-extension/` folder
5. Make sure NOVA AI is running: `nova serve`

## Packaging

```bash
# From the repo root — produces a zip for the Chrome Web Store
bash scripts/install/build-extension.sh
```

## Usage

| Action | How |
|:--|:--|
| Open sidebar | `Alt+N` or click the NOVA icon |
| Ask about selection | Select text → right-click → Ask NOVA AI |
| Summarize page | Right-click → Summarize with NOVA AI |
| Quick question | Click extension icon → type in popup |

## Icons

`icons/` expects `icon16.png`, `icon48.png`, `icon128.png` — see [icons/README.md](icons/README.md).

## Supported Browsers
- Chrome 88+
- Edge 88+
- Firefox (with minor manifest adjustments)
