# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
"""
Useful tools for Vertex Groups
"""
from math import sqrt as _sqrt

import bpy as _bpy
import bmesh as _bmesh
import bpy.app

from . import _internals
from . import _doc
from ._internals import log as _log
from . import objects as _objects
from . import meshes as _meshes

import typing as _typing

if _typing.TYPE_CHECKING:
	from .objects import HandyMultiObject
	from typing import Union, Tuple, Dict, List, Optional
	from bpy.types import Object, Mesh, VertexGroup, Context, MeshVertex, Operator
	from bmesh.types import BMLayerItem, BMDeformVert


def _any_weight(mesh: 'Mesh', group_index: 'int', limit: 'float' = 0.0):
	# В худшем случае производительность NxM, но иначе никак:
	# VertexGroup.weight(index) требует теста
	for i in range(len(mesh.vertices)):
		for vge in mesh.vertices[i].groups.values():
			if vge.group == group_index and vge.weight > limit:
				return True
	return False


def get_weight_safe(group: 'VertexGroup', index: 'int', default=0.0):
	try:
		return group.weight(index)
	except RuntimeError:
		return default


def halfbone_apply_armature(objs: 'HandyMultiObject'):
	objs = list(_objects.resolve_objects(objs))
	armature_obj = list(obj for obj in objs if obj.type == 'ARMATURE' and isinstance(obj.data, _bpy.types.Armature))
	if len(armature_obj) != 1:
		raise RuntimeError(f"There is no single Armature-Object provided ({len(armature_obj)})")
	armature_obj = armature_obj[0]  # type: Union[Object, List[Object]]
	
	armature_data = armature_obj.data  # type: _bpy.types.Armature
	
	if armature_data.bones.active is None:
		raise RuntimeError(f"There is no active bone in Armature-Object provided ({armature_obj})")
	half_name = armature_data.bones.active.name
	
	selected = list(bone.name for bone in armature_data.bones if armature_data.bones.active != bone and bone.select)
	if len(selected) != 2:
		raise RuntimeError(f"There is no two selected control bones in Armature-Object provided ({len(selected)})")
	ctrl_a, ctrl_b = selected
	
	mesh_objs = list(obj for obj in objs if _meshes.is_mesh_object(obj))
	if len(mesh_objs) < 1:
		raise RuntimeError(f"There is no Mesh-Objects provided ({len(mesh_objs)})")
	
	halfbone_apply_weight(mesh_objs, ctrl_a, ctrl_b, half_name)


def halfbone_apply_weight(objs: '_objects.HandyMultiObject', ctrl_a: 'Union[str, int]', ctrl_b: 'Union[str, int]',
		half_name: 'Union[str, int]'):
	for obj in _objects.resolve_objects(objs):
		halfbone_apply_weight_single(obj, ctrl_a, ctrl_b, half_name)


def halfbone_apply_weight_single(obj: 'Object', ctrl_a: 'Union[str, int]', ctrl_b: 'Union[str, int]', half_name: 'Union[str, int]'):
	mesh = obj.data  # type: Mesh
	a_group = obj.vertex_groups.get(ctrl_a)
	b_group = obj.vertex_groups.get(ctrl_b)
	if a_group is None or b_group is None:
		return
	half_group = obj.vertex_groups.get(half_name)
	if half_group is None:
		half_group = obj.vertex_groups.new(name=half_name)
	index_list = [0]
	for v in mesh.vertices:  # type: MeshVertex
		a_w = get_weight_safe(a_group, v.index)
		if 1.0 <= a_w or a_w <= 0.0:
			continue
		b_w = get_weight_safe(b_group, v.index)
		if 1.0 <= a_w or a_w <= 0.0:
			continue
		lg = a_w + b_w  # <1
		a_wn, b_wn = a_w / lg, b_w / lg
		# вычисляем новый вес для полугурппы
		h_wn = min(a_wn, b_wn) * 2.0 * lg
		# отображение [0.5..1] в [0...1]
		a_wn = min(max(a_wn * 2.0 - 1.0, 0.0), 1.0) * lg
		b_wn = min(max(b_wn * 2.0 - 1.0, 0.0), 1.0) * lg
		#
		print("#{}: {}, {} -> {}, {} and {}".format(v.index, a_w, b_w, a_wn, b_wn, h_wn))
		index_list[0] = v.index
		a_group.add(index_list, a_wn, 'REPLACE')
		b_group.add(index_list, b_wn, 'REPLACE')
		half_group.add(index_list, h_wn, 'ADD')


