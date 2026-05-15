# Chrome Web Store — Automated CI/CD Publishing

Automate the publish-to-CWS step so that pushing a version tag triggers
a GitHub Actions workflow that builds the zip and submits it without
touching the dashboard.

---

## One-time manual setup

### 1. Google Cloud project

Create or designate a GCP project. Enable the Chrome Web Store Publish API:

```
https://console.cloud.google.com/apis/library/chromewebstore.googleapis.com
```

### 2. Service account

In the GCP project → **IAM & Admin → Service Accounts** → Create:

- Name: `cws-publisher` (or similar)
- No GCP roles needed (CWS auth is separate)
- Create a JSON key → download it

### 3. Link service account to CWS

In the CWS Developer Dashboard → **Settings → Service account**:

- Paste the service account email (e.g. `cws-publisher@<project>.iam.gserviceaccount.com`)
- Click **Add a service account**

### 4. GitHub Actions secret

In the GitHub repo → **Settings → Secrets and variables → Actions**:

- Name: `CWS_SERVICE_ACCOUNT_JSON`
- Value: contents of the downloaded JSON key file

Also add:
- `CWS_EXTENSION_ID` — the extension ID from the CWS dashboard URL (32-character string)

---

## Workflow file

`packaging/build-chrome-zip.sh` already builds the zip. The workflow calls it,
then uses the [Chrome Web Store Upload Action](https://github.com/mobilefirstllc/cws-publish)
(or direct API calls via `curl`) to upload and publish.

```yaml
# .github/workflows/publish-chrome.yml
name: Publish to Chrome Web Store

on:
  push:
    tags:
      - 'v*'

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Build Chrome zip
        run: bash packaging/build-chrome-zip.sh

      - name: Publish to Chrome Web Store
        uses: mobilefirstllc/cws-publish@latest
        with:
          action: publish
          client_id: ${{ secrets.CWS_CLIENT_ID }}
          client_secret: ${{ secrets.CWS_CLIENT_SECRET }}
          refresh_token: ${{ secrets.CWS_REFRESH_TOKEN }}
          extension_id: ${{ secrets.CWS_EXTENSION_ID }}
          zip_file: dist/claude-usage-chrome-*.zip
```

> **Note:** `mobilefirstllc/cws-publish` uses OAuth2 client credentials
> (client_id + client_secret + refresh_token), not a service account JSON key
> directly. The service account approach requires exchanging for OAuth tokens
> first. Revisit auth flow during implementation — the GCP service account
> JSON key may need to be exchanged for an access token via the Google auth
> library before being passed to the CWS API.

---

## Version bump workflow

Tie publishing to `manifest.json` version bumps. Suggested flow:

1. Edit `chrome-extension/manifest.json` — bump `"version"`
2. `git tag v<version> && git push --tags`
3. GitHub Actions builds and publishes automatically

Could add a helper script:

```bash
# packaging/release.sh <version>
# Updates manifest.json version, commits, tags, pushes
```

---

## Files to create

| File | Purpose |
|------|---------|
| `.github/workflows/publish-chrome.yml` | CI/CD workflow |
| `packaging/release.sh` | Version bump + tag helper |

---

## Blockers before starting

- [ ] GCP project created and CWS API enabled
- [ ] Service account created and JSON key downloaded
- [ ] Service account email added to CWS dashboard
- [ ] `CWS_EXTENSION_ID` known (available after first manual publish)
- [ ] GitHub Actions secrets populated
