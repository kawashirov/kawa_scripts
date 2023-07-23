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
import gc

import bpy
import bpy.app
from bpy.types import Object, Context, Operator
from bpy.types import Mesh, VertexGroup, MeshVertex

import bmesh
from bmesh.types import BMVert, BMLayerItem, BMDeformVert

from . import _internals
from . import _doc
from ._internals import log
from . import commons
from . import armature
from . import attributes
from . import objects
from . import meshes

import typing

if typing.TYPE_CHECKING:
	from .objects import HandyMultiObject


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
	objs = list(objects.resolve_objects(objs))
	armature_obj = list(obj for obj in objs if armature.is_armature_object(obj))
	if len(armature_obj) != 1:
		raise RuntimeError(f"There is no single Armature-Object provided ({len(armature_obj)})")
	armature_obj = armature_obj[0]  # type: Object|list[Object]
	
	armature_data = armature.get_safe(armature_obj, strict=True)
	
	if armature_data.bones.active is None:
		raise RuntimeError(f"There is no active bone in Armature-Object provided ({armature_obj})")
	half_name = armature_data.bones.active.name
	
	selected = list(bone.name for bone in armature_data.bones if armature_data.bones.active != bone and bone.select)
	if len(selected) != 2:
		raise RuntimeError(f"There is no two selected control bones in Armature-Object provided ({len(selected)})")
	ctrl_a, ctrl_b = selected
	
	mesh_objs = list(obj for obj in objs if meshes.is_mesh_object(obj))
	if len(mesh_objs) < 1:
		raise RuntimeError(f"There is no Mesh-Objects provided ({len(mesh_objs)})")
	
	halfbone_apply_weight(mesh_objs, ctrl_a, ctrl_b, half_name)


def halfbone_apply_weight(objs: 'objects.HandyMultiObject', ctrl_a: 'str|int', ctrl_b: 'str|int', half_name: 'str|int'):
	for obj in objects.resolve_objects(objs):
		halfbone_apply_weight_single(obj, ctrl_a, ctrl_b, half_name)


def halfbone_apply_weight_single(obj: 'Object', ctrl_a: 'str|int', ctrl_b: 'str|int', half_name: 'str|int'):
	log.info(f"{obj=!r}, {ctrl_a=!r}, {ctrl_b=!r}, {half_name=!r}")
	mesh = meshes.get_safe(obj)
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
		if log.is_debug():
			log.info(f"#{v.index}: {a_w}, {b_w} -> {a_wn}, {b_wn} and {h_wn}")
		index_list[0] = v.index
		a_group.add(index_list, a_wn, 'REPLACE')
		b_group.add(index_list, b_wn, 'REPLACE')
		half_group.add(index_list, h_wn, 'ADD')


