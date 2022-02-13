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

from . import _internals
from . import _doc
from . import commons as _commons
from . import objects as _objects
from . import meshes as _meshes
from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import Object, Mesh, ShapeKey, Key, Operator, Context
	from .objects import HandyMultiObject


def ensure_shape_shape_len_match(shape_a: 'ShapeKey', shape_b: 'ShapeKey', op: 'Operator' = None):
	"""
	Ensure `len(shape_a.data) == len(shape_b.data)`. Helps to detect corrupted Mesh/Key datablocks.
	"""
	len_a = len(shape_a.data)
	len_b = len(shape_b.data)
	if len_a == len_b:
		return True
	_log.error(f"Size of {shape_a.data} ({len_a}) and size of {shape_b.data} ({len_b}) does not match!", op=op)
	return False


def ensure_mesh_shape_len_match(mesh: 'Mesh', shape_key: 'ShapeKey', op: 'Operator' = None):
	"""
	Ensure `len(mesh.vertices) == len(shape_key.data)`. Helps to detect corrupted Mesh/Key datablocks.
	"""
	len_vts = len(mesh.vertices)
	len_skd = len(shape_key.data)
	if len_vts == len_skd:
		return True
	_log.error(f"Size of {mesh.vertices} ({len_vts}) and size of {shape_key.data} ({len_skd}) does not match! Is shape key corrupted?", op=op)
	return False


def _mesh_have_shapekeys(mesh: 'Mesh', n: int = 1):
	return mesh is not None and mesh.shape_keys is not None and len(mesh.shape_keys.key_blocks) >= n


def _obj_have_shapekeys(obj: 'Object', n: int = 1, strict: 'Optional[bool]' = None):
	mesh = _meshes.get_mesh_safe(obj, strict=strict)
	return mesh is not None and _mesh_have_shapekeys(mesh, n=n)


def _mesh_selection_to_vertices(mesh: 'Mesh'):
	for p in mesh.polygons:
		if p.select:
			for i in p.vertices:
				mesh.vertices[i].select = True
	for e in mesh.edges:
		if e.select:
			for i in e.vertices:
				mesh.vertices[i].select = True


class OperatorSelectVerticesAffectedByShapeKey(_internals.KawaOperator):
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
		if not _meshes.is_mesh_object(obj):
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
		mesh = _meshes.get_mesh_safe(obj)
		shape_key = obj.active_shape_key
		reference = mesh.shape_keys.reference_key
		
		match_skd = ensure_mesh_shape_len_match(mesh, shape_key, op=self)
		match_ref = ensure_mesh_shape_len_match(mesh, reference, op=self)
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


class OperatorRevertSelectedInActiveToBasis(_internals.KawaOperator):
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
		if not _meshes.is_mesh_object(obj):
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
		mesh = _meshes.get_mesh_safe(obj)
		shape_key = obj.active_shape_key
		reference = mesh.shape_keys.reference_key
		
		match_skd = ensure_mesh_shape_len_match(mesh, shape_key, op=self)
		match_ref = ensure_mesh_shape_len_match(mesh, reference, op=self)
		if not match_skd or not match_ref:
			return {'CANCELLED'}
		
		_mesh_selection_to_vertices(mesh)
		
		for i in range(len(mesh.vertices)):
			if mesh.vertices[i].select:
				shape_key.data[i].co = reference.data[i].co.copy()
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class OperatorRevertSelectedInAllToBasis(_internals.KawaOperator):
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
		mesh = _meshes.get_mesh_safe(obj, strict=False)
		if mesh is None:
			return False  # Требуется активный меш-объект
		if mesh.shape_keys is None or len(mesh.shape_keys.key_blocks) < 2:
			return False  # Требуется что бы было 2 или более шейпкея
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = _meshes.get_mesh_safe(obj)
		reference = mesh.shape_keys.reference_key
		
		if not ensure_mesh_shape_len_match(mesh, reference, op=self):
			return {'CANCELLED'}
		
		_mesh_selection_to_vertices(mesh)
		
		for shape_key in mesh.shape_keys.key_blocks:
			if shape_key == reference:
				continue
			if not ensure_mesh_shape_len_match(mesh, shape_key, op=self):
				continue
			for i in range(len(mesh.vertices)):
				if mesh.vertices[i].select:
					shape_key.data[i].co = reference.data[i].co.copy()
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


