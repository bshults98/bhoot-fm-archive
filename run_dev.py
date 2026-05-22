"""Dev server launcher with hot reload.

Calling uvicorn through the shell on Windows gets nasty fast — patterns
like `audio/*` get glob-expanded by Git Bash / MSYS / WSL layers before
they reach Click, and the whole command falls apart. Doing it from
Python sidesteps all of that: no shell, no quoting, no expansion.
"""
import sys
import uvicorn


def main() -> int:
    print("Dev server with hot reload — http://127.0.0.1:8000")
    print("Watching: server.py, static/, scripts/, ingest.py, prepare_production_db.py")
    print("Ignoring: audio/, transcripts/, *.db, *.json, .venv/")
    print("Press Ctrl+C to stop.\n")
    try:
        uvicorn.run(
            "server:app",
            host="127.0.0.1",
            port=8000,
            reload=True,
            reload_dirs=["static", "scripts"],
            reload_includes=[
                "server.py",
                "ingest.py",
                "prepare_production_db.py",
            ],
            reload_excludes=[
                "audio/*",
                "transcripts/*",
                "*.db",
                "*.db-journal",
                "*.json",
                ".venv/*",
            ],
        )
    except KeyboardInterrupt:
        print("\nServer stopped.")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
