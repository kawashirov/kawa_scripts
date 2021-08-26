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
from collections import deque as _deque

import bpy as _bpy
from bmesh import new as _bmesh_new
from mathutils import Vector as _Vector

from ._internals import log as _log
from ._internals import KawaOperator as _KawaOperator
from . import _doc
from . import commons as _commons
from . import vertex_groups as _vertex_groups

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import List, Iterable, Dict, Tuple, Container, Deque, Set
	from bpy.types import Context, Object, Bone, EditBone, PoseBone, Operator


class _KawaBoneModeOperator(_KawaOperator):
	@classmethod
	def get_selected_bones(cls, context: 'Context') -> 'List[Bone]':
		# Note: only returns exist bones (saved from edit-mode)
		# TODO
		if context.mode == 'EDIT_ARMATURE':
			ebs = context.selected_editable_bones  # type: Iterable[EditBone]
			return list(eb2 for eb2 in (eb1.id_data.bones.get(eb1.name) for eb1 in ebs) if eb2 is not None)
		elif context.mode == 'POSE':
			pbs = context.selected_pose_bones  # type: Iterable[PoseBone]
			return list(pb.bone for pb in pbs)


def _is_valid_armature(arm_obj: 'Object'):
	return arm_obj is not None and arm_obj.type == 'ARMATURE' or arm_obj.data is not None


def _ensure_valid_armature(arm_obj: 'Object'):
	if not _is_valid_armature(arm_obj):
		_log.raise_error(ValueError, '{!r} is not valid armature-object!'.format(arm_obj))


def remove_bones(arm_obj: 'Object', bones_to_remove: 'Container[str]'):
	bones_removed = 0
	_ensure_valid_armature(arm_obj)
	_commons.ensure_deselect_all_objects()
	_commons.activate_object(arm_obj)
	try:
		_commons.object_mode_set_strict('EDIT')
		for edit_bone in list(arm_obj.data.edit_bones):  # type: EditBone
			if edit_bone.name in bones_to_remove:
				arm_obj.data.edit_bones.remove(edit_bone)
				bones_removed += 1
	finally:
		_commons.object_mode_set_strict('OBJECT')
	_commons.ensure_deselect_all_objects()
	return bones_removed


def merge_bones(arm_obj: 'Object', mapping: 'Dict[str, Dict[str, float]]', meshes_objs: 'List[Object]' = None) -> 'Tuple[int, int, int, int]':
	verts_modified, groups_removed, meshes_modified, bones_removed = 0, 0, 0, 0
	_ensure_valid_armature(arm_obj)
	meshes_objs = _commons.find_meshes_affected_by_armatue(arm_obj, where=meshes_objs)
	if len(meshes_objs) < 1:
		return verts_modified, groups_removed, meshes_modified, bones_removed
	verts_modified, groups_removed, meshes_modified = _vertex_groups.merge_weights(meshes_objs, mapping)
	bones_removed = remove_bones(arm_obj, mapping.keys())
	return verts_modified, groups_removed, meshes_modified, bones_removed


