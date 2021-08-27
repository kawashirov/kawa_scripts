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

from ._internals import log as _log
from . import objects as _objects
from . import commons as _commons

import typing as _typing

if _typing.TYPE_CHECKING:
	from mathutils import Vector
	from typing import Optional, Iterable, List, Sequence, Set
	from bpy.types import Object, Mesh, Material


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


def get_mesh_safe(obj: 'Object', strict: 'Optional[bool]' = None) -> 'Optional[Mesh]':
	if strict is None:
		strict = True
		
	if obj is None:
		if strict:
			raise ValueError("Object is None!")
		return None  # silent none
	
	if obj.type != 'MESH' or not isinstance(obj.data, _bpy.types.Mesh):
		if strict:
			raise ValueError("{!r}.data is not Mesh! ({!r})".format(obj, type(obj.data)), obj, obj.data)
		return None  # silent none
	
	return obj.data


def remove_all_geometry(obj: 'Object', strict: 'Optional[bool]' = None):
	# Очистка геометрии
	mesh = get_mesh_safe(obj, strict=strict)
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
	mesh = get_mesh_safe(obj, strict=strict)
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


def is_mesh_affected_by_armature(arm_obj: 'Object', mesh_obj: 'Object') -> 'bool':
	if arm_obj.type != 'ARMATURE':
		raise ValueError("arm_obj {} is not 'ARMATURE' type ({})".format(repr(arm_obj), repr(arm_obj.type)))
	if mesh_obj.type != 'MESH':
		raise ValueError("mesh_obj {} is not 'MESH' type ({})".format(repr(mesh_obj), repr(mesh_obj.type)))
	for mod in mesh_obj.modifiers:
		if mod.type == 'ARMATURE' and mod.object == arm_obj:
			return True
	return False


def is_mesh_affected_by_any_armature(arm_objs: 'Iterable[Object]', mesh_obj: 'Object') -> 'bool':
	return any(is_mesh_affected_by_armature(arm_obj, mesh_obj) for arm_obj in arm_objs)


def find_meshes_affected_by_armatue(arm_obj: 'Object', where: 'Iterable[Object]' = None) -> 'List[Object]':
	if where is None:
		where = _bpy.data.objects
	return list(obj for obj in where if obj.type == 'MESH' and is_mesh_affected_by_armature(arm_obj, obj))


def merge_same_material_slots(obj: 'Object'):
	# Объединяет слоты с одинаковыми материалами:
	# Сначала объединяет индексы, затем удаляет освободившиеся слоты.
	# Игнорирует пустые слоты
	if len(obj.material_slots) < 2:
		return
	_objects.deselect_all()
	_objects.activate(obj)
	mesh = get_mesh_safe(obj)
	# Все материалы используемые на объекте
	mats = set()
	run_op = False
	for slot in obj.material_slots:
		if slot is None or slot.material is None:
			continue
		mats.add(slot.material)
	for proc_mat in mats:
		indices = list()
		for slot in range(len(obj.material_slots)):
			if obj.material_slots[slot].material is proc_mat:
				indices.append(slot)
		if len(indices) < 2:
			continue
		run_op = True
		main_idx = indices[0]
		for idx in indices[1:]:
			for poly in mesh.polygons:
				if poly.material_index == idx:
					poly.material_index = main_idx
	if run_op:
		_commons.ensure_op_finished_or_cancelled(
			_bpy.ops.object.material_slot_remove_unused(), name='bpy.ops.object.material_slot_remove_unused'
		)
	_objects.deselect_all()
