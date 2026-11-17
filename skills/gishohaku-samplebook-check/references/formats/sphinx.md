# Sphinx の奥付

## 仕組み

Sphinx には奥付の標準機能がない。`conf.py` の `project` / `author` / `copyright` / `release` はメタデータやフッター用で、同人誌の奥付の要件（連絡先・初回発行日・印刷所）は満たさない。
奥付は次のような形で用意されていることが多い。

- 最後の章として置かれた `colophon.rst` / `colophon.md` などのページ
- LaTeX 出力のカスタマイズ（`conf.py` の `latex_elements` や、独自の `.tex` / `.sty`）

## 手順

1. `python scripts/check_source.py <プロジェクト> --format sphinx` を実行する
2. `colophon_candidates` を確認する。見つからなければ、`index.rst`（または `index.md`）の toctree の最後のファイルを読む
3. `latex_elements_defined` が true なら `conf.py` の該当部分と、参照している `.tex` / `.sty` を確認する
4. `conf.py` のメタデータしか見つからない場合は「奥付ページがない可能性が高い」として ❌ 候補とし、ユーザーに確認する
5. 最終確認はビルド済みPDFで行うよう案内する
