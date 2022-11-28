# Kawashirov's Scripts (c) 2022 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import bpy as _bpy
import bpy.types

from . import _internals
from . import objects as _objects
from . import meshes as _meshes
from . import commons as _commons

import typing as _typing

if _typing.TYPE_CHECKING:
	from mathutils import Vector
	from typing import Optional, Union, Tuple, Iterable
	from bpy.types import Object, Context, Attribute, BoolAttribute
	from bpy.types import Mesh, MeshVertex, MeshEdge, MeshPolygon
	
	from objects import HandyMultiObject


def _prepare_attribute_save_load(mesh: 'Mesh',
		attribute: 'Union[str, Attribute]', mode: 'str', only_visible: 'bool',
		strict: 'Optional[bool]') -> 'Tuple[Mesh, BoolAttribute, str, bool, Iterable[Union[MeshVertex, MeshEdge, MeshPolygon]]]':
	if strict is None:
		strict = True
	
	if mode is None:
		mode = 'SET'
	if mode not in ('SET', 'EXTEND', 'SUBTRACT', 'INTERSECT', 'DIFFERENCE'):
		raise ValueError('mode')
	
	only_visible = bool(only_visible) if only_visible is not None else True
	
	if attribute is None:
		attribute = mesh.attributes.active
	elif not isinstance(attribute, _bpy.types.Attribute):
		attribute = mesh.attributes.get(attribute)
	if not isinstance(attribute, _bpy.types.Attribute):
		if strict:
			raise ValueError('attribute')
		else:
			return None, None, None, None, None
	
	if attribute not in mesh.attributes.values():
		if strict:
			raise ValueError('attribute')
		else:
			return None, None, None, None, None
	
	if attribute.domain not in ('POINT', 'EDGE', 'FACE'):
		if strict:
			raise ValueError('attribute')
		else:
			return None, None, None, None, None
	
	# Необходимо установить соотв. mesh_select_mode, иначе при
	# изменении .select будут также выбиратьcя лишние части геометрии
	geometries = None
	if attribute.domain == 'POINT':
		geometries = mesh.vertices
		_bpy.context.tool_settings.mesh_select_mode = (True, False, False)
	elif attribute.domain == 'EDGE':
		geometries = mesh.edges
		_bpy.context.tool_settings.mesh_select_mode = (False, True, False)
	elif attribute.domain == 'FACE':
		geometries = mesh.polygons
		_bpy.context.tool_settings.mesh_select_mode = (False, False, True)
	
	return mesh, attribute, mode, only_visible, geometries


def save_selection_to_attribute_mesh(mesh: 'Mesh',
		attribute: 'Union[str, Attribute]' = None, mode: 'str' = None, only_visible: 'bool' = None,
		strict: 'Optional[bool]' = None):
	mesh, attribute, mode, only_visible, geometries = \
		_prepare_attribute_save_load(mesh, attribute, mode, only_visible, strict)
	if mesh is None:
		return 0
	
	changes = 0
	for geometry in geometries:
		if only_visible and geometry.hide:
			continue
		av = attribute.data[geometry.index]
		before = av.value
		if mode == 'SET':
			av.value = geometry.select
		elif mode == 'EXTEND':
			av.value |= geometry.select
		elif mode == 'SUBTRACT':
			av.value &= not geometry.select
		elif mode == 'INTERSECT':
			av.value &= geometry.select
		elif mode == 'DIFFERENCE':
			av.value ^= geometry.select
		if before != av.value:
			changes += 1
	
	return changes


def save_selection_to_attribute(objs: 'HandyMultiObject', attribute: 'Union[str, Attribute]' = None,
		strict: 'Optional[bool]' = None) -> 'int':
	meshes, changes = set(), 0
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_safe(obj, strict=strict)
		if mesh is not None and mesh not in meshes:
			meshes.add(mesh)
			changes += save_selection_to_attribute_mesh(mesh, attribute=attribute, strict=strict)
	return changes


def load_selection_from_attribute_mesh(mesh: 'Mesh',
		attribute: 'Union[str, Attribute]' = None, mode: 'str' = None, only_visible: 'bool' = None,
		strict: 'Optional[bool]' = None):
	mesh, attribute, mode, only_visible, geometries = \
		_prepare_attribute_save_load(mesh, attribute, mode, only_visible, strict)
	if mesh is None:
		return 0
	changes = 0
	for geometry in geometries:  # type: Union[MeshVertex, MeshEdge, MeshPolygon]
		if only_visible and geometry.hide:
			continue
		av = bool(attribute.data[geometry.index].value)
		before = geometry.select
		if mode == 'SET':
			geometry.select = av
		elif mode == 'EXTEND':
			geometry.select |= av
		elif mode == 'SUBTRACT':
			geometry.select &= not av
		elif mode == 'INTERSECT':
			geometry.select &= av
		elif mode == 'DIFFERENCE':
			geometry.select ^= av
		if before != geometry.select:
			changes += 1
	
	return changes


