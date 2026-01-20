bl_info = {
    "name": "Star Mesh Creator (Simple + Pinned Editor)",
    "author": "Ayaka Matsubayashi",
    "version": (1, 0, 1),
    "blender": (3, 6, 0),
    "location": "View3D > Sidebar (N) > Star",
    "description": "Create 2D/3D star mesh (triangle fan from center). Pinned bottom-left editor with realtime rebuild and preset saving to Scene Collection.",
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

    # Triangle fan from center
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
        return context.window_manager.invoke_props_dialog(self, width=360)

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
#  Fix for selection responsiveness:
#   - Only handle mouse events inside panel rect
#   - Timer runs only while dirty or dragging (on-demand)
#   - Redraw only when needed
# ============================================================

_EDITOR_RUNNING = False
_EDITOR_DRAW_HANDLE = None


def _active_star_object(context):
    obj = context.view_layer.objects.active if context and context.view_layer else None
    if obj and obj.type == "MESH" and getattr(obj, "star_mesh_creator_obj", None) and obj.star_mesh_creator_obj.is_star:
        return obj
    return None


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


class STAR_OT_pinned_editor(bpy.types.Operator):
    bl_idname = "star_mesh_creator.pinned_editor"
    bl_label = "Star Edit "
    bl_options = {'INTERNAL'}

    # State
    _timer = None
    _dirty = False
    _dirty_time = 0.0
    _updating = False
    _dragging = None
    _needs_redraw = True

    # Panel rect
    _rect_panel = None

    # Layout
    pad = 10
    w = 360
    header_h = 26
    line_h = 20
    row_h = 24
    slider_w = 160
    slider_h = 10
    footer_h = 40

    # Click rects
    _rect_save = None
    _rect_close = None

    # Slider rects
    _r_spikes = None
    _r_outer = None
    _r_inner = None
    _r_scale = None
    _r_thick = None

    # timer params
    _timer_interval = 0.12  # slower = less interference

    def _ensure_timer(self, context):
        if self._timer is None:
            self._timer = context.window_manager.event_timer_add(self._timer_interval, window=context.window)

    def _stop_timer_if_idle(self, context):
        # Stop timer if nothing to do
        if self._timer is None:
            return
        if self._dirty or self._dragging:
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
        """Return True if a rebuild occurred."""
        if not self._dirty:
            return False
        if (time.time() - self._dirty_time) < 0.12:
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

    def _draw_slider_row(self, x0, y, label, value_str, rect_attr, t_norm):
        label_x = x0 + 12
        slider_x = x0 + 150
        value_x = x0 + self.w - 58

        _draw_text(label_x, y + 4, label, 11, (1, 1, 1, 1))

        bar = _UIRect(slider_x, y + 6, self.slider_w, self.slider_h)
        setattr(self, rect_attr, bar)

        _draw_rect(bar.x, bar.y, bar.w, bar.h, (0.18, 0.18, 0.18, 0.95))
        t = _clamp(t_norm, 0.0, 1.0)
        _draw_rect(bar.x, bar.y, bar.w * t, bar.h, (0.35, 0.55, 0.95, 0.95))
        _draw_text(value_x, y + 4, value_str, 11, (0.95, 0.95, 0.95, 1))

    def _compute_panel_height(self, context):
        obj = _active_star_object(context)
        has_target = bool(obj)
        is_3d = has_target and (obj.star_mesh_creator_obj.star_type == "STAR_3D")
        rows = 4 + (1 if is_3d else 0)
        panel_h = (
            self.pad * 2
            + self.header_h
            + self.line_h
            + rows * self.row_h
            + self.footer_h
        )
        return panel_h

    def _draw(self, context):
        panel_h = self._compute_panel_height(context)
        x0 = self.pad
        y0 = self.pad

        # Store panel rect for fast event gating
        self._rect_panel = _UIRect(x0, y0, self.w, panel_h)

        obj = _active_star_object(context)
        has_target = bool(obj)
        op = obj.star_mesh_creator_obj if has_target else None
        is_3d = has_target and (op.star_type == "STAR_3D")

        _draw_rect(x0, y0, self.w, panel_h, (0.08, 0.08, 0.08, 0.78))
        _draw_text(x0 + 12, y0 + panel_h - 20, "Star Edit (Pinned)", 13, (1, 1, 1, 1))

        target_txt = obj.name if has_target else "(No Star Selected)"
        _draw_text(x0 + 12, y0 + panel_h - 44, f"Target: {target_txt}", 11, (0.9, 0.9, 0.9, 1))

        if not has_target:
            _draw_text(x0 + 12, y0 + panel_h - 64, "Select a Star created by this addon.", 11, (1, 0.8, 0.2, 1))
            self._r_spikes = self._r_outer = self._r_inner = self._r_scale = self._r_thick = None
            self._rect_save = self._rect_close = None
            return

        ok, msg = _validate(op.star_type, op.spikes, op.outer_radius, op.inner_radius, op.global_scale, op.thickness)
        if not ok:
            _draw_text(x0 + 12, y0 + panel_h - 64, f"Invalid: {msg}", 11, (1, 0.35, 0.35, 1))

        y = y0 + panel_h - 44 - self.line_h - self.row_h

        spikes_ui_max = 64
        spikes_t = (op.spikes - 3) / (spikes_ui_max - 3) if spikes_ui_max > 3 else 0.0
        self._draw_slider_row(x0, y, "Spikes", str(op.spikes), "_r_spikes", spikes_t)
        y -= self.row_h

        outer_t = (op.outer_radius - 0.01) / (10.0 - 0.01)
        self._draw_slider_row(x0, y, "Outer Radius", f"{op.outer_radius:.3f}", "_r_outer", outer_t)
        y -= self.row_h

        inner_t = (op.inner_radius - 0.01) / (9.5 - 0.01)
        self._draw_slider_row(x0, y, "Inner Radius", f"{op.inner_radius:.3f}", "_r_inner", inner_t)
        y -= self.row_h

        scale_t = (op.global_scale - 0.01) / (10.0 - 0.01)
        self._draw_slider_row(x0, y, "Global Scale", f"{op.global_scale:.3f}", "_r_scale", scale_t)
        y -= self.row_h

        if is_3d:
            thick_t = (op.thickness - 0.0) / (5.0 - 0.0)
            self._draw_slider_row(x0, y, "Thickness", f"{op.thickness:.3f}", "_r_thick", thick_t)
        else:
            self._r_thick = None

        # Footer buttons (side-by-side)
        footer_y = y0 + 10
        btn_h = 22
        gap = 10
        btn_w = int((self.w - 12 * 2 - gap) / 2)

        self._rect_save = _UIRect(x0 + 12, footer_y, btn_w, btn_h)
        self._rect_close = _UIRect(x0 + 12 + btn_w + gap, footer_y, btn_w, btn_h)

        _draw_rect(self._rect_save.x, self._rect_save.y, self._rect_save.w, self._rect_save.h, (0.25, 0.25, 0.25, 0.95))
        _draw_text_centered_in_rect(self._rect_save, "Save Preset", 11, (1, 1, 1, 1))

        _draw_rect(self._rect_close.x, self._rect_close.y, self._rect_close.w, self._rect_close.h, (0.25, 0.25, 0.25, 0.95))
        _draw_text_centered_in_rect(self._rect_close, "Close", 11, (1, 1, 1, 1))

    def _draw_callback(self, _self, context):
        self._draw(context)

    def _set_slider_value(self, context, key, t_norm):
        obj = _active_star_object(context)
        if not obj:
            return
        op = obj.star_mesh_creator_obj
        t = _clamp(t_norm, 0.0, 1.0)

        if key == "spikes":
            v = int(round(3 + t * (64 - 3)))
            v = max(3, min(256, v))
            op.spikes = v

        elif key == "outer":
            v = 0.01 + t * (10.0 - 0.01)
            op.outer_radius = max(0.0001, v)
            if op.inner_radius >= op.outer_radius:
                op.inner_radius = max(0.0001, op.outer_radius * 0.5)

        elif key == "inner":
            v = 0.01 + t * (9.5 - 0.01)
            v = max(0.0001, v)
            op.inner_radius = min(v, max(0.0001, op.outer_radius * 0.999))

        elif key == "scale":
            v = 0.01 + t * (10.0 - 0.01)
            op.global_scale = max(0.0001, v)

        elif key == "thick":
            v = 0.0 + t * (5.0 - 0.0)
            op.thickness = max(0.0, v)

        self._set_dirty(context)

    def invoke(self, context, event):
        global _EDITOR_RUNNING, _EDITOR_DRAW_HANDLE
        if _EDITOR_RUNNING:
            return {'CANCELLED'}

        _EDITOR_RUNNING = True
        self._needs_redraw = True

        _EDITOR_DRAW_HANDLE = bpy.types.SpaceView3D.draw_handler_add(
            self._draw_callback, (self, context), 'WINDOW', 'POST_PIXEL'
        )

        # Start without timer; create on-demand when dirty/dragging
        self._timer = None
        context.window_manager.modal_handler_add(self)

        # Ensure first draw appears
        self._tag_redraw_view3d(context)

        return {'RUNNING_MODAL'}

    def modal(self, context, event):
        # TIMER: rebuild only when needed; stop timer when idle
        if event.type == 'TIMER':
            did = self._debounced_rebuild(context)
            if did:
                self._needs_redraw = True
            # If we aren't dirty or dragging, stop timer (reduces interference)
            self._stop_timer_if_idle(context)
            self._tag_redraw_view3d(context)
            return {'PASS_THROUGH'}

        # Gate mouse events: if outside panel and not dragging, do nothing
        if event.type in {'LEFTMOUSE', 'MOUSEMOVE'}:
            mx = event.mouse_region_x
            my = event.mouse_region_y

            if self._dragging is None:
                # If we haven't drawn yet, do not block anything
                if self._rect_panel and (not self._rect_panel.contains(mx, my)):
                    return {'PASS_THROUGH'}

        if event.type == 'LEFTMOUSE':
            mx = event.mouse_region_x
            my = event.mouse_region_y

            if event.value == 'PRESS':
                # inside panel only
                if self._rect_save and self._rect_save.contains(mx, my):
                    try:
                        bpy.ops.star_mesh_creator.save_preset_dialog('INVOKE_DEFAULT')
                    except Exception:
                        pass
                    # redraw to keep UI responsive
                    self._needs_redraw = True
                    self._tag_redraw_view3d(context)
                    return {'RUNNING_MODAL'}

                if self._rect_close and self._rect_close.contains(mx, my):
                    self._finish(context)
                    return {'CANCELLED'}

                # Sliders
                for key, rect in (
                    ("spikes", self._r_spikes),
                    ("outer", self._r_outer),
                    ("inner", self._r_inner),
                    ("scale", self._r_scale),
                    ("thick", self._r_thick),
                ):
                    if rect and rect.contains(mx, my):
                        self._dragging = key
                        self._ensure_timer(context)  # dragging needs timer for debounced rebuild
                        t = (mx - rect.x) / rect.w if rect.w > 0 else 0.0
                        self._set_slider_value(context, key, t)
                        self._needs_redraw = True
                        self._tag_redraw_view3d(context)
                        return {'RUNNING_MODAL'}

            elif event.value == 'RELEASE':
                if self._dragging is not None:
                    self._dragging = None
                    # keep timer only if still dirty; otherwise stop soon
                    self._stop_timer_if_idle(context)
                    self._needs_redraw = True
                    self._tag_redraw_view3d(context)
                return {'RUNNING_MODAL'}

        if event.type == 'MOUSEMOVE' and self._dragging:
            rect = {
                "spikes": self._r_spikes,
                "outer": self._r_outer,
                "inner": self._r_inner,
                "scale": self._r_scale,
                "thick": self._r_thick,
            }.get(self._dragging)
            if rect:
                mx = event.mouse_region_x
                t = (mx - rect.x) / rect.w if rect.w > 0 else 0.0
                self._set_slider_value(context, self._dragging, t)
                self._needs_redraw = True
                self._tag_redraw_view3d(context)
            return {'RUNNING_MODAL'}

        return {'PASS_THROUGH'}

    def _finish(self, context):
        global _EDITOR_RUNNING, _EDITOR_DRAW_HANDLE

        # Remove timer if running
        if self._timer is not None:
            try:
                context.window_manager.event_timer_remove(self._timer)
            except Exception:
                pass
            self._timer = None

        # Remove draw handler
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
