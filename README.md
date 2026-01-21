# Star Mesh Creator (Blender 3.6+)

Blender 3.6以降で動作する「星形メッシュ（2D/3D）」生成アドオンです。  
中心点から各頂点へエッジが伸びる **三角形ファン（Triangle Fan）構成**で星形を作成します。

- 2D / 3D 星形の生成（3Dはモディファイアではなく"押し出し"で厚み付け）
- **Viewport 左下に常駐する「Star Edit (Pinned)」パネル**で、生成後もリアルタイム編集
- プリセット保存（保存先：**Scene Collection** のカスタムプロパティ）

---

## 対応バージョン

- Blender 3.6 以上

---

## インストール

1. このリポジトリから `star_mesh_creator.py` をダウンロード（または Releases から zip をダウンロード）
2. Blender を開く → `Edit > Preferences > Add-ons`
3. `Install...` → `star_mesh_creator.py` を選択
4. チェックを入れて有効化

---

## 使い方（基本）

### 1) 星形を作成する（Nパネル）

`View3D > Sidebar (N) > Star > Star Mesh Creator` から作成できます。

- 上段：Preset を選択 → `Use Preset`（ONにすると 2D/3D が無効化）
- その下：2D / 3D を選択（Use Preset がOFFのときのみ）
- Object Name / Collection を指定
- `Create Star` を押す

> Preset が適用されていない場合、デフォルトで **5スパイク**の星が生成されます。

---

### 2) 生成後に形状を編集する（左下の常駐パネル）

`Create Star` 実行後、Viewport 左下に **Star Edit** が表示されます。

- Spikes / Outer Radius / Inner Radius / Global Scale を編集  
- 3Dの場合のみ Thickness を編集  
- 変更は **リアルタイムでメッシュに反映**されます

#### 数値入力の操作方法

| 操作 | 動作 |
|------|------|
| シングルクリック | 全選択編集モード（値全体を選択、背景が青色に） |
| 全選択中に再クリック | カーソル編集モード（末尾に `\|` が表示され、追記入力可能） |
| ドラッグ | 値をドラッグで増減 |
| `<` / `>` ボタン | 値をステップ単位で増減 |
| Enter | 入力確定（空の場合はデフォルト値に） |
| Escape | 入力キャンセル（元の値に戻る） |

#### Save Preset
左下パネルの `Save Preset` から、現在の形状設定をプリセットとして保存できます。

#### Close
`Close` を押すと左下パネルを閉じます。

---

## プリセット保存先について

プリセットは外部ファイルではなく、Blender 内の **Scene Collection** に JSON として保存されます。  
**.blend に保存するとプリセットも一緒に保存**されます。

- 保存場所：`Scene Collection` のカスタムプロパティ  
- キー：`STAR_MESH_CREATOR_PRESETS_JSON`

---

## 仕様（生成メッシュ）

- 星形は「外周（Outer/Inner）を交互に配置した頂点列」を作り、  
  中心頂点から各辺へ三角形を張る **Triangle Fan** 構成です。
- 3D は生成後に面を押し出して厚みを付けます（Solidify Modifier は使用しません）

---

## 制限 / 注意

- 左下パネルでの編集は、メッシュを再生成して反映します。  
  そのため、ユーザーが手動でメッシュを編集した場合、その形状は上書きされます。
- 3D の厚みは Z方向押し出しです（原点/姿勢の変更は行いません）

---

## ファイル構成

```
star-mesh-creator/
├── star_mesh_creator.py      # メインアドオンファイル（最新版）
├── legacy/
│   └── star_mesh_creater_ver1_0_0.py   # 旧バージョン
├── README.md
├── CHANGELOG.md
└── LICENSE
```

---

## ライセンス

- MIT License
