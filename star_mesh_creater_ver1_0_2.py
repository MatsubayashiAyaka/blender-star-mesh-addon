# -*- coding: utf-8 -*-
bl_info = {
    "name": "Star Mesh Creator (Blender 3.6+)",
    "author": "Ayaka Matsubayashi",
    "version": (1, 0, 2),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > Star",
    "description": "Create 2D/3D star mesh (triangle fan from center). Pinned bottom-left editor with realtime edits and preset saving to Scene Collection.",
    "category": "Add Mesh",
}

import bpy
import bmesh
import math
import json
import time

from bpy.props import (
    BoolProperty,
    EnumProperty,
    FloatProperty,
    IntProperty,
    PointerProperty,
    StringProperty,
)

import gpu
from gpu_extras.batch import batch_for_shader
import blf


# ============================================================
# Presets stored in Scene Collection (root)
# ============================================================

_PRESET_KEY = "STAR_MESH_CREATOR_PRESETS_JSON"
_PRESET_SCHEMA_VERSION = 1


def _root_collection(context) -> bpy.types.Collection:
    return context.scene.collection


def _load_presets(context) -> dict:
    col = _root_collection(context)
    raw = col.get(_PRESET_KEY, "")
    if not raw:
        return {"version": _PRESET_SCHEMA_VERSION, "presets": {}}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            return {"version": _PRESET_SCHEMA_VERSION, "presets": {}}
        data.setdefault("version", _PRESET_SCHEMA_VERSION)
        if "presets" not in data or not isinstance(data["presets"], dict):
            data["presets"] = {}
        return data
    except Exception:
        return {"version": _PRESET_SCHEMA_VERSION, "presets": {}}


def _save_presets(context, data: dict) -> None:
    col = _root_collection(context)
    col[_PRESET_KEY] = json.dumps(data, ensure_ascii=False, indent=2)


def _preset_items(self, context):
    if not context or not context.scene:
        return [("NONE", "(no presets)", "No presets available")]
    data = _load_presets(context)
    names = sorted(list(data.get("presets", {}).keys()))
    if not names:
        return [("NONE", "(no presets)", "No presets available")]
    items = [("NONE", "(none)", "No preset")]
    for n in names:
        items.append((n, n, f"Preset: {n}"))
    return items


# ============================================================
# Star mesh building (triangle fan from center -> triangles)
# ============================================================

def _validate(star_type: str, spikes: int, outer: float, inner: float, scale: float, thickness: float):
    if spikes < 3:
        return False, "Spikes must be >= 3"
    if outer <= 0.0 or inner <= 0.0 or scale <= 0.0:
        return False, "Outer/Inner/Scale must be > 0"
    if inner >= outer:
        return False, "Inner Radius must be smaller than Outer Radius"
    if star_type == "STAR_3D" and thickness < 0.0:
        return False, "Thickness must be >= 0"
    return True, ""


def _make_name(pattern: str, spikes: int) -> str:
    s2 = f"{spikes:02d}"
    name = (pattern or "Star_##").replace("##", s2).replace("{spikes}", str(spikes))
    return name.strip() or f"Star_{s2}"


def _build_star_bmesh(bm: bmesh.types.BMesh, spikes: int, outer_r: float, inner_r: float, rot_deg: float):
    count = spikes * 2
    step = (2.0 * math.pi) / count
    rot = math.radians(rot_deg)

    ring = []
    for i in range(count):
        ang = i * step + rot
        r = outer_r if (i % 2 == 0) else inner_r
        ring.append(bm.verts.new((math.cos(ang) * r, math.sin(ang) * r, 0.0)))

    center = bm.verts.new((0.0, 0.0, 0.0))
    bm.verts.ensure_lookup_table()

    for i in range(count):
        v0 = ring[i]
        v1 = ring[(i + 1) % count]
        bm.faces.new((center, v0, v1))

    bm.faces.ensure_lookup_table()
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def _extrude_thickness(bm: bmesh.types.BMesh, thickness: float):
    if thickness <= 0.0:
        return
    bm.faces.ensure_lookup_table()
    res = bmesh.ops.extrude_face_region(bm, geom=list(bm.faces))
    extruded_verts = [e for e in res["geom"] if isinstance(e, bmesh.types.BMVert)]
    bmesh.ops.translate(bm, verts=extruded_verts, vec=(0.0, 0.0, thickness))
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)


def rebuild_star_mesh(obj: bpy.types.Object, *, star_type: str, spikes: int, outer: float, inner: float, scale: float, thickness: float, rot_deg: float):
    ok, msg = _validate(star_type, spikes, outer, inner, scale, thickness)
    if not ok:
        raise ValueError(msg)

    outer_r = outer * scale
    inner_r = inner * scale
    thick = thickness * scale

    bm = bmesh.new()
    _build_star_bmesh(bm, spikes, outer_r, inner_r, rot_deg)
    if star_type == "STAR_3D":
        _extrude_thickness(bm, thick)

    mesh = obj.data
    mesh.clear_geometry()
    bm.to_mesh(mesh)
    bm.free()
    mesh.update()


# ============================================================
# Properties
# ============================================================

