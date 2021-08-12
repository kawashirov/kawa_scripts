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
from bpy import context as _C

from ._internals import log as _log
from ._internals import KawaOperator as _KawaOperator

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
	return obj is not None and obj.type != 'MESH' and _mesh_have_shapekeys(obj.data, n=n)


def _mesh_selection_to_vertices(mesh: 'Mesh'):
	for p in mesh.polygons:
		if p.select:
			for i in p.vertices:
				mesh.vertices[i].select = True
	for e in mesh.edges:
		if e.select:
			for i in e.vertices:
				mesh.vertices[i].select = True


class KawaSelectVerticesAffectedByShapeKey(_KawaOperator):
	"""
	**Select Vertices Affected by Active Shape Key.**
	"""
	bl_idname = "kawa.select_vertices_affected_by_shape_key"
	bl_label = "Select Vertices Affected by Active Shape Key"
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


class KawaRevertSelectedInActiveToBasis(_KawaOperator):
	"""
	**Revert selected vertices in edit-mode to Reference Shape Key (Basis) in active Shape Key.**
	"""
	bl_idname = "kawa.revert_selected_shape_keys_in_active_to_basis"
	bl_label = "REVERT SELECTED Vertices in ACTIVE Shape Key to BASIS"
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
				shape_key.data[i].co = reference.data[i].co
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class KawaRevertSelectedInAllToBasis(_KawaOperator):
	"""
	**Revert selected vertices in edit-mode to Reference Shape Key (Basis) in every Shape Key.**
	"""
	bl_idname = "kawa.revert_selected_shape_keys_in_all_to_basis"
	bl_label = "REVERT SELECTED Vertices in ALL Shape Keys to BASIS"
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
					shape_key.data[i].co = reference.data[i].co
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class KawaApplySelectedInActiveToBasis(_KawaOperator):
	"""
	Same as `KawaApplyActiveToBasis`, but only for selected vertices in edit-mode.
	See also: `apply_active_to_basis`.
	"""
	bl_idname = "kawa.apply_selected_shape_keys_in_active_to_basis"
	bl_label = "APPLY SELECTED Vertices in ACTIVE Shape Key to Basis"
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
				ref_key.data[i].co = active_key.data[i].co
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class KawaApplySelectedInActiveToAll(_KawaOperator):
	"""
	Same as `KawaApplyActiveToAll`, but only for selected vertices in edit-mode.
	See also: `apply_active_to_all`.
	"""
	bl_idname = "kawa.apply_selected_shape_keys_in_active_to_all"
	bl_label = "APPLY SELECTED Vertices in ACTIVE Shape Key to ALL Others"
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
				ref_key.data[i].co = active_key.data[i].co
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


#
# Object-mode operators