def apply_active(obj: 'Object', apply_to: 'str',
		only_selected=False, keep_reverted=False, value: 'Optional[float]' = None,
		progress_callback=None, op: 'Operator' = None):
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
	
	if apply_to not in ('ALL', 'BASIS'):
		raise ValueError(f"apply_to={apply_to}")
	
	# No context control
	if not _objects.ensure_in_mode(obj, 'OBJECT', strict=True):
		return False
	mesh = _meshes.get_mesh_safe(obj)
	active_key = obj.active_shape_key
	ref_key = mesh.shape_keys.reference_key
	
	if value is None:
		value = active_key.value
	value = float(value)
	if value == 0.0:
		return False
	
	match_active = ensure_mesh_shape_len_match(mesh, active_key, op=op)
	match_ref = ensure_mesh_shape_len_match(mesh, ref_key, op=op)
	if not match_active or not match_ref:
		return False
	
	if progress_callback:
		progress_callback()
	
	if apply_to == 'ALL':
		for other_key in mesh.shape_keys.key_blocks:
			if other_key == active_key or other_key == ref_key:
				continue
			if not ensure_mesh_shape_len_match(mesh, other_key, op=op):
				continue
			for i in range(len(mesh.vertices)):
				if only_selected and not mesh.vertices[i].select:
					continue
				active_offset = active_key.data[i].co - ref_key.data[i].co
				other_key.data[i].co = other_key.data[i].co + active_offset * value
			if progress_callback:
				progress_callback()
	
	for i in range(len(mesh.vertices)):
		if only_selected and not mesh.vertices[i].select:
			continue
		ref_co = ref_key.data[i].co
		active_co = active_key.data[i].co
		ref_key.data[i].co = active_co * value + ref_co * (1.0 - value)
		active_key.data[i].co = ref_co * value + active_co * (1.0 - value)
		mesh.vertices[i].co = ref_key.data[i].co.copy()
	
	if progress_callback:
		progress_callback()
	
	if keep_reverted:
		active_key.name += ' (Reverted)'
	else:
		obj.active_shape_key_index = 0
		obj.shape_key_remove(active_key)
	return True


class OperatorApplyActive(_internals.KawaOperator):
	"""
	Operator of `apply_active`.
	[Video demonstration.](https://www.youtube.com/watch?v=xfKzI0hn8os)
	"""
	bl_idname = "kawa.apply_active_shape_key"
	bl_label = "Apply Active Shape Key"
	bl_description = \
		"Apply positions of active Shape Key to Reference Shape Key (Basis) or to All other Shape Keys."
	bl_options = {'REGISTER', 'UNDO'}
	
	apply_to_items = [
		("ALL", "All", "Apply to all other Shape Keys", "SHAPEKEY_DATA", 1),
		("BASIS", "Basis", "Apply to Basis (Reference) Shape Key", "SHAPEKEY_DATA", 2),
	]
	
	apply_to: _bpy.props.EnumProperty(
		items=apply_to_items,
		default='ALL',
		name="Apply to",
		description="Apply Shape Key to all other Keys or only to Basis (reference) Key",
	)
	
	only_selected: _bpy.props.BoolProperty(
		name="Only selected vertices",
		description="Only apply changes to selected vertices",
		default=False,
	)
	
	keep_reverted: _bpy.props.BoolProperty(
		name="Keep Reverted Shape Key",
		description="Keep Reverted Shape Key",
		default=False,
	)
	
	use_custom_value: _bpy.props.BoolProperty(
		name="Use own value of Shape Key",
		description="Use explicit custom value of Shape Key scale",
		default=True,
	)
	
	custom_value: _bpy.props.FloatProperty(
		name="Custom value of Shape Key",
		description="Explicit custom value of Shape Key scale",
		default=1.0,
		soft_min=0,
		soft_max=1,
		subtype='FACTOR',
	)
	
	@classmethod
	def poll(cls, context: 'Context'):
		obj = cls.get_active_obj(context)
		if not _meshes.is_mesh_object(obj):
			return False  # Требуется активный меш-объект
		if not obj.active_shape_key or obj.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'OBJECT' and context.mode != 'EDIT_MESH':
			return False  # Требуется режим OBJECT или EDIT_MESH
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		self.progress_begin()
		
		original_mode = context.mode
		if original_mode == 'EDIT_MESH':
			# Рофл в том, что операции над мешью надо проводить вне эдит-мода
			_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		
		value = self.custom_value if self.use_custom_value else None
		result = apply_active(self.get_active_obj(context), self.apply_to,
			only_selected=self.only_selected, keep_reverted=self.keep_reverted, value=value,
			progress_callback=self.progress_next, op=self)
		
		if original_mode == 'EDIT_MESH':
			_bpy.ops.object.mode_set(mode='EDIT', toggle=False)
		
		return {'FINISHED'} if result else {'CANCELLED'}