class STAR_ObjProps(bpy.types.PropertyGroup):
    is_star: BoolProperty(default=False, options={'HIDDEN'})
    star_type: EnumProperty(
        name="Type",
        items=[("STAR_2D", "2D", ""), ("STAR_3D", "3D", "")],
        default="STAR_2D",
    )
    spikes: IntProperty(name="Spikes", default=5, min=3, max=256)
    outer_radius: FloatProperty(name="Outer Radius", default=1.0, min=0.0001, precision=4)
    inner_radius: FloatProperty(name="Inner Radius", default=0.5, min=0.0001, precision=4)
    global_scale: FloatProperty(name="Global Scale", default=1.0, min=0.0001, precision=4)
    thickness: FloatProperty(name="Thickness", default=0.2, min=0.0, precision=4)
    rotation_deg: FloatProperty(name="Rotation", default=0.0, precision=3, options={'HIDDEN'})


class STAR_SceneProps(bpy.types.PropertyGroup):
    preset_select: EnumProperty(name="Preset", items=_preset_items)
    use_preset: BoolProperty(name="Use Preset", default=False)

    star_type: EnumProperty(
        name="Type",
        items=[("STAR_2D", "2D", "Create 2D star"), ("STAR_3D", "3D", "Create 3D star (extrude)")],
        default="STAR_2D",
    )

    name_pattern: StringProperty(
        name="Object Name",
        description='Supports "##" (2-digit spikes) and "{spikes}"',
        default="Star_##",
        maxlen=128,
    )
    target_collection: PointerProperty(
        name="Collection",
        type=bpy.types.Collection,
        description="Target collection to link the created object",
    )

    # Defaults when preset is NOT used (must be 5 spikes by default)
    default_spikes: IntProperty(default=5, min=3, max=256, options={'HIDDEN'})
    default_outer: FloatProperty(default=1.0, min=0.0001, precision=4, options={'HIDDEN'})
    default_inner: FloatProperty(default=0.5, min=0.0001, precision=4, options={'HIDDEN'})
    default_scale: FloatProperty(default=1.0, min=0.0001, precision=4, options={'HIDDEN'})
    default_thickness: FloatProperty(default=0.2, min=0.0, precision=4, options={'HIDDEN'})


# ============================================================
# Create operator
# ============================================================

def _get_create_params(context):
    sp = context.scene.star_mesh_creator
    params = {
        "star_type": sp.star_type,
        "spikes": int(sp.default_spikes),
        "outer_radius": float(sp.default_outer),
        "inner_radius": float(sp.default_inner),
        "global_scale": float(sp.default_scale),
        "thickness": float(sp.default_thickness),
        "rotation_deg": 0.0,
    }

    if sp.use_preset and sp.preset_select and sp.preset_select != "NONE":
        data = _load_presets(context)
        p = data.get("presets", {}).get(sp.preset_select)
        if isinstance(p, dict):
            params["star_type"] = p.get("star_type", params["star_type"])
            params["spikes"] = int(p.get("spikes", params["spikes"]))
            params["outer_radius"] = float(p.get("outer_radius", params["outer_radius"]))
            params["inner_radius"] = float(p.get("inner_radius", params["inner_radius"]))
            params["global_scale"] = float(p.get("global_scale", params["global_scale"]))
            params["thickness"] = float(p.get("thickness", params["thickness"]))
    return params


class STAR_OT_create(bpy.types.Operator):
    bl_idname = "star_mesh_creator.create_star"
    bl_label = "Create Star"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        sp = context.scene.star_mesh_creator
        params = _get_create_params(context)

        ok, msg = _validate(params["star_type"], params["spikes"], params["outer_radius"], params["inner_radius"], params["global_scale"], params["thickness"])
        if not ok:
            self.report({'ERROR'}, msg)
            return {'CANCELLED'}

        name = _make_name(sp.name_pattern, params["spikes"])
        mesh = bpy.data.meshes.new(name + "_Mesh")
        obj = bpy.data.objects.new(name, mesh)

        target_col = sp.target_collection or context.collection
        target_col.objects.link(obj)

        obj.select_set(True)
        context.view_layer.objects.active = obj

        op = obj.star_mesh_creator_obj
        op.is_star = True
        op.star_type = params["star_type"]
        op.spikes = params["spikes"]
        op.outer_radius = params["outer_radius"]
        op.inner_radius = params["inner_radius"]
        op.global_scale = params["global_scale"]
        op.thickness = params["thickness"]
        op.rotation_deg = params["rotation_deg"]

        try:
            rebuild_star_mesh(
                obj,
                star_type=op.star_type,
                spikes=op.spikes,
                outer=op.outer_radius,
                inner=op.inner_radius,
                scale=op.global_scale,
                thickness=op.thickness,
                rot_deg=op.rotation_deg,
            )
        except Exception as e:
            self.report({'ERROR'}, f"Build failed: {e}")
            bpy.data.objects.remove(obj, do_unlink=True)
            bpy.data.meshes.remove(mesh, do_unlink=True)
            return {'CANCELLED'}

        # Open pinned editor (non-blocking)
        try:
            bpy.ops.star_mesh_creator.pinned_editor('INVOKE_DEFAULT')
        except Exception:
            pass

        return {'FINISHED'}


# ============================================================
# Preset save (from selected star)
#   IMPORTANT: no REGISTER -> no Redo panel
# ============================================================

