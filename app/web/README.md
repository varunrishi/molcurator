# MolCurator web app

Plain HTML, CSS and JavaScript: no build step. The API server serves it at `/`
(`./run.sh`, then open http://127.0.0.1:8000). It can also be opened from any static host or
from disk, pointed at a server in **Settings**.

## What it does

- **New run** (left): pick a preset, set the target window, enter or draw a seed, choose search,
  QM and budget settings. The server checks the config as you edit and shows blocking
  problems and warnings before **Start run**.
- **Runs** (right): pick a run and follow it live: current step, budgets, every step's result,
  LLM or rule decisions. Browse the molecules (values with their level: QM, xTB or ML),
  open one for its 3D geometry, read the summary, run the trajectory evaluator, read the
  process log, stop, resume, download.
- **Header**: connection status, **Docs**, **Source code**, **Settings** (server address, API
  token, source link, refresh interval), light/dark theme.
- **Contributors** at the bottom, from `js/contributors.js`.

Every number shown comes from the server. If the server cannot be reached, the app says so;
it never shows estimated or example values instead.

## Files

| File | What it does |
|---|---|
| `index.html` | page layout, dialogs, and the loader for the two libraries in `lib/` |
| `css/styles.css` | all styles; colours are tokens at the top (light and dark) |
| `js/config.js` | settings kept in this browser (localStorage) |
| `js/ui.js` | small helpers: escaping, formatting, toasts, copy, downloads |
| `js/api.js` | API client: token, ngrok header, timeouts, readable errors |
| `js/chem.js` | OpenChemLib helpers: quick SMILES check, 2D drawings, the structure editor |
| `js/viewer.js` | 3Dmol.js wrapper for XYZ geometries |
| `js/form.js` | the New run panel |
| `js/monitor.js` | the Runs panel |
| `js/app.js` | start-up, connection, header, Settings and Docs dialogs, contributors |
| `js/contributors.js` | the people listed under Contributors (empty for now) |
| `lib/` | OpenChemLib 8.15.0 and 3Dmol.js, vendored so the app works offline |

Scripts are ordinary `<script>` tags sharing one global, `MOL`; their order in `index.html`
matters (config → ui → api → chem → viewer → form → monitor → app).

## Following a run without many requests

A running run is refreshed with one request every 5 s (Settings), which returns only the new
trace events. The molecule list is fetched again only after a step that changed molecules,
and polling pauses while the browser tab is hidden. This matters behind ngrok's free plan
(20,000 requests a month).