def cleanup_active(obj: 'Object', epsilon: 'float', op: 'Operator' = None, strict: 'Optional[bool]' = None) -> 'int':
	"""
	**Removes micro-offsets in active Shape Key.**
	If position of a vertex differs from position in Reference Shape Key (Basis) for `epsilon` or less,
	then it's position will be reverted (to be the same as in Reference Shape Key)
	
	Returns: number of changed vertices.
	
	Available as operator `OperatorCleanupActive`
	"""
	mesh = _meshes.get_mesh_safe(obj, strict=strict)
	if mesh is None:
		return 0
	if not _objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
		return 0
	if not _mesh_have_shapekeys(mesh, n=2):
		return 0
	
	active_key = obj.active_shape_key
	ref_key = mesh.shape_keys.reference_key
	if active_key == ref_key:
		return 0
	
	match_active = ensure_mesh_shape_len_match(mesh, active_key, op=op)
	match_ref = ensure_mesh_shape_len_match(mesh, ref_key, op=op)
	if not match_active or not match_ref:
		return 0
	
	changed = 0
	for i in range(len(mesh.vertices)):
		if (ref_key.data[i].co - active_key.data[i].co).magnitude <= epsilon:
			active_key.data[i].co = ref_key.data[i].co.copy()
			changed += 1
	
	return changed


class OperatorCleanupActive(_internals.KawaOperator):
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


def cleanup(objs: 'HandyMultiObject', epsilon: float, op: 'Operator' = None, strict: 'Optional[bool]' = None) -> 'Tuple[int, int, int]':
	"""
	**Removes micro-offsets in all Shape Keys.**
	Same as `cleanup_active`, but for every shape key (except reference one) for every object.
	
	Returns: (number of changed vertices, number of changed shape keys, number of changed meshes).
	
	Available as operator `OperatorCleanupAll`
	"""
	meshes = set()
	vertices_changed, shapekeys_changed, meshes_changed = 0, 0, 0
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_mesh_safe(obj, strict=strict)
		if mesh in meshes:
			continue  # Уже трогали
		meshes.add(mesh)
		if not _objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		if not _mesh_have_shapekeys(mesh, n=2):
			continue
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


