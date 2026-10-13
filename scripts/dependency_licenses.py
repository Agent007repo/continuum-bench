import importlib.metadata
import json

rows = []
for package in importlib.metadata.distributions():
    m = package.metadata
    rows.append(
        {
            "name": m.get("Name"),
            "version": package.version,
            "license": m.get("License-Expression") or m.get("License") or "UNVERIFIED",
        }
    )
print(json.dumps(sorted(rows, key=lambda r: str(r["name"]).lower()), indent=2))
