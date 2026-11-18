#!/usr/bin/env python3
"""Vivliostyle / Typst / Sphinx（および形式不明）のソースから奥付の記述を探す。

使い方:
    python check_source.py <プロジェクトのディレクトリ> [--format auto|vivliostyle|typst|sphinx|review]

これらの形式には Re:VIEW のような「奥付専用の設定キー」がないため、
1. 形式を判定し、メタデータ（書名・著者など）を設定ファイルから拾う
2. 奥付らしいファイル・箇所をスコアで探し、項目候補を抽出する
という2段構えで情報を集める。判定は Claude が行う。

Re:VIEW と判定された場合は check_review_config.py の利用を促す。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colophon_lib as lib  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "_build", "build", "dist", ".venv", "venv", "__pycache__", ".vivliostyle"}
TEXT_EXT = {".md", ".markdown", ".html", ".htm", ".typ", ".rst", ".txt", ".tex", ".re", ".css", ".js", ".mjs", ".cjs", ".ts", ".py", ".toml", ".yml", ".yaml", ".json"}


def detect_format(root: Path) -> str:
    names = {p.name for p in root.rglob("*") if p.is_file() and not any(s in p.parts for s in SKIP_DIRS)}
    if "catalog.yml" in names and "config.yml" in names:
        return "review"
    if any(n.startswith("vivliostyle.config") for n in names):
        return "vivliostyle"
    if "conf.py" in names and any(n.endswith(".rst") for n in names) or "conf.py" in names and "index.md" in names:
        return "sphinx"
    if any(n.endswith(".typ") for n in names):
        return "typst"
    return "unknown"


def _grab(pattern: str, text: str, flags=re.M) -> list[str]:
    return [m.group(1).strip() for m in re.finditer(pattern, text, flags)]


def metadata(root: Path, fmt: str) -> dict:
    meta: dict = {}
    if fmt == "vivliostyle":
        for cfg in root.rglob("vivliostyle.config.*"):
            t = cfg.read_text(encoding="utf-8", errors="ignore")
            meta[str(cfg.relative_to(root))] = {
                "title": _grab(r"title\s*:\s*['\"`](.+?)['\"`]", t),
                "author": _grab(r"author\s*:\s*['\"`](.+?)['\"`]", t),
                "entry": _grab(r"['\"`]([^'\"`]+\.(?:md|html))['\"`]", t)[:50],
            }
    elif fmt == "typst":
        for f in root.rglob("*.typ"):
            if any(s in f.parts for s in SKIP_DIRS):
                continue
            t = f.read_text(encoding="utf-8", errors="ignore")
            doc = _grab(r"#set\s+document\((.+?)\)", t, re.S)
            if doc:
                meta[str(f.relative_to(root))] = {"set_document": doc}
    elif fmt == "sphinx":
        for conf in root.rglob("conf.py"):
            if any(s in conf.parts for s in SKIP_DIRS):
                continue
            t = conf.read_text(encoding="utf-8", errors="ignore")
            meta[str(conf.relative_to(root))] = {
                k: _grab(rf"^{k}\s*=\s*['\"](.+?)['\"]", t)
                for k in ("project", "author", "copyright", "release", "version")
            }
            meta[str(conf.relative_to(root))]["latex_elements_defined"] = "latex_elements" in t
    return meta


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--format", default="auto")
    args = ap.parse_args()
    root = Path(args.project)
    fmt = detect_format(root) if args.format == "auto" else args.format

    if fmt == "review":
        lib.dump_json({"format": "review", "message": "Re:VIEW プロジェクト。check_review_config.py を使うこと。"})
        return

    candidates = []
    for p in root.rglob("*"):
        if not p.is_file() or p.suffix.lower() not in TEXT_EXT or any(s in p.parts for s in SKIP_DIRS):
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if len(text) > 400_000:
            continue
        score, reasons = lib.colophon_score(text, 0, 10)
        name_bonus = bool(re.search(r"(colophon|okuduke|okuzuke|奥付|imprint)", p.name, re.I))
        if name_bonus:
            score += 5
            reasons.append("ファイル名")
        if score >= 7:
            # ファイル全体ではなく、奥付キーワード周辺だけを抜き出す
            norm = lib.normalize(text)
            idx = max(norm.find("奥付"), 0)
            snippet = norm[max(0, idx - 200) : idx + 2000] if "奥付" in norm else norm[:2200]
            candidates.append(
                {
                    "file": str(p.relative_to(root)),
                    "score": score,
                    "reasons": reasons,
                    "fields": lib.extract_fields(snippet),
                    "snippet": snippet,
                }
            )
    candidates.sort(key=lambda c: -c["score"])

    result = {
        "format": fmt,
        "metadata": metadata(root, fmt),
        "colophon_candidates": candidates[:5],
        "note": "ソースからの抽出は補助的なもの。ビルド後のPDFがあれば extract_colophon.py の結果を正とすること。",
    }
    lib.dump_json(result)


if __name__ == "__main__":
    main()