# def halfbone_apply_weight(obj: 'bpy.types.Object', control_names: 'Iterable[Union[str, int]]', half_name: 'Union[str, int]',
# 		step=0.5, smoothstep=1.0, amplitide=1.0):
# 	mesh = obj.data  # type: Mesh
# 	control_groups = list(obj.vertex_groups.get(n) for n in control_names)
# 	if any(True for g in control_groups if g is None):
# 		raise ValueError('control_names')
#
# 	control_group = obj.vertex_groups.get(control_name)
# 	half_group = obj.vertex_groups.get(half_name)
# 	if half_group is None:
# 		raise ValueError('half_name')
# 	step = max(min(step, 1), 0)
# 	vert_count = 0
# 	for v in mesh.vertices:  # type: MeshVertex
# 		control_w = get_weight_safe(control_group, v.index)
# 		f = 1.0 - abs(control_w * 2.0 - 1.0)  # отображает [0..0.5],[0.5..1] в [0..1],[1..0]
# 		f = (f - step) / (1.0 - step)  # отображает [0..1] в [step..1]
# 		if f < 0:
# 			continue
# 		smooth_f = f * f * (3.0 - 2.0 * f)  # cubic smoothstep ([0..1] в [0..1])
# 		f = smooth_f * smoothstep + f * (1 - smoothstep)  # линкомбинация
# 		half_w = f * amplitide
# 		index_list = [v.index]
# 		for other_group in obj.vertex_groups:
# 			if other_group is half_group:
# 				continue
# 			other_w = get_weight_safe(other_group, v.index)
# 			if other_w <= 0.0:
# 				continue
# 			other_w = other_w * (1.0 - half_w)
# 			other_group.add(index_list, other_w, 'REPLACE')
# 		half_group.add(index_list, half_w, 'REPLACE')
# 		vert_count += 1
# 	return vert_count


