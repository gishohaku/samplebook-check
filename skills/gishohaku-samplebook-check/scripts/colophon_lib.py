"""奥付チェック用の共通ロジック。

PDF・ソースファイルのどちらから得たテキストにも同じ抽出処理をかけられるよう、
ここでは「テキスト → 候補」の変換だけを扱う。判定（OK/NG）は行わない。
最終判定は Claude が references/colophon-rules.md に沿って行う。
"""

from __future__ import annotations

import re
import subprocess
import unicodedata
from datetime import date
from pathlib import Path

HERE = Path(__file__).resolve().parent
REFERENCES = HERE.parent / "references"

# ---------------------------------------------------------------------------
# 正規化
# ---------------------------------------------------------------------------

_CJK = r"[\u3040-\u30ff\u3400-\u9fff\uf900-\ufaff々〆ヵヶー・]"


def _base(text: str) -> str:
    t = unicodedata.normalize("NFKC", text)
    # ソフトハイフンや各種ハイフンは、メールアドレス・URL の検出を妨げるので ASCII に寄せる
    t = t.replace("\u00ad", "-")
    return re.sub("[\u2010\u2011\u2012\u2212]", "-", t)


def normalize(text: str) -> str:
    """照合用の正規化。全角英数を半角に寄せ、日本語の文字間の空白をすべて詰める。

    PDFの抽出テキストは「著 者」「発　行　所」のように字間に空白が入りやすいので、
    ラベルや語の検出の前に必ず通す。
    """
    return re.sub(rf"(?<={_CJK})[ \t]+(?={_CJK})", "", _base(text))


def compact(text: str, keep_gaps: bool = False) -> str:
    """Claude に読ませるテキスト用。連続する空白を1つにし、空行を除く。

    pdftotext -layout の出力は桁揃えの空白が多く、そのまま読むとトークンを浪費する。
    keep_gaps=True のときは、2つ以上続く空白を「項目と値の区切り」として1つ残す
    （奥付の「著者    山田太郎」が「著者山田太郎」にならないようにする）。
    """
    t = _base(text)
    if keep_gaps:
        t = re.sub(rf"(?<={_CJK})[ \t](?![ \t])(?={_CJK})", "", t)  # 字間の1つだけの空白は詰める
    else:
        t = re.sub(rf"(?<={_CJK})[ \t]+(?={_CJK})", "", t)
    t = re.sub(r"[ \t\u3000]+", " ", t)
    return "\n".join(ln.strip() for ln in t.splitlines() if ln.strip())


def dump_json(obj, out: str | None = None) -> None:
    """JSON をインデントなしで出力する（インデントの空白もトークンになるため）。"""
    import json

    text = json.dumps(obj, ensure_ascii=False, separators=(",", ":"), default=str)
    if out:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(text, encoding="utf-8")
        print(f"saved: {out}")
    else:
        print(text)


# ---------------------------------------------------------------------------
# ラベル・パターン定義
# ---------------------------------------------------------------------------

# 奥付の各項目を示すラベル。行頭付近にあることが多いが、表組みでは行の途中にも出る。
LABELS = {
    "title": r"(書名|タイトル|題名|Title)",
    "circle": r"(発行所|発行元|発行サークル|サークル名?|\bCircle\b\s*[:：]|Publisher)",
    "author": r"(著者|著\s*[:：]|発行者|発行人|発行責任者|編者|編集|執筆|Author|Writer)",
    "contact": r"(連絡先|お問い?合わ?せ|問合せ|Contact|E-?mail|Mail|メール|Web|URL|Twitter|Bluesky|GitHub|^X\s*[:：(（]|\bX\s*[:：])",
    "printer": r"(印刷所|印刷・製本|印刷製本|印刷|製本|Printed\s*(by|at)|Printer|Printing)",
    "date": r"(初版|第1版|初刷|第1刷|1st\s*edition|発行日|発行(?!所|元|者|人|責任)|発売|刊行|頒布日|公開日)",
}

