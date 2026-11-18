#!/usr/bin/env bash
# tests/fixtures/ の合成PDFを、evals の各ケースにコピーする。
# フィクスチャを作り直したとき（python tests/make_fixtures.py のあと）に実行する。
set -eu
cd "$(dirname "$0")/.."
E=skills/gishohaku-samplebook-check/evals
cp tests/fixtures/good.pdf               "$E/colophon-pass-asks-content-check/files/book.pdf"
cp tests/fixtures/missing.pdf            "$E/colophon-missing-items/files/book.pdf"
cp tests/fixtures/contact_in_preface.pdf "$E/contact-in-preface-passes/files/book.pdf"
cp tests/fixtures/risky_toc.pdf          "$E/risky-toc-strongly-recommends/files/book.pdf"
cp tests/fixtures/dualuse_ok.pdf         "$E/dualuse-adult-disclaimer-ok/files/book.pdf"
cp tests/fixtures/dualuse_missing.pdf    "$E/dualuse-missing-disclaimer-required/files/book.pdf"
cp tests/fixtures/scan.pdf               "$E/scan-pdf-no-content-verdict/files/book.pdf"
echo "synced"