class OperatorCleanupAll(_internals.KawaOperator):
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
		if not any(True for obj in cls.get_selected_objs(context) if _obj_have_shapekeys(obj, n=2, strict=False)):
			return False  # Должны быть выбраны Меш-объекты c 2 или более шейпами
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		selected = list(self.get_selected_objs(context))
		if len(selected) < 1:
			_log.warning("No mesh-objects with multiple shape keys selected.", op=self)
			return {'CANCELLED'}
		vertices_cleaned, shapekeys_cleaned, objects_cleaned = cleanup(selected, self.epsilon, op=self)
		_log.info("Cleaned {0} Vertices in {1} Shape Keys in {2} Meshes from micro-offsets (<{3}).".format(
			vertices_cleaned, shapekeys_cleaned, objects_cleaned, float(self.epsilon)), op=self)
		return {'FINISHED'} if vertices_cleaned > 0 else {'CANCELLED'}


def remove_empty(objs: 'HandyMultiObject', epsilon: float,
		allow_remove_predicate: 'Optional[Callable[[Object, Mesh, ShapeKey], bool]]' = None,
		op: 'Operator' = None, strict: 'Optional[bool]' = None) -> 'Tuple[int, int]':
	"""
	**Removes empty Shape Keys from Mesh-objects.**
	Shape Key is empty, if positions of **every** vertex differ from Reference Shape Key (Basis) for `epsilon` or less.
	
	`allow_remove_predicate` makes it possible to keep some shape keys.
	Should return `True` if it is OK to remove given `ShapeKey`.
	Should return `False` if given `ShapeKey` can be removed.
	
	Returns: (number of removed Shape Keys, number of meshes changed)
	
	Available as operator `OperatorRemoveEmpty`
	"""
	removed_shapekeys, changed_meshes = 0, 0
	meshes = set()
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_mesh_safe(obj, strict=strict)
		if mesh in meshes:
			continue  # Уже трогали
		meshes.add(mesh)
		if not _objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		if not _mesh_have_shapekeys(mesh, n=2):
			continue
		key = mesh.shape_keys  # type: Key
		reference = key.reference_key
		empty_keys = set()  # type: Set[str]
		for shape_key in key.key_blocks:
			if shape_key == reference:
				continue  # Базис не удаялется
			match1 = ensure_mesh_shape_len_match(mesh, reference, op=op)
			match2 = ensure_mesh_shape_len_match(mesh, shape_key, op=op)
			if not match1 or not match2:
				continue
			# Имеются ли различия между шейпами?
			if any((shape_key.data[i].co - reference.data[i].co).magnitude > epsilon for i in range(len(mesh.vertices))):
				continue
			if allow_remove_predicate is not None and not allow_remove_predicate(obj, mesh, shape_key):
				continue
			empty_keys.add(shape_key.name)
		# _log.info("Found {0} empty shape keys in mesh {1}: {2}, removing...".format(len(empty_keys), repr(mesh), repr(empty_keys)), op=op)
		if len(empty_keys) < 1:
			continue
		for empty_key in empty_keys:
			# На всякий случай удаляю по прямому пути, вдруг там что-то перестраивается в процессе удаления.
			# Не спроста же Key-блоки можно редактировать только через Object-блоки
			obj.shape_key_remove(mesh.shape_keys.key_blocks[empty_key])
		removed_shapekeys += len(empty_keys)
		changed_meshes += 1
	return removed_shapekeys, changed_meshes


class OperatorRemoveEmpty(_internals.KawaOperator):
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
		if not any(True for obj in cls.get_selected_objs(context) if _obj_have_shapekeys(obj, n=2, strict=False)):
			return False  # Должны быть выбраны какие-то Меш-объекты
		return True
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		objs = self.get_selected_objs(context)
		removed_shapekeys, changed_meshes = remove_empty(objs, self.epsilon, op=self)
		_log.info("Total {0} shape keys removed from {1} Meshes.".format(removed_shapekeys, changed_meshes), op=self)
		return {'FINISHED'} if removed_shapekeys > 0 else {'CANCELLED'}


def _transfer_shape2mesh_co(key_from: 'ShapeKey', mesh_to: 'Mesh', mesh_from: 'Mesh' = None, op: 'Operator' = None):
	if mesh_from is not None and not ensure_mesh_shape_len_match(mesh_from, key_from, op=op):
		return
	if not ensure_mesh_shape_len_match(mesh_to, key_from, op=op):
		return
	for i in range(len(key_from.data)):
		mesh_to.vertices[i].co = key_from.data[i].co