def merge_weights(objs: 'HandyMultiObject', mapping: 'Dict[str, Dict[str, float]]',
		strict: 'Optional[bool]' = None) -> 'Tuple[int, int, int]':
	"""
	Merges vertex groups weights on given Mesh-objects, using given mapping of weights.
	Mapping should contain names of groups that should be merged as keys and list of tuple-pairs as values.
	Each pair should contain name of target vertex group and it's weight.
	Sum of pair's weights may not be 1, but if you want to preserve original sum of weights (keep normalized weights)
	you must keep pair's weights sum at 1.
	
	For example, if a vertex on your object have following weights:
	
	`Apple`: `0.1`, `Orange`: `0.2`, `Grape`: `0.3`, `Banana`: `0.4` (their sum is `1.0`)
	
	and then you run this function with `mapping` = `{'Banana': {'Apple': 0.75, 'Orange': 0.25)}`
	
	you will get next weights:
	
	`Apple`: `0.4`, `Orange`: `0.3`, `Grape`: `0.3` (their sum is also `1.0`)
	
	75% of `Banana` weight (which is `0.3`) was added to `Apple` and
	25% of `Banana` weight (which is `0.1`) was added to `Orange` and
	vertex group `Banana` it self was removed.
	
	This function can be used to merge one bones of armatures to others,
	like in CATS, but multiple targets are supported.
	
	Returns tuple of 3 ints: verts_modified, groups_removed, objects_modified
	"""
	
	verts_modified, groups_removed, meshes_modified = 0, 0, 0
	new_weights = dict()  # type: Dict[int, float]  # временный
	remap = list()  # type: List[Union[None, List[float]]]  # также временный
	
	# In Blender 3.0+ vertex weight data fully stored in Mesh, not Object, so we can skip repeating meshes.
	meshes = set() if bpy.app.version[0] >= 3 else None
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_mesh_safe(obj, strict=strict)
		if mesh is None:
			continue
		if meshes is not None:
			if mesh in meshes:
				continue
			meshes.add(mesh)
		if len(obj.vertex_groups) < 1:
			# Если на меши нет групп вообще, то и объединять нечего.
			continue
		# досоздаём необходимые группы на объекте
		object_modified = False
		any_to_merge = False
		for src_bone, targets in mapping.items():
			if src_bone in obj.vertex_groups:
				any_to_merge = True
				for dst_bone, _ in targets.items():
					if dst_bone not in obj.vertex_groups:
						obj.vertex_groups.new(name=dst_bone)
		if not any_to_merge:
			# Если на меши нет объединяемых групп, то делать тут тоже нечего.
			_log.info('There is no groups to merge on {} (any_to_merge).'.format(repr(obj)))
			continue
		# создаём отображение на листе в intах что бы быстро
		for i in range(max(len(obj.vertex_groups), len(remap))):
			if len(remap) <= i:
				remap.append(None)  # Дорасширяем лист
			else:
				remap[i] = None
		# заполняем отображение
		for src_bone, targets in mapping.items():
			src_vg = obj.vertex_groups.get(src_bone)
			if src_vg is None or len(targets) < 1:
				continue
			remap[src_vg.index] = list()
			for dst_bone, weight in targets.items():
				dst_vg = obj.vertex_groups.get(dst_bone)
				remap[src_vg.index].append((dst_vg.index, weight))
		if not any(remap):
			_log.info('There is no groups to merge on {} (any(remap)).'.format(repr(obj)))
			continue  # на этом объекте нет групп, которые нужно смешивать
		_log.info('Remap for {}: {}.'.format(repr(obj), repr(remap)))
		bm = _bmesh.new()
		try:
			bm.from_mesh(obj.data)
			deform_layer = bm.verts.layers.deform.active  # type: BMLayerItem
			if deform_layer is None:
				# Такая ситуация случается если на меши есть группы, но ни одна точка не привязана.
				_log.info('There is no deform layer on {}.'.format(repr(obj)))
				continue
			bm.verts.ensure_lookup_table()
			for v in bm.verts:
				dv = v[deform_layer]  # type: BMDeformVert
				modified = False
				new_weights.clear()
				for src_index, src_weight in dv.items():
					if remap[src_index] is None:
						# вес не сливается: сохраняем как есть
						new_weights[src_index] = src_weight + new_weights.get(src_index, 0.0)
					else:
						# вес сливается: микшируем
						for dst_index, dst_weight in remap[src_index]:
							new_weights[dst_index] = dst_weight * src_weight + new_weights.get(dst_index, 0.0)
						modified = True
				if modified:
					object_modified = True
					dv.clear()
					for new_index, new_weight in new_weights.items():
						dv[new_index] = new_weight  # slice not supported
					# _log.info('New weights for {!r} in {!r}: new_weights={!r}, v[deform_layer]={!r}.'.format(obj, v, new_weights, dv))
					verts_modified += 1
			bm.to_mesh(obj.data)
		finally:
			if bm is not None:
				bm.free()
		for src_name, src_group in obj.vertex_groups.items():
			if src_name in mapping:
				groups_removed += 1
				object_modified = True
				obj.vertex_groups.remove(src_group)
		if object_modified:
			meshes_modified += 1
	if verts_modified == 0 or groups_removed == 0 or meshes_modified == 0:
		# Если любой равен нулю, то и остальые тоже должны быть равны нулю.
		assert verts_modified == 0 and groups_removed == 0 and meshes_modified == 0
	return verts_modified, groups_removed, meshes_modified


