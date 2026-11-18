#!/usr/bin/env python3
"""一次レビュー: 本文を読む前に、表紙・目次・まえがき・あとがきから内容面のリスクを推定する。

使い方:
    python triage.py book.pdf [--out /tmp/gishohaku/triage.json]

本の「顔」にあたる部分だけを取り出し、注意すべき語が見出しや前書きに出ていないかを調べる。
章や節の見出しに危うい題材がそのまま出ている本は、本文にも問題がある可能性が高い。
逆に、ここで何も出なくても本文に問題がないとは限らない（見出しに出ない記述は拾えない）。

出力（JSON）:
    sections        表紙・目次・まえがき・あとがきの各ページとテキスト
    toc_headings    目次から取り出した見出し行
    signals         注意語に当たった見出し・行（区分ごと）
    adult_target    読者を成人に限る記述と、その文脈（注意書きの一部か、対象読者の指定か）
    notes           Claude への注意点

リスクの段階（高・中・低）の判定は references/triage-rules.md に沿って Claude が行う。
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import colophon_lib as lib  # noqa: E402
from scan_content import HINT_TERMS  # noqa: E402

# 本文用のヒントに加えて、題材そのものが注意を要することを示す語
TOPIC_TERMS = {
    "relationship_sexual_topic": [r"恋愛|交際|異性", r"モテ", r"合コン|婚活|ナンパ|口説", r"浮気|不倫", r"アルコール|飲酒|お酒|飲み会|酔"],
    "identification_privacy": [r"特定|割り出|突き止め", r"身元|個人情報", r"晒", r"OSINT|オシント", r"追跡|尾行", r"監視|盗聴|盗撮"],
    "offensive_security": [r"ハッキング|ハック(?!ス\b)", r"攻撃", r"侵入", r"クラッキング", r"脆弱性", r"マルウェア", r"エクスプロイト"],
    "dangerous_making": [r"製造", r"合成", r"自作.{0,6}(銃|爆|薬)", r"作り方"],
    "religion_politics": [r"宗教", r"勧誘", r"カルト", r"政治"],
    "real_people_incident": [r"実話|実録|体験談", r"暴露|告発|内部事情|裏話", r"逮捕|事件|不祥事|トラブル"],
    "company_promotion": [r"起業|創業|会社を?(作|立ち上げ|設立|起こ)|会社(紹介|概要)", r"事業(紹介|内容)", r"採用|求人", r"(製品|サービス)紹介"],
}

ADULT_TARGET = re.compile(
    r"(対象|読者).{0,300}?(?<![未])(成年|成人|18歳以上)|未成年.{0,15}(読ま|禁止|不可)|成人向け|R-?18", re.S
)

TOC_MARK = re.compile(r"^\s*(目\s*次|もくじ|CONTENTS|Contents|Table of Contents)\s*$", re.M)
TOC_LINE = re.compile(r"((\s?\.){3,}|…{2,}|・{3,}|\s{2,})\s*-?\s*[ivxlcdm\d]{1,4}\s*-?\s*$", re.I)
FRONT_MARK = re.compile(r"^\s*(まえがき|前書き|はじめに|序文|序章|本書について)\s*$", re.M)
BACK_MARK = re.compile(r"^\s*(あとがき|後書き|おわりに|終わりに|おしまいに)\s*$", re.M)


def find_toc_pages(pages: list[str], limit: int = 20) -> list[int]:
    toc = []
    for i, t in enumerate(pages[:limit]):
        n_lines = sum(1 for ln in t.splitlines() if TOC_LINE.search(ln))
        if TOC_MARK.search(t) or (toc and i == toc[-1] + 1 and n_lines >= 5):
            toc.append(i)
    return toc


def toc_headings(text: str) -> list[str]:
    out = []
    for ln in text.splitlines():
        s = re.sub(r"((\s?\.){3,}|…{2,}|・{3,})", " ", ln)
        s = re.sub(r"\s+-?\s*[ivxlcdm\d]{1,4}\s*-?\s*$", "", s, flags=re.I).strip()
        if 2 <= len(s) <= 80 and not TOC_MARK.match(s):
            out.append(s)
    return out


def matches(text: str, groups: dict[str, list[str]]) -> dict[str, list[str]]:
    """区分ごとに、注意語を含む行（短い行のみ）を返す。"""
    found: dict[str, list[str]] = {}
    for line in text.splitlines():
        s = line.strip()
        if not s or len(s) > 120:
            continue
        for cat, pats in groups.items():
            if any(re.search(p, s) for p in pats):
                found.setdefault(cat, [])
                if s not in found[cat]:
                    found[cat].append(s)
    return found


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--out")
    args = ap.parse_args()

    raw = lib.load_pdf_pages(args.pdf)
    pages = [lib.normalize(p) for p in raw]
    total = len(pages)
    warn = lib.cjk_mapping_warning(args.pdf)

    sec: dict[str, list[int]] = {"cover": [0] + ([total - 1] if total > 1 else [])}
    toc = find_toc_pages(pages)
    sec["toc"] = toc
    front = [i for i, t in enumerate(pages[:20]) if FRONT_MARK.search(t)]
    sec["preface"] = sorted({j for i in front for j in (i, i + 1) if j < total and j not in toc})
    back = [i for i in range(max(0, total - 12), total) if BACK_MARK.search(pages[i])]
    sec["afterword"] = sorted({j for i in back for j in (i, i + 1) if j < total})

    sections = {"toc_pages": [i + 1 for i in toc]} | {
        # 目次は toc_headings に整形済みなので本文は載せない。他も先頭だけに絞る
        name: [{"page": i + 1, "text": lib.compact(pages[i])[:1200]} for i in idx]
        for name, idx in sec.items()
        if name != "toc"
    }

    headings: list[str] = []
    for i in toc:
        for h in toc_headings(pages[i]):
            if h not in headings:
                headings.append(h)

    all_terms = {**HINT_TERMS, **TOPIC_TERMS}
    signals = {
        "toc_headings": matches("\n".join(headings), all_terms),
        "cover": matches("\n".join(pages[i] for i in sec["cover"]), all_terms),
        "preface": matches("\n".join(pages[i] for i in sec["preface"]), all_terms),
        "afterword": matches("\n".join(pages[i] for i in sec["afterword"]), all_terms),
    }

    front_back = "\n".join(pages[i] for name in ("cover", "preface", "afterword", "toc") for i in sec[name])
    # 成人に限る記述は、文脈で意味が変わる。
    #   注意書きの一部（悪用の禁止などと並んでいる） → 危険性のある技術の本に認められた例外。マイナスの信号ではない
    #   それ以外（対象読者の指定など）               → 全年齢の原則に反する可能性がある
    adult = []
    for m in ADULT_TARGET.finditer(front_back):
        around = front_back[max(0, m.start() - 150) : m.end() + 150]
        in_disclaimer = bool(re.search(r"悪用|技術解説|違法|脱法|助長", around))
        item = {
            "text": re.sub(r"\s+", " ", m.group(0))[-50:],
            "context": "注意書きの一部" if in_disclaimer else "対象読者の指定など",
        }
        if item not in adult:
            adult.append(item)

    notes = []
    if warn:
        notes.append("【最優先】" + warn)
    if not toc:
        notes.append("目次ページを検出できなかった。本の前のほうのページを render_pages.py で画像化し、章タイトルを確認すること。")
    if not sec["preface"] and not sec["afterword"]:
        notes.append("まえがき・あとがきを検出できなかった。見出しの表記が違う可能性があるので、本の最初と最後のページを画像で確認すること。")
    notes.append("signals は語の出現にすぎない。見出しの文脈で読み、references/triage-rules.md に沿ってリスクを判定すること。")

    result = {
        "pages_total": total,
        "sections": sections,
        "toc_headings": headings[:200],
        "signals": signals,
        "adult_target": adult,
        "notes": notes,
    }
    lib.dump_json(result, args.out)


if __name__ == "__main__":
    main()
