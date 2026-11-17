#!/usr/bin/env python3
"""Re:VIEW プロジェクトの奥付設定を検査する。

使い方:
    python check_review_config.py <プロジェクトのディレクトリ> [--config config.yml]

Re:VIEW は config.yml の値から奥付を自動生成する（colophon: true のとき）。
主に見るキー:
    booktitle  書名
    aut        著者（文字列・配列・{name: ...} の配列のいずれか）
    pbl        発行所（サークル名を入れることが多い）
    prt        印刷所
    contact    連絡先
    date / history  発行日（history の最初の要素が初版）
    colophon   奥付を出力するか
    inherit    別の設定ファイルを継承

サークル独自のテンプレートでは、奥付を .re ファイルやスタイルファイルに直接書くことがある。
その場合に備えて、プロジェクト内で「奥付らしい記述」があるファイルも探す。

出力はJSON。最終判定は references/colophon-rules.md と formats/review.md に沿って Claude が行う。
ビルド後のPDFがあれば、そちらを正として扱うこと。
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colophon_lib as lib  # noqa: E402

SKIP_DIRS = {".git", "node_modules", "vendor", "webroot", ".bundle"}
SOURCE_EXT = {".re", ".sty", ".tex", ".cls", ".erb", ".html", ".yml", ".yaml"}
TEMPLATE_DEFAULTS = {"著者名", "出版社", "印刷所", "書名", "連絡先", "サークル名"}  # 完全一致
TEMPLATE_SUBSTRINGS = ("サンプル書籍", "Re:VIEWサンプル", "your name")  # 部分一致


def load_config(path: Path, seen: set[Path] | None = None) -> dict:
    """inherit を解決しながら config.yml を読む（後に読んだものが優先）。"""
    seen = seen or set()
    path = path.resolve()
    if path in seen or not path.exists():
        return {}
    seen.add(path)
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    merged: dict = {}
    inherits = data.get("inherit") or []
    if isinstance(inherits, str):
        inherits = [inherits]
    for inh in inherits:
        merged.update(load_config(path.parent / inh, seen))
    merged.update(data)
    return merged


def as_names(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [str(value.get("name", ""))]
    if isinstance(value, list):
        names = []
        for v in value:
            names.extend(as_names(v))
        return [n for n in names if n]
    return [str(value)]


def first_edition(cfg: dict) -> tuple[str | None, str]:
    hist = cfg.get("history")
    if hist:
        try:
            first = hist[0][0] if isinstance(hist[0], list) else hist[0]
            return str(first), "history[0][0]"
        except (IndexError, TypeError):
            pass
    if cfg.get("date"):
        return str(cfg["date"]), "date"
    return None, ""


def is_default(value: str) -> bool:
    v = value.strip().lower()
    return (
        v in {d.lower() for d in TEMPLATE_DEFAULTS}
        or any(sub.lower() in v for sub in TEMPLATE_SUBSTRINGS)
        or bool(lib.PLACEHOLDER.search(value))
    )


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("project")
    ap.add_argument("--config", help="config.yml のパス（省略時は project/config.yml）")
    args = ap.parse_args()

    root = Path(args.project)
    cfg_path = Path(args.config) if args.config else root / "config.yml"
    if not cfg_path.exists():
        cands = sorted(root.rglob("config.yml"))
        cfg_path = cands[0] if cands else cfg_path
    findings: list[dict] = []

    def add(item: str, status: str, detail: str) -> None:
        findings.append({"item": item, "status": status, "detail": detail})

    if not cfg_path.exists():
        lib.dump_json({"error": "config.yml が見つからない", "project": str(root)})
        return

    cfg = load_config(cfg_path)

    # 奥付の出力は maker ごとに設定できる。PDFでは pdfmaker.colophon が最上位の colophon より優先される
    col = {"top": cfg.get("colophon")}
    for maker in ("pdfmaker", "epubmaker"):
        sub = cfg.get(maker)
        if isinstance(sub, dict) and "colophon" in sub:
            col[maker] = sub["colophon"]
    effective_pdf = col.get("pdfmaker", col["top"])
    if effective_pdf:
        add("奥付の出力", "OK", f"PDFの奥付は有効（{col}）")
    else:
        add("奥付の出力", "要確認", f"PDFの自動奥付が有効になっていない（{col}）。独自の奥付ファイルがあるか custom_colophon_files を確認する")

    title = cfg.get("booktitle")
    title_s = title if isinstance(title, str) else (title or {}).get("name") if isinstance(title, dict) else None
    if not title_s:
        add("書名", "NG", "booktitle が未設定")
    elif is_default(title_s):
        add("書名", "要確認", f"booktitle がテンプレートの初期値のまま？: {title_s}")
    else:
        add("書名", "OK", title_s)

    auts = as_names(cfg.get("aut"))
    pbls = as_names(cfg.get("pbl"))
    if not auts and not pbls:
        add("サークル名／発行責任者名", "NG", "aut も pbl も未設定")
    else:
        vals = auts + pbls
        if all(is_default(v) for v in vals):
            add("サークル名／発行責任者名", "要確認", f"テンプレートの初期値のまま？: {vals}")
        else:
            add("サークル名／発行責任者名", "OK", f"aut={auts} pbl={pbls}")

    contact = cfg.get("contact")
    contact_s = ", ".join(as_names(contact))
    if not contact_s:
        add("連絡先", "要確認", "contact が未設定。独自の奥付やまえがき・著者紹介に連絡先があるかを確認する")
    else:
        c = lib.find_contacts(contact_s)
        if c["flagged"]:
            add("連絡先", "要確認", f"{contact_s} / {c['flagged']}")
        elif is_default(contact_s):
            add("連絡先", "要確認", f"テンプレートの初期値のまま？: {contact_s}")
        else:
            add("連絡先", "OK", contact_s)

    first, source = first_edition(cfg)
    if not first:
        add("初回発行日", "NG", "history も date も未設定")
    else:
        dates = lib.find_dates(first)
        if not dates:
            add("初回発行日", "要確認", f"{source} の値を日付として読めない: {first}")
        else:
            iso = dates[0]["iso"]
            note = f"{source} = {first}"
            try:
                age_days = (date.today() - date.fromisoformat(iso)).days if iso else None
            except ValueError:
                age_days = None
            if age_days is not None and age_days > 365 * 2:
                add("初回発行日", "要確認", note + "（2年以上前。既刊でなければテンプレートの初期値の可能性）")
            else:
                add("初回発行日", "OK", note)

    prts = as_names(cfg.get("prt"))
    if not prts:
        add("印刷所名", "条件付き", "prt が未設定。印刷所で印刷する場合は必須（コピー本・電子版のみなら省略可）")
    elif any(is_default(p) for p in prts):
        add("印刷所名", "要確認", f"テンプレートの初期値のまま？: {prts}")
    else:
        add("印刷所名", "OK", ", ".join(prts))

    order = cfg.get("colophon_order")
    if order:
        missing = [k for k in ("aut", "pbl", "prt", "contact") if k not in order]
        if missing:
            add("colophon_order", "要確認", f"colophon_order に {missing} が含まれていない。設定していても奥付に出力されない")

    # 独自奥付の探索
    custom = []
    for p in root.rglob("*"):
        if any(part in SKIP_DIRS for part in p.parts) or not p.is_file() or p.suffix not in SOURCE_EXT:
            continue
        if p.resolve() == cfg_path.resolve():
            continue
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        score, reasons = lib.colophon_score(text, 0, 10)
        if "奥付" in text or "colophon" in text.lower() or score >= 7:
            custom.append({"file": str(p.relative_to(root)), "reasons": reasons[:6]})

    result = {
        "config": str(cfg_path),
        "values": {k: cfg.get(k) for k in ("booktitle", "aut", "pbl", "prt", "contact", "date", "history", "colophon", "colophon_order")} | {"maker_colophon": col},
        "findings": findings,
        "custom_colophon_files": custom[:20],
        "note": "ソース上の設定は出力結果と一致しないことがある（テンプレートの上書き・colophon_order 等）。ビルド後のPDFで最終確認すること。",
    }
    lib.dump_json(result)


if __name__ == "__main__":
    main()
