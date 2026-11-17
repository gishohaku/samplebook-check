#!/usr/bin/env bash
# スキルを配布用の .skill ファイル（zip形式）にまとめる。
#   ./tools/build.sh   →  dist/gishohaku-samplebook-check.skill
# evals/ はテスト用なので含めない。
set -eu
cd "$(dirname "$0")/.."
NAME=gishohaku-samplebook-check
mkdir -p dist
rm -f "dist/$NAME.skill"
(cd skills && zip -qr "../dist/$NAME.skill" "$NAME" -x "$NAME/evals/*" -x "*/__pycache__/*" -x "*.pyc")
echo "built: dist/$NAME.skill"
