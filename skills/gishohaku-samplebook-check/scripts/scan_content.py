#!/usr/bin/env python3
"""内容チェックの下準備をする。

1. 全ページのテキストを、読みやすい単位（既定25ページ）に分割して保存する
2. 注意して読むべきページの「ヒント」を、カテゴリ別に出す
3. デュアルユース本に求められる「まえがきの4項目」の記載状況を調べる
4. 企業名が出てくるページを数える（企業の説明は1社2ページまでという規定の確認用）

使い方:
    python scan_content.py book.pdf --out /tmp/gishohaku/content [--chunk 25]

重要: ヒントは単語の出現を拾っているだけで、判定ではない。
技術書では「脆弱性」「攻撃」などの語は普通に出てくるので、ヒントがあることは問題を意味しない。
逆に、ヒントがないページにも問題が潜んでいる可能性があるので、本文は分割ファイルで全体を読むこと。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colophon_lib as lib  # noqa: E402

# 注意して読むべき箇所の目印。語の出現は問題を意味しない。
HINT_TERMS = {
    # 正規表現。部分一致の誤検知（「個性的」の「性的」、「グローバル」の「グロ」など）を避けるため、語の形を絞っている
    "weapons_explosives": [r"爆薬", r"(?<!処理)爆弾(?!処理)", r"起爆", r"火薬", r"銃器", r"(?<![機])銃(?!後)", r"弾薬", r"兵器"],
    "drugs_poisons": [r"麻薬", r"覚醒剤", r"覚せい剤", r"大麻", r"危険ドラッグ", r"脱法ドラッグ", r"毒物", r"劇物", r"毒ガス"],
    "self_harm": [r"自殺", r"自死", r"自傷", r"致死量"],
    "crime_evasion": [r"(住所|自宅|本名|勤務先|身元|個人|アカウント)(の|を)?(特定|割り出|突き止め|調べ上げ)", r"泥酔", r"酔(って|わせ)", r"脱税", r"脱法", r"法の抜け穴", r"マネーロンダリング", r"詐欺", r"なりすまし", r"不正アクセス", r"盗聴", r"ストーキング", r"ストーカー", r"住所特定", r"個人特定", r"身元特定"],
    "dual_use_security": [r"OSINT", r"ペネトレーション", r"エクスプロイト", r"(?i)exploit", r"マルウェア", r"ランサムウェア", r"バックドア", r"クラッキング", r"スクレイピング", r"攻撃手法", r"権限昇格", r"フィッシング"],
    "sexual": [r"(?<![個中理感知慢弾惰属特両異習])性的", r"情事", r"性欲", r"性癖", r"快楽", r"S\s*[〇○◯●Ｏ*＊]\s*X|セ[ッ〇○◯●＊*]?[クッ〇○◯●＊*]ス", r"処女|童貞", r"下ネタ", r"(体|肉体)の?(関係|相性)", r"性行為", r"成人向け", r"R-?18", r"18禁", r"アダルト", r"全裸|半裸|裸体", r"ヌード", r"わいせつ|猥褻", r"不同意"],
    "violence_gore": [r"殺害", r"殺人", r"残虐", r"流血", r"死体", r"グロテスク|グロい|グロ描写", r"拷問", r"虐待"],
    "harassment_discrimination": [r"メンヘラ", r"ヒステリック", r"(宗教|カルト).{0,6}(ハマ|はま|洗脳)", r"陰キャ|コミュ障", r"差別", r"侮辱", r"誹謗", r"中傷", r"晒し", r"炎上させ"],
    "promotion": [r"採用情報", r"採用募集", r"求人", r"中途採用", r"新卒採用", r"(?i)we.?re hiring|we are hiring", r"エントリーはこちら", r"会社概要", r"事業内容", r"弊社", r"製品紹介", r"サービス紹介", r"無料トライアル", r"導入事例"],
}

# 危険性のある技術の本に必要な注意書き。
# required の2点（技術解説のみが目的・悪用の拒否）があれば合格。recommended は記載を求める場合がある4項目の残りで、あれば望ましい。
DISCLAIMER_ELEMENTS = {
    "required_技術解説のみが目的": [r"技術(的な)?解説(のみ|だけ|を目的|が目的)", r"(学習|教育|研究|啓発)(のみ|だけ)?を?目的", r"解説を目的"],
    "required_悪用の拒否・禁止": [r"悪用(を|は|に)?.{0,12}(禁止|禁じ|しないで|お控え|厳禁|拒否|認めません|許しません|お断り)", r"悪用しない(で|こと)"],
    "recommended_違法行為を助長しない": [r"(違法|脱法|犯罪)(行為)?を?(助長|推奨|教唆)(する|し)(もの|ため|意図)?(では|で|は)?(ない|ありません|ございません)"],
    "recommended_成人に限る": [r"未成年", r"成人(の方|向け|に限|である|を対象)", r"18歳(未満|以上)"],
}


def image_pages(pdf: str, min_px: int = 80) -> list[int]:
    """埋め込み画像を含むページ番号を返す（小さな装飾画像は除く）。

    ベクターで描かれた図は対象外。画像の妥当性は判定しない。著者にセルフレビューしてもらう
    ページの一覧として使う。
    """
    import subprocess

    r = subprocess.run(["pdfimages", "-list", pdf], capture_output=True)
    pages: set[int] = set()
    for line in r.stdout.decode("utf-8", errors="replace").splitlines()[2:]:
        cols = line.split()
        if len(cols) < 5 or not cols[0].isdigit():
            continue
        page, typ, w, h = int(cols[0]), cols[2], cols[3], cols[4]
        if typ in ("smask", "stencil"):
            continue
        if w.isdigit() and h.isdigit() and int(w) >= min_px and int(h) >= min_px:
            pages.add(page)
    return sorted(pages)


def compress_ranges(nums: list[int]) -> str:
    """[1,2,3,7,9,10] -> "1-3, 7, 9-10" """
    if not nums:
        return ""
    out, start, prev = [], nums[0], nums[0]
    for n in nums[1:] + [None]:
        if n is not None and n == prev + 1:
            prev = n
            continue
        out.append(f"{start}-{prev}" if start != prev else str(start))
        if n is not None:
            start = prev = n
    return ", ".join(out)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out", default="/tmp/gishohaku/content")
    ap.add_argument("--chunk", type=int, default=25)
    args = ap.parse_args()

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    warn = lib.cjk_mapping_warning(args.pdf)
    if warn:
        print("WARNING: " + warn, file=sys.stderr)
    pages = [lib.normalize(p) for p in lib.load_pdf_pages(args.pdf)]
    total = len(pages)

    # 1. 分割保存
    chunk_files = []
    for start in range(0, total, args.chunk):
        end = min(total, start + args.chunk)
        name = out / f"pages_{start + 1:04d}-{end:04d}.txt"
        with name.open("w", encoding="utf-8") as f:
            for i in range(start, end):
                f.write(f"=== p.{i + 1}\n")
                f.write(lib.compact(pages[i]) + "\n")
        chunk_files.append(str(name))

    # 2. ヒント
    hints: dict[str, list[dict]] = {}
    for cat, terms in HINT_TERMS.items():
        hits = []
        for i, text in enumerate(pages):
            found = sorted({m.group(0) for t in terms for m in [re.search(t, text)] if m})
            if found:
                hits.append({"page": i + 1, "terms": found})
        hints[cat] = hits

    # 3. まえがき4項目
    front = "\n".join(pages[: min(15, total)])
    disclaimer = {}
    for key, pats in DISCLAIMER_ELEMENTS.items():
        pages_hit = [i + 1 for i, t in enumerate(pages) if any(re.search(p, t) for p in pats)]
        disclaimer[key] = {
            "in_front_matter": any(re.search(p, front) for p in pats),
            "pages": pages_hit[:10],
        }

    # 4. 企業名の出現ページ
    companies: dict[str, set[int]] = defaultdict(set)
    for i, text in enumerate(pages):
        for m in lib.COMPANY.finditer(text):
            name = re.sub(r"\s+", "", m.group(0))
            companies[name].add(i + 1)
    company_pages = {k: sorted(v) for k, v in sorted(companies.items(), key=lambda kv: -len(kv[1]))}

    textless = [i + 1 for i, p in enumerate(pages) if len(p.strip()) < 15]
    if total and len(textless) / total > 0.5:
        warn = (warn + " " if warn else "") + (
            "半数以上のページからテキストを取り出せない（スキャン画像やアウトライン化されたPDF）。"
            "この本の内容チェックはテキストではできない。「問題は見当たらない」と報告してはいけない。"
        )
    imgs = sorted(set(image_pages(args.pdf)) | set(textless))

    result = {
        "pages_total": total,
        "chunk_files": chunk_files,
        "textless_pages": textless,
        "image_pages_text": compress_ranges(imgs),
        "hints": hints,
        "dual_use_disclaimer": disclaimer,
        "company_mentions": company_pages,
        "warning": warn,
        "notes": "hints は語の出現のみで判定ではない。会社名は宣伝ページの数え上げ用。画像は判定しない。",
    }
    lib.dump_json(result, str(out / "scan.json"))
    lib.dump_json(result)


if __name__ == "__main__":
    main()
