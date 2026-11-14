"""Start a throwaway local Postgres (pgserver) and print its connection URI. Keeps running until Ctrl-C.
Usage: .venv/bin/python dev/pg.py            # data dir .data/pg, URI written to .data/pg.uri
"""
import os, sys, time, pathlib
import pgserver

# optional argument: data directory (tests pass a temp dir for a fresh database every run)
custom = pathlib.Path(sys.argv[1]) if len(sys.argv) > 1 else None
root = pathlib.Path(__file__).resolve().parent.parent / '.data'
root.mkdir(exist_ok=True)
srv = pgserver.get_server(custom or (root / 'pg'), cleanup_mode='stop' if custom else None)
uri = srv.get_uri()
if not custom: (root / 'pg.uri').write_text(uri)
print(uri, flush=True)
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