class STAR_OT_save_preset_dialog(bpy.types.Operator):
    bl_idname = "star_mesh_creator.save_preset_dialog"
    bl_label = "Save Preset"
    bl_options = {'INTERNAL'}

    preset_name: StringProperty(name="Preset Name", default="MyPreset", maxlen=64)

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=300)

    def execute(self, context):
        obj = context.view_layer.objects.active
        if not (obj and obj.type == "MESH" and getattr(obj, "star_mesh_creator_obj", None) and obj.star_mesh_creator_obj.is_star):
            self.report({'ERROR'}, "Select a Star object to save as preset.")
            return {'CANCELLED'}

        name = (self.preset_name or "").strip()
        if not name:
            self.report({'ERROR'}, "Preset name is empty.")
            return {'CANCELLED'}

        op = obj.star_mesh_creator_obj
        data = _load_presets(context)
        presets = data.setdefault("presets", {})
        presets[name] = {
            "star_type": op.star_type,
            "spikes": int(op.spikes),
            "outer_radius": float(op.outer_radius),
            "inner_radius": float(op.inner_radius),
            "global_scale": float(op.global_scale),
            "thickness": float(op.thickness),
        }
        _save_presets(context, data)
        context.scene.star_mesh_creator.preset_select = name
        self.report({'INFO'}, f"Saved preset '{name}' to Scene Collection.")
        return {'FINISHED'}


# ============================================================
# Sidebar UI (Generate only, requested order)
# ============================================================

class STAR_PT_sidebar(bpy.types.Panel):
    bl_label = "Star Mesh Creator"
    bl_idname = "STAR_PT_sidebar_star_mesh_creator"
    bl_space_type = "VIEW_3D"
    bl_region_type = "UI"
    bl_category = "Star"

    def draw(self, context):
        sp = context.scene.star_mesh_creator
        layout = self.layout

        box = layout.box()
        box.label(text="Preset")
        box.prop(sp, "preset_select", text="")
        box.prop(sp, "use_preset", toggle=True, text="Use Preset")

        box = layout.box()
        box.label(text="Shape Type")
        row = box.row()
        row.enabled = not sp.use_preset
        row.prop(sp, "star_type", expand=True)

        box = layout.box()
        box.label(text="Naming / Collection")
        box.prop(sp, "name_pattern")
        box.prop(sp, "target_collection")

        layout.separator()
        layout.operator("star_mesh_creator.create_star", icon="MESH_CIRCLE")


# ============================================================
# Pinned bottom-left editor (Overlay)
# - Inline numeric editing (no dialogs)
# - Numpad input captured while editing
# - < > buttons shown only on hover (or editing), row brightens on hover
# ============================================================

_EDITOR_RUNNING = False
_EDITOR_DRAW_HANDLE = None


class _UIRect:
    __slots__ = ("x", "y", "w", "h")

    def __init__(self, x, y, w, h):
        self.x, self.y, self.w, self.h = x, y, w, h

    def contains(self, mx, my):
        return (self.x <= mx <= self.x + self.w) and (self.y <= my <= self.y + self.h)


def _clamp(v, a, b):
    return a if v < a else b if v > b else v


def _draw_rect(x, y, w, h, color):
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    verts = [(x, y), (x + w, y), (x + w, y + h), (x, y + h)]
    indices = [(0, 1, 2), (2, 3, 0)]
    batch = batch_for_shader(shader, 'TRIS', {"pos": verts}, indices=indices)
    gpu.state.blend_set('ALPHA')
    shader.bind()
    shader.uniform_float("color", color)
    batch.draw(shader)
    gpu.state.blend_set('NONE')


def _draw_text(x, y, text, size=12, color=(1, 1, 1, 1)):
    font_id = 0
    blf.position(font_id, x, y, 0)
    blf.size(font_id, size)
    blf.color(font_id, *color)
    blf.draw(font_id, text)


def _text_dimensions(text: str, size: int):
    font_id = 0
    blf.size(font_id, size)
    return blf.dimensions(font_id, text)


def _draw_text_centered_in_rect(rect: _UIRect, text: str, size=11, color=(1, 1, 1, 1)):
    tw, _th = _text_dimensions(text, size)
    x = rect.x + (rect.w - tw) * 0.5
    y = rect.y + (rect.h - size) * 0.5 + 2
    _draw_text(x, y, text, size, color)


def _active_star_object(context):
    obj = context.view_layer.objects.active if context and context.view_layer else None
    if obj and obj.type == "MESH" and getattr(obj, "star_mesh_creator_obj", None) and obj.star_mesh_creator_obj.is_star:
        return obj
    return None


def _format_float(v: float) -> str:
    # Blender-like: show up to 3 decimals by default
    return f"{v:.3f}"


def _step_multiplier(event) -> float:
    # Blender-like modifiers
    mult = 1.0
    if getattr(event, "shift", False):
        mult *= 10.0
    if getattr(event, "ctrl", False):
        mult *= 0.1
    return mult


