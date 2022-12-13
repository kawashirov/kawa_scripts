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

import bpy
import bpy.app
from bpy.types import Object, Mesh, VertexGroup, Context, Operator

import bmesh
from bmesh.types import BMVert, BMLayerItem, BMDeformVert

from . import _internals
from . import _doc
from ._internals import log
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
	processed_meshes = set() if bpy.app.version[0] >= 3 else None
	for obj in objects.resolve_objects(objs):
		mesh = meshes.get_safe(obj, strict=strict)
		if mesh is None:
			continue
		if processed_meshes is not None:
			if mesh in processed_meshes:
				continue
			processed_meshes.add(mesh)
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
	'remove_empty',
	'OperatorRemoveEmpty'
]

__pdoc__ = dict()
_doc.process_blender_classes(__pdoc__, classes)
