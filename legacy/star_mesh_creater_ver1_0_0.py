import bpy
import bmesh
import math

bl_info = {
    "name": "サンプルアドオン：Star Adder",
    "version": (1, 0, 0),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar > Star Tool",  # 正確な場所を記載
    "description": "シーンに星型メッシュを追加するアドオン",
    "warning": "",
    "support": "COMMUNITY",
    "doc_url": "",
    "tracker_url": "",
    "category": "Sample"
}


# ============================================================
# オペレータークラス（処理を定義）
# ============================================================
class SAMPLE_OT_CreateStarPolygon(bpy.types.Operator):
    """星型メッシュを追加するオペレーター"""
    
    bl_idname = "sample.create_star_polygon"
    bl_label = "星型メッシュを追加"
    bl_description = "シーンに星型メッシュを追加します"
    bl_options = {'REGISTER', 'UNDO'}
    
    # プロパティ定義
    num_sides: bpy.props.IntProperty(
        name="角の数",
        description="星型のメッシュの角の数",
        default=10,
        min=3,
        max=20
    )
    
    radius: bpy.props.FloatProperty(
        name="サイズ",
        description="星型のメッシュのサイズ",
        default=2.0,  # 100.0 → 2.0 に変更（適切なサイズ）
        min=0.1,
        max=100.0
    )
    
    def execute(self, context):
        num_sides = self.num_sides
        radius = self.radius
        
        # メッシュとオブジェクトを作成
        new_mesh = bpy.data.meshes.new("Regular N-sided Star Polygon")
        new_obj = bpy.data.objects.new("Regular N-sided Star Polygon", new_mesh)
        bpy.context.scene.collection.objects.link(new_obj)
        bpy.context.view_layer.objects.active = new_obj
        new_obj.select_set(True)
        
        # bmeshで星の形状を作成
        bm = bmesh.new()
        verts = []
        dtheta = 2.0 * math.pi / num_sides
        
        for i in range(num_sides):
            # 外側の頂点
            outer_x = radius * math.cos(i * dtheta)
            outer_y = radius * math.sin(i * dtheta)
            outer_vert = bm.verts.new([outer_x, outer_y, 0.0])
            verts.append(outer_vert)
            
            # 内側の頂点
            inner_x = (radius / 2) * math.cos(i * dtheta + dtheta / 2)
            inner_y = (radius / 2) * math.sin(i * dtheta + dtheta / 2)
            inner_vert = bm.verts.new([inner_x, inner_y, 0.0])
            verts.append(inner_vert)
        
        bm.faces.new(verts)
        bm.to_mesh(new_mesh)
        bm.free()  # メモリ解放
        
        print("オペレータを実行しました")
        return {'FINISHED'}


# ============================================================
# パネルクラス（サイドバーのUIを定義）← これが必要！
# ============================================================
class SAMPLE_PT_StarPanel(bpy.types.Panel):
    """サイドバーに表示されるパネル"""
    
    bl_label = "Star Adder"                    # パネルのタイトル
    bl_idname = "SAMPLE_PT_star_panel"         # パネルのID
    bl_space_type = 'VIEW_3D'                  # 3Dビューに表示
    bl_region_type = 'UI'                      # サイドバー（UI領域）に表示
    bl_category = "Star Tool"                  # タブの名前
    
    def draw(self, context):
        """パネルの内容を描画"""
        layout = self.layout
        
        # 説明文
        layout.label(text="星型メッシュを追加:")
        
        # 区切り線
        layout.separator()
        
        # オペレーターを呼び出すボタン（デフォルト値）
        layout.operator(
            "sample.create_star_polygon",
            text="星を追加 (デフォルト)",
            icon='SOLO_ON'
        )
        
        layout.separator()
        
        # プリセットボタン
        layout.label(text="プリセット:")
        
        # 5角星
        row = layout.row()
        op = row.operator("sample.create_star_polygon", text="5角星")
        op.num_sides = 5
        op.radius = 2.0  # 適切なサイズに変更
        
        # 8角星
        op = row.operator("sample.create_star_polygon", text="8角星")
        op.num_sides = 8
        op.radius = 2.0  # 適切なサイズに変更
        
        # 10角星
        row = layout.row()
        op = row.operator("sample.create_star_polygon", text="10角星")
        op.num_sides = 10
        op.radius = 2.0  # 適切なサイズに変更
        
        # 12角星
        op = row.operator("sample.create_star_polygon", text="12角星")
        op.num_sides = 12
        op.radius = 2.0  # 適切なサイズに変更


# ============================================================
# 登録するクラスのリスト（Panelを追加！）
# ============================================================
classes = [
    SAMPLE_OT_CreateStarPolygon,  # オペレーター
    SAMPLE_PT_StarPanel,          # パネル ← 追加！
]


def register():
    """アドオンを登録"""
    for cls in classes:
        bpy.utils.register_class(cls)
    
    print("=" * 60)
    print(f"✅ アドオン「{bl_info['name']}」が登録されました")
    print(f"   場所: View3D > Sidebar > Star Tool タブ")
    print(f"   ショートカット: Nキーでサイドバー表示/非表示")
    print("=" * 60)


def unregister():
    """アドオンを登録解除"""
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)
    
    print(f"❌ アドオン「{bl_info['name']}」が登録解除されました")


# スクリプトとして直接実行された場合
if __name__ == "__main__":
    register()