# 奥付ページらしさのスコア
COLOPHON_KEYWORDS = {
    "奥付": 5,
    "初版": 3,
    "第1刷": 3,
    "初刷": 3,
    "第1版": 2,
    "発行日": 3,
    "印刷所": 3,
    "印刷・製本": 3,
    "発行所": 2,
    "発行者": 2,
    "発行人": 2,
    "発行": 1,
    "著者": 1,
    "連絡先": 2,
    "お問い合わせ": 1,
    "©": 1,
    "(C)": 1,
    "Copyright": 1,
    "無断": 1,
    "Printed": 1,
}

DATE_PATTERNS = [
    # 2026年11月17日
    re.compile(r"(?P<y>(?:19|20)\d{2})\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"),
    # 2026-11-17 / 2026/11/17 / 2026.11.17
    re.compile(r"(?<!\d)(?P<y>(?:19|20)\d{2})[./-](?P<m>\d{1,2})[./-](?P<d>\d{1,2})(?!\d)"),
    # 令和8年11月17日
    re.compile(r"令和\s*(?P<ry>\d{1,2}|元)\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日"),
]
_MONTHS = "January|February|March|April|May|June|July|August|September|October|November|December"
_MONTH_NUM = {m.lower()[:3]: i + 1 for i, m in enumerate(_MONTHS.split("|"))}
# January 18, 2026 / Jan. 18, 2026
DATE_EN = re.compile(rf"(?P<mon>{_MONTHS}|Jan|Feb|Mar|Apr|Jun|Jul|Aug|Sep|Sept|Oct|Nov|Dec)\.?\s+(?P<d>\d{{1,2}})(?:st|nd|rd|th)?,?\s+(?P<y>(?:19|20)\d{{2}})", re.I)
# 平成30年10月8日
DATE_HEISEI = re.compile(r"平成\s*(?P<hy>\d{1,2}|元)\s*年\s*(?P<m>\d{1,2})\s*月\s*(?P<d>\d{1,2})\s*日")
# 年月のみ（日がない。「吉日」もここに入る）
MONTH_ONLY_PATTERN = re.compile(r"(?P<y>(?:19|20)\d{2})\s*年\s*(?P<m>\d{1,2})\s*月(?!\s*\d{1,2}\s*日)")

FIRST_EDITION = re.compile(r"(初版|第1版|初刷|第1刷|1st|first\s+edition|v1\.0(?!\.\d*[1-9])|ver\.?\s*1\.0)", re.I)
LATER_EDITION = re.compile(r"(第\s*([2-9]|\d{2,})\s*(版|刷)|改訂|増補|再版|[2-9](nd|rd|th)\s*edition|v[2-9]\.\d|ver\.?\s*[2-9])", re.I)

EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
EMAIL_OBFUSCATED = re.compile(
    r"[A-Za-z0-9._%+-]+\s*[\[\(（]\s*(?:at|アット)\s*[\]\)）]\s*[A-Za-z0-9.-]+\.[A-Za-z]{2,}", re.I
)
URL = re.compile(r"https?://[^\s)）」』>\]]+")
SOCIAL_DOMAIN = re.compile(
    r"(?:https?://)?(?:www\.)?(x\.com|twitter\.com|bsky\.app|[a-z0-9-]+\.bsky\.social|facebook\.com|"
    r"instagram\.com|github\.com|threads\.net|linkedin\.com|misskey\.io|mstdn\.jp|qiita\.com|zenn\.dev|note\.com)"
    r"(/[^\s)）」』]*)?",
    re.I,
)
# コード中のアノテーションやリソース参照（@string、@Override など）はSNSアカウントではない
HANDLE_STOPWORDS = {
    "string", "drawable", "layout", "id", "color", "dimen", "style", "mipmap", "android", "anim", "xml", "raw", "menu",
    "override", "param", "return", "returns", "throws", "test", "media", "import", "keyframes", "font-face", "charset",
    "deprecated", "suppresslint", "suppresswarnings", "composable", "preview", "inject", "component", "autowired",
    "entity", "property", "staticmethod", "classmethod", "dataclass", "author", "since", "see", "link", "type",
    "types", "latest", "next", "app", "main", "objc", "available", "mainactor", "state", "binding", "published",
    "observable", "environment", "escaping", "discardableresult", "ibaction", "iboutlet", "click", "submit", "input",
    "output", "click.prevent", "ts-ignore", "ts-expect-error", "jsx", "apply", "tailwind", "layer", "extend",
}
HANDLE = re.compile(r"(?<![A-Za-z0-9._%+-])@[A-Za-z0-9_]{2,30}(?:\.[A-Za-z0-9-]+)*")

