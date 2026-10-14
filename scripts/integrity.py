import hashlib
import json
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
errors = []
tracked = subprocess.check_output(["git", "ls-files", "-z"], cwd=root).decode().split("\0")
for name in filter(None, tracked):
    p = root / name
    if p.suffix in {".md", ".tex", ".html", ".yaml", ".yml"}:
        if chr(8212) in p.read_text():
            errors.append("Forbidden punctuation: " + name)
    if name in {".env", ".env.local"}:
        errors.append("Secret environment file tracked: " + name)
pin = json.loads((root / "configs/preregistration.json").read_text())
actual = hashlib.sha256((root / "PREREGISTRATION.md").read_bytes()).hexdigest()
if actual != pin["sha256"]:
    errors.append(
        "Preregistration changed: add a new protocol and dated deviation, do not overwrite."
    )
if errors:
    raise SystemExit("\n".join(errors))
print("Integrity checks passed; this is not a substitute for gitleaks.")
