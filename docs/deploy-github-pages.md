# Deploy the web app to GitHub Pages

The web app (`app/web/`) is static HTML, CSS and JavaScript, so GitHub Pages can host it.
The workflow `.github/workflows/deploy-web.yml` publishes the `app/web` folder every time it
changes on `main`.

Only the web app goes on Pages. The MolCurator **server** (`scripts/run.sh`) still runs elsewhere
(your machine, a lab server or Kaggle) and must be reachable over HTTPS, e.g. through ngrok.

## Before you start

- **A public repository**, or a paid GitHub plan. GitHub Free offers Pages for public
  repositories only.
- **Admin access** to the repository, to change its Pages settings.
- The workflow file at `.github/workflows/deploy-web.yml` on the `main` branch.

## Steps

1. **Turn on Pages with GitHub Actions.**
   In the repository: **Settings → Pages → Build and deployment → Source: GitHub Actions**.
   Not "Deploy from a branch": that makes GitHub build the repository with Jekyll, which fails.

2. **Push the workflow and the web app to `main`.**
   ```bash
   git add .github/workflows/deploy-web.yml app/web
   git commit -m "Deploy the web app to GitHub Pages"
   git push origin main
   ```
   If your default branch is not `main`, change `branches: [main]` in the workflow first.

3. **Wait for the deployment.**
   Open the **Actions** tab and the **Deploy web app** run. When it finishes, its summary shows
   the address, usually `https://<user-or-org>.github.io/<repository>/`.
   To deploy again without changing files: **Actions → Deploy web app → Run workflow**.

4. **Start the server and make it reachable over HTTPS.**
   A page served over HTTPS can only call an HTTPS server, so use a tunnel:
   ```bash
   MOLCURATOR_CORS_ORIGINS=https://<user-or-org>.github.io scripts/run.sh   # prints the API token
   ngrok http 8000                                                    # prints https://….ngrok-free.app
   ```
   `MOLCURATOR_CORS_ORIGINS` allows only your Pages site to call the server. Use the origin
   only (no `/<repository>/` path). On Kaggle, `notebooks/deploy_kaggle.ipynb` does this part.

5. **Connect the web app to the server.**
   Open the Pages address, click the gear (**Settings**) and enter:
   - **Server address**: the ngrok address, e.g. `https://name.ngrok-free.app`
   - **API token**: the token the server printed

   Click **Test connection**, then **Save**. Each browser stores these once.

## Updating

Change files under `app/web/` and push to `main`; the workflow publishes them in about a
minute. Edits to `templates/documentation.html` and `js/contributors.js` go live the same way.

## If something goes wrong

| Problem | What to do |
|---|---|
| A run called **pages build and deployment** fails with a Jekyll error | That is GitHub's own branch build, not this workflow: Pages is still set to **Deploy from a branch**, so GitHub runs Jekyll on the repository (and `docs/` holds Markdown it tries to build). Set **Settings → Pages → Source** to **GitHub Actions**; that build then stops and only **Deploy web app** publishes |
| The workflow fails at "deploy" with a permissions or environment error | Check that **Settings → Pages → Source** is **GitHub Actions** |
| The workflow fails at "Check the web app files" | A file the app needs is missing from `app/web/`; the log names it |
| The page shows 404 | Wait a minute after the first deployment; use the address from the workflow summary, including the `/<repository>/` path |
| "Cannot reach the MolCurator server" | Is the server running and the tunnel open? Is the address in Settings `https://`? Does `MOLCURATOR_CORS_ORIGINS` match the Pages origin exactly? |
| "The server needs a valid API token" | Enter the token the server printed at its last start (it changes at each start unless `MOLCURATOR_API_TOKEN` is set) |
| The tunnel address changed | Enter the new address in Settings, or use a fixed ngrok domain |

Not tested yet: whether ngrok's free-plan warning page interferes with the browser's CORS
preflight when the app is on Pages. If API calls fail only from Pages, check this first
(the browser's developer console shows the failing request).
