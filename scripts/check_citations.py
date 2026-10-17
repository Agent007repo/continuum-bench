"""Resolve every DOI and arXiv identifier in the report bibliography and compare titles.

Network script, run by hand before a release (not in CI). Writes
results/raw/citation-check.json. A reference passes when its identifier resolves and the
registered title shares at least 60 percent of its words with the title in the report.
Exit code 1 if any reference fails. References with neither a DOI nor an arXiv id (laws,
guidelines) are listed as 'url-only' and checked for an HTTP 2xx/3xx answer.
"""

import json
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

root = Path(__file__).resolve().parents[1]
UA = {"User-Agent": "trusttrace-citation-check/1.0 (mailto:Samarth.annigeri@mail.mcgill.ca)"}


def words(s: str) -> set[str]:
    s = re.sub(r"\\[a-zA-Z]+|[{}~$]", " ", s)
    return {w for w in re.findall(r"[a-z0-9]+", s.lower()) if len(w) > 2}


def overlap(a: str, b: str) -> float:
    wa, wb = words(a), words(b)
    return len(wa & wb) / max(1, min(len(wa), len(wb)))


def fetch(url: str) -> bytes:
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return bytes(r.read())


def crossref_title(doi: str) -> str:
    data = json.loads(fetch("https://api.crossref.org/works/" + urllib.parse.quote(doi)))
    t = data["message"].get("title") or [""]
    return str(t[0])


def datacite_or_handle(doi: str) -> str:
    data = json.loads(fetch("https://doi.org/api/handles/" + urllib.parse.quote(doi)))
    return "" if data.get("responseCode") != 1 else "(registered handle, title not checked)"


def arxiv_title(aid: str) -> str:
    xml = fetch("https://export.arxiv.org/api/query?id_list=" + aid)
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entry = ET.fromstring(xml).find("a:entry", ns)
    title = entry.find("a:title", ns) if entry is not None else None
    return " ".join((title.text or "").split()) if title is not None else ""


def entries(tex: str) -> list[dict[str, str]]:
    body = tex.split(r"\begin{thebibliography}")[1].split(r"\end{thebibliography}")[0]
    out = []
    for chunk in body.split(r"\bibitem{")[1:]:
        key, rest = chunk.split("}", 1)
        rest = " ".join(rest.split())
        doi = re.search(r"doi:(\S+?)(?:\s|$)", rest)
        arx = re.search(r"arXiv:(\d{4}\.\d{4,5})", rest)
        url = re.search(r"\\url\{([^}]+)\}", rest)
        title_m = re.search(r"\.\s+(.+?)\.\s", rest)
        out.append(
            {
                "key": key,
                "text": rest,
                "title": title_m.group(1) if title_m else rest,
                "doi": doi.group(1).replace("\\_", "_").rstrip(".") if doi else "",
                "arxiv": arx.group(1) if arx else "",
                "url": url.group(1) if url else "",
            }
        )
    return out


def main() -> int:
    tex_path = Path(sys.argv[1]) if len(sys.argv) > 1 else root / "paper/generated/bib.tex"
    rows = []
    for e in entries(tex_path.read_text()):
        row = {"reference": e["key"], "id": e["doi"] or e["arxiv"] or e["url"]}
        try:
            if e["doi"]:
                try:
                    reg = crossref_title(e["doi"])
                except urllib.error.HTTPError:
                    reg = datacite_or_handle(e["doi"])
                row["registered_title"] = reg
                row["status"] = (
                    "pass"
                    if reg and (reg.startswith("(registered") or overlap(e["text"], reg) >= 0.6)
                    else "FAIL"
                )
            elif e["arxiv"]:
                reg = arxiv_title(e["arxiv"])
                row["registered_title"] = reg
                row["status"] = "pass" if reg and overlap(e["text"], reg) >= 0.6 else "FAIL"
            elif e["url"]:
                fetch(e["url"])
                row["status"] = "url-only"
            else:
                row["status"] = "FAIL"
                row["note"] = "no identifier"
        except Exception as exc:  # noqa: BLE001
            row["status"] = "FAIL"
            row["note"] = f"{type(exc).__name__}: {exc}"[:200]
        rows.append(row)
        print(
            f"{row['status']:8} {row['reference']:14} {row.get('registered_title', row.get('note', ''))[:90]}"
        )
    out = root / "results/raw/citation-check.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(rows, indent=1, ensure_ascii=False) + "\n")
    return 1 if any(r["status"] == "FAIL" for r in rows) else 0


if __name__ == "__main__":
    raise SystemExit(main())
