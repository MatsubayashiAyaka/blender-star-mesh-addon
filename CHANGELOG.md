## [1.0.1]
### Added
- Viewport 左下に常駐する「Star Edit」パネルからのリアルタイム編集
- プリセット保存（保存先：Scene Collection）

### Changed
- 左下パネルの UI を整理（Type 表示削除、Save/Close 横並び、文字中央寄せ）
- Save Preset 実行後に Blender の Redo パネルが残らないように改善（REGISTER除去）
- Star Edit 表示中の選択操作が重くならないよう最適化
  - パネル外クリックは完全スルー
  - タイマーは dirty/dragging のときのみ起動
  - redraw を必要時のみに限定

### Fixed
- 左下パネルの重なり表示、ラベル不明瞭、ボタン表示崩れ

## [1.0.0]
### Added
- Nパネルから 2D/3D の星形メッシュを生成
- 三角形ファン（中心から各頂点へ）での星形生成
- 3D は押し出しで厚み付け
