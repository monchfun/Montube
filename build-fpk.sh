#!/bin/bash
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"
command -v fnpack >/dev/null || { echo "fnpack is required to build a Fnos package." >&2; exit 127; }
if [ -d "$ROOT/frontend" ]; then
  command -v npm >/dev/null || { echo "npm is required to build the React/shadcn UI." >&2; exit 127; }
  if [ ! -d "$ROOT/frontend/node_modules" ] && [ -d "$HOME/Git/VidSortBot/fnos/frontend/node_modules" ]; then
    ln -s "$HOME/Git/VidSortBot/fnos/frontend/node_modules" "$ROOT/frontend/node_modules"
  fi
  (cd "$ROOT/frontend" && npm run build)
fi
# Stamp every build so /api/health and the startup log identify which FPK is running.
python3 - "$ROOT" <<'PY'
import re, sys
from pathlib import Path
root = Path(sys.argv[1])
build_id = "montube-" + re.sub(r"\D", "", __import__("datetime").datetime.now().strftime("%Y%m%d%H%M%S"))
main = root / "app" / "main.py"
text = main.read_text()
text = re.sub(r'BUILD_ID = "[^"]*"', f'BUILD_ID = "{build_id}"', text, count=1)
main.write_text(text)
print(f"build id: {build_id}")
PY
# fnOS desktop entries need the packaged ui/ dir (ui/map); rebuild it from ui/ contents.
if [ -d "$ROOT/app/ui" ]; then
  if command -v python3 >/dev/null && command -v gzip >/dev/null; then
    python3 - "$ROOT/app/ui" "$ROOT/app/ui/map" <<'PY'
import gzip, io, sys, tarfile
from pathlib import Path
src, dest = Path(sys.argv[1]), Path(sys.argv[2])
buf = io.BytesIO()
with tarfile.open(fileobj=buf, mode="w") as tar:
    for path in sorted(p for p in src.rglob("*") if p.name != "map" and not str(p.relative_to(src)).startswith("ui/")):
        tar.add(path, arcname="ui/" + str(path.relative_to(src)))
dest.write_bytes(gzip.compress(buf.getvalue(), mtime=0))
print(f"ui/map: {len(dest.read_bytes())} bytes")
PY
  fi
fi
fnpack build