class WeightsMerger:
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
	
	def __init__(self, objs: 'HandyMultiObject', mapping: 'dict[str, dict[str, float]]', strict: 'bool|None' = None):
		self.objs = objs
		self.mapping = mapping
		self.strict = strict
		
		self.verts_modified = 0
		self.groups_removed = 0
		self.objects_iterated = 0
		self.objects_modified = 0
		
		# Используются как локальные переменные между методами
		self._cur_obj = None  # type: Object|None
		self._cur_mesh = None  # type: Mesh|None
		self._int_mapping = None  # type: list[list[tuple[int,float]]|None]|None
		self._deform_layer = None  # type: BMLayerItem|None
		# общий временный для избегания новых аллокаций, номер группы -> новый вес
		self._new_weights = dict()  # type: dict[int, float]
	
	def _need_mapping(self, obj: 'Object'):
		if obj.vertex_groups is None or len(obj.vertex_groups) < 1:
			return False
		return any(src_name in obj.vertex_groups for src_name in self.mapping.keys())
	
	def _ensure_groups_exist(self):
		# досоздаём необходимые группы на объекте
		for src_name, targets in self.mapping.items():
			if src_name in self._cur_obj.vertex_groups:
				for dst_name, _ in targets.items():
					if dst_name not in self._cur_obj.vertex_groups:
						dst_group = self._cur_obj.vertex_groups.new(name=dst_name)
						assert dst_group.name == dst_name, f"{dst_group.name=!r}, {dst_name=!r}"
						msg = f'Created new VertexGroup {dst_group.name!r} on Object {self._cur_obj.name!r}, Mesh {self._cur_mesh.name!r}.'
						log.info(msg)
	
	def _make_int_mapping(self):
		# создаём отображение на листе в intах что бы быстро
		self._int_mapping = list(None for _ in range(len(self._cur_obj.vertex_groups)))  # type: list[list[tuple[int,float]]|None]
		# заполняем отображение
		for src_name, targets in self.mapping.items():
			src_group = self._cur_obj.vertex_groups.get(src_name)
			if src_group is None or len(targets) < 1:
				continue
			weights = self._int_mapping[src_group.index] = list()  # type: list[tuple[int,float]]
			for dst_name, weight in targets.items():
				dst_vg = self._cur_obj.vertex_groups.get(dst_name)
				assert dst_vg, f"{self._cur_obj!r}, {self._cur_mesh!r}: missing group {dst_name!r}: {dst_vg!r}"
				weights.append((dst_vg.index, weight))
		assert len(self._int_mapping) > 0, f"{self._cur_obj!r}, {self._cur_mesh!r}: int-mapping is empty!"
	
	def _apply_mapping_vert(self, bm_vert: 'BMVert'):
		bm_deform_vert = bm_vert[self._deform_layer]  # type: BMDeformVert
		modified_weights = False
		self._new_weights.clear()
		for src_index, src_weight in bm_deform_vert.items():
			if self._int_mapping[src_index] is None:
				# вес не сливается: сохраняем как есть
				self._new_weights[src_index] = src_weight + self._new_weights.get(src_index, 0.0)
			else:
				# вес сливается: микшируем
				for dst_index, dst_weight in self._int_mapping[src_index]:
					self._new_weights[dst_index] = dst_weight * src_weight + self._new_weights.get(dst_index, 0.0)
				modified_weights = True
		if modified_weights:
			bm_deform_vert.clear()
			for new_index, new_weight in self._new_weights.items():
				bm_deform_vert[new_index] = new_weight  # slice not supported
		# dbg_msg = f'New weights for Object {self._cur_obj.name!r}, Mesh {self._cur_mesh.name!r} on {bm_vert!r}: '
		# f'{self._new_weights=!r}, {bm_deform_vert=!r}.'
		# _log.info(dbg_msg)
		return modified_weights
	
	def _apply_mapping(self) -> 'bool':
		bm = bmesh.new()
		try:
			bm.from_mesh(self._cur_mesh)
			self._deform_layer = bm.verts.layers.deform.active  # type: BMLayerItem
			if self._deform_layer is None:
				# Такая ситуация случается если на меши есть группы, но ни одна точка не привязана.
				log.info(f'There is no deform_layer on Object {self._cur_obj.name!r}, Mesh {self._cur_mesh.name!r}.')
				return False
			bm.verts.ensure_lookup_table()
			verts_modified = 0
			for bm_vert in bm.verts:
				if self._apply_mapping_vert(bm_vert):
					verts_modified += 1
			log.info(f'Modified {verts_modified} vertices weights on Object {self._cur_obj.name!r}, Mesh {self._cur_mesh.name!r}.')
			if verts_modified > 0:
				bm.to_mesh(self._cur_mesh)
				self.verts_modified += verts_modified
		finally:
			if bm is not None:
				bm.free()
		return verts_modified > 0
	
	def _remove_remapped_groups(self):
		groups_removed = 0
		for src_name, src_group in self._cur_obj.vertex_groups.items():
			if src_name in self.mapping.keys():
				groups_removed += 1
				self._cur_obj.vertex_groups.remove(src_group)
		# Если мы начали обрабатывать этот объект,
		# значит была хотя бы одна группа, которая сейчас должна быть удалена.
		assert groups_removed > 0, f"{self._cur_obj!r}, {self._cur_mesh!r}: {groups_removed=!r}"
		self.groups_removed += groups_removed
	
	def merge_weights(self):
		# TODO args checks
		processed_meshes = set() if bpy.app.version[0] >= 3 else None
		for _obj in objects.resolve_objects(self.objs):
			self.objects_iterated += 1
			self._cur_obj = _obj
			self._cur_mesh = meshes.get_safe(self._cur_obj, strict=self.strict)
			if self._cur_mesh is None:
				continue
			if processed_meshes is not None:
				if self._cur_mesh in processed_meshes:
					continue
				processed_meshes.add(self._cur_mesh)
			if not objects.ensure_in_mode(self._cur_obj, 'OBJECT', strict=self.strict):
				continue
			
			if not self._need_mapping(self._cur_obj):
				log.info(f'There is no groups to merge on Object {self._cur_obj.name!r} (Mesh {self._cur_mesh.name!r}).')
				return False
			
			self._ensure_groups_exist()
			self._make_int_mapping()
			
			if not self._apply_mapping():
				log.info(f'Actual weights values was not changed on Object {self._cur_obj.name!r} (Mesh {self._cur_mesh.name!r}).')
			
			self._remove_remapped_groups()
			self.objects_modified += 1
		log.info(f"Merged weights on {self.objects_modified}/{self.objects_iterated} objects: {self.verts_modified} vertices changed.")


