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

import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


def _ensure_len_match(op: 'Operator', mesh: 'Mesh', shape_key: 'ShapeKey'):
	len_vts = len(mesh.vertices)
	len_skd = len(shape_key.data)
	if len_vts == len_skd:
		return True
	op.report({'ERROR'}, "Size of {0} ({1}) and size of {2} ({3}) does not match! Is shape key corrupted?"
		.format(repr(mesh.vertices), len_vts, repr(shape_key.data), len_skd))
	return False


class KawaSelectVerticesAffectedByShapeKey(_bpy.types.Operator):
	bl_idname = "mesh.kawa_select_vertices_affected_by_shape_key"
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
		if not context.object or context.object.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not context.object.active_shape_key or context.object.active_shape_key_index == 0:
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
		
		mesh = context.view_layer.objects.active.data  # type: Mesh
		shape_key = context.view_layer.objects.active.active_shape_key
		reference = mesh.shape_keys.reference_key
		
		match_skd = _ensure_len_match(self, mesh, shape_key)
		match_ref = _ensure_len_match(self, mesh, reference)
		if not match_skd or not match_ref:
			return {'CANCELLED'}

		for p in mesh.polygons:
			p.select = False
			
		for e in mesh.edges:
			e.select = False
		
		for i in range(len(mesh.vertices)):
			mesh.vertices[i].select = (shape_key.data[i].co - reference.data[i].co).magnitude > self.epsilon
			pass
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class KawaRemoveEmptyShapeKeys(_bpy.types.Operator):
	bl_idname = "mesh.kawa_remove_empty_shape_keys"
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
		if len(context.selected_objects) < 1:
			return False  # Должны быть выбраны какие-то объекты
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def invoke(self, context: 'Context', event):
		wm = context.window_manager
		# return wm.invoke_props_popup(self, event)
		# return {'RUNNING_MODAL'}
		return wm.invoke_props_dialog(self)
	
	def execute(self, context: 'Context'):
		objs = list()  # type: List[Object]
		for obj in context.selected_objects:
			if obj.type != 'MESH':
				continue
			if obj.data.shape_keys is None:
				continue
			if len(obj.data.shape_keys.key_blocks) < 2:
				continue
			objs.append(obj)
		
		if len(objs) < 1:
			self.report({'WARNING'}, "No mesh-objects with multiple shape keys selected.")
			return {'CANCELLED'}
		
		for obj in objs:
			obj.data.tag = False
	
		empty_keys_count = 0
		for obj in objs:
			context.view_layer.objects.active = obj
			mesh = obj.data  # type: Mesh
			if mesh.tag:
				continue  # Уже трогали
			mesh.tag = True
			key = mesh.shape_keys  # type: Key
			reference = key.reference_key
			empty_keys = set()  # type: Set[str]
			for shape_key in key.key_blocks:
				if shape_key == reference:
					continue  # Базис не удаялется
				len_ref = len(reference.data)
				len_shk = len(shape_key.data)
				if len_ref != len_shk:
					self.report({'ERROR'}, "Data size ({0}) of key {1} and data size ({2}) of key {3} in mesh {4} does not match! Is shape key corrupted?"
						.format(len_ref, repr(reference), len_shk, repr(shape_key), repr(mesh)))
					continue
				# Имеются ли различия между шейпами?
				if not any((shape_key.data[i].co - reference.data[i].co).magnitude > self.epsilon for i in range(len_shk)):
					empty_keys.add(shape_key.name)
			self.report({'INFO'}, "Found {0} empty shape keys in mesh {1}: {2}, removing...".format(len(empty_keys), repr(mesh), repr(empty_keys)))
			if len(empty_keys) < 1:
				continue
			for empty_key in empty_keys:
				# На всякий случай удаляю по прямому пути, вдруг там что-то перестраивается в процессе удаления.
				# Не спроста же Key-блоки можно редактировать только через Object-блоки
				obj.shape_key_remove(obj.data.shape_keys.key_blocks[empty_key])
			empty_keys_count += len(empty_keys)
		self.report({'INFO'}, "Total {0} shape keys removed.".format(empty_keys_count))
		return {'FINISHED'} if empty_keys_count > 0 else {'CANCELLED'}


class KawaRevertSelectedInActiveToBasis(_bpy.types.Operator):
	bl_idname = "mesh.kawa_revert_selected_in_active_to_basis"
	bl_label = "Revert SELECTED Vertices in ACTIVE Shape Key to Basis"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if not context.object or context.object.type != 'MESH':
			return False  # Требуется активный меш-объект
		if not context.object.active_shape_key or context.object.active_shape_key_index == 0:
			return False  # Требуется что бы был активный не первый шейпкей
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = context.view_layer.objects.active.data  # type: Mesh
		shape_key = context.view_layer.objects.active.active_shape_key
		reference = mesh.shape_keys.reference_key
		
		match_skd = _ensure_len_match(self, mesh, shape_key)
		match_ref = _ensure_len_match(self, mesh, reference)
		if not match_skd or not match_ref:
			return {'CANCELLED'}
		
		for p in mesh.polygons:
			if p.select:
				for i in p.vertices:
					mesh.vertices[i].select = True
		
		for e in mesh.edges:
			if e.select:
				for i in e.vertices:
					mesh.vertices[i].select = True
		
		for i in range(len(mesh.vertices)):
			if mesh.vertices[i].select:
				shape_key.data[i].co = reference.data[i].co
		
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


class KawaRevertSelectedInAllToBasis(_bpy.types.Operator):
	bl_idname = "mesh.kawa_revert_selected_in_all_to_basis"
	bl_label = "Revert SELECTED Vertices in ALL Shape Keys to Basis"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if not context.object or context.object.type != 'MESH':
			return False  # Требуется активный меш-объект
		data = context.object.data  # type: Mesh
		if data.shape_keys is None or len(data.shape_keys.key_blocks) < 2:
			return False  # Требуется что бы было 2 или более шейпкея
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		return True
	
	def execute(self, context: 'Context'):
		# Рофл в том, что операции над мешью надо проводить вне эдит-мода
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		mesh = context.view_layer.objects.active.data  # type: Mesh
		reference = mesh.shape_keys.reference_key
		
		if not _ensure_len_match(self, mesh, reference):
			return {'CANCELLED'}
		
		for p in mesh.polygons:
			if p.select:
				for i in p.vertices:
					mesh.vertices[i].select = True
		
		for e in mesh.edges:
			if e.select:
				for i in e.vertices:
					mesh.vertices[i].select = True
		
		for shape_key in mesh.shape_keys.key_blocks:
			if shape_key == reference:
				continue
			if not _ensure_len_match(self, mesh, shape_key):
				continue
			for i in range(len(mesh.vertices)):
				if mesh.vertices[i].select:
					shape_key.data[i].co = reference.data[i].co
			
		_bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		
		return {'FINISHED'}


classes = (
	KawaSelectVerticesAffectedByShapeKey,
	KawaRemoveEmptyShapeKeys,
	KawaRevertSelectedInActiveToBasis,
	KawaRevertSelectedInAllToBasis,
)
