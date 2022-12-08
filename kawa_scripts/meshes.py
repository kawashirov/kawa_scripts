# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import bpy as _bpy
import mathutils as _mu
import bmesh as _bmesh

from . import _internals
from ._internals import log as _log
from . import armature as _armatures
from . import objects as _objects
from . import commons as _commons

import typing as _typing

if _typing.TYPE_CHECKING:
	from mathutils import Vector
	from typing import Optional, Iterable, List, Sequence, Set
	from bpy.types import Object, Mesh, Material, Operator
	from .objects import HandyMultiObject


def poly2_area2(ps: 'Sequence[Vector]'):
	# Площадь полигона, примерно, без учёта вогнутостей
	length = len(ps)
	if length < 3:
		return 0
	_area_tri = _mu.geometry.area_tri
	if length == 3:
		# Частый случай, оптимизация для треугольника
		return _area_tri(ps[0], ps[1], ps[2])
	if length == 4:
		# Частый случай, оптимизация для квада
		return _area_tri(ps[0], ps[1], ps[2]) + _area_tri(ps[0], ps[2], ps[3])
	# Для пентагона и выше - Формула Гаусса
	s = ps[length - 1].x * ps[0].y - ps[0].x * ps[length - 1].y
	for i in range(length - 1):
		s += ps[i].x * ps[i + 1].y
		s -= ps[i + 1].x * ps[i].y
	return 0.5 * abs(s)


def is_mesh_object(obj: 'Object') -> 'bool':
	return obj is not None and obj.type == 'MESH' and isinstance(obj.data, _bpy.types.Mesh)


def get_safe(obj: 'Object', strict: 'bool' = None, op: 'Operator' = None) -> 'Optional[Mesh]':
	return _internals.get_data_safe(obj, is_mesh_object, 'Mesh', strict=strict, op=op)


def remove_all_geometry(obj: 'Object', strict: 'Optional[bool]' = None):
	# Очистка геометрии
	mesh = get_safe(obj, strict=strict)
	if mesh is None:
		return
	bm = _bmesh.new()
	try:
		# Дегенеративные уебки, почему в Mesh нет API для удаления геометрии?
		bm.from_mesh(mesh)
		bm.clear()  # TODO optimize?
		bm.to_mesh(mesh)
	finally:
		bm.free()


def remove_all_vertex_colors(obj: 'Object', strict: 'Optional[bool]' = None):
	mesh = get_safe(obj, strict=strict)
	if mesh is None:
		return
	while len(mesh.vertex_colors) > 0:
		mesh.vertex_colors.remove(mesh.vertex_colors[0])


def remove_all_material_slots(obj: 'Object', slots=0):
	while len(obj.material_slots) > slots:
		_bpy.context.view_layer.objects.active = obj
		_commons.ensure_op_finished(_bpy.ops.object.material_slot_remove(), name='bpy.ops.object.material_slot_remove')


def find_objects_with_material(material: 'Material', where: 'Iterable[Object]' = None) -> 'Set[Object]':
	objects = set()
	if where is None:
		where = _bpy.context.scene.objects
	for obj in where:
		if not isinstance(obj.data, _bpy.types.Mesh):
			continue
		for slot in obj.material_slots:
			if slot.material == material:
				objects.add(obj)
	return objects


def is_mesh_affected_by_armature(arm_obj: 'Object', mesh_obj: 'Object', strict: 'bool' = None, op: 'Operator' = None) -> 'bool':
	if _armatures.get_safe(arm_obj, strict=strict, op=op) is None:
		return False
	if get_safe(arm_obj, strict=strict, op=op) is None:
		return False
	for mod in mesh_obj.modifiers:
		if mod.type == 'ARMATURE' and mod.object == arm_obj:
			return True
	return False


def is_mesh_affected_by_any_armature(arm_objs: 'Iterable[Object]', mesh_obj: 'Object',
		strict: 'bool' = None, op: 'Operator' = None) -> 'bool':
	return any(is_mesh_affected_by_armature(arm_obj, mesh_obj, strict=strict, op=op) for arm_obj in arm_objs)


def find_meshes_affected_by_armatue(arm_obj: 'Object', where: 'Iterable[Object]' = None,
		strict: 'bool' = None, op: 'Operator' = None) -> 'List[Object]':
	if where is None:
		where = _bpy.data.objects
	return list(obj for obj in where if is_mesh_object(obj) and is_mesh_affected_by_armature(arm_obj, obj, strict=strict, op=op))


def _merge_same_material_slots_single(obj: 'Object', mesh: 'Mesh'):
	_log.info(f"Merging same slots on {obj!r}...")
	# Этап 1: собираем уникальные материалы
	mats = set(slot.material for slot in obj.material_slots if slot is not None and slot.material is not None)
	# Этап 2: собираем отображения для замены
	mapping = list(i for i in range(len(obj.material_slots)))
	need_remap = False
	for proc_mat in mats:
		# Индексы слотов, которые используют этот материал, всегда есть хотя бы один.
		indices = list(slot for slot in range(len(obj.material_slots)) if obj.material_slots[slot].material is proc_mat)
		for idx in indices:
			# Отображения самого на себя тоже включены,
			# что бы не делать лишний None-чек на долгой итерации
			mapping[idx] = indices[0]
		if len(indices) > 2:
			need_remap = True
	if not need_remap:
		return False
	# Этап 3: производим замену
	_log.info(f"Merging same slots on {obj!r}: {mapping!r}")
	bm = _bmesh.new()
	try:
		bm.from_mesh(mesh)
		bm.faces.ensure_lookup_table()
		for face in bm.faces:
			face.material_index = mapping[face.material_index]
		bm.to_mesh(mesh)
	finally:
		bm.free()
	return True


def merge_same_material_slots(objs: 'HandyMultiObject', strict: 'bool' = None):
	# Объединяет слоты с одинаковыми материалами:
	# Сначала объединяет индексы, затем удаляет освободившиеся слоты.
	# Игнорирует пустые слоты
	objs = list(_objects.resolve_objects(objs))
	_log.info(f"Merging same slots on {len(objs)} objects...")
	
	# Этап 1: Сначала просто убрать неиспользуемые слоты.
	_objects.deselect_all()
	_objects.activate(objs)
	_bpy.ops.object.material_slot_remove_unused()  # Может быть не-FINISHED
	
	# Этап 2: Ищем меш-объекты с 2 или более слотами в обжект-моде.
	no_dup = set()
	remapped = list()
	for obj in objs:
		mesh = get_safe(obj, strict=strict)
		if mesh is None or mesh in no_dup or len(obj.material_slots) < 2:
			continue
		if not _objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		no_dup.add(mesh)
		_objects.deselect_all()
		_objects.activate(obj)
		if _merge_same_material_slots_single(obj, mesh):
			remapped.append(obj)
	
	# Этап 3: На обработанных мешах убираем неиспользуемые слоты еще раз.
	if len(remapped) > 0:
		_objects.deselect_all()
		_objects.activate(remapped)
		_commons.ensure_op_finished_or_cancelled(
			_bpy.ops.object.material_slot_remove_unused(), name='bpy.ops.object.material_slot_remove_unused'
		)
		_objects.deselect_all()
	_log.info(f"Merged same slots on {len(remapped)}/{len(objs)} objects.")
