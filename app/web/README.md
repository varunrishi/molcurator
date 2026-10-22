# MolCurator web app

Plain HTML, CSS and JavaScript: no build step. The API server serves it at `/` (`scripts/run.sh`,
then open http://127.0.0.1:8000). Any static host works too (e.g. GitHub Pages), pointed at a
server in **Settings**. Open it from a web server rather than as a file on disk: the Docs
dialog reads `templates/documentation.html`, which browsers block for local files.

## What it does

- **Connect** (opens as soon as the page loads): server address and API token, prefilled with
  the last ones used (or a `#token=` link). After a successful connection the app opens the
  agent view; **Not now** keeps the dashboard with the saved settings. The connection status at
  the top reopens it.
- **Agent view** (opens after connecting when the server has Claude): describe the run in plain language,
  e.g. "start from bithiophene, gap 4.0–4.5 eV, 3 rounds", or a TADF run on the S1–T1 gap. Claude turns it into a proposal; the
  view shows the target, the seed drawing, budgets, problems and warnings, and nothing runs until
  **Start run**. Follow-up messages change the proposal; **Edit in dashboard** opens it in the
  form. After starting, the run's progress and curated molecules appear in the conversation.
  Without `ANTHROPIC_API_KEY` on the server, this view and its button are hidden.
- **Switch button** (bottom right): agent view ↔ dashboard. The choice is remembered.
- **New run** (left): pick a preset, choose the property (any single-number property the tools
  compute, in its own unit), set the target window, enter or draw a seed, choose search, PREDICT
  method, QM and budget settings. **Validate hits with QM** is on by default; it is switched off
  when the server has no ORCA. The server checks the config as you edit and shows blocking
  problems and warnings before **Start run**.
- **Runs** (right): pick a run and follow it live: current step, budgets, every step's result,
  LLM or rule decisions. Browse the molecules (values with their level: QM, the PREDICT method
  such as xTB→DFT (corrected), xTB or B97-3c, or ML; the raw xTB value is shown next to a corrected one),
  open one for its 3D geometry, read the summary, run the trajectory evaluator, read the
  process log, stop, resume, download.
- **Header**: connection status, **Docs**, **Source code**, **Settings** (server address, API
  token, refresh interval), light/dark theme.
- **Docs** shows `templates/documentation.html`, including the contributors from
  `js/contributors.js` with their GitHub avatars. Edit the template to change the text.

Every number shown comes from the server. If the server cannot be reached, the app says so;
it never shows estimated or example values instead.

## Files

| File | What it does |
|---|---|
| `index.html` | page layout, dialogs, and the library loader (OpenChemLib and 3Dmol.js from CDNs first, `lib/` as fallback) |
| `css/styles.css` | all styles; colours are tokens at the top (light and dark) |
| `js/config.js` | settings kept in this browser (localStorage) |
| `js/ui.js` | small helpers: escaping, formatting, toasts, copy, downloads |
| `js/api.js` | API client: token, ngrok header, timeouts, readable errors |
| `js/chem.js` | OpenChemLib helpers: quick SMILES check, 2D drawings, the structure editor |
| `js/viewer.js` | 3Dmol.js wrapper for XYZ geometries |
| `js/form.js` | the New run panel |
| `js/monitor.js` | the Runs panel |
| `js/assistant.js` | the agent view: prompt → proposal → start, then live progress |
| `js/app.js` | start-up, Connect dialog, header, Settings and Docs dialogs, contributor cards |
| `js/contributors.js` | the people listed in the documentation (name, email, GitHub, areas) |
| `templates/documentation.html` | text of the Docs dialog, with `{{REPO_URL}}`, `{{API_DOCS_URL}}` and `{{CONTRIBUTORS}}` placeholders |
| `lib/` | OpenChemLib 8.15.0 and 3Dmol.js 2.1.0, the same files as on the CDNs; used when the CDNs cannot be reached (offline, blocked) |

Scripts are ordinary `<script>` tags sharing one global, `MOL`; their order in `index.html`
matters (config → contributors → ui → api → chem → viewer → form → monitor → assistant → app).

The two structure libraries load from jsDelivr / unpkg / cdnjs first and from `lib/` only if
those fail or take longer than 8 s each. The app's own stylesheet (`css/styles.css`) and the
fonts' CSS (Google Fonts) are not affected: the first is always served with the app, the second
always comes from Google.

## Following a run without many requests

A running run is refreshed with one request every 5 s (Settings), which returns only the new
trace events. The molecule list is fetched again only after a step that changed molecules,
and polling pauses while the browser tab is hidden. This matters behind ngrok's free plan
(20,000 requests a month).