PLACEHOLDER = re.compile(
    r"(example\.(com|org|net|jp)|\bTODO\b|FIXME|TBD|\bxxx+\b|hoge|fuga|piyo|foo@|"
    r"your[-_ ]?(name|mail|email|address)|〇〇|○○|◯◯|●●|△△|xx+年|XX+月|ダミー|"
    r"本のタイトル|ここに入|ここに記|未定)",
    re.I,
)
# 「著者：著者名」のように、ラベルの値がテンプレートの初期値のまま残っているケース
TEMPLATE_VALUE = re.compile(r"[:：]\s*(著者名|サークル名|書名|タイトル|発行者名|印刷所名|連絡先|メールアドレス|出版社|YYYY|yyyy)\s*$")

# 会社名（広報規定の確認用）
_NAME = r"[ァ-ヶーA-Za-z0-9&＆・\u3400-\u9fff]{1,20}"  # ひらがなを含めない（助詞で名前が終わるように）
COMPANY = re.compile(
    rf"((?:株式会社|有限会社|合同会社)\s*{_NAME}|{_NAME}\s*(?:株式会社|有限会社|合同会社)|"
    r"[A-Z][A-Za-z0-9&.\- ]{1,30}\s(?:Inc\.|Co\.,?\s*Ltd\.|LLC|Corporation|K\.K\.))"
)

PREFACE_MARKERS = re.compile(r"(まえがき|はじめに|序文|著者紹介|著者について|プロフィール|About\s+the\s+author|あとがき|おわりに)", re.I)


def load_list(name: str) -> list[str]:
    path = REFERENCES / name
    if not path.exists():
        return []
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            items.append(line.lower())
    return items


# ---------------------------------------------------------------------------
# PDF テキスト読み込み
# ---------------------------------------------------------------------------


def load_pdf_pages(pdf_path: str | Path) -> list[str]:
    """pdftotext で全ページのテキストを取得し、ページごとのリストで返す。"""
    result = subprocess.run(
        ["pdftotext", "-layout", "-enc", "UTF-8", str(pdf_path), "-"],
        capture_output=True,
    )
    if result.returncode != 0:
        err = result.stderr.decode("utf-8", errors="replace")
        reason = "パスワードで保護されている" if re.search(r"password|encrypt", err, re.I) else "PDFとして読み込めない"
        raise SystemExit(
            f"ERROR: {pdf_path} を読めません（{reason}）。"
            "パスワードや閲覧制限を外したPDFを用意してもらうよう、ユーザーに伝えること。"
        )
    text = result.stdout.decode("utf-8", errors="replace")
    pages = text.split("\f")
    if pages and not pages[-1].strip():
        pages = pages[:-1]
    return pages


def cjk_mapping_warning(pdf_path: str | Path) -> str | None:
    """日本語フォントのマッピング用データ（poppler-data）が無い環境を検出する。

    これが欠けていると、埋め込まれていない日本語フォントの文字がテキスト抽出でも
    画像化でも欠落し、「2026   5   10」のように数字だけが残る。
    """
    r = subprocess.run(["pdftotext", "-l", "3", str(pdf_path), "-"], capture_output=True)
    err = r.stderr.decode("utf-8", errors="replace")
    if "Missing language pack" in err:
        return (
            "poppler-data が未導入のため日本語が欠落している。"
            "`apt-get install -y poppler-data`（失敗したら先に `apt-get update`）を実行してから再実行すること。"
        )
    return None


def pdf_info(pdf_path: str | Path) -> dict:
    info: dict = {}
    try:
        out = subprocess.run(["pdfinfo", "-box", str(pdf_path)], capture_output=True, check=True).stdout
        for line in out.decode("utf-8", errors="replace").splitlines():
            if ":" in line:
                k, v = line.split(":", 1)
                info[k.strip()] = v.strip()
    except Exception as e:  # noqa: BLE001
        info["error"] = str(e)
    return info


