import json
from pathlib import Path

root = Path(__file__).resolve().parents[1]
files = sorted(p.relative_to(root).as_posix() for p in (root / "results/raw").glob("*.jsonl"))
state = {
    "status": "pending",
    "research_runs": files,
    "reason": "No validated research data and analysis contract exist in this milestone.",
}
path = root / "results/derived/state.json"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_text(json.dumps(state, indent=2) + "\n")
