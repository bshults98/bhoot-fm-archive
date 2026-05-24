"""Upload `archive.prod.db` to the HF Dataset repo that the Space image
pulls from at build time.

Why this exists
---------------
HF Spaces have a 1 GB Git Storage limit, and every redeploy used to push a
fresh ~190 MB copy of `archive.prod.db` to the Space's LFS store. The
orphan-branch trick in `redeploy_hf.bat` resets git history each push but
does NOT garbage-collect orphaned LFS blobs, so the LFS bucket grew by
~190 MB per deploy until we filled the quota.

Fix: take the DB out of the Space repo entirely. Host it on an HF Dataset
(generous quota, separate from Space storage) and have the Dockerfile
`urlretrieve` it during image build. The Space repo stays a few hundred
KB forever.

One-time setup
--------------
1. `pip install huggingface_hub`         (already in requirements.txt)
2. `huggingface-cli login`               (saves a token to ~/.cache/huggingface)
   Token needs *write* access to your namespace; create one at
   https://huggingface.co/settings/tokens .
3. Run this script. It creates the dataset repo on first run.

Every subsequent redeploy: `redeploy_hf.bat` invokes this automatically.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

DATASET_REPO = "xer2ten/bhoot-fm-archive-db"
LOCAL_DB = Path(__file__).resolve().parent.parent / "archive.prod.db"


def main() -> int:
    try:
        from huggingface_hub import HfApi
    except ImportError:
        print(
            "ERROR: huggingface_hub not installed. Run:\n"
            "    pip install huggingface_hub",
            file=sys.stderr,
        )
        return 2

    if not LOCAL_DB.exists():
        print(
            f"ERROR: {LOCAL_DB} not found. "
            "Run `python prepare_production_db.py` first.",
            file=sys.stderr,
        )
        return 1

    size_mb = LOCAL_DB.stat().st_size / (1024 * 1024)
    api = HfApi(token=os.environ.get("HF_TOKEN") or None)

    # Create the dataset repo on the first run; subsequent calls no-op.
    api.create_repo(
        repo_id=DATASET_REPO,
        repo_type="dataset",
        exist_ok=True,
        private=False,   # public — the contents are already exposed via the search API
    )

    print(f"Uploading {LOCAL_DB.name} ({size_mb:.1f} MB) -> dataset {DATASET_REPO}")
    api.upload_file(
        path_or_fileobj=str(LOCAL_DB),
        path_in_repo="archive.prod.db",
        repo_id=DATASET_REPO,
        repo_type="dataset",
        commit_message=f"Refresh production DB ({size_mb:.0f} MB)",
    )
    print("Done. The Dockerfile will fetch this on the next Space build.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
