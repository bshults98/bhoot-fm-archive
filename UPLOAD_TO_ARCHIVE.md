# Upload mp3s to Internet Archive

Why: Internet Archive (archive.org) is the right permanent home for these
broadcast files. **Free, no quota, won't disappear, real CDN with Range
support, no egress fees.** It's also where this kind of preservation work
belongs ethically — IA is a non-profit library with a clear DMCA process.

Each episode becomes its own IA item at
`https://archive.org/details/bhoot-fm-YYYY-MM-DD`. After upload, our
production DB rewrites every `mp3_url` to point there instead of
dl.bhoot-fm.com.

## One-time setup (~3 min)

### 1. Create an Internet Archive account
- <https://archive.org/account/signup>
- Free. Verify email.

### 2. Get your S3-style keys
- <https://archive.org/account/s3.php> (while logged in)
- Two strings: an **access key** and a **secret key**

### 3. Configure the `ia` CLI once
```powershell
cd "C:\Users\User\Desktop\ETC\BhootFM Archive"
.\.venv\Scripts\Activate.ps1
ia configure
```
- It'll ask for your IA email + password
- Stores credentials at `%USERPROFILE%\.config\internetarchive\ia.ini`

Alternatively, set env vars (don't commit these anywhere):
```powershell
$env:IA_S3_ACCESS_KEY = "your-access-key"
$env:IA_S3_SECRET_KEY = "your-secret-key"
```

## Upload

```powershell
# Test with one episode first (fast sanity check)
python scripts/upload_to_archive.py --limit 1

# Then everything
python scripts/upload_to_archive.py
```

- ~487 episodes × ~25 MB ≈ 12 GB total upload
- IA's S3 endpoint is reasonably fast (~10-30 MB/s depending on geography)
- Estimate: **2-4 hours** on a typical home connection
- **Resumable**: writes `ia_manifest.json` after each upload. Re-run any time.

You can run only a year at a time if you want:
```powershell
python scripts/upload_to_archive.py --year 2019
```

## After upload

When `redeploy.bat` runs, `prepare_production_db.py` automatically:
1. Strips local file paths
2. **Reads `ia_manifest.json` and rewrites every `mp3_url` to the IA URL**
3. Vacuums + ships

So once you've uploaded everything, the deployed archive serves audio from
archive.org with zero dependency on dl.bhoot-fm.com.

## Metadata applied to each item

| Field | Value |
|---|---|
| identifier | `bhoot-fm-2019-04-26` (date-based) |
| title | `Bhoot FM — 26 April 2019` |
| creator | RJ Russell |
| publisher | Radio Foorti 88.0 FM |
| date | 2019-04-26 |
| language | ben |
| mediatype | audio |
| collection | opensource_audio |
| subject | Bhoot FM, ভূত এফএম, RJ Russell, Radio Foorti, Bangla horror, … |
| description | Bhoot FM is a Bangla-language horror radio show … |

That metadata makes each episode discoverable on archive.org's own search too.

## If you ever need to re-upload one

```powershell
python scripts/upload_to_archive.py --date 2019-04-26 --force
```

## If IA flags something

IA honours DMCA. If the rights holder ever requests takedown, items can be
darkened by their team. Our site keeps working in either case because the
`mp3_url` field would just 404 — search and transcripts still work.
