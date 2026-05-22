# Deploy BhootFM Archive to Fly.io (free)

Total cost: **$0**. Audio is *not* hosted by us — the server 302-redirects to
the existing `dl.bhoot-fm.com` CDN. The deployed image is ~120 MB and serves
only the search UI, transcripts DB, and audio redirects.

## One-time setup (~5 min, you must do these)

### 1. Sign up for Fly.io
- Go to <https://fly.io/app/sign-up>
- Verify your email
- Add a credit card (Fly requires this for abuse prevention; the free tier
  charges $0 if you stay in limits — see <https://fly.io/docs/about/pricing/>)

### 2. Install flyctl
Open PowerShell as Administrator and run:
```powershell
iwr https://fly.io/install.ps1 -useb | iex
```
Close and reopen PowerShell so `flyctl` lands on your PATH.

### 3. Authenticate
```powershell
fly auth login
```
Opens a browser. Click "Continue" on the Fly page.

### 4. Create the app (only once)
```powershell
cd "C:\Users\User\Desktop\ETC\BhootFM Archive"
fly launch --no-deploy --copy-config --name bhoot-fm-archive --region sin
```
- `--no-deploy` so we deploy after we generate the prod DB
- `--name` — Fly app names are globally unique; if `bhoot-fm-archive` is
  taken, pick something else and update `fly.toml` accordingly
- `--region sin` — Singapore, closest free region to Bangladesh

If Fly asks about Postgres / Redis / sentry, say **no** to all (we only need
the web service).

## Every deploy after that

```powershell
.\redeploy.bat
```

That:
1. Re-runs `ingest.py` so any new transcripts land in `archive.db`
2. Strips local-only fields → `archive.prod.db`
3. Builds the Docker image and pushes to Fly

You'll see `https://bhoot-fm-archive.fly.dev` (or your chosen name) printed
at the end.

## How redeployment cycles work

```
transcribe more episodes  →  json sidecars land in transcripts/
                              ↓
                       redeploy.bat
                              ↓
              new ingest + new prod DB + new image
                              ↓
              Fly machine rolls in the new code+DB
```

The transcripts you've already ingested stay; only new ones get added. There
is no DB migration to worry about — each deploy ships a fresh `archive.db`
snapshot built from your local data.

## Limits (and what to do when you hit them)

| Limit | Free allowance | Notes |
|---|---|---|
| Outbound bandwidth | 160 GB / month | We don't serve mp3 bytes (302 redirect); plenty |
| Concurrent machines | Up to 3 shared-cpu-1x VMs | We use 1 |
| Image size | 8 GB | Ours is ~120 MB |
| Cold start | n/a (auto_stop_machines, ~3 sec to wake) | Set in fly.toml |

If `dl.bhoot-fm.com` ever goes down, the audio won't play. The text archive
still works fine.

## Optional: custom domain

```powershell
fly certs add yourdomain.com
```
Then point your DNS A/AAAA record to the IPs `fly` prints.
