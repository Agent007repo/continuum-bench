"""Read-only Mac capability inventory. No sudo, downloads, model calls or power capture."""

import argparse
import datetime
import json
import platform
import subprocess
from pathlib import Path

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--output", type=Path)
args = parser.parse_args()
if platform.system() != "Darwin":
    parser.error("This preflight must run on your Mac; Linux cannot supply Mac evidence")
timestamp = datetime.datetime.now(datetime.UTC)
output = args.output or Path("results/local") / f"mac-preflight-{timestamp:%Y%m%dT%H%M%SZ}.json"
if output.exists():
    parser.error("Refuse to overwrite an existing preflight record")
commands = [
    ["sw_vers"],
    ["df", "-h", str(Path.home())],
    ["sysctl", "-n", "hw.memsize"],
    ["sysctl", "-n", "hw.model"],
    ["sysctl", "-n", "machdep.cpu.brand_string"],
    ["which", "powermetrics"],
    ["powermetrics", "--help"],
]
records = []
for command in commands:
    try:
        result = subprocess.run(command, capture_output=True, text=True, timeout=20, check=False)
        records.append(
            {
                "command": command,
                "exit_code": result.returncode,
                "stdout": result.stdout,
                "stderr": result.stderr,
            }
        )
    except (OSError, subprocess.TimeoutExpired) as error:
        records.append({"command": command, "error": str(error)})
record = {
    "timestamp": timestamp.isoformat(),
    "platform": platform.platform(),
    "python": platform.python_version(),
    "provenance": "observed:mac-read-only-preflight",
    "power_samples_collected": False,
    "models_loaded": False,
    "commands": records,
}
output.parent.mkdir(parents=True, exist_ok=True)
with output.open("x") as stream:
    json.dump(record, stream, indent=2)
print(
    f"Saved {output}. This is capability inventory, not a power measurement or a verified metering adapter."
)
