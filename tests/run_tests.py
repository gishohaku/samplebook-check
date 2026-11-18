#!/usr/bin/env python3
"""スクリプトの回帰テスト。正規表現やヒント語を直したら必ず実行する。

    python tests/run_tests.py

tests/fixtures/ の合成PDFにスクリプトをかけ、出力が期待どおりかを確かめる。
Claude の判定そのものは対象外（そちらは skills/gishohaku-samplebook-check/evals/ のケースで確かめる）。
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
ROOT = REPO / "skills" / "gishohaku-samplebook-check"  # スキル本体
FIX = REPO / "tests" / "fixtures"
sys.path.insert(0, str(ROOT / "scripts"))
import colophon_lib as lib  # noqa: E402

results: list[tuple[bool, str]] = []


def check(name: str, cond: bool) -> None:
    results.append((bool(cond), name))


def run(script: str, *args: str) -> dict:
    out = subprocess.run([sys.executable, str(ROOT / "scripts" / script), *args], capture_output=True, text=True)
    lines = [ln for ln in out.stdout.splitlines() if ln.startswith("{")]
    return json.loads(lines[-1]) if lines else {"_stderr": out.stderr, "_code": out.returncode}


tmp = tempfile.mkdtemp(prefix="gishohaku-test-")

# --- 奥付の抽出 ---
d = run("extract_colophon.py", str(FIX / "good.pdf"))
c = d["colophon_candidates"][0]
f = c["fields"]
check("good: 奥付は最終ページ", c["page"] == d["pages_total"])
check("good: 初版の日付を取得", any(x["iso"] == "2026-11-30" and x["edition"] == "first" for x in f["dates"]))
check("good: メールアドレスを取得（ハイフン入り）", "taro@yamada-circle.jp" in f["contacts"]["emails"])
check("good: 印刷所を取得", "日光企画" in f["known_printers"])
check("good: 項目と値の間の空白が残る", "山田太郎" in c["text"] and "者山田太郎" not in c["text"])
check("ラベル: 字間が空いた「著 者」も拾う", any("山田太郎" in x for x in f["labeled_lines"]["author"]))
check("good: 指摘なし", not f["contacts"]["flagged"] and not f["placeholders"])

d = run("extract_colophon.py", str(FIX / "missing.pdf"))
f = d["colophon_candidates"][0]["fields"]
check("missing: 年月のみの日付", any(x.get("month_only") for x in f["dates"]))
check("missing: 使い捨てメールを検出", any("使い捨て" in x["reason"] for x in f["contacts"]["flagged"]))
check("missing: テンプレートの初期値を検出", any("著者名" in x for x in f["placeholders"]))

d = run("extract_colophon.py", str(FIX / "contact_in_preface.pdf"))
check("preface: 奥付に連絡先なし", not d["colophon_candidates"][0]["fields"]["contacts"]["emails"])
check("preface: まえがきの連絡先を検出", any(x["section_hint"] == "まえがき" and "@yamada_taro" in x["handles"] for x in d["contact_elsewhere"]))

d = run("extract_colophon.py", str(FIX / "scan.pdf"))
check("scan: 画像で確認するよう案内", any("画像" in h for h in d["hints"]))

# --- 一次レビュー ---
d = run("triage.py", str(FIX / "good.pdf"))
check("good: 目次を検出", len(d["toc_headings"]) >= 2)
check("good: 見出しに注意信号なし", not d["signals"]["toc_headings"] and not d["adult_target"])

d = run("triage.py", str(FIX / "risky_toc.pdf"))
toc = json.dumps(d["signals"]["toc_headings"], ensure_ascii=False)
check("risky: 飲酒の見出しを検出", "飲み会" in toc)
check("risky: 性的な見出しを検出", "性的な関係" in toc)
check("risky: 成人限定は「対象読者の指定」", any(a["context"] == "対象読者の指定など" for a in d["adult_target"]))

d = run("triage.py", str(FIX / "dualuse_ok.pdf"))
check("dualuse: OSINTの見出しを検出", "OSINT" in json.dumps(d["signals"]["toc_headings"], ensure_ascii=False))
check("dualuse: 成人限定は「注意書きの一部」のみ", d["adult_target"] and all(a["context"] == "注意書きの一部" for a in d["adult_target"]))

# --- 内容チェックの下準備 ---
d = run("scan_content.py", str(FIX / "dualuse_ok.pdf"), "--out", tmp + "/a")
dd = d["dual_use_disclaimer"]
check("dualuse: 必須の文言2点あり", all(v["in_front_matter"] for k, v in dd.items() if k.startswith("required_")))
check("dualuse: 警告なし", not d["warning"])
check("dualuse: 本文ファイルに余分な空白なし", "  " not in Path(d["chunk_files"][0]).read_text(encoding="utf-8"))

d = run("scan_content.py", str(FIX / "dualuse_missing.pdf"), "--out", tmp + "/d")
check("dualuse_missing: 必須の文言がどちらもない", not any(v["pages"] for k, v in d["dual_use_disclaimer"].items() if k.startswith("required_")))

d = run("scan_content.py", str(FIX / "good.pdf"), "--out", tmp + "/b")
check("good: 必須の文言なし（一般の本）", not any(v["pages"] for k, v in d["dual_use_disclaimer"].items() if k.startswith("required_")))

d = run("scan_content.py", str(FIX / "scan.pdf"), "--out", tmp + "/c")
check("scan: テキストを取り出せない警告", "取り出せない" in (d["warning"] or ""))

# --- 個別の関数（過去に直した誤検知・見落とし）---
check("日付: 英語・平成", [x["iso"] for x in lib.find_dates("January 18, 2026 / 平成30年10月8日")] == ["2026-01-18", "2018-10-08"])
check("ラベル: Circle:", bool(re.search(lib.LABELS["circle"], "Circle: Foo", re.I)))
check("ラベル: メールの circle は拾わない", not re.search(lib.LABELS["circle"], "taro@yamada-circle.jp", re.I))
check("連絡先: コードの @string は除外", lib.find_contacts('android:text="@string/app" @Override')["handles"] == [])
check("印刷所: K-9 と K9 を同じに扱う", lib.known_printer_hits("印刷所 K9") == ["k-9"] and lib.known_printer_hits("印刷所 K-9") == ["k-9"])
check("印刷所: PICO を拾い、別の語の一部は拾わない", lib.known_printer_hits("印刷 PICO") == ["pico"] and lib.known_printer_hits("Picoscope / K-90") == [])
check("会社名: 助詞で切る", lib.COMPANY.search("株式会社テックホゲの製品紹介").group(0) == "株式会社テックホゲ")

import scan_content as sc  # noqa: E402


def hit(cat: str, text: str) -> bool:
    return any(re.search(p, text) for p in sc.HINT_TERMS[cat])


check("ヒント: 「個性的」は性的に当たらない", not hit("sexual", "個性的なキャラクター"))
check("ヒント: 「グローバル」は暴力に当たらない", not hit("violence_gore", "グローバル変数"))
check("ヒント: 伏せ字を検出", hit("sexual", "S〇X") and hit("sexual", "セッ〇ス"))
check("ヒント: 「セールス」は伏せ字に当たらない", not hit("sexual", "セールス資料"))
check("ヒント: 住所の特定を検出", hit("crime_evasion", "住所の特定"))

ok = sum(1 for r, _ in results if r)
for r, name in results:
    if not r:
        print("FAIL:", name)
print(f"{ok}/{len(results)} passed")
sys.exit(0 if ok == len(results) else 1)