def weights_control_points(objs: 'HandyMultiObject', smooth_points: 'str', ref_points: 'str', iterations=100,
		strict: 'bool|None' = None, op: 'Operator' = None):
	for obj in objects.resolve_objects(objs):
		mesh = meshes.get_safe(obj, strict=strict)
		if mesh is None:
			continue
		if not objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		smooth_attr = mesh.attributes.get(smooth_points)
		if not smooth_attr:
			log.warning(f"No {smooth_attr=!r}")
			continue
		ref_attr = mesh.attributes.get(ref_points)
		if not ref_attr:
			log.warning(f"No {ref_attr=!r}")
			continue
		
		attributes.load_selection_from_attribute_mesh(
			mesh, attribute=ref_points, mode='SET', only_visible=False, strict=True)
		ref_memory = dict()  # type: dict[int, dict[int, float]]
		for vert in mesh.vertices:  # type: bpy.types.MeshVertex
			if vert.select:
				ref_memory[vert.index] = {vge.group: vge.weight for vge in vert.groups}
		
		for i in range(iterations):
			max_dev, avg_dev, counter = 0, 0, 0
			attributes.load_selection_from_attribute_mesh(
				mesh, attribute=smooth_points, mode='SET', only_visible=False, strict=True)
			bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
			bpy.ops.object.vertex_group_smooth(group_select_mode='ALL', factor=0.5, repeat=1, expand=0.1)
			if (i > 0 and i % 10 == 0) or i == iterations - 1:
				bpy.ops.object.vertex_group_clean(group_select_mode='ALL', limit=0.001, keep_single=True)
				bpy.ops.object.vertex_group_normalize_all(group_select_mode='ALL', lock_active=False)
			bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
			attributes.load_selection_from_attribute_mesh(
				mesh, attribute=ref_points, mode='SET', only_visible=False, strict=True)
			for vert in mesh.vertices:  # type: bpy.types.MeshVertex
				if vert.select:
					mem = ref_memory[vert.index]
					for vge in vert.groups:
						new_weight = mem.get(vge.group, 0)
						dev = abs(new_weight - vge.weight)
						max_dev = max(max_dev, dev)
						avg_dev += dev
						counter += 1
						vge.weight = new_weight
			avg_dev /= counter
			log.info(f"Iter {i=!r}: {avg_dev=!r} {max_dev=!r}")


def _annihilate_deform(bm_deform: 'BMDeformVert|dict[int, float]', group_a: 'int', group_b: 'int', group_dst: 'int') -> 'bool':
	weight_a = bm_deform.get(group_a, 0)
	weight_b = bm_deform.get(group_b, 0)
	if weight_a <= 0 or weight_b <= 0:
		return False  # need both weights to exist
	weight_dst = bm_deform.get(group_dst, 0)
	if weight_a == weight_b:
		bm_deform[group_dst] = weight_dst + weight_a + weight_b
		bm_deform[group_a] = 0
		del bm_deform[group_a]
		bm_deform[group_b] = 0
		del bm_deform[group_b]
	elif weight_a > weight_b:
		bm_deform[group_dst] = weight_dst + weight_b * 2
		bm_deform[group_a] = weight_a - weight_b
		bm_deform[group_b] = 0
		del bm_deform[group_b]
	else:
		bm_deform[group_dst] = weight_dst + weight_a * 2
		bm_deform[group_a] = 0
		del bm_deform[group_a]
		bm_deform[group_b] = weight_b - weight_a
	return True