def apply_active_to_basis(obj: 'Object', keep_reverted=True, op: 'Operator' = None):
	"""
	**Applies positions of active Shape Key to Reference ShapeKey (Basis).**
	Positions (shapes) will be moved from active Shape Key to Reference ShapeKey (Basis).
	Other Shape Keys keep their positions (shapes).
	If `keep_reverted` then old positions from Reference ShapeKey (Basis) will be moved to active Shape Key,
	so active Shape Key act as reverted. ` (Reverted)` will be added to it's name.
	If not `keep_reverted` then active Shape Key will be deleted.
	
	Returns: True if succeeded, False otherwise.
	
	Available as operator `KawaApplyActiveToBasis`.
	See also: `KawaApplySelectedInActiveToBasis`.
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
		v = ref_key.data[i].co
		ref_key.data[i].co = active_key.data[i].co
		active_key.data[i].co = v
	
	if keep_reverted:
		active_key.name += ' (Reverted)'
	else:
		obj.active_shape_key_index = 0
		obj.shape_key_remove(active_key)
	return True


class KawaApplyActiveToBasis(_KawaOperator):
	"""
	Operator of `apply_active_to_basis`.
	See also: `KawaApplySelectedInActiveToBasis`.
	"""
	bl_idname = "kawa.apply_active_shape_keys_to_basis"
	bl_label = "APPLY ACTIVE Shape Key to Basis"
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
	Same as `apply_active_to_basis`, but other Shape Key will be also edited.
	It's like changing whole base mesh with all it's shape keys.
	If `keep_reverted` then old positions from Reference ShapeKey (Basis) will be moved to active Shape Key,
	so active Shape Key act as reverted. ` (Reverted)` will be added to it's name.
	If not `keep_reverted` then active Shape Key will be deleted.
	
	Returns: True if succeeded, False otherwise.
	
	Available as operator `KawaApplyActiveToAll`.
	See also: `KawaApplySelectedInActiveToAll`.
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
		v = ref_key.data[i].co
		ref_key.data[i].co = active_key.data[i].co
		active_key.data[i].co = v
	
	if keep_reverted:
		active_key.name += ' (Reverted)'
	else:
		obj.active_shape_key_index = 0
		obj.shape_key_remove(active_key)
	return True


class KawaApplyActiveToAll(_KawaOperator):
	"""
	Operator of `apply_active_to_all`.
	See also: `KawaApplySelectedInActiveToAll`.
	"""
	bl_idname = "kawa.apply_active_shape_keys_to_all"
	bl_label = "APPLY ACTIVE Shape Key to ALL Others"
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
	
	Available as operator `KawaCleanupActive`
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
			active_key.data[i].co = ref_key.data[i].co
			changed += 1
	
	return changed


class KawaCleanupActive(_KawaOperator):
	"""
	Operator of `cleanup_active`
	"""
	bl_idname = "kawa.cleanup_active_shape_key"
	bl_label = "Remove Mirco-offsets in ACTIVE Shape Key"
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
	
	Available as operator `KawaCleanupAll`
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
			for shape_key_index in range(1, len(obj.data.key_blocks)):
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


class KawaCleanupAll(_KawaOperator):
	"""
	Operator of `cleanup_all`
	"""
	bl_idname = "kawa.cleanup_all_shape_keys"
	bl_label = "Remove Mirco-offsets in ALL Shape Keys"
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
		if any(True for obj in cls.get_selected_objs(context) if _obj_have_shapekeys(obj, n=2)):
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
	
	Available as operator `KawaRemoveEmpty`
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
			len_ref = len(reference.data)
			len_shk = len(shape_key.data)
			if len_ref != len_shk:
				_log.error("Data size ({0}) of key {1} and data size ({2}) of key {3} in mesh {4} does not match! Is shape key corrupted?"
					.format(len_ref, repr(reference), len_shk, repr(shape_key), repr(mesh)), op=op)
				continue
			# Имеются ли различия между шейпами?
			if not any((shape_key.data[i].co - reference.data[i].co).magnitude > epsilon for i in range(len_shk)):
				empty_keys.add(shape_key.name)
		_log.info("Found {0} empty shape keys in mesh {1}: {2}, removing...".format(len(empty_keys), repr(mesh), repr(empty_keys)), op=op)
		if len(empty_keys) < 1:
			continue
		for empty_key in empty_keys:
			# На всякий случай удаляю по прямому пути, вдруг там что-то перестраивается в процессе удаления.
			# Не спроста же Key-блоки можно редактировать только через Object-блоки
			obj.shape_key_remove(obj.data.shape_keys.key_blocks[empty_key])
		removed_shapekeys += len(empty_keys)
		changed_meshes += 1
	return removed_shapekeys, changed_meshes


class KawaRemoveEmpty(_KawaOperator):
	"""
	Operator of `remove_empty`.
	"""
	bl_idname = "kawa.remove_empty_shape_keys"
	bl_label = "Remove Empty Shape Keys"
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
		if any(True for obj in cls.get_selected_objs(context) if obj.type == 'MESH'):
			return False  # Должны быть выбраны какие-то Меш-объекты
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		objs = self.get_selected_objs(context)
		if len(objs) < 1:
			_log.warning("No mesh-objects with multiple shape keys selected.", op=self)
			return {'CANCELLED'}
		removed_shapekeys, changed_meshes = remove_empty(objs, self.epsilon, op=self)
		_log.info("Total {0} shape keys removed from {1} Meshes.".format(removed_shapekeys, changed_meshes), op=self)
		return {'FINISHED'} if removed_shapekeys > 0 else {'CANCELLED'}


classes = (
	# Edit-mode
	KawaSelectVerticesAffectedByShapeKey,
		#
	KawaRevertSelectedInActiveToBasis,
	KawaRevertSelectedInAllToBasis,
		#
	KawaApplySelectedInActiveToBasis,
	KawaApplySelectedInActiveToAll,
		#
		# Object-mode
	KawaApplyActiveToBasis,
	KawaApplyActiveToAll,
		#
	KawaCleanupActive,
	KawaCleanupAll,
	KawaRemoveEmpty,
)

__pdoc__ = dict()
for _x in classes:
	# Содержимое операторов не докумнтируется.
	_doc = getattr(_x, '__doc__', '')
	if _doc is None or len(_doc) < 1:
		_x.__doc__ = ''
	for _n in dir(_x):
		if hasattr(_x, _n):
			__pdoc__[_x.__name__ + '.' + _n] = False
	if 'bl_idname' in _x.__dict__:
		_x.__doc__ += '\n\nID name: `{0}`.'.format(_x.bl_idname)
	if 'bl_label' in _x.__dict__:
		_x.__doc__ += '\n\nLabel: `{0}`.'.format(_x.bl_label)
	if 'bl_description' in _x.__dict__:
		_x.__doc__ += '\n\nDescription: `{0}`.'.format(_x.bl_description)
		
		
