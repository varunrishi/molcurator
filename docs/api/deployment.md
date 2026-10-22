# Running the server

## On your own machine

```bash
scripts/setup.sh             # once: Python environment (.venv), xtb, .env
./run.sh --install           # once: the API server's packages (fastapi, uvicorn)
./run.sh                     # http://127.0.0.1:8000
```

Open http://127.0.0.1:8000, click the connection pill (or the gear) and paste the API token
`run.sh` printed. Set `MOLCURATOR_API_TOKEN` in `.env` to keep the same token across restarts.

`./run.sh --help` lists the options (`--host`, `--port`, `--install`). By default the server
listens on 127.0.0.1 only.

## Sharing it for testing (tunnel)

Keep the server on 127.0.0.1 and put a tunnel in front of it; the tunnel gives a public HTTPS
address. Always keep authentication on: anyone with the address could otherwise start runs.

ngrok (free plan: one fixed `*.ngrok-free.app` domain, 1 GB and 20,000 requests a month):

```bash
ngrok http 8000              # fixed address: ngrok http --url=<your-domain>.ngrok-free.app 8000
                             # (older ngrok agents use --domain instead of --url)
```

ngrok shows a warning page before HTML pages on the free plan; visitors click through once.
The web app sends the `ngrok-skip-browser-warning` header with its API requests, so API calls
are not affected.

Each refresh of a running run is one request (every 5 s by default; change it in the web
app's Settings). Watching a run for an hour at 5 s is about 720 requests.

## On Kaggle

`notebooks/deploy_kaggle.ipynb` installs everything in a Kaggle notebook, starts the server
from `/kaggle/working/molcurator` and opens an ngrok tunnel. Its first cell lists what to set
up first (Internet access, the `NGROK_AUTHTOKEN` secret, the code as a Kaggle Dataset or a
Git URL).

Things to know:
- The session is temporary. Download each run (web app: **Download → Whole run**, or the
  archive endpoint) before it ends; files under `/kaggle/working` are kept only if you save a
  notebook version.
- ORCA is not installed there (licence), so runs use xTB (and ML) only: QM is off.
- A CPU session is enough; xTB does not use a GPU.

## Security checklist

- Authentication on (the default). Share the token only with people who should start runs.
- `MOLCURATOR_MAX_RUNS` limits how many runs can use the machine at once (default 1).
- The API only reads and writes inside the runs folder; ids are checked so they cannot point
  outside it.
- Restrict `MOLCURATOR_CORS_ORIGINS` if the web app is hosted at a known address.
