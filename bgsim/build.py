"""Builds the web page from bgsim/template.html and data/results.json.

The template is an HTML fragment (starts with <title> and <style>, without
<!doctype>/<html>/<head>/<body>). The placeholder /*__DATA__*/null is replaced
with JSON {"results": ..., "history": ...}.

Output: docs/index.html, a standalone page (GitHub Pages / local viewing).
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = ROOT / "bgsim" / "template.html"
DOCS = ROOT / "docs" / "index.html"
PLACEHOLDER = "/*__DATA__*/null"


def build() -> None:
    results = json.loads((ROOT / "data" / "results.json").read_text(encoding="utf-8"))
    hist_path = ROOT / "data" / "history.json"
    history = json.loads(hist_path.read_text(encoding="utf-8")) if hist_path.exists() else []
    tpl = TEMPLATE.read_text(encoding="utf-8")
    if PLACEHOLDER not in tpl:
        raise RuntimeError(f"Template is missing the placeholder {PLACEHOLDER}")
    payload = json.dumps({"results": results, "history": history}, ensure_ascii=False,
                         separators=(",", ":")).replace("</", "<\\/")
    fragment = tpl.replace(PLACEHOLDER, payload)
    DOCS.parent.mkdir(parents=True, exist_ok=True)
    DOCS.write_text(
        "<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "<style>html{color-scheme:light dark}body{margin:0}img{max-width:100%}"
        "[hidden]{display:none!important}</style>\n</head>\n<body>\n"
        + fragment + "\n</body>\n</html>\n", encoding="utf-8")


if __name__ == "__main__":
    build()
    print(f"Wrote {DOCS.relative_to(ROOT)}")