def _transfer_shape2shape_co(key_from: 'ShapeKey', key_to: 'ShapeKey', mesh_from: 'Mesh' = None, mesh_to: 'Mesh' = None,
		op: 'Operator' = None):
	if mesh_from is not None and not ensure_mesh_shape_len_match(mesh_from, key_from, op=op):
		return
	if mesh_to is not None and not ensure_mesh_shape_len_match(mesh_to, key_to, op=op):
		return
	if not ensure_shape_shape_len_match(key_from, key_to, op=op):
		return
	for i in range(len(key_from.data)):
		key_to.data[i].co = key_from.data[i].co


def _transfer_shape2shape(name: str, mesh_from: 'Mesh', mesh_to: 'Mesh', op: 'Operator' = None):
	key_from = mesh_from.shape_keys.key_blocks[name]
	key_to = mesh_to.shape_keys.key_blocks[name]
	_transfer_shape2shape_co(key_from, key_to, mesh_from=mesh_from, mesh_to=mesh_to, op=op)
	key_to.interpolation = key_from.interpolation
	key_to.mute = key_from.mute
	key_to.relative_key = mesh_to.shape_keys.key_blocks[key_from.relative_key.name] if key_from.relative_key is not None else None
	key_to.slider_max = key_from.slider_max
	key_to.slider_min = key_from.slider_min
	key_to.value = key_from.value
	key_to.vertex_group = key_from.vertex_group


def _fix_corrupted_single(obj: 'Object', progress_callback=None, op: 'Operator' = None):
	if progress_callback:
		progress_callback()
	copy_obj = None  # Временная копия
	copy_keep = False
	try:
		_objects.deselect_all()
		_objects.activate(obj, op=op)
		_commons.ensure_op_finished(_bpy.ops.object.duplicate(linked=True), op=op)
		assert len(_bpy.context.selected_objects) == 1
		assert _bpy.context.selected_objects[0] == _bpy.context.active_object
		copy_obj = _bpy.context.active_object  # type: Object
		_commons.ensure_op_finished(_bpy.ops.object.make_single_user(type='SELECTED_OBJECTS', obdata=True), op=op)
		assert obj.data != copy_obj.data  # Странный баг
		assert obj.data.shape_keys != copy_obj.data.shape_keys
		
		_objects.deselect_all()
		_objects.activate(obj, op=op)
		
		original_mesh = _meshes.get_mesh_safe(obj)  # type: Mesh
		copy_mesh = _meshes.get_mesh_safe(copy_obj)  # type: Mesh
		
		active_index = obj.active_shape_key_index
		# Удаляем шейпы с оригинала, т.к. они коррапченые
		corrupted_keys = original_mesh.shape_keys
		# Берем имя заранее, т.к. shape_key_clear позже удалит блок
		corrupted_keys_name = corrupted_keys.name
		# _commons.ensure_op_finished(_bpy.ops.object.shape_key_remove(all=True))
		obj.shape_key_clear()
		assert original_mesh.shape_keys is None
		
		if progress_callback:
			progress_callback()
		
		copy_ref = copy_mesh.shape_keys.reference_key
		_transfer_shape2mesh_co(copy_ref, original_mesh, mesh_from=copy_mesh, op=op)
		
		# Пересоздаем новые шейпы на оригинале
		new_ref = obj.shape_key_add(name=copy_ref.name)
		# _commons.ensure_op_finished(_bpy.ops.object.shape_key_add(from_mix=False))
		assert original_mesh.shape_keys is not None
		assert original_mesh.shape_keys != corrupted_keys
		assert original_mesh.shape_keys != copy_mesh.shape_keys
		
		# Копирование данных из копии в оригинал
		_transfer_shape2shape_co(copy_ref, new_ref, copy_mesh, original_mesh, op=op)
		for copy_key in list(copy_mesh.shape_keys.key_blocks):  # type: ShapeKey
			if copy_key != copy_ref:
				obj.shape_key_add(name=copy_key.name)
		for copy_key in list(copy_mesh.shape_keys.key_blocks):  # type: ShapeKey
			if copy_key != copy_ref:
				if progress_callback:
					progress_callback()
				_transfer_shape2shape(copy_key.name, copy_mesh, original_mesh, op=op)
		obj.active_shape_key_index = active_index
		original_mesh.shape_keys.name = corrupted_keys_name
		if progress_callback:
			progress_callback()
		return len(original_mesh.shape_keys.key_blocks)
	except Exception as exc:
		# Сохраняем копию в случае какой-то проблемы в дебаг-режиме
		copy_keep |= _log.debug
		_log.error(f"Error fixing corrupted shape keys on {obj!r}: {exc!r}", op=op)
		raise exc
	finally:
		if not copy_keep:
			copy_mesh = _meshes.get_mesh_safe(copy_obj, strict=False)
			if copy_obj is not None:
				_bpy.data.objects.remove(copy_obj, do_unlink=True, do_ui_user=True)
			if copy_mesh:
				_bpy.data.meshes.remove(copy_mesh, do_unlink=True, do_ui_user=True)


