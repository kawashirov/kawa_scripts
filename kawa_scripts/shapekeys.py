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
Useful tools for Shape Keys

**Most of the functions available as operators from UI:**

In "*Shape Keys*" area in "*Properties*" editor window:

![menu_shapekeys.png](https://i.imgur.com/hqzhUqy.png)

In Object context menu in "*3D Viewport*" window at Object-mode:

![menu_object.png](https://i.imgur.com/I8DAm2u.png)

In Vertex context menu in "*3D Viewport*" window at Mesh-Edit-mode:

![menu_vertex.png](https://i.imgur.com/CZtWPHN.png)

"""

import bpy as _bpy

from ._internals import log as _log
from ._internals import KawaOperator as _KawaOperator
from . import _doc

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


def ensure_len_match(mesh: 'Mesh', shape_key: 'ShapeKey', op: 'Operator' = None):
	"""
	Ensure `len(mesh.vertices) == len(shape_key.data)`. Helps to detect corrupted Mesh/Key datablocks.
	"""
	len_vts = len(mesh.vertices)
	len_skd = len(shape_key.data)
	if len_vts == len_skd:
		return True
	_log.error("Size of {0} ({1}) and size of {2} ({3}) does not match! Is shape key corrupted?"
		.format(repr(mesh.vertices), len_vts, repr(shape_key.data), len_skd), op=op)
	return False


def _mesh_have_shapekeys(mesh: 'Mesh', n: int = 1):
	return mesh is not None and mesh.shape_keys is not None and len(mesh.shape_keys.key_blocks) >= n


def _obj_have_shapekeys(obj: 'Object', n: int = 1):
	return obj is not None and obj.type == 'MESH' and _mesh_have_shapekeys(obj.data, n=n)


def _mesh_selection_to_vertices(mesh: 'Mesh'):
	for p in mesh.polygons:
		if p.select:
			for i in p.vertices:
				mesh.vertices[i].select = True
	for e in mesh.edges:
		if e.select:
			for i in e.vertices:
				mesh.vertices[i].select = True


class OperatorSelectVerticesAffectedByShapeKey(_KawaOperator):
	"""
	**Select Vertices Affected by Active Shape Key.**
	"""
	bl_idname = "kawa.select_vertices_affected_by_shape_key"
	bl_label = "Select Vertices Affected by Active Shape Key"
	bl_description = "Select Vertices Affected by Active Shape Key."
	bl_options = {'REGISTER', 'UNDO'}

	epsilon: _bpy.props.FloatProperty(
		name="Epsilon",
		description="Selection precision in local space",
		min=1e-07,
		default=1e-06,
		max=1,
		precision=6,
		unit='LENGTH'
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'EDIT_MESH' and context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT или EDIT_MESH
		return True
	
	def invoke(self, context: 'Context', event):
		wm = context.window_manager
		# return wm.invoke_props_popup(self, event)
		# return {'RUNNING_MODAL'}
		return wm.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		
		obj = self.get_active_obj(context)
		mesh = obj.data  # type: Mesh
		shape_key = obj.active_shape_key
		reference = mesh.shape_keys.reference_key
		
		match_skd = ensure_len_match(mesh, shape_key, op=self)
		match_ref = ensure_len_match(mesh, reference, op=self)
		if not match_skd or not match_ref:
			return {'CANCELLED'}

		for p in mesh.polygons:
			p.select = False
		for e in mesh.edges:
			e.select = False
		
		counter = 0
		for i in range(len(mesh.vertices)):
			mesh.vertices[i].select = (shape_key.data[i].co - reference.data[i].co).magnitude > self.epsilon
			counter += 1
		_log.info("Selected {0} vertices affected by {1} in {2}".format(counter, repr(shape_key), repr(obj)))
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class OperatorRevertSelectedInActiveToBasis(_KawaOperator):
	"""
	**Revert selected vertices in edit-mode to Reference Shape Key (Basis) in active Shape Key.**
	"""
	bl_idname = "kawa.revert_selected_shape_keys_in_active_to_basis"
	bl_label = "REVERT SELECTED Vertices in ACTIVE Shape Key to BASIS"
	bl_description = "Revert selected vertices in edit-mode to Reference Shape Key (Basis) in active Shape Key."
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = obj.data  # type: Mesh
		shape_key = obj.active_shape_key
		reference = mesh.shape_keys.reference_key
		
		match_skd = ensure_len_match(mesh, shape_key, op=self)
		match_ref = ensure_len_match(mesh, reference, op=self)
		if not match_skd or not match_ref:
			return {'CANCELLED'}
		
		_mesh_selection_to_vertices(mesh)
		
		for i in range(len(mesh.vertices)):
			if mesh.vertices[i].select:
				shape_key.data[i].co = reference.data[i].co.copy()
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class OperatorRevertSelectedInAllToBasis(_KawaOperator):
	"""
	**Revert selected vertices in edit-mode to Reference Shape Key (Basis) in every Shape Key.**
	"""
	bl_idname = "kawa.revert_selected_shape_keys_in_all_to_basis"
	bl_label = "REVERT SELECTED Vertices in ALL Shape Keys to BASIS"
	bl_description = "Revert selected vertices in edit-mode to Reference Shape Key (Basis) in every Shape Key."
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		data = obj.data  # type: Mesh
		if data.shape_keys is None or len(data.shape_keys.key_blocks) < 2:
			return False  # Требуется что бы было 2 или более шейпкея
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = obj.data  # type: Mesh
		reference = mesh.shape_keys.reference_key
		
		if not ensure_len_match(mesh, reference, op=self):
			return {'CANCELLED'}
		
		_mesh_selection_to_vertices(mesh)
		
		for shape_key in mesh.shape_keys.key_blocks:
			if shape_key == reference:
				continue
			if not ensure_len_match(mesh, shape_key, op=self):
				continue
			for i in range(len(mesh.vertices)):
				if mesh.vertices[i].select:
					shape_key.data[i].co = reference.data[i].co.copy()
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class OperatorApplySelectedInActiveToBasis(_KawaOperator):
	"""
	Same as `OperatorApplyActiveToBasis`, but only for selected vertices in edit-mode.
	See also: `apply_active_to_basis`.
	"""
	bl_idname = "kawa.apply_selected_shape_keys_in_active_to_basis"
	bl_label = "APPLY SELECTED Vertices in ACTIVE Shape Key to Basis"
	# bl_description at the end of file.
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = obj.data  # type: Mesh
		active_key = obj.active_shape_key
		ref_key = mesh.shape_keys.reference_key
		
		match_active = ensure_len_match(mesh, active_key, op=self)
		match_ref = ensure_len_match(mesh, ref_key, op=self)
		if not match_active or not match_ref:
			return {'CANCELLED'}
		
		_mesh_selection_to_vertices(mesh)
		
		for i in range(len(mesh.vertices)):
			if mesh.vertices[i].select:
				ref_key.data[i].co = active_key.data[i].co.copy()
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class OperatorApplySelectedInActiveToAll(_KawaOperator):
	"""
	Same as `OperatorApplyActiveToAll`, but only for selected vertices in edit-mode.
	See also: `apply_active_to_all`.
	"""
	bl_idname = "kawa.apply_selected_shape_keys_in_active_to_all"
	bl_label = "APPLY SELECTED Vertices in ACTIVE Shape Key to ALL Others"
	# bl_description at the end of file.
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = obj.data  # type: Mesh
		active_key = obj.active_shape_key
		ref_key = mesh.shape_keys.reference_key
		
		match_active = ensure_len_match(mesh, active_key, op=self)
		match_ref = ensure_len_match(mesh, ref_key, op=self)
		if not match_active or not match_ref:
			return {'CANCELLED'}
		
		_mesh_selection_to_vertices(mesh)
		
		for other_key in mesh.shape_keys.key_blocks:
			if other_key == active_key or other_key == ref_key:
				continue
			if not ensure_len_match(mesh, other_key, op=self):
				continue
			for i in range(len(mesh.vertices)):
				if mesh.vertices[i].select:
					other_offset = other_key.data[i].co - ref_key.data[i].co
					active_offset = active_key.data[i].co - ref_key.data[i].co
					other_key.data[i].co = ref_key.data[i].co + other_offset + active_offset
		
		for i in range(len(mesh.vertices)):
			if mesh.vertices[i].select:
				ref_key.data[i].co = active_key.data[i].co.copy()
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


#
# Object-mode operators


def apply_active_to_basis(obj: 'Object', keep_reverted=True, op: 'Operator' = None):
	"""
	**Applies positions of active Shape Key to Reference ShapeKey (Basis).**
	Positions (shapes) will be transferred from active Shape Key to Reference ShapeKey (Basis).
	Other Shape Keys keep their positions (shapes).
	If `keep_reverted` then old positions from Reference ShapeKey (Basis) will be transferred to active Shape Key,
	so active Shape Key act as reverted. ` (Reverted)` will be added to it's name.
	If not `keep_reverted` then active Shape Key will be deleted.
	
	Returns: True if succeeded, False otherwise.
	
	Available as operator `OperatorApplyActiveToBasis`.
	See also: `apply_active_to_all`, `OperatorApplySelectedInActiveToBasis`.
	"""
	# No context control
	mesh = obj.data  # type: Mesh
	active_key = obj.active_shape_key
	ref_key = mesh.shape_keys.reference_key
	
	match_active = ensure_len_match(mesh, active_key, op=op)
	match_ref = ensure_len_match(mesh, ref_key, op=op)
	if not match_active or not match_ref:
		return False
	
	for i in range(len(mesh.vertices)):
		v = ref_key.data[i].co.copy()
		ref_key.data[i].co = active_key.data[i].co.copy()
		active_key.data[i].co = v
	
	if keep_reverted:
		active_key.name += ' (Reverted)'
	else:
		obj.active_shape_key_index = 0
		obj.shape_key_remove(active_key)
	return True


class OperatorApplyActiveToBasis(_KawaOperator):
	"""
	Operator of `apply_active_to_basis`.
	See also: `OperatorApplySelectedInActiveToBasis`.
	"""
	bl_idname = "kawa.apply_active_shape_keys_to_basis"
	bl_label = "APPLY ACTIVE Shape Key to Basis"
	bl_description = "\n".join((
		"Positions (shapes) will be transferred from active Shape Key to Reference ShapeKey (Basis).",
		"Other Shape Keys keep their positions (shapes).",
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	keep_reverted: _bpy.props.BoolProperty(
		name="Keep Reverted Shape Key",
		default=True,
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		return {'FINISHED'} if apply_active_to_basis(self.get_active_obj(context), keep_reverted=self.keep_reverted, op=self) else {'CANCELLED'}


def apply_active_to_all(obj: 'Object', keep_reverted=False, op: 'Operator' = None):
	"""
	**Applies offsets of active Shape Key to every other shape key.**
	Same as `apply_active_to_basis`, but other Shape Keys will be also edited.
	It's like changing whole base mesh with all it's shape keys.
	If `keep_reverted` then old positions from Reference ShapeKey (Basis) will be moved to active Shape Key,
	so active Shape Key act as reverted. ` (Reverted)` will be added to it's name.
	If not `keep_reverted` then active Shape Key will be deleted.
	
	Returns: True if succeeded, False otherwise.
	
	Available as operator `OperatorApplyActiveToAll`.
	See also: `OperatorApplySelectedInActiveToAll`.
	"""
	# No context control
	mesh = obj.data  # type: Mesh
	active_key = obj.active_shape_key
	ref_key = mesh.shape_keys.reference_key
	
	match_active = ensure_len_match(mesh, active_key, op=op)
	match_ref = ensure_len_match(mesh, ref_key, op=op)
	if not match_active or not match_ref:
		return False
	
	for other_key in mesh.shape_keys.key_blocks:
		if other_key == active_key or other_key == ref_key:
			continue
		if not ensure_len_match(mesh, other_key, op=op):
			continue
		for i in range(len(mesh.vertices)):
			other_offset = other_key.data[i].co - ref_key.data[i].co
			active_offset = active_key.data[i].co - ref_key.data[i].co
			other_key.data[i].co = ref_key.data[i].co + other_offset + active_offset
	
	for i in range(len(mesh.vertices)):
		v = ref_key.data[i].co.copy()
		ref_key.data[i].co = active_key.data[i].co.copy()
		active_key.data[i].co = v
	
	if keep_reverted:
		active_key.name += ' (Reverted)'
	else:
		obj.active_shape_key_index = 0
		obj.shape_key_remove(active_key)
	return True


class OperatorApplyActiveToAll(_KawaOperator):
	"""
	Operator of `apply_active_to_all`.
	See also: `OperatorApplySelectedInActiveToAll`.
	"""
	bl_idname = "kawa.apply_active_shape_keys_to_all"
	bl_label = "APPLY ACTIVE Shape Key to ALL Others"
	bl_description = "Same as {}, but other Shape Keys will be also edited.".format(
		repr(OperatorApplyActiveToBasis.bl_label))
	bl_options = {'REGISTER', 'UNDO'}
	
	keep_reverted: _bpy.props.BoolProperty(
		name="Keep Reverted Shape Key",
		default=False,
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		return {'FINISHED'} if apply_active_to_all(self.get_active_obj(context), keep_reverted=self.keep_reverted, op=self) else {'CANCELLED'}


def cleanup_active(obj: 'Object', epsilon: 'float', op: 'Operator' = None) -> 'int':
	"""
	**Removes micro-offsets in active Shape Key.**
	If position of a vertex differs from position in Reference Shape Key (Basis) for `epsilon` or less,
	then it's position will be reverted (to be the same as in Reference Shape Key)
	
	Returns: number of changed vertices.
	
	Available as operator `OperatorCleanupActive`
	"""
	if not _obj_have_shapekeys(obj, n=2):
		return 0
	mesh = obj.data  # type: Mesh
	active_key = obj.active_shape_key
	ref_key = mesh.shape_keys.reference_key
	if active_key == ref_key:
		return 0
	
	match_active = ensure_len_match(mesh, active_key, op=op)
	match_ref = ensure_len_match(mesh, ref_key, op=op)
	if not match_active or not match_ref:
		return 0
	
	changed = 0
	for i in range(len(mesh.vertices)):
		if (ref_key.data[i].co - active_key.data[i].co).magnitude <= epsilon:
			active_key.data[i].co = ref_key.data[i].co.copy()
			changed += 1
	
	return changed


class OperatorCleanupActive(_KawaOperator):
	"""
	Operator of `cleanup_active`
	"""
	bl_idname = "kawa.cleanup_active_shape_key"
	bl_label = "Remove Mirco-offsets in ACTIVE Shape Key"
	bl_description = "\n".join((
		"If position of a vertex differs from position in Reference Shape Key (Basis) for `epsilon` or less,",
		"then it's position will be reverted (to be the same as in Reference Shape Key)",
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	epsilon: _bpy.props.FloatProperty(
		name="Epsilon",
		description="Threshold in local space",
		min=1e-07,
		default=1e-04,
		max=1,
		precision=6,
		unit='LENGTH'
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not obj or obj.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		changed = cleanup_active(self.get_active_obj(context), self.epsilon, op=self)
		_log.info("Cleaned {0} vertices.".format(changed), op=self)
		return {'FINISHED'} if changed > 0 else {'CANCELLED'}


def cleanup_all(objs: 'Iterable[Object]', epsilon: float, op: 'Operator' = None) -> 'Tuple[int, int, int]':
	"""
	**Removes micro-offsets in all Shape Keys.**
	Same as `cleanup_active`, but for every shape key (except reference one) for every object.
	
	Returns: (number of changed vertices, number of changed shape keys, number of changed meshes).
	
	Available as operator `OperatorCleanupAll`
	"""
	objs = list(obj for obj in objs if _obj_have_shapekeys(obj, n=2))  # type: List[Object]
	meshes = set()
	vertices_changed, shapekeys_changed, meshes_changed = 0, 0, 0
	for obj in objs:
		mesh = obj.data  # type: Mesh
		if mesh in meshes:
			continue  # Уже трогали
		meshes.add(mesh)
		last_shape_key_index = obj.active_shape_key_index
		try:
			mesh_changed = False
			for shape_key_index in range(1, len(mesh.shape_keys.key_blocks)):
				obj.active_shape_key_index = shape_key_index
				vc = cleanup_active(obj, epsilon, op=op)
				if vc > 0:
					vertices_changed += vc
					shapekeys_changed += 1
					mesh_changed = True
			if mesh_changed:
				meshes_changed += 1
		finally:
			obj.active_shape_key_index = last_shape_key_index
	return vertices_changed, shapekeys_changed, meshes_changed


class OperatorCleanupAll(_KawaOperator):
	"""
	Operator of `cleanup_all`
	"""
	bl_idname = "kawa.cleanup_all_shape_keys"
	bl_label = "Remove Mirco-offsets in ALL Shape Keys"
	bl_description = "Same as {}, but for every shape key (except reference one) for every object".format(
		repr(OperatorCleanupActive.bl_label))
	bl_options = {'REGISTER', 'UNDO'}
	
	epsilon: _bpy.props.FloatProperty(
		name="Epsilon",
		description="Threshold in local space",
		min=1e-07,
		default=1e-04,
		max=1,
		precision=6,
		unit='LENGTH'
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		if not any(True for obj in cls.get_selected_objs(context) if _obj_have_shapekeys(obj, n=2)):
			return False  # Должны быть выбраны Меш-объекты c 2 или более шейпами
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		selected = list(self.get_selected_objs(context))
		if len(selected) < 1:
			_log.warning("No mesh-objects with multiple shape keys selected.", op=self)
			return {'CANCELLED'}
		vertices_cleaned, shapekeys_cleaned, objects_cleaned = cleanup_all(selected, self.epsilon, op=self)
		_log.info("Cleaned {0} Vertices in {1} Shape Keys in {2} Meshes from micro-offsets (<{3}).".format(
			vertices_cleaned, shapekeys_cleaned, objects_cleaned, float(self.epsilon)), op=self)
		return {'FINISHED'} if vertices_cleaned > 0 else {'CANCELLED'}


def remove_empty(objs: 'Iterable[Object]', epsilon: float, op: 'Operator' = None) -> 'Tuple[int, int]':
	"""
	**Removes empty Shape Keys from Mesh-objects.**
	Shape Key is empty, if positions of **every** vertex differ from Reference Shape Key (Basis) for `epsilon` or less.
	
	Returns: (number of removed Shape Keys, number of meshes changed)
	
	Available as operator `OperatorRemoveEmpty`
	"""
	objs = list(obj for obj in objs if _obj_have_shapekeys(obj, n=2))  # type: List[Object]
	removed_shapekeys, changed_meshes = 0, 0
	meshes = set()
	for obj in objs:
		mesh = obj.data  # type: Mesh
		if mesh in meshes:
			continue  # Уже трогали
		meshes.add(mesh)
		key = mesh.shape_keys  # type: Key
		reference = key.reference_key
		empty_keys = set()  # type: Set[str]
		for shape_key in key.key_blocks:
			if shape_key == reference:
				continue  # Базис не удаялется
			match1 = ensure_len_match(mesh, reference, op=op)
			match2 = ensure_len_match(mesh, shape_key, op=op)
			if not match1 or not match2:
				continue
			# Имеются ли различия между шейпами?
			if not any((shape_key.data[i].co - reference.data[i].co).magnitude > epsilon for i in range(len(mesh.vertices))):
				empty_keys.add(shape_key.name)
		# _log.info("Found {0} empty shape keys in mesh {1}: {2}, removing...".format(len(empty_keys), repr(mesh), repr(empty_keys)), op=op)
		if len(empty_keys) < 1:
			continue
		for empty_key in empty_keys:
			# На всякий случай удаляю по прямому пути, вдруг там что-то перестраивается в процессе удаления.
			# Не спроста же Key-блоки можно редактировать только через Object-блоки
			obj.shape_key_remove(obj.data.shape_keys.key_blocks[empty_key])
		removed_shapekeys += len(empty_keys)
		changed_meshes += 1
	return removed_shapekeys, changed_meshes


class OperatorRemoveEmpty(_KawaOperator):
	"""
	Operator of `remove_empty`.
	"""
	bl_idname = "kawa.remove_empty_shape_keys"
	bl_label = "Remove Empty Shape Keys"
	bl_description = "\n".join((
		"Shape Key is empty, if positions of EVERY vertex differ ",
		"from Reference Shape Key (Basis) for Epsilon or less.",
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	epsilon: _bpy.props.FloatProperty(
		name="Epsilon",
		description="Selection precision in local space",
		min=1e-07,
		default=1e-06,
		max=1,
		precision=6,
		unit='LENGTH'
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		if not any(True for obj in cls.get_selected_objs(context) if _obj_have_shapekeys(obj, n=2)):
			return False  # Должны быть выбраны какие-то Меш-объекты
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		objs = self.get_selected_objs(context)
		removed_shapekeys, changed_meshes = remove_empty(objs, self.epsilon, op=self)
		_log.info("Total {0} shape keys removed from {1} Meshes.".format(removed_shapekeys, changed_meshes), op=self)
		return {'FINISHED'} if removed_shapekeys > 0 else {'CANCELLED'}


OperatorApplySelectedInActiveToBasis.bl_description = \
	"Same as {}, but only for selected vertices in edit-mode.".format(repr(OperatorApplyActiveToBasis.bl_label))
OperatorApplySelectedInActiveToAll.bl_description = \
	"Same as {}, but only for selected vertices in edit-mode.".format(repr(OperatorApplyActiveToAll.bl_label))

classes = (
	# Edit-mode
	OperatorSelectVerticesAffectedByShapeKey,
		#
	OperatorRevertSelectedInActiveToBasis,
	OperatorRevertSelectedInAllToBasis,
		#
	OperatorApplySelectedInActiveToBasis,
	OperatorApplySelectedInActiveToAll,
		#
		# Object-mode
	OperatorApplyActiveToBasis,
	OperatorApplyActiveToAll,
		#
	OperatorCleanupActive,
	OperatorCleanupAll,
	OperatorRemoveEmpty,
)

__pdoc__ = dict()
_doc.process_blender_classes(__pdoc__, classes)