class OperatorMergeActiveUniformly(_KawaOperator):
	"""
	Operator of `kawa_scripts.vertex_groups.merge_bones` that merges weights of **active bone into selected bone** uniformly.
	"""
	
	bl_idname = "kawa.bone_merge_active_into_selected"
	bl_label = "Merge ACTIVE bone into SELECTED bones uniformly"
	bl_description = "\n".join((
		"Merges weights of active bone into selected bone uniformly in all affected Mesh-type Objects.",
		"Removes active bone afterwards. Reparents all children into active's parent if available.",
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		active = cls.get_active_obj(context)
		if active is None or active.type != 'ARMATURE':
			return False  # Должна быть активная арматура
		if context.mode == 'EDIT_ARMATURE':
			if context.active_bone is None:
				return False  # Должна быть активная кость
			if not any(True for pb in context.selected_bones if pb != context.active_bone):
				return False  # Должна быть выбрана какая-то кость, кроме активной
		elif context.mode == 'POSE':
			if context.active_pose_bone is None:
				return False  # Должна быть активная кость
			if not any(True for pb in context.selected_pose_bones if pb != context.active_pose_bone):
				return False  # Должна быть выбрана какая-то кость, кроме активной
		else:
			return False  # Требуется режим EDIT_ARMATURE или POSE
		return True
	
	def invoke(self, context: 'Context', event):
		return self.execute(context)
	
	def _execute_edit_mode(self, context: 'Context'):
		arm_obj = self.get_active_obj(context)
		# повторные проверки, т.к. при смене режима что-то могло поменяться.
		if context.active_bone is None:
			return {'CANCELLED'}
		active_bone = context.active_bone  # type: EditBone
		active_name = active_bone.name  # type: str
		other_bones = list(eb for eb in context.selected_bones if eb != active_bone)  # type: List[EditBone]
		if len(other_bones) < 1:
			return {'CANCELLED'}
		meshes_objs = _commons.find_meshes_affected_by_armatue(arm_obj)
		if len(meshes_objs) < 1:
			self.warning("There is no meshes affected by {}, so there is no point to run this complex merge. ".format(
				repr(arm_obj)) + "Operation CANCELLED. Why not just delete active bone?")
			return {'CANCELLED'}
		weights = dict((eb.name, 1.0 / len(other_bones)) for eb in other_bones)
		mapping = {active_name: weights}
		
		verts_modified, groups_removed, meshes_modified = _vertex_groups.merge_weights(meshes_objs, mapping)
		if verts_modified < 1 or meshes_modified < 1 or groups_removed < 1:
			self.warning("No meshes modified. These bones probably did not affect anything.")
		
		# ctx = context.copy()
		# ctx['active_bone'] = active_bone
		# ctx['selected_bones'] = [active_bone]
		# ctx['selected_editable_bones'] = [active_bone]
		# _bpy.ops.armature.delete(ctx)
		# Удаление через переопределение контекста не работает,
		# код armature_delete_selected_exec (в armature_edit.c)
		# удаляет кости по флажку .selected (curBone->flag & BONE_SELECTED)
		# Внимание: вызывает рассинхроны иерархий, но чинится блендером само при смене режимов
		arm_obj.data.edit_bones.remove(active_bone)
		
		other_names = ', '.join(repr(n) for n in weights.keys())
		self.info("Merged weights of bone {0} to bones {1} on {2} vertices in {3} objects.".format(
			repr(active_name), other_names, verts_modified, meshes_modified))
		
		# Это нобходимо, что бы засинхронить кости всех видов арматур и перерисовать View3D.
		_bpy.ops.object.mode_set(mode='OBJECT')
		# Далее в execute восстановится правильный режим редактирования
		
		return {'FINISHED'}
	
	def execute(self, context: 'Context'):
		arm_obj = self.get_active_obj(context)
		original_mode = arm_obj.mode
		try:
			_commons.object_mode_set_strict('EDIT', context=context, op=self)
			return self._execute_edit_mode(context)
		finally:
			_commons.object_mode_set_strict(original_mode, context=context, op=self)


def _find_parent_target(merging_bone: 'EditBone', invalid_bones: 'Container[EditBone]') -> 'EditBone':
	parent = merging_bone.parent
	while parent is not None and parent in invalid_bones:
		parent = parent.parent
	return parent


def _find_children_targets(merging_bone: 'EditBone', invalid_bones: 'Container[EditBone]') -> 'List[Tuple[EditBone, float]]':
	valid_children = list()  # type: List[Tuple[EditBone, float]]
	queue = _deque()  # type: Deque[Tuple[EditBone, float]]
	queue.append((merging_bone, 1.0))
	while len(queue) > 0:
		bone, weight = queue.pop()
		if bone in invalid_bones or bone is merging_bone:
			iter_children = bone.children  # type: List[EditBone]
			if len(iter_children) < 1:
				continue
			weight = weight / len(iter_children)
			queue.extend((child, weight) for child in iter_children)
		else:
			valid_children.append((bone, weight))
	if len(valid_children) > 0:
		# normalize
		w_sum = sum(item[1] for item in valid_children)
		for i in range(len(valid_children)):
			bone, weight = valid_children[i]
			valid_children[i] = (bone, weight / w_sum)
	return valid_children


def _find_hierarchy_targets(
		merging_bone: 'EditBone', invalid_bones: 'Container[EditBone]', to_parents=True, to_children=True
) -> 'Dict[str, float]':
	# find valid parent
	parent = _find_parent_target(merging_bone, invalid_bones) if to_parents else None
	# find valid children
	children = _find_children_targets(merging_bone, invalid_bones) if to_children else list()
	target_weights = dict()
	if parent is None and len(children) < 1:
		return target_weights  # empty
	if parent is not None:
		target_weights[parent.name] = 0.5 if len(children) > 0 else 1.0
	for child, weight in children:
		if parent is not None:
			weight *= 0.5
		target_weights[child.name] = weight
	return target_weights


def _find_hierarchy_mapping(
		merging_bones: 'Iterable[EditBone]', invalid_bones: 'Container[EditBone]', to_parents=True, to_children=True
) -> 'Tuple[Dict[str, Dict[str, float]], List[EditBone]]':
	mapping, cancelled = dict(), list()
	for merging_bone in merging_bones:
		target_weights = _find_hierarchy_targets(merging_bone, invalid_bones, to_parents=to_parents, to_children=to_children)
		if len(target_weights) < 1:
			cancelled.append(merging_bone)
		else:
			mapping[merging_bone.name] = target_weights
	return mapping, cancelled


def merge_to_hierarchy(
		arm_obj: 'Object', bones: 'Set[str]',
		meshes_objs: 'List[Object]' = None, to_parents=True, to_children=True, allow_cancelled=False,
		op: 'Operator' = None
) -> 'Tuple[int, int, int, int, List[str]]':
	_ensure_valid_armature(arm_obj)
	_commons.ensure_deselect_all_objects()
	_commons.activate_object(arm_obj)
	mapping, cancelled = None, None
	try:
		_commons.object_mode_set_strict('EDIT', op=op)
		merge_ebones = list(eb for eb in arm_obj.data.edit_bones if eb.name in bones)
		mapping, cancelled = _find_hierarchy_mapping(merge_ebones, merge_ebones, to_parents=to_parents, to_children=to_children)
		cancelled = list(eb.name for eb in cancelled)
	finally:
		_commons.object_mode_set_strict('OBJECT', op=op)
	if not allow_cancelled and len(cancelled) > 0:
		msg = 'Can not merge bones: {!r}'.format(cancelled)
		_log.raise_error(ValueError, msg, op=op)
		
	result = merge_bones(arm_obj, mapping, meshes_objs=meshes_objs)
	return (*result, cancelled)


class OperatorMergeSelectedToHierarchy(_KawaOperator):
	"""
	Operator of `kawa_scripts.vertex_groups.merge_bones` that merges weights of **selected bones** into
	hierarchy of unselected **parent** and/or **children**.
	If merge is not possible (there is no valid parent or children) bone will not be changed.
	"""
	
	bl_idname = "kawa.bone_merge_selected_to_hierarchy"
	bl_label = "Merge SELECTED bones into hierarchy of PARENTS or CHILDREN"
	bl_description = "\n".join((
		"Merges weights of SELECTED bones into hierarchy of unselected PARENT and/or CHILDREN.",
		"Removes bones afterwards.",
		"If merge is not possible (there is no valid parent or children) bone will not be changed."
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	hierarchy_lookup: _bpy.props.EnumProperty(
		items=[
			('PARENTS', 'Parents', 'Marge bones to parents, not children.', 'SORT_DESC', 1),
			('BOTH', 'Parents and Children', 'Marge bones both to parents and to children.', 'UV_SYNC_SELECT', 3),
			('CHILDREN', 'Children', 'Marge bones to children, not parents.', 'SORT_ASC', 2),
		],
		name="Hierarchy Lookup",
		description="What should merged the selected bones into?",
		default='BOTH',
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode == 'EDIT_ARMATURE':
			if len(context.selected_bones) < 1:
				return False  # Должна быть выбраная кость
		elif context.mode == 'POSE':
			if len(context.selected_pose_bones) < 1:
				return False  # Должна быть выбраная кость
		else:
			return False  # Требуется режим EDIT_ARMATURE или POSE
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def _execute_edit_mode(self, context: 'Context'):
		arm_obj = self.get_active_obj(context)
		selected_bones = context.selected_bones  # type: List[EditBone]
		if len(selected_bones) < 1:
			return {'CANCELLED'}
		meshes_objs = _commons.find_meshes_affected_by_armatue(arm_obj)
		if len(meshes_objs) < 1:
			self.warning("There is no meshes affected by {}, so there is no point to run this complex merge. ".format(
				repr(arm_obj)) + "Operation CANCELLED. Why not just delete selected bones?")
			return {'CANCELLED'}
		l_parents = self.hierarchy_lookup in ('BOTH', 'PARENTS')
		l_children = self.hierarchy_lookup in ('BOTH', 'CHILDREN')
		mapping, cancelled = _find_hierarchy_mapping(selected_bones, selected_bones, to_parents=l_parents, to_children=l_children)
		if len(mapping) < 1:
			self.warning("Can not merge bones. At all. Operation CANCELLED. May be there is no valid parent or children?")
			return {'CANCELLED'}
		if len(cancelled) > 0:
			cancelled_txt = ', '.join(repr(c.name) for c in cancelled)
			self.warning("Can not merge bones: {}. These bones will not be changed.".format(cancelled_txt))
		if self.is_debug() or True:
			mapping_txt = '\n'.join('{} -> {}'.format(repr(src), repr(dst)) for src, dst in mapping.items())
			self.info('Mapping: \n' + mapping_txt)
		targets_count = len(set(b for d in mapping.values() for b in d.keys()))
		
		verts_modified, groups_removed, objects_modified = _vertex_groups.merge_weights(meshes_objs, mapping)
		if verts_modified < 1:
			self.warning("No vertices modified. These bones probably did not affect anything.")
		
		delete_bones = list(b for b in selected_bones if b not in cancelled)
		# ctx = context.copy()
		# ctx['active_bone'] = delete_bones[0]
		# ctx['selected_bones'] = delete_bones
		# ctx['selected_editable_bones'] = delete_bones
		# _bpy.ops.armature.delete(ctx)
		# Удаление через переопределение контекста не работает,
		# код armature_delete_selected_exec (в armature_edit.c)
		# удаляет кости по флажку .selected (curBone->flag & BONE_SELECTED)
		for eb in delete_bones:
			# Внимание: вызывает рассинхроны иерархий, но чинится блендером само при смене режимов
			arm_obj.data.edit_bones.remove(eb)
		
		self.info("Merged weights of {0} bones to {1} bones on {2} vertices and {3} groups in {4} objects.".format(
			len(delete_bones), targets_count, verts_modified, groups_removed, objects_modified))
		
		# Это нобходимо, что бы засинхронить кости всех видов арматур и перерисовать View3D.
		_bpy.ops.object.mode_set(mode='OBJECT')
		# Далее в execute восстановится правильный режим редактирования
		
		return {'FINISHED'}
	
	def execute(self, context: 'Context'):
		arm_obj = self.get_active_obj(context)
		original_mode = arm_obj.mode
		try:
			_commons.object_mode_set_strict('EDIT', context=context, op=self)
			return self._execute_edit_mode(context)
		finally:
			_commons.object_mode_set_strict(original_mode, context=context, op=self)


classes = (
	OperatorMergeActiveUniformly,
	OperatorMergeSelectedToHierarchy,
)
