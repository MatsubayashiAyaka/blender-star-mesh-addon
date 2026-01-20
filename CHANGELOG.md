# Changelog

## [1.0.1] - 2026-01-20
### Added
- Viewport 左下に常駐する「Star Edit (Pinned)」パネル
- 生成後のリアルタイム形状編集
- プリセット保存（Scene Collection に保存）

### Changed
- 左下パネルのUI整理（Type表示削除、Save/Close横並び、文字中央寄せ）
- Save Preset 実行後に Redo パネルが残らないよう改善（REGISTER除去）
- Star Edit 表示中の選択操作が重くならないよう最適化
  - パネル外クリックは完全スルー
  - タイマーは dirty/dragging のときのみ起動
  - redraw を必要時のみに限定

### Fixed
- 左下UIの重なり表示
- Save Preset 実行後に不要なUIが残る問題
- アクティブオブジェクト選択が反応しづらくなる問題


## [1.0.0]
### Added
- Nパネルから星形メッシュを生成
- 外側/内側頂点による星形生成
- シンプルなパラメータ指定（角数・サイズ）
