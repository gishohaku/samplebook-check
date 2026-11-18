#!/usr/bin/env python3
"""回帰テスト用の合成PDFを作る（実在の本は使わない）。

    python tests/make_fixtures.py

PyMuPDF と日本語の TrueType フォントが必要。生成済みのPDFを tests/fixtures/ に同梱しているので、
通常は実行しなくてよい。フィクスチャの内容を変えたいときだけ使う。
"""
from __future__ import annotations

import glob
from pathlib import Path

import pymupdf

OUT = Path(__file__).resolve().parent / "fixtures"
FONT = next(iter(glob.glob("/usr/share/fonts/**/ipag.ttf", recursive=True)), None)
W, H = 420, 595  # A5


def page(doc, lines, y=60, size=10):
    p = doc.new_page(width=W, height=H)
    for ln in lines:
        p.insert_text((36, y), ln, fontname="jp", fontfile=FONT, fontsize=size)
        y += size + 7
    return p


def build(name, title, toc, preface, body, afterword, colophon, as_image=False):
    doc = pymupdf.open()
    page(doc, [title], y=200, size=20)
    page(doc, ["まえがき", *preface])
    page(doc, ["目次", *[f"{t} ........ {i + 3}" for i, t in enumerate(toc)]])
    for t in toc:
        page(doc, [t, *body])
    page(doc, ["あとがき", *afterword])
    page(doc, colophon, y=380)
    doc.set_metadata({"title": title})
    if as_image:  # 全ページを画像にして、テキストを取り出せないPDFにする
        img = pymupdf.open()
        for p in doc:
            q = img.new_page(width=W, height=H)
            q.insert_image(q.rect, pixmap=p.get_pixmap(dpi=60))
        doc = img
    else:
        doc.subset_fonts()
    OUT.mkdir(exist_ok=True)
    doc.save(OUT / name, garbage=4, deflate=True)


BODY = ["この章では仕組みを順に説明します。", "サンプルコードは付録にまとめています。"]
COLOPHON_OK = [
    "テスト技術書",
    "2026年11月30日 初版第1刷 発行",
    "著 者    山田太郎",
    "発行所    テストサークル",
    "連絡先    taro@yamada-circle.jp",
    "印刷所    日光企画",
]

if __name__ == "__main__":
    assert FONT, "日本語フォント（ipag.ttf）が見つからない"
    build("good.pdf", "テスト技術書", ["第1章 はじめての設定", "第2章 しくみを知る"], ["本書は入門書です。"], BODY, ["お読みいただきありがとうございました。"], COLOPHON_OK)
    build("missing.pdf", "テスト技術書", ["第1章 はじめての設定"], ["本書は入門書です。"], BODY, ["ありがとうございました。"],
          ["2026年11月 発行", "著者：著者名", "連絡先 hoge@mailinator.com"])
    build("contact_in_preface.pdf", "テスト技術書", ["第1章 はじめての設定"], ["ご意見は X: @yamada_taro までお寄せください。"], BODY, ["ありがとうございました。"],
          [ln for ln in COLOPHON_OK if "連絡先" not in ln])
    build("scan.pdf", "テスト技術書", ["第1章 はじめての設定"], ["本書は入門書です。"], BODY, ["ありがとうございました。"], COLOPHON_OK, as_image=True)
    # 架空の本。特定の実在の本をもとにしていない
    build("risky_toc.pdf", "エンジニアのための恋愛入門", ["第1章 出会いを増やす", "第2章 飲み会で関係を進める", "第3章 性的な関係の進め方"],
          ["本書の対象読者", "・恋愛に自信がない方", "・成人の方"], BODY, ["ありがとうございました。"], COLOPHON_OK)
    build("dualuse_ok.pdf", "はじめてのOSINT", ["第1章 OSINTとは", "第2章 公開情報の集め方"],
          ["本書は技術解説のみを目的としています。", "違法行為を助長するものではありません。", "悪用は固くお断りします。", "本書は成人の方を対象とし、未成年には読ませないでください。"],
          BODY, ["ありがとうございました。"], COLOPHON_OK)
    build("dualuse_missing.pdf", "はじめてのOSINT", ["第1章 OSINTとは", "第2章 公開情報の集め方"],
          ["本書はOSINTの入門書です。"], BODY, ["ありがとうございました。"], COLOPHON_OK)
    print("fixtures:", sorted(p.name for p in OUT.glob("*.pdf")))