def _box_mm(value: str) -> tuple[float, float] | None:
    nums = [float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", value or "")]
    if len(nums) != 4:
        return None
    w = (nums[2] - nums[0]) * 25.4 / 72
    h = (nums[3] - nums[1]) * 25.4 / 72
    return round(w, 1), round(h, 1)


KNOWN_SIZES = {
    "A4": (210, 297),
    "B5": (182, 257),
    "A5": (148, 210),
    "B6": (128, 182),
    "A6": (105, 148),
}


def describe_page_size(info: dict) -> dict:
    """ページサイズ（mm）と、近い判型・塗り足しの有無を推定する。印刷形態の推定材料にする。"""
    media = _box_mm(info.get("MediaBox", ""))
    trim = _box_mm(info.get("TrimBox", ""))
    bleed = _box_mm(info.get("BleedBox", ""))
    result: dict = {"media_mm": media, "trim_mm": trim, "bleed_mm": bleed}
    if media:
        w, h = sorted(media)
        guess = None
        for name, (sw, sh) in KNOWN_SIZES.items():
            if abs(w - sw) <= 2 and abs(h - sh) <= 2:
                guess = f"{name}（仕上がりサイズ）"
            elif abs(w - sw - 6) <= 2 and abs(h - sh - 6) <= 2:
                guess = f"{name}＋塗り足し3mm（印刷所入稿用の可能性）"
        result["size_guess"] = guess
    if media and trim and media != trim:
        result["note"] = "TrimBox が MediaBox と異なる（塗り足し・トンボ付きの入稿データの可能性）"
    return result


# ---------------------------------------------------------------------------
# 抽出
# ---------------------------------------------------------------------------


def find_dates(text: str) -> list[dict]:
    """日付候補と、その行が初版／後版のどちらを示すかを返す。"""
    found = []
    for line in normalize(text).splitlines():
        for pat in DATE_PATTERNS:
            for m in pat.finditer(line):
                g = m.groupdict()
                if g.get("ry") is not None:
                    ry = 1 if g["ry"] == "元" else int(g["ry"])
                    y = 2018 + ry
                else:
                    y = int(g["y"])
                mo, d = int(g["m"]), int(g["d"])
                try:
                    iso = date(y, mo, d).isoformat()
                except ValueError:
                    iso = None
                kind = "unknown"
                if FIRST_EDITION.search(line):
                    kind = "first"
                elif LATER_EDITION.search(line):
                    kind = "later"
                found.append(
                    {
                        "raw": m.group(0),
                        "iso": iso,
                        "valid": iso is not None,
                        "edition": kind,
                        "line": line.strip()[:120],
                    }
                )
        for pat in (DATE_EN, DATE_HEISEI):
            for m in pat.finditer(line):
                g = m.groupdict()
                if "mon" in g:
                    y, mo = int(g["y"]), _MONTH_NUM[g["mon"].lower()[:3]]
                else:
                    y, mo = 1988 + (1 if g["hy"] == "元" else int(g["hy"])), int(g["m"])
                try:
                    iso = date(y, mo, int(g["d"])).isoformat()
                except ValueError:
                    iso = None
                kind = "first" if FIRST_EDITION.search(line) else "later" if LATER_EDITION.search(line) else "unknown"
                found.append({"raw": m.group(0), "iso": iso, "valid": iso is not None, "edition": kind, "line": line.strip()[:120]})
        for m in MONTH_ONLY_PATTERN.finditer(line):
            found.append(
                {
                    "raw": m.group(0),
                    "iso": None,
                    "valid": False,
                    "edition": "unknown",
                    "month_only": True,
                    "line": line.strip()[:120],
                }
            )
    # 重複除去
    seen, uniq = set(), []
    for f in found:
        key = (f["raw"], f["line"])
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return uniq


def find_contacts(text: str, disposable: list[str] | None = None) -> dict:
    t = normalize(text)
    disposable = disposable if disposable is not None else load_list("disposable-domains.txt")
    emails = sorted(set(EMAIL.findall(t)))
    obfuscated = sorted(set(m.group(0) for m in EMAIL_OBFUSCATED.finditer(t)))
    urls = sorted(set(URL.findall(t)))
    socials = sorted(set(m.group(0) for m in SOCIAL_DOMAIN.finditer(t)))
    handles = sorted({h for h in HANDLE.findall(t) if h[1:].lower() not in HANDLE_STOPWORDS})
    flagged = []
    for e in emails + obfuscated:
        domain = re.split(r"@|[\[\(（]\s*(?:at|アット)\s*[\]\)）]", e, flags=re.I)[-1].strip().lower()
        if any(domain == d or domain.endswith("." + d) for d in disposable):
            flagged.append({"value": e, "reason": "使い捨てメールのドメインに一致"})
        if PLACEHOLDER.search(e):
            flagged.append({"value": e, "reason": "プレースホルダーの可能性"})
    for u in urls:
        if PLACEHOLDER.search(u):
            flagged.append({"value": u, "reason": "プレースホルダーの可能性"})
    return {
        "emails": emails,
        "emails_obfuscated": obfuscated,
        "urls": urls,
        "social_links": socials,
        "handles": handles,
        "flagged": flagged,
    }


def labeled_lines(text: str, max_len: int = 120) -> dict:
    """各ラベルを含む行を集める（値の解釈は Claude に任せる）。"""
    t = normalize(text)
    out: dict[str, list[str]] = {k: [] for k in LABELS}
    for line in t.splitlines():
        s = line.strip()
        if not s or len(s) > max_len:
            continue
        for key, pat in LABELS.items():
            if re.search(pat, s, re.I):
                out[key].append(s)
    return out


def placeholder_lines(text: str) -> list[str]:
    t = normalize(text)
    return [
        ln.strip()[:120]
        for ln in t.splitlines()
        if ln.strip() and (PLACEHOLDER.search(ln) or TEMPLATE_VALUE.search(ln.strip()))
    ]


def known_printer_hits(text: str) -> list[str]:
    """known-printers.txt にある印刷所名を探す。

    英数字の名前（K-9、PICO など）は、別の語の一部に当たらないよう単語の境界で照合し、
    ハイフンの有無（K-9 / K9）も同じものとして扱う。
    """
    t = normalize(text)
    hits = []
    for name in load_list("known-printers.txt"):
        if not name:
            continue
        if name.isascii():
            pat = r"(?<![A-Za-z0-9])" + re.escape(name).replace(r"\-", "-?") + r"(?![A-Za-z0-9])"
            if re.search(pat, t, re.I):
                hits.append(name)
        elif name in t.lower():
            hits.append(name)
    return hits


def colophon_score(text: str, page_index: int, total: int) -> tuple[int, list[str]]:
    t = normalize(text)
    score, reasons = 0, []
    for kw, w in COLOPHON_KEYWORDS.items():
        if kw.lower() in t.lower():
            score += w
            reasons.append(kw)
    if any(p.search(t) for p in (*DATE_PATTERNS, DATE_EN, DATE_HEISEI)):
        score += 2
        reasons.append("日付あり")
    if EMAIL.search(t) or SOCIAL_DOMAIN.search(t) or HANDLE.search(t):
        score += 1
        reasons.append("連絡先らしき文字列")
    if page_index >= total - 5:
        score += 2
        reasons.append("末尾5ページ以内")
    n = len(t.strip())
    if 0 < n < 1500:
        score += 1
    elif n > 3500:
        score -= 3
        reasons.append("本文量が多い（本文ページの可能性）")
    return score, reasons


def extract_fields(text: str) -> dict:
    """1ページ（または1ファイル）分のテキストから奥付項目の候補を抽出する。"""
    return {
        "labeled_lines": labeled_lines(text),
        "dates": find_dates(text),
        "contacts": find_contacts(text),
        "known_printers": known_printer_hits(text),
        "placeholders": placeholder_lines(text),
        "first_lines": [ln.strip() for ln in normalize(text).splitlines() if ln.strip()][:5],
    }