def _annihilate_single(obj: 'Object', group_a_name: 'str', group_b_name: 'str', group_dst_name: 'str',
		op: 'Operator' = None) -> 'bool':
	# internal method, always strict.
	mesh = meshes.get_safe(obj, strict=True)
	mesh_modified = False
	
	if obj.vertex_groups is None or len(obj.vertex_groups) < 2:
		return False  # at least 2 any vertex groups should exist.
	
	group_a = obj.vertex_groups.get(group_a_name)
	group_b = obj.vertex_groups.get(group_b_name)
	if group_a is None or group_b is None:
		return False  # both source groups should exist
	
	group_dst = obj.vertex_groups.get(group_dst_name)
	if group_dst is None:
		# create a destination group if necessary
		group_dst = obj.vertex_groups.new(group_dst_name)
		mesh_modified = True
	
	bm = bmesh.new()
	try:
		bm.from_mesh(mesh)
		bm.verts.ensure_lookup_table()
		bm_deform_layer = bm.verts.layers.deform.active  # type: BMLayerItem
		if not bm_deform_layer:
			log.raise_error(RuntimeError, f"No deform layer on {obj!r}, {mesh!r}, but it must be!")
		verts_modified = 0
		for bm_vert in bm.verts:
			if _annihilate_deform(bm_vert[bm_deform_layer], group_a.index, group_b.index, group_dst.index):
				verts_modified += 1
		if verts_modified > 0:
			bm.to_mesh(mesh)
			mesh_modified = True
			what_obj = f"Object {obj.name!r}, Mesh {mesh.name!r}"
			what_groups = f"Annihilated {group_a_name!r} and {group_b_name!r} into {group_dst_name!r}."
			log.info(f"Modified {verts_modified} vertices weights on {what_obj}. ({what_groups})", op=op)
	finally:
		bm.free()
	return mesh_modified


def annihilate(objs: 'HandyMultiObject', rules: 'dict[tuple[str,str], str]', strict: 'bool|None' = None, op: 'Operator' = None):
	"""
	Allows you to modify the weights of the vertices in a given list of objects
	by negating the same weights of conjugated vertex groups and adding the negated amount to a destination group.
	This can be used to ensure that no vertices are affected by both the weights of a pair of vertex groups,
	such as the left and right sides of a character.
	To specify the negation rules, you must provide a dictionary with a tuple of source vertex group names as the key
	and a destination vertex group name as the value.
	For example, to negate the weights of the left and right legs and add the negated amount to the hips vertex group,
	you would use the rule {('Left leg', 'Right leg'): 'Hips'}.
	If the destination vertex group does not exist, it will be created.
	The behavior is undefined if a vertex group is conjugated with more than one other vertex group.
	
	Here, a few more examples, how vertices weights for rule {('a', 'b'): 'd'} will change the mesh:
	
	{'a': 0.3, 'b': 0.3, 'c': 0.2, 'd': 0.2} -> {'c': 0.2, 'd': 0.8}
	(Both sources have equal weight, so negated each other completely.)
	
	{'a': 0.2, 'b': 0.4, 'c': 0.2, 'd': 0.2} -> {'b': 0.2, 'c': 0.2, 'd': 0.6}
	('b' have more weight than 'a', so only 0.2 of each is negated.)
	
	{'a': 0.6, 'b': 0.0, 'c': 0.2, 'd': 0.2} -> {'a': 0.6, 'b': 0.0, 'c': 0.2, 'd': 0.2}
	(No change, as 'b' have no actual weight to negate.)
	
	This can be used to merge unnecessary paired bones weights,
	for example, {('Left leg', 'Right leg'): 'Hips'},
	to make sure no vertices are affected by both left and right sides.
	"""
	for obj in objects.resolve_objects(objs):
		mesh = meshes.get_safe(obj, strict=strict)
		if mesh is not None:
			for (group_a, group_b), group_dst in rules.items():
				try:
					_annihilate_single(obj, group_a, group_b, group_dst, op=op)
				except Exception as exc:
					what = f"{obj!r} ({mesh!r}), {group_a!r}, {group_b!r}, {group_dst!r}"
					log.error(f"Failed to _annihilate_single on {what}: {exc}", exc_info=exc, op=op)
					raise exc