class STAR_OT_pinned_editor(bpy.types.Operator):
    bl_idname = "star_mesh_creator.pinned_editor"
    bl_label = "Star Edit"
    bl_options = {'INTERNAL'}

    # ---- runtime state ----
    _timer = None
    _dirty = False
    _dirty_time = 0.0
    _updating = False
    _needs_redraw = True

    # panel rect
    _rect_panel = None

    # hover / editing
    _hover_field = None  # "spikes"/"outer"/"inner"/"scale"/"thick"
    _editing_field = None
    _editing_text = ""
    _editing_original_value = None
    _editing_select_all = True  # True: 全選択モード, False: カーソル編集モード

    # drag value change
    _drag_field = None
    _drag_start_x = 0
    _drag_start_value = 0.0
    _drag_threshold_px = 4
    _dragging_value = False
    _click_initiated_field = None  # シングルクリック開始時のフィールド

    # layout constants (修正: パネル幅を340pxに縮小)
    pad = 10
    w = 340
    header_h = 26
    sub_h = 20
    row_h = 26
    footer_h = 40

    # value ui sizes (修正: 幅を調整)
    label_w = 115
    btn_w = 16
    gap = 4
    value_w = 80
    btn_h = 16
    value_h = 18

    # computed rects per field (stored each draw)
    _row_rects = None  # dict field->row rect
    _value_rects = None  # dict field->value rect (includes buttons area)
    _btn_left_rects = None
    _btn_right_rects = None

    # footer buttons
    _rect_save = None
    _rect_close = None

    _timer_interval = 0.10  # for debounce + caret blink

    # --------------------------------------------------------

    def _ensure_timer(self, context):
        if self._timer is None:
            self._timer = context.window_manager.event_timer_add(self._timer_interval, window=context.window)

    def _stop_timer_if_idle(self, context):
        if self._timer is None:
            return
        # keep timer while dirty, dragging, or editing (caret blink)
        if self._dirty or self._dragging_value or (self._editing_field is not None):
            return
        try:
            context.window_manager.event_timer_remove(self._timer)
        except Exception:
            pass
        self._timer = None

    def _tag_redraw_view3d(self, context):
        if not self._needs_redraw:
            return
        self._needs_redraw = False
        for area in context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()

    def _set_dirty(self, context):
        self._dirty = True
        self._dirty_time = time.time()
        self._needs_redraw = True
        self._ensure_timer(context)

    def _debounced_rebuild(self, context) -> bool:
        if not self._dirty:
            return False
        if (time.time() - self._dirty_time) < 0.10:
            return False

        obj = _active_star_object(context)
        self._dirty = False

        if not obj:
            return False
        if context.mode != "OBJECT":
            return False
        if self._updating:
            return False

        op = obj.star_mesh_creator_obj
        ok, _ = _validate(op.star_type, op.spikes, op.outer_radius, op.inner_radius, op.global_scale, op.thickness)
        if not ok:
            return False

        self._updating = True
        try:
            rebuild_star_mesh(
                obj,
                star_type=op.star_type,
                spikes=op.spikes,
                outer=op.outer_radius,
                inner=op.inner_radius,
                scale=op.global_scale,
                thickness=op.thickness,
                rot_deg=op.rotation_deg,
            )
            return True
        except Exception:
            return False
        finally:
            self._updating = False

    # --------------------------------------------------------
    # Value access helpers

    def _get_field_value(self, op, field):
        if field == "spikes":
            return int(op.spikes)
        if field == "outer":
            return float(op.outer_radius)
        if field == "inner":
            return float(op.inner_radius)
        if field == "scale":
            return float(op.global_scale)
        if field == "thick":
            return float(op.thickness)
        return 0.0

    def _set_field_value(self, op, field, value):
        # clamp + dependency rules
        if field == "spikes":
            op.spikes = max(3, min(256, int(round(value))))
            return

        if field == "outer":
            op.outer_radius = max(0.0001, float(value))
            if op.inner_radius >= op.outer_radius:
                op.inner_radius = max(0.0001, op.outer_radius * 0.5)
            return

        if field == "inner":
            v = max(0.0001, float(value))
            op.inner_radius = min(v, max(0.0001, op.outer_radius * 0.999))
            return

        if field == "scale":
            op.global_scale = max(0.0001, float(value))
            return

        if field == "thick":
            op.thickness = max(0.0, float(value))
            return


    def _field_default(self, field):
        # Default values (reset target) - match PropertyGroup defaults / typical expectations
        if field == "spikes":
            return 5
        if field == "outer":
            return 1.0
        if field == "inner":
            return 0.5
        if field == "scale":
            return 1.0
        if field == "thick":
            return 0.2
        return 0.0

    def _field_step(self, field) -> float:
        if field == "spikes":
            return 1.0
        # float fields
        return 0.01

    def _field_label(self, field) -> str:
        return {
            "spikes": "Spikes",
            "outer": "Outer Radius",
            "inner": "Inner Radius",
            "scale": "Global Scale",
            "thick": "Thickness",
        }.get(field, field)

    # --------------------------------------------------------
    # Inline editing

    def _start_editing(self, context, field, select_all: bool = True):
        """
        編集モードを開始する
        select_all=True: 全選択モード（シングルクリック）
        select_all=False: カーソル編集モード（ダブルクリック）
        """
        obj = _active_star_object(context)
        if not obj:
            return
        op = obj.star_mesh_creator_obj
        self._editing_field = field
        self._editing_original_value = self._get_field_value(op, field)
        v = self._editing_original_value
        self._editing_text = str(v) if field == "spikes" else _format_float(float(v))
        self._editing_select_all = select_all
        self._needs_redraw = True
        self._ensure_timer(context)

    def _cancel_editing(self, context):
        if self._editing_field is None:
            return
        obj = _active_star_object(context)
        if obj:
            op = obj.star_mesh_creator_obj
            self._set_field_value(op, self._editing_field, self._editing_original_value)
            self._set_dirty(context)
        self._editing_field = None
        self._editing_text = ""
        self._editing_original_value = None
        self._editing_select_all = True
        self._needs_redraw = True

    def _commit_editing(self, context):
        if self._editing_field is None:
            return
        obj = _active_star_object(context)
        if not obj:
            self._editing_field = None
            self._editing_select_all = True
            return
        op = obj.star_mesh_creator_obj

        text = (self._editing_text or "").strip()

        # If empty / cleared, or explicit 0 entered -> reset to field default (Blender-like convenience)
        if text in {"", "-", ".", "-.", "+", "+."}:
            v = self._field_default(self._editing_field)
        else:
            try:
                if self._editing_field == "spikes":
                    v = int(float(text))
                else:
                    v = float(text)
            except Exception:
                v = self._field_default(self._editing_field)

        # 0 input also resets to default (common in DCC UIs)
        if self._editing_field == "spikes":
            if int(v) == 0:
                v = self._field_default("spikes")
        else:
            try:
                if abs(float(v)) < 1e-12:
                    v = self._field_default(self._editing_field)
            except Exception:
                v = self._field_default(self._editing_field)

        self._set_field_value(op, self._editing_field, v)

        ok, _msg = _validate(op.star_type, op.spikes, op.outer_radius, op.inner_radius, op.global_scale, op.thickness)
        if not ok:
            self._cancel_editing(context)
            return

        self._editing_field = None
        self._editing_text = ""
        self._editing_original_value = None
        self._editing_select_all = True
        self._set_dirty(context)
        self._needs_redraw = True

    def _handle_text_input(self, context, event) -> bool:
        """Return True if event consumed."""
        if self._editing_field is None:
            return False

        # Confirm / cancel
        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            self._commit_editing(context)
            return True
        if event.type == 'ESC' and event.value == 'PRESS':
            self._cancel_editing(context)
            return True

        # Navigation / delete
        if event.type in {'BACK_SPACE', 'DEL'} and event.value == 'PRESS':
            if self._editing_select_all:
                # 全選択モードでDelete/BackSpace → 全削除
                self._editing_text = ""
                self._editing_select_all = False
            else:
                # カーソル編集モード → 末尾1文字削除
                if self._editing_text:
                    self._editing_text = self._editing_text[:-1]
            self._needs_redraw = True
            return True

        # Ignore non-press
        if event.value != 'PRESS':
            return True

        # Accept numeric input (including numpad)
        ch = ""
        if hasattr(event, "ascii") and event.ascii:
            ch = event.ascii
        else:
            # Fallback for numpad keys (Blender sometimes doesn't provide ascii)
            numpad_map = {
                'NUMPAD_0': '0', 'NUMPAD_1': '1', 'NUMPAD_2': '2', 'NUMPAD_3': '3', 'NUMPAD_4': '4',
                'NUMPAD_5': '5', 'NUMPAD_6': '6', 'NUMPAD_7': '7', 'NUMPAD_8': '8', 'NUMPAD_9': '9',
                'NUMPAD_PERIOD': '.', 'NUMPAD_MINUS': '-', 'NUMPAD_PLUS': '+',
            }
            ch = numpad_map.get(event.type, "")

        if not ch:
            # swallow other keys while editing so viewport doesn't react
            return True

        allowed = "0123456789.-+"
        if self._editing_field == "spikes":
            allowed = "0123456789-+"

        if ch in allowed:
            if self._editing_select_all:
                # 全選択モードで入力 → 既存テキストをクリアして入力
                self._editing_text = ch
                self._editing_select_all = False
            else:
                # カーソル編集モード → 末尾に追加
                self._editing_text += ch
            self._needs_redraw = True
        return True

    # --------------------------------------------------------
    # Hover detection

    def _update_hover(self, mx, my):
        self._hover_field = None
        if not self._value_rects:
            return

        # detect over value interaction area (value box + btns)
        for field, rect in self._value_rects.items():
            if rect and rect.contains(mx, my):
                self._hover_field = field
                return

    # --------------------------------------------------------
    # Drawing

    def _compute_panel_height(self, context):
        obj = _active_star_object(context)
        has_target = bool(obj)
        is_3d = has_target and (obj.star_mesh_creator_obj.star_type == "STAR_3D")
        rows = 4 + (1 if is_3d else 0)
        return self.pad * 2 + self.header_h + self.sub_h + rows * self.row_h + self.footer_h

    def _draw_param_row(self, x0, y, field, op, hovered: bool, editing: bool):
        # Row background highlight (subtle)
        bg = (0.10, 0.10, 0.10, 0.55)
        if hovered:
            bg = (0.12, 0.12, 0.12, 0.72)
        if editing:
            bg = (0.14, 0.14, 0.14, 0.80)

        row_rect = _UIRect(x0 + 6, y + 2, self.w - 12, self.row_h - 4)
        self._row_rects[field] = row_rect
        _draw_rect(row_rect.x, row_rect.y, row_rect.w, row_rect.h, bg)

        # Label
        _draw_text(x0 + 12, y + 7, self._field_label(field), 11, (0.92, 0.92, 0.92, 1))

        # Value interaction area
        base_x = x0 + 12 + self.label_w
        value_x = base_x + self.btn_w + self.gap
        right_btn_x = value_x + self.value_w + self.gap

        # Value area rect includes buttons (hover target)
        full_rect = _UIRect(base_x, y + 4, self.btn_w + self.gap + self.value_w + self.gap + self.btn_w, self.value_h)
        self._value_rects[field] = full_rect

        # Buttons appear only on hover or editing (like Blender)
        show_arrows = hovered or editing
        left_rect = _UIRect(base_x, y + 4, self.btn_w, self.btn_h) if show_arrows else None
        right_rect = _UIRect(right_btn_x, y + 4, self.btn_w, self.btn_h) if show_arrows else None
        self._btn_left_rects[field] = left_rect
        self._btn_right_rects[field] = right_rect

        # Value box
        val_rect = _UIRect(value_x, y + 4, self.value_w, self.value_h)

        # Blender-ish field color: slightly brighter on hover/edit
        val_bg = (0.16, 0.16, 0.16, 0.85)
        if hovered:
            val_bg = (0.19, 0.19, 0.19, 0.92)
        if editing:
            if self._editing_select_all:
                # 全選択モード: 選択状態の背景色（青みがかった色）
                val_bg = (0.20, 0.35, 0.55, 0.98)
            else:
                # カーソル編集モード: 通常の編集背景色
                val_bg = (0.22, 0.22, 0.22, 0.98)

        _draw_rect(val_rect.x, val_rect.y, val_rect.w, val_rect.h, val_bg)

        # Arrows
        if show_arrows:
            btn_bg = (0.14, 0.14, 0.14, 0.80)
            if hovered:
                btn_bg = (0.18, 0.18, 0.18, 0.92)
            _draw_rect(left_rect.x, left_rect.y, left_rect.w, left_rect.h, btn_bg)
            _draw_rect(right_rect.x, right_rect.y, right_rect.w, right_rect.h, btn_bg)
            _draw_text_centered_in_rect(left_rect, "<", 11, (0.92, 0.92, 0.92, 1))
            _draw_text_centered_in_rect(right_rect, ">", 11, (0.92, 0.92, 0.92, 1))

        # Value text (editing shows caret if not select_all)
        if editing:
            txt = self._editing_text
            if not self._editing_select_all:
                # カーソル編集モード: カーソル（|）を末尾に表示
                txt = txt + "|"
        else:
            v = self._get_field_value(op, field)
            txt = str(v) if field == "spikes" else _format_float(float(v))

        # right-aligned in value box
        tw, _ = _text_dimensions(txt, 11)
        tx = val_rect.x + val_rect.w - tw - 4
        ty = val_rect.y + 3
        _draw_text(tx, ty, txt, 11, (0.95, 0.95, 0.95, 1))

    def _draw(self, context):
        panel_h = self._compute_panel_height(context)
        x0 = self.pad
        y0 = self.pad

        self._rect_panel = _UIRect(x0, y0, self.w, panel_h)

        obj = _active_star_object(context)
        has_target = bool(obj)
        op = obj.star_mesh_creator_obj if has_target else None
        is_3d = has_target and (op.star_type == "STAR_3D")

        # reset rect dicts
        self._row_rects = {}
        self._value_rects = {}
        self._btn_left_rects = {}
        self._btn_right_rects = {}

        _draw_rect(x0, y0, self.w, panel_h, (0.08, 0.08, 0.08, 0.78))
        _draw_text(x0 + 10, y0 + panel_h - 20, "Star Edit", 13, (1, 1, 1, 1))

        target_txt = obj.name if has_target else "(No Star Selected)"
        _draw_text(x0 + 10, y0 + panel_h - 42, f"Target: {target_txt}", 11, (0.9, 0.9, 0.9, 1))

        if not has_target:
            _draw_text(x0 + 10, y0 + panel_h - 62, "Select a Star created by this addon.", 11, (1, 0.8, 0.2, 1))
            self._rect_save = self._rect_close = None
            return

        ok, msg = _validate(op.star_type, op.spikes, op.outer_radius, op.inner_radius, op.global_scale, op.thickness)
        if not ok:
            _draw_text(x0 + 10, y0 + panel_h - 62, f"Invalid: {msg}", 11, (1, 0.35, 0.35, 1))

        # rows start
        y = y0 + panel_h - 42 - self.sub_h - self.row_h

        fields = ["spikes", "outer", "inner", "scale"]
        if is_3d:
            fields.append("thick")

        for f in fields:
            hovered = (self._hover_field == f)
            editing = (self._editing_field == f)
            self._draw_param_row(x0, y, f, op, hovered, editing)
            y -= self.row_h

        # Footer buttons
        footer_y = y0 + 8
        btn_h = 20
        btn_gap = 8
        btn_w = int((self.w - 10 * 2 - btn_gap) / 2)

        self._rect_save = _UIRect(x0 + 10, footer_y, btn_w, btn_h)
        self._rect_close = _UIRect(x0 + 10 + btn_w + btn_gap, footer_y, btn_w, btn_h)

        _draw_rect(self._rect_save.x, self._rect_save.y, self._rect_save.w, self._rect_save.h, (0.25, 0.25, 0.25, 0.95))
        _draw_text_centered_in_rect(self._rect_save, "Save Preset", 10, (1, 1, 1, 1))

        _draw_rect(self._rect_close.x, self._rect_close.y, self._rect_close.w, self._rect_close.h, (0.25, 0.25, 0.25, 0.95))
        _draw_text_centered_in_rect(self._rect_close, "Close", 10, (1, 1, 1, 1))

    def _draw_callback(self, _self, context):
        self._draw(context)

    # --------------------------------------------------------
    # Interactions

    def _apply_step(self, context, field, direction: int, event):
        obj = _active_star_object(context)
        if not obj:
            return
        op = obj.star_mesh_creator_obj
        cur = self._get_field_value(op, field)
        step = self._field_step(field) * _step_multiplier(event)
        nxt = cur + (direction * step)
        self._set_field_value(op, field, nxt)
        self._set_dirty(context)

    def _start_value_drag(self, context, field, mx):
        obj = _active_star_object(context)
        if not obj:
            return
        op = obj.star_mesh_creator_obj

        self._drag_field = field
        self._drag_start_x = mx
        self._drag_start_value = float(self._get_field_value(op, field))
        self._dragging_value = False
        self._click_initiated_field = field
        self._ensure_timer(context)

    def _update_value_drag(self, context, mx, event):
        if not self._drag_field:
            return
        dx = mx - self._drag_start_x
        if not self._dragging_value:
            if abs(dx) < self._drag_threshold_px:
                return
            self._dragging_value = True
            # ドラッグ開始時に編集中なら確定
            if self._editing_field is not None:
                self._commit_editing(context)

        obj = _active_star_object(context)
        if not obj:
            return
        op = obj.star_mesh_creator_obj

        field = self._drag_field
        mult = _step_multiplier(event)

        if field == "spikes":
            # 10px per spike step
            delta = int(round(dx / 10.0))
            self._set_field_value(op, field, self._drag_start_value + delta)
        else:
            # float: pixels -> delta
            # base sensitivity: 0.002 per px, scaled by modifiers
            sens = 0.002 * mult
            self._set_field_value(op, field, self._drag_start_value + dx * sens)

        self._set_dirty(context)

    def _end_value_drag(self, context):
        """ドラッグ終了処理。閾値未満ならシングルクリックとして処理"""
        was_dragging = self._dragging_value
        click_field = self._click_initiated_field
        
        self._drag_field = None
        self._dragging_value = False
        self._click_initiated_field = None
        
        # 閾値未満のクリック（ドラッグしなかった）→ シングルクリックとして編集開始
        if not was_dragging and click_field is not None:
            # 既に同じフィールドを編集中
            if self._editing_field == click_field:
                if self._editing_select_all:
                    # 全選択モード中に再クリック → カーソル編集モードへ
                    self._editing_select_all = False
                    return True
                return False
            # 別のフィールドを編集中なら確定してから新しいフィールドの編集開始
            if self._editing_field is not None:
                self._commit_editing(context)
            # シングルクリック → 全選択モードで編集開始
            self._start_editing(context, click_field, select_all=True)
            return True
        
        return False

    # --------------------------------------------------------

    def invoke(self, context, event):
        global _EDITOR_RUNNING, _EDITOR_DRAW_HANDLE

        if _EDITOR_RUNNING:
            return {'CANCELLED'}

        _EDITOR_RUNNING = True
        self._needs_redraw = True

        _EDITOR_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (self, context), 'WINDOW', 'POST_PIXEL'
        )

        self._timer = None
        context.window_manager.modal_handler_add(self)
        self._tag_redraw_view3d(context)
        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # While editing: capture key events (especially NUMPAD) so viewport doesn't react.
        if self._editing_field is not None and event.type not in {'MOUSEMOVE', 'TIMER'}:
            if event.type in {'LEFTMOUSE', 'RIGHTMOUSE', 'MIDDLEMOUSE'}:
                # clicks handled below (allow clicking arrows etc)
                pass
            else:
                consumed = self._handle_text_input(context, event)
                if consumed:
                    self._tag_redraw_view3d(context)
                    return {'RUNNING_MODAL'}

        if event.type == 'TIMER':

            did = self._debounced_rebuild(context)
            if did:
                self._needs_redraw = True

            self._stop_timer_if_idle(context)
            self._tag_redraw_view3d(context)
            return {'PASS_THROUGH'}

        # Mouse gating: if outside panel and not dragging, handle specially
        if event.type in {'LEFTMOUSE', 'MOUSEMOVE'}:
            mx = event.mouse_region_x
            my = event.mouse_region_y
            if self._drag_field is None:
                if self._rect_panel and (not self._rect_panel.contains(mx, my)):
                    # パネル外でのクリック処理
                    if event.type == 'LEFTMOUSE' and event.value == 'PRESS':
                        # パネル外クリック → 編集中なら確定
                        if self._editing_field is not None:
                            self._commit_editing(context)
                            self._needs_redraw = True
                            self._tag_redraw_view3d(context)
                        return {'PASS_THROUGH'}
                    
                    if event.type == 'MOUSEMOVE':
                        # clear hover if we leave panel
                        if self._hover_field is not None:
                            self._hover_field = None
                            self._needs_redraw = True
                            self._tag_redraw_view3d(context)
                    return {'PASS_THROUGH'}

        # Update hover on move (only within panel)
        if event.type == 'MOUSEMOVE':
            mx = event.mouse_region_x
            my = event.mouse_region_y
            prev = self._hover_field
            self._update_hover(mx, my)
            if self._hover_field != prev:
                self._needs_redraw = True
                self._tag_redraw_view3d(context)

            # Dragging value?
            if self._drag_field is not None:
                self._update_value_drag(context, mx, event)
                self._needs_redraw = True
                self._tag_redraw_view3d(context)
                return {'RUNNING_MODAL'}

            return {'PASS_THROUGH'}

        # Click handling
        if event.type == 'LEFTMOUSE':
            mx = event.mouse_region_x
            my = event.mouse_region_y

            if event.value == 'PRESS':
                # Footer
                if self._rect_save and self._rect_save.contains(mx, my):
                    # 編集中なら確定
                    if self._editing_field is not None:
                        self._commit_editing(context)
                    try:
                        bpy.ops.star_mesh_creator.save_preset_dialog('INVOKE_DEFAULT')
                    except Exception:
                        pass
                    self._needs_redraw = True
                    self._tag_redraw_view3d(context)
                    return {'RUNNING_MODAL'}

                if self._rect_close and self._rect_close.contains(mx, my):
                    # 編集中なら確定
                    if self._editing_field is not None:
                        self._commit_editing(context)
                    self._finish(context)
                    return {'CANCELLED'}

                # If clicked on arrows (only exist when hover/edit)
                for field in list(self._btn_left_rects.keys()):
                    lrect = self._btn_left_rects.get(field)
                    rrect = self._btn_right_rects.get(field)
                    if lrect and lrect.contains(mx, my):
                        # If editing another field, commit it first (Blender-like)
                        if self._editing_field is not None and self._editing_field != field:
                            self._commit_editing(context)
                        elif self._editing_field == field:
                            self._commit_editing(context)
                        self._apply_step(context, field, -1, event)
                        self._needs_redraw = True
                        self._tag_redraw_view3d(context)
                        return {'RUNNING_MODAL'}
                    if rrect and rrect.contains(mx, my):
                        if self._editing_field is not None and self._editing_field != field:
                            self._commit_editing(context)
                        elif self._editing_field == field:
                            self._commit_editing(context)
                        self._apply_step(context, field, +1, event)
                        self._needs_redraw = True
                        self._tag_redraw_view3d(context)
                        return {'RUNNING_MODAL'}

                # シングルクリック in value area: ドラッグ候補開始
                # （マウスリリース時に閾値未満ならシングルクリックとして全選択編集モードに入る）
                for field, vrect in (self._value_rects or {}).items():
                    if vrect and vrect.contains(mx, my):
                        self._start_value_drag(context, field, mx)
                        self._needs_redraw = True
                        self._tag_redraw_view3d(context)
                        return {'RUNNING_MODAL'}

            elif event.value == 'RELEASE':
                if self._drag_field is not None:
                    # ドラッグ終了（閾値未満ならシングルクリックとして処理）
                    started_edit = self._end_value_drag(context)
                    self._stop_timer_if_idle(context)
                    self._needs_redraw = True
                    self._tag_redraw_view3d(context)
                    return {'RUNNING_MODAL'}

        # Allow other events to pass through
        return {'PASS_THROUGH'}

    def _finish(self, context):
        global _EDITOR_RUNNING, _EDITOR_DRAW_HANDLE

        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

        try:
            if _EDITOR_DRAW_HANDLE is not None:
                bpy.types.SpaceView3D.draw_handler_remove(_EDITOR_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass

        _EDITOR_DRAW_HANDLE = None
        _EDITOR_RUNNING = False

        for area in context.window.screen.areas:
            if area.type == 'VIEW_3D':
                area.tag_redraw()


# ============================================================
# Register
# ============================================================

classes = (
    STAR_ObjProps,
    STAR_SceneProps,
    STAR_OT_create,
    STAR_OT_save_preset_dialog,
    STAR_PT_sidebar,
    STAR_OT_pinned_editor,
)


def register():
    for c in classes:
        bpy.utils.register_class(c)
    bpy.types.Object.star_mesh_creator_obj = PointerProperty(type=STAR_ObjProps)
    bpy.types.Scene.star_mesh_creator = PointerProperty(type=STAR_SceneProps)


def unregister():
    global _EDITOR_RUNNING, _EDITOR_DRAW_HANDLE
    _EDITOR_RUNNING = False
    if _EDITOR_DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceView3D.draw_handler_remove(_EDITOR_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass
        _EDITOR_DRAW_HANDLE = None

    del bpy.types.Scene.star_mesh_creator
    del bpy.types.Object.star_mesh_creator_obj
    for c in reversed(classes):
        bpy.utils.unregister_class(c)


if __name__ == "__main__":
    register()
