#!/usr/bin/env python3
"""PDFのページを画像化する。奥付の目視確認と、図版・表紙の内容確認に使う。

使い方:
    # 指定ページを画像化（L は最終ページ、L-1 は最後から2ページ目、範囲は a:b）
    python render_pages.py book.pdf --pages 1,L-1,L --dpi 110 --out /tmp/gishohaku/render

    # 全ページ（または範囲）を縮小して一覧画像（コンタクトシート）にする
    python render_pages.py book.pdf --sheet --cols 4 --rows 3 --dpi 40 --out /tmp/gishohaku/sheets
    python render_pages.py book.pdf --sheet --pages 20:60 --out /tmp/gishohaku/sheets

出力した画像のパスを標準出力に1行ずつ表示する。それらを view で開いて確認する。
"""

from __future__ import annotations

import argparse
import re
import subprocess
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw


def page_count(pdf: Path) -> int:
    out = subprocess.run(["pdfinfo", str(pdf)], capture_output=True, check=True).stdout.decode()
    m = re.search(r"^Pages:\s+(\d+)", out, re.M)
    return int(m.group(1)) if m else 0


def resolve(token: str, total: int) -> int:
    token = token.strip()
    if token.upper().startswith("L"):
        rest = token[1:]
        n = total - int(rest[1:]) if rest.startswith("-") else total
    else:
        n = int(token)
    return max(1, min(total, n))


def parse_pages(spec: str | None, total: int) -> list[int]:
    if not spec:
        return list(range(1, total + 1))
    pages: list[int] = []
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":", 1)
            s, e = resolve(a, total), resolve(b, total)
            pages.extend(range(min(s, e), max(s, e) + 1))
        elif part.strip():
            pages.append(resolve(part, total))
    seen, uniq = set(), []
    for p in pages:
        if p not in seen:
            seen.add(p)
            uniq.append(p)
    return uniq


def render(pdf: Path, page: int, dpi: int, prefix: Path) -> Path:
    subprocess.run(
        ["pdftoppm", "-jpeg", "-r", str(dpi), "-f", str(page), "-l", str(page), "-singlefile", str(pdf), str(prefix)],
        check=True,
    )
    return prefix.with_suffix(".jpg")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("pdf")
    ap.add_argument("--pages", help="例: 1,L-1,L / 10:20")
    ap.add_argument("--dpi", type=int, default=None)
    ap.add_argument("--out", default="/tmp/gishohaku/render")
    ap.add_argument("--sheet", action="store_true", help="縮小一覧画像を作る")
    ap.add_argument("--cols", type=int, default=4)
    ap.add_argument("--rows", type=int, default=3)
    args = ap.parse_args()

    pdf = Path(args.pdf)
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    total = page_count(pdf)
    pages = parse_pages(args.pages, total)

    if not args.sheet:
        dpi = args.dpi or 110
        for p in pages:
            path = render(pdf, p, dpi, out / f"page-{p:04d}")
            print(path)
        return

    dpi = args.dpi or 40
    per_sheet = args.cols * args.rows
    with tempfile.TemporaryDirectory() as tmp:
        tmpdir = Path(tmp)
        for start in range(0, len(pages), per_sheet):
            chunk = pages[start : start + per_sheet]
            images = [Image.open(render(pdf, p, dpi, tmpdir / f"p{p:04d}")).convert("RGB") for p in chunk]
            w = max(im.width for im in images)
            h = max(im.height for im in images)
            label_h = 18
            sheet = Image.new("RGB", (w * args.cols, (h + label_h) * args.rows), "white")
            draw = ImageDraw.Draw(sheet)
            for idx, (p, im) in enumerate(zip(chunk, images)):
                x = (idx % args.cols) * w
                y = (idx // args.cols) * (h + label_h)
                draw.text((x + 4, y + 2), f"p.{p}", fill="red")
                sheet.paste(im, (x, y + label_h))
                draw.rectangle([x, y + label_h, x + im.width - 1, y + label_h + im.height - 1], outline="gray")
            name = out / f"sheet-p{chunk[0]:04d}-p{chunk[-1]:04d}.jpg"
            sheet.save(name, quality=80)
            print(name)


if __name__ == "__main__":
    main()