def fix_ghost_weights(objs: 'HandyMultiObject', strict: 'bool|None' = None, op: 'Operator' = None):
	for obj in objects.resolve_objects(objs):
		mesh = meshes.get_safe(obj, strict=strict)
		if mesh is None:
			continue
		if not objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		max_id = len(obj.vertex_groups) if obj.vertex_groups else 0
		bm = bmesh.new()
		modified = 0
		try:
			bm.from_mesh(mesh)
			bm.verts.ensure_lookup_table()
			deform_layer = bm.verts.layers.deform.active  # type: BMLayerItem
			if not deform_layer:
				if log.is_debug():
					log.info(f"No deform layer on {obj!r}, {mesh!r}.", op=op)
				continue
			new_weights = dict()
			for bm_vert in bm.verts:
				new_weights.clear()
				reassign = False
				bm_deform_vert = bm_vert[deform_layer]  # type: BMDeformVert
				for index, weight in bm_deform_vert.items():
					if index >= max_id:
						# Индекс группы больше, чем групп на объекте.
						if log.is_debug():
							msg = f"Detected ghost group #{index} with weight {weight}"
							log.warning(f"{msg} on vert #{bm_vert.index} on {obj!r}, {mesh!r}.", op=op)
						reassign = True
						continue
					elif (already_weight := new_weights.get(index)) is not None:
						# Индекс повторется.
						if log.is_debug():
							msg = f"Detected duplicate group #{index} with weight {weight} (against {already_weight})"
							log.warning(f"{msg} on vert #{bm_vert.index} on {obj!r}, {mesh!r}.", op=op)
						reassign = True
						continue
					else:
						new_weights[index] = weight
				if reassign:
					modified += 1
					bm_deform_vert.clear()
					for index, weight in new_weights.items():
						bm_deform_vert[index] = weight
			if modified > 0:
				log.warning(f"Reassigned weights on {modified}/{len(bm.verts)} vertices on Object {obj.name!r}, Mesh {mesh.name!r}.", op=op)
				bm.to_mesh(mesh)
		except Exception as exc:
			log.error(f"Failed to fix_ghost_weights on {obj!r}, {mesh!r}: {exc}", exc_info=exc, op=op)
		finally:
			bm.free()


def remove_empty(objs: 'HandyMultiObject', limit: 'float' = 0.0, ignore_locked: 'bool' = False,
		strict: 'bool|None' = None, op: 'Operator' = None) -> 'tuple[int, int]':
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
	for obj in objects.resolve_objects(objs):
		mesh = meshes.get_safe(obj, strict=strict)
		if mesh is None:
			continue
		if not objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		if obj.vertex_groups is None or len(obj.vertex_groups) < 1:
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
	
	limit: bpy.props.FloatProperty(
		name="Limit",
		description="Do not count vertices which weight is below or equal to this limit. Count everything if less than zero.",
		min=-1e-05,
		default=0.0,
		max=1.0,
		precision=6,
		subtype='FACTOR',
	)
	
	ignore_locked: bpy.props.BoolProperty(
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
		log.info("Removed {0} vertex groups from {1} objects.".format(removed_groups, removed_objects), op=self)
		return {'FINISHED'} if removed_groups > 0 else {'CANCELLED'}


classes = (
	OperatorRemoveEmpty,
)

__all__ = [
	'get_weight_safe',
	'WeightsMerger',
	'weights_control_points',
	'annihilate',
	'fix_ghost_weights',
	'remove_empty',
	'OperatorRemoveEmpty'
]

__pdoc__ = dict()
_doc.process_blender_classes(__pdoc__, classes)
