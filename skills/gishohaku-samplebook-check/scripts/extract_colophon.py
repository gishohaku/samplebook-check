#!/usr/bin/env python3
"""PDFから奥付ページの候補と、奥付6項目の候補を抽出する。

使い方:
    python extract_colophon.py book.pdf [--top 3] [--out result.json]

出力（JSON）:
    pages_total          総ページ数
    page_size            判型の推定（印刷形態を推測する材料。断定には使わない）
    metadata_title       PDFメタデータのタイトル
    textless_pages       テキストがほぼないページ（画像化された奥付・表紙の可能性）
    colophon_candidates  奥付らしいページの上位（スコア順）。各候補に抽出結果つき
    contact_elsewhere    奥付以外で連絡先が見つかったページ（まえがき・著者紹介など）
    hints                Claude への注意点

判定はしない。判定は references/colophon-rules.md に沿って Claude が行う。
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colophon_lib as lib  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--top", type=int, default=2, help="出力する奥付候補ページ数")
    ap.add_argument("--out", help="JSONの保存先（省略時は標準出力）")
    args = ap.parse_args()

    pdf = Path(args.pdf)
    pages = lib.load_pdf_pages(pdf)
    total = len(pages)
    info = lib.pdf_info(pdf)

    textless = [i + 1 for i, p in enumerate(pages) if len(lib.normalize(p).strip()) < 15]

    scored = []
    for i, text in enumerate(pages):
        score, reasons = lib.colophon_score(text, i, total)
        if score > 0:
            scored.append((score, i, reasons))
    scored.sort(key=lambda x: (-x[0], -x[1]))

    candidates = []
    for rank, (score, i, reasons) in enumerate(scored[: args.top]):
        cand = {"page": i + 1, "score": score, "reasons": reasons, "text": lib.compact(pages[i], keep_gaps=True)[:1500]}
        if rank == 0:  # 抽出結果は最有力の1ページだけ（2番目以降は本文で足りる）
            cand["fields"] = lib.extract_fields(pages[i])
        candidates.append(cand)

    # 除外するのは最有力の奥付ページだけ。2番目の候補がまえがきのこともあるため
    candidate_pages = {candidates[0]["page"]} if candidates else set()
    contact_elsewhere = []
    for i, text in enumerate(pages):
        if i + 1 in candidate_pages:
            continue
        c = lib.find_contacts(text)
        if c["emails"] or c["emails_obfuscated"] or c["social_links"] or c["handles"]:
            norm = lib.normalize(text)
            marker = lib.PREFACE_MARKERS.search(norm)
            contact_elsewhere.append(
                {
                    "page": i + 1,
                    "section_hint": marker.group(0) if marker else None,
                    "emails": c["emails"] + c["emails_obfuscated"],
                    "social_links": c["social_links"][:5],
                    "handles": c["handles"][:5],
                    "flagged": c["flagged"],
                }
            )

    hints = []
    warn = lib.cjk_mapping_warning(pdf)
    if warn:
        hints.insert(0, "【最優先】" + warn)
    best = candidates[0] if candidates else None
    if not best or best["score"] < 6:
        hints.append(
            "奥付ページを確信できない。末尾4ページを render_pages.py で画像化し、目視で奥付を探すこと。"
        )
    tail_textless = [p for p in textless if p > total - 4]
    if tail_textless:
        hints.append(
            f"末尾付近にテキストのないページがある（{tail_textless}）。奥付が画像・アウトライン化されている可能性があるので画像で確認すること。"
        )
    if total and len(textless) / total > 0.5:
        hints.append("半数以上のページにテキストがない。スキャン画像のPDFの可能性が高いので、画像での確認を主にすること。")
    if best and best["score"] >= 6:
        hints.append(
            f"奥付候補 p.{best['page']} は、抽出結果を鵜呑みにせず必ず画像でも確認すること（表組みの読み取り崩れがあるため）。"
        )

    result = {
        "file": str(pdf),
        "pages_total": total,
        "page_size": lib.describe_page_size(info),
        "metadata_title": info.get("Title") or None,
        "textless_pages": textless,
        "colophon_candidates": candidates,
        # まえがき・あとがき・著者紹介などのページを先頭に並べる
        "contact_elsewhere": sorted(contact_elsewhere, key=lambda c: (c["section_hint"] is None, c["page"]))[:8],
        "hints": hints,
    }
    lib.dump_json(result, args.out)


if __name__ == "__main__":
    main()