def fix_corrupted(objs: 'HandyMultiObject', strict: 'Optional[bool]' = None,
		progress_callback=None, op: 'Operator' = None):
	"""
	**Fixes corrupted Shape Keys on Mesh-objects.**
	"""
	if progress_callback:
		progress_callback()
	shape_keys = 0
	meshes = set()
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_mesh_safe(obj, strict=strict)
		if mesh is None:
			continue  # Не меш
		if not _objects.ensure_in_mode(obj, 'OBJECT', strict=strict):
			continue
		if not _obj_have_shapekeys(obj, n=1, strict=strict):
			continue  # Меш без шейпов
		if mesh in meshes:
			continue  # Уже фиксили
		meshes.add(mesh)
		shape_keys += _fix_corrupted_single(obj, progress_callback=progress_callback, op=op)
		if progress_callback:
			progress_callback()
	return len(meshes), shape_keys


class OperatorFixCorrupted(_internals.KawaOperator):
	"""
	Operator of `fix_corrupted`.
	"""
	bl_idname = "kawa.fix_corrupted_shape_keys"
	bl_label = "Fix Corrupted Shape Keys"
	bl_description = "\n".join((
		"Fix Corrupted Shape Keys on selected Mesh-Objects",
		"This is done by reconstructing Shape Key data block of the mesh.",
		"All Shape Keys will be removed and new will be recreated instead.",
	))  # TODO
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		if not any(True for obj in cls.get_selected_objs(context) if _obj_have_shapekeys(obj, n=1, strict=False)):
			return False  # Должны быть выбраны какие-то Меш-объекты
		return True
	
	def execute(self, context: 'Context'):
		objs = list(obj for obj in self.get_selected_objs(context) if _meshes.get_mesh_safe(obj, strict=False) is not None)
		changed_meshes, changed_keys = fix_corrupted(objs, op=self)
		_log.info(f"Recreated (fixed corrupted) {changed_keys} Shape Keys on {changed_meshes} Meshes.", op=self)
		return {'FINISHED'} if changed_meshes > 0 else {'CANCELLED'}


classes = (
	# Edit-mode
	OperatorSelectVerticesAffectedByShapeKey,
		#
	OperatorRevertSelectedInActiveToBasis,
	OperatorRevertSelectedInAllToBasis,
		#
		# Object-mode
	OperatorApplyActive,
		#
	OperatorCleanupActive,
	OperatorCleanupAll,
	OperatorRemoveEmpty,
		#
	OperatorFixCorrupted,
)

__pdoc__ = dict()
_doc.process_blender_classes(__pdoc__, classes)