def load_selection_from_attribute(objs: 'HandyMultiObject', attribute: 'Union[str, Attribute]' = None,
		strict: 'Optional[bool]' = None) -> 'int':
	meshes, changes = set(), 0
	for obj in _objects.resolve_objects(objs):
		mesh = _meshes.get_safe(obj, strict=strict)
		if mesh is not None and mesh not in meshes:
			meshes.add(mesh)
			changes += load_selection_from_attribute_mesh(mesh, attribute=attribute, strict=strict)
	return changes


class _OperatorSaveLoadSelectionAttribute(_internals.KawaOperator):
	only_visible: _bpy.props.BoolProperty(
		default=True,
		name="Only visible",
		description="Only update selection values of visible geometry. Hidden will not be changed.",
	)
	
	def invoke(self, context: 'Context', event):
		return context.window_manager.invoke_props_dialog(self)
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode != 'EDIT_MESH':
			return False  # Требуется режим  EDIT_MESH
		obj = cls.get_active_obj(context)
		mesh = _meshes.get_safe(obj, strict=False)
		if mesh is None:
			return False  # Требуется активный меш-объект
		attribute = mesh.attributes.active
		if attribute is None:
			return False  # Требуется активный аттрибут
		if attribute.data_type not in ('BOOLEAN', 'FLOAT', 'INT'):
			return False  # Требуется верный тип аттрибута
		if attribute.domain not in ('POINT', 'EDGE', 'FACE'):
			return False  # Требуется верный тип аттрибута
		if attribute.domain == 'POINT' and not context.tool_settings.mesh_select_mode[0]:
			return False  # Для POINT требуется активный VERT mesh_select_mode
		if attribute.domain == 'EDGE' and not context.tool_settings.mesh_select_mode[1]:
			return False  # Для EDGE требуется активный EDGE mesh_select_mode
		if attribute.domain == 'FACE' and not context.tool_settings.mesh_select_mode[3]:
			return False  # Для FACE требуется активный FACE mesh_select_mode
		return True


class OperatorSaveSelectionToAttribute(_OperatorSaveLoadSelectionAttribute):
	"""
	****
	"""
	bl_idname = "kawa.save_selection_to_attribute"
	bl_label = "Save selection to active attribute"
	bl_description = ""
	bl_options = {'REGISTER', 'UNDO'}
	
	mode_items = [
		("SET", "Set", "Overwrite saved selection with current", "SELECT_SET", 0),
		("EXTEND", "Extend", "Add current selection to saved", "SELECT_EXTEND", 1),
		("SUBTRACT", "Subtract", "Subtract current selection from saved", "SELECT_SUBTRACT", 2),
		("INTERSECT", "Intersect", "Intersect current and saved selection", "SELECT_INTERSECT", 3),
		("DIFFERENCE", "Difference", "Difference current and saved selection", "SELECT_DIFFERENCE", 4),
	]
	
	mode: _bpy.props.EnumProperty(
		items=mode_items,
		default='SET',
		name="Selection mode",
		description="Selection mode",  # TODO
	)
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# операции над мешью надо проводить вне эдит-мода
		mesh = _meshes.get_safe(obj)
		attribute_name = mesh.attributes.active.name
		
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		
		mesh = _meshes.get_safe(obj)
		attribute = mesh.attributes[attribute_name]
		changes = save_selection_to_attribute_mesh(mesh,
			attribute=attribute, mode=str(self.mode), only_visible=bool(self.only_visible))
		
		_bpy.ops.object.mode_set(mode='EDIT', toggle=False)
		
		return {'FINISHED'} if changes > 0 else {'CANCELLED'}


class OperatorLoadSelectionFromAttribute(_OperatorSaveLoadSelectionAttribute):
	"""
	****
	"""
	bl_idname = "kawa.load_selection_from_attribute"
	bl_label = "Load selection from active attribute"
	bl_description = ""
	bl_options = {'REGISTER', 'UNDO'}
	
	mode_items = [
		("SET", "Set", "Overwrite current selection with saved", "SELECT_SET", 0),
		("EXTEND", "Extend", "Add saved selection to current selection", "SELECT_EXTEND", 1),
		("SUBTRACT", "Subtract", "Subtract saved selection from current selection", "SELECT_SUBTRACT", 2),
		("INTERSECT", "Intersect", "Intersect current and saved selection", "SELECT_INTERSECT", 3),
		("DIFFERENCE", "Difference", "Difference current and saved selection", "SELECT_DIFFERENCE", 4),
	]
	
	mode: _bpy.props.EnumProperty(
		items=mode_items,
		default='SET',
		name="Selection mode",
		description="Selection mode",  # TODO
	)
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		# операции над мешью надо проводить вне эдит-мода
		mesh = _meshes.get_safe(obj)
		attribute_name = mesh.attributes.active.name
		
		_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
		
		attribute = mesh.attributes[attribute_name]
		changes = load_selection_from_attribute_mesh(mesh,
			attribute=attribute, mode=str(self.mode), only_visible=bool(self.only_visible))
		
		_bpy.ops.object.mode_set(mode='EDIT', toggle=False)
		
		return {'FINISHED'} if changes > 0 else {'CANCELLED'}


classes = (
	OperatorSaveSelectionToAttribute,
	OperatorLoadSelectionFromAttribute,
)
