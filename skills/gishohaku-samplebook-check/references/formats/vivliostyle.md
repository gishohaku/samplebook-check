# Vivliostyle の奥付

## 仕組み

Vivliostyle（Vivliostyle CLI / Create Book）には、Re:VIEW のような奥付専用の設定キーはない。
多くの場合、奥付は次のどちらかの形で書かれている。

- `vivliostyle.config.js` の `entry` の末尾に置かれた、奥付用の Markdown / HTML ファイル（`colophon.md`、`okuduke.md` など）
- 本文の最後のファイルの末尾に、見出し「奥付」として直接書かれている

`vivliostyle.config.js` の `title` / `author` は書名・著者のメタデータだが、ページに印字されるとは限らない。奥付の項目としては数えない（奥付内の記述を探す手がかりにする）。

## 手順

1. `python scripts/check_source.py <プロジェクト> --format vivliostyle` を実行する
2. `colophon_candidates` の上位ファイルを開き、6項目を `colophon-rules.md` に沿って判定する
3. 候補が見つからなければ、`entry` の最後の数ファイルを直接読む
4. テーマやCSSで奥付を生成している場合もあるので、見つからないときはユーザーに奥付の場所を尋ねる
5. 最終確認はビルド済みPDFで行うよう案内する
