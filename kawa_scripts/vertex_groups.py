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

import bpy as _bpy

from ._internals import log as _log
from ._internals import KawaOperator as _KawaOperator
from . import _doc

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


def _any_weight(mesh: 'Mesh', group_index: 'int', limit: 'float' = 0.0):
	# В худшем случае производительность NxM, но иначе никак:
	# VertexGroup.weight(index) требует теста
	for i in range(len(mesh.vertices)):
		for vge in mesh.vertices[i].groups.values():
			if vge.group == group_index and vge.weight > limit:
				return True
	return False


def remove_empty(objs: 'Iterable[Object]', limit: 'float' = 0.0, ignore_locked: 'bool' = False, op: 'Operator' = None) -> 'Tuple[int, int]':
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
	for obj in objs:
		if obj.type != 'MESH':
			continue
		if obj.vertex_groups is None or len(obj.vertex_groups) < 1:
			continue
		if obj.mode != 'OBJECT':
			_log.warning('{0} is in {1} mode, ignored.'.format(repr(obj), repr(obj.mode)), op=op)
			continue
		mesh = obj.data  # type: Mesh
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


class OperatorRemoveEmpty(_KawaOperator):
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