def remove_empty(objs: 'HandyMultiObject', limit: 'float' = 0.0, ignore_locked: 'bool' = False,
		strict: 'Optional[bool]' = None, op: 'Operator' = None) -> 'Tuple[int, int]':
	"""
	**Removes empty Vertex Groups from given objects.**
	
	Vertex Group is empty, if every it's weight is less or equals `limit`.
	If `limit` is less than zero, then any weight (even zero) counted as non-empty
	(in this case Vertex Group will be removed only if it's not assigned at all).
	
	If `ignore_locked` is set, then locked Vertex Groups (with `lock_weight` flag)
	will not be removed.
	
	If object mode is not `OBJECT` it is ignored with warning.
	(You must ensure there is no objets in edit-mode.)
	
	Returns: `(removed_groups, removed_objects)`, where
	`removed_groups` - how many Vertex Group were removed (`int`),
	`removed_objects` - how many objects were removed from (`int`).
	
	This feature already exist in *CATS Blender Plugin*,
	but my friend asked me to implement it separately by myself because
	"*It's very scary to use CATS, it will break my whole model again.*"
	
	Available as operator `OperatorRemoveEmpty`.
	"""
	removed_groups, removed_objects = 0, 0
	# In Blender 3.0+ vertex weight data fully stored in Mesh, not Object, so we can skip repeating meshes.
	meshes = set() if _bpy.app.version[0] >= 3 else None
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_mesh_safe(obj, strict=strict)
		if mesh is None:
			continue
		if meshes is not None:
			if mesh in meshes:
				continue
			meshes.add(mesh)
		if obj.vertex_groups is None or len(obj.vertex_groups) < 1:
			continue
		if obj.mode != 'OBJECT':
			_log.warning('{0} is in {1} mode, ignored.'.format(repr(obj), repr(obj.mode)), op=op)
			continue
		removed = 0
		for group in list(obj.vertex_groups.values()):
			if ignore_locked and group.lock_weight:
				continue
			if not _any_weight(mesh, group.index, limit):
				obj.vertex_groups.remove(group)
				removed += 1
		if removed > 0:
			removed_groups += removed
			removed_objects += 1
	return removed_groups, removed_objects


class OperatorRemoveEmpty(_internals.KawaOperator):
	"""
	Operator of `remove_empty`.
	"""
	
	bl_idname = "kawa.vertex_group_remove_empty"
	bl_label = "Remove Empty Vertex Groups"
	bl_description = "\n".join((
		"Vertex Group is empty, if every it's weight is less or equals `limit`.",
		"If `limit` is less than zero, then any weight (even zero) counted as non-empty",
		"(in this case Vertex Group will be removed only if it's not assigned at all).",
		"If `ignore_locked` is set, then locked Vertex Groups (with `lock_weight` flag) will not be removed."
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	limit: _bpy.props.FloatProperty(
		name="Limit",
		description="Do not count vertices which weight is below or equal to this limit. Count everything if less than zero.",
		min=-1e-05,
		default=0.0,
		max=1.0,
		precision=6,
		subtype='FACTOR',
	)
	
	ignore_locked: _bpy.props.BoolProperty(
		name="Ignore Locked",
		description="Do not remove locked (with flag lock_weight) groups.",
		default=False,
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		selected = cls.get_selected_objs(context)
		if not any(True for obj in selected if obj.type == 'MESH'):
			return False  # Должны быть выбраны какие-то Меш-объекты
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		removed_groups, removed_objects = remove_empty(self.get_selected_objs(context),
			limit=self.limit, ignore_locked=self.ignore_locked, op=self)
		_log.info("Removed {0} vertex groups from {1} objects.".format(removed_groups, removed_objects), op=self)
		return {'FINISHED'} if removed_groups > 0 else {'CANCELLED'}


classes = (
	OperatorRemoveEmpty,
)

__pdoc__ = dict()
_doc.process_blender_classes(__pdoc__, classes)
