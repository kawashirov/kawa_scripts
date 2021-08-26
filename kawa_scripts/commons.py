# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
from collections import deque as _deque
from time import perf_counter as _perf_counter
import contextlib as _contextlib

import bpy as _bpy
from mathutils import Vector as _Vector
from mathutils import Quaternion as _Quaternion
from mathutils import Matrix as _Matrix
from mathutils.geometry import area_tri as _area_tri

from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


class ConfigurationError(RuntimeError):
	# Ошибка конфигурации
	pass


class MaterialConfigurationError(ConfigurationError):
	def __init__(self, mat, msg: str):
		self.material = mat
		msg = 'Material={0}: {1}'.format(mat, msg)
		super().__init__(msg)


def poly2_area2(ps: 'Sequence[Vector]'):
	# Площадь полигона, примерно, без учёта вогнутостей
	length = len(ps)
	if length < 3:
		return 0
	elif length == 3:
		# Частый случай, оптимизация для треугольника
		return _area_tri(ps[0], ps[1], ps[2])
	elif length == 4:
		# Частый случай, оптимизация для квада
		return _area_tri(ps[0], ps[1], ps[2]) + _area_tri(ps[0], ps[2], ps[3])
	else:
		# Для пентагона и выше - Формула Гаусса
		s = ps[length - 1].x * ps[0].y - ps[0].x * ps[length - 1].y
		for i in range(length - 1):
			s += ps[i].x * ps[i + 1].y
			s -= ps[i + 1].x * ps[i].y
		return 0.5 * abs(s)


def is_none_or_bool(value: 'Optional[bool]') -> 'bool':
	return value is None or isinstance(value, bool)


def is_positive_int(pint: 'int') -> 'bool':
	return isinstance(pint, int) and pint > 0


def is_positive_float(pfloat: 'float') -> 'bool':
	return (isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat > 0


def is_none_or_positive_float(pfloat: 'float') -> 'bool':
	return pfloat is None or ((isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat > 0)


def is_positive_or_zero_float(pfloat: 'float') -> 'bool':
	return (isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat >= 0


def is_none_or_positive_or_zero_float(pfloat: 'float') -> 'bool':
	return pfloat is None or ((isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat >= 0)


def is_valid_size_int(size: 'Tuple[int, int]') -> 'bool':
	return isinstance(size, tuple) and len(size) == 2 and is_positive_int(size[0]) and is_positive_int(size[1])


def is_valid_size_float(size: 'Tuple[float, float]') -> 'bool':
	return isinstance(size, tuple) and len(size) == 2 and is_positive_float(size[0]) and is_positive_float(size[1])


def is_valid_string(string: 'str') -> 'bool':
	return isinstance(string, str) and len(string) > 0


def is_none_or_valid_string(string: 'str') -> 'bool':
	return string is None or (isinstance(string, str) and len(string) > 0)


def identity_transform(obj: 'Object'):
	obj.location = _Vector.Fill(3, 0.0)
	obj.rotation_mode = 'QUATERNION'
	obj.rotation_quaternion = _Quaternion()
	obj.scale = _Vector.Fill(3, 1.0)


def copy_transform(from_obj: 'Object', to_obj: 'Object'):
	to_obj.location = from_obj.location
	to_obj.rotation_mode = from_obj.rotation_mode
	to_obj.rotation_axis_angle = from_obj.rotation_axis_angle
	to_obj.rotation_euler = from_obj.rotation_euler
	to_obj.rotation_quaternion = from_obj.rotation_quaternion
	to_obj.scale = from_obj.scale


def move_children_to_grandparent(obj: 'Object'):
	for child in obj.children:
		set_parent_keep_world(child, obj.parent)


def set_parent_keep_world(child: 'Object', parent: 'Object'):
	m = child.matrix_world.copy()
	child.parent = parent
	child.parent_type = 'OBJECT'
	child.matrix_parent_inverse = _Matrix.Identity(4)
	child.matrix_world = m


def apply_parent_inverse_matrix(obj: 'Object'):
	identity = _Matrix.Identity(4)
	if obj.parent_type != 'OBJECT' or obj.matrix_parent_inverse == identity:
		return False
	mw = obj.matrix_world.copy()
	obj.matrix_parent_inverse = identity
	obj.parent_type = 'OBJECT'
	obj.matrix_world = mw
	return True


class KawaApplyParentInverseMatrices(_bpy.types.Operator):
	bl_idname = "object.kawa_apply_parent_inverse_matrices"
	bl_label = "Apply Parent Inverse Transform Matricies"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if len(context.selected_objects) < 1:
			return False  # Должны быть выбраны какие-то объекты
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def execute(self, context: 'Context'):
		applied = list(obj for obj in context.selected_objects if apply_parent_inverse_matrix(obj))
		applied_strs = "".join("\n-\t{0}".format(repr(obj)) for obj in applied)
		self.report({'INFO'}, "Applied {0} parent inverse matrices:{1}".format(len(applied), applied_strs))
		return {'FINISHED'} if len(applied) > 0 else {'CANCELLED'}


def ensure_op_result(result: 'Iterable[str]', allowed_results: 'Iterable[str]', **kwargs):
	if set(result) >= set(allowed_results):
		raise RuntimeError('Operator has invalid result:', result, allowed_results, list(_bpy.context.selected_objects), kwargs)


def ensure_op_finished(result, **kwargs):
	if 'FINISHED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', result, list(_bpy.context.selected_objects), kwargs)


def ensure_op_finished_or_cancelled(result, **kwargs):
	if 'FINISHED' not in result and 'CANCELLED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', result, list(_bpy.context.selected_objects), kwargs)


def select_set_all(objects: 'Iterable[Object]', state: bool):
	for obj in objects:
		try:
			obj.hide_set(False)
			obj.select_set(state)
		except Exception as exc:
			_log.error(str(exc))
			_log.error(repr(objects))
			raise exc
		

def activate_object(obj: 'Object'):
	obj.hide_set(False)
	obj.select_set(True)
	_bpy.context.view_layer.objects.active = obj


def activate_objects(objs: 'Iterable[Object]'):
	for obj in objs:
		activate_object(obj)


def ensure_deselect_all_objects():
	# ensure_op_finished(bpy.ops.object.select_all(action='DESELECT'), name="bpy.ops.object.select_all(action='DESELECT')")
	# Это быстрее, чем оператор, и позволяет отжать скрытые объекты
	# bpy.context.selected_objects выдаёт AttributeError: '_RestrictContext' object has no attribute 'selected_objects'
	while len(_bpy.context.view_layer.objects.selected) > 0:
		_bpy.context.view_layer.objects.selected[0].select_set(False)


def object_mode_set_strict(mode: 'str', context: 'Context' = None, op: 'Operator' = None):
	context = context or _bpy.context
	active_object = context.object or context.active_object or context.view_layer.objects.active
	if active_object is None:
		msg = 'There is no active object, can not set mode {}.'.format(repr(mode))
		_log.raise_error(RuntimeError, msg, op=op)
	if active_object.mode != mode:
		_bpy.ops.object.mode_set(mode=mode)
	if active_object.mode != mode:
		msg = 'Can not switch object {} to mode {}, got {} instead.'.format(repr(active_object), repr(mode), repr(context.object.mode))
		_log.raise_error(RuntimeError, msg, op=op)


class _TemporaryViewLayer(_contextlib.ContextDecorator):
	# Does not work
	def __init__(self, name=None):
		self.name = None if name is None else str(name)
		self.scene = None  # type: Scene
		self.temp_view_layer = None  # type: ViewLayer
		self.original_view_layer = None  # type: ViewLayer
	
	def __enter__(self):
		self.scene = _bpy.context.scene
		self.original_view_layer = _bpy.context.view_layer
		name = '__Temporary'
		if self.name:
			name += '-' + self.name
		self.temp_view_layer = self.scene.view_layers.new(name)
		# _bpy.context.window.view_layer = self.temp_view_layer
		_bpy.context.view_layer = self.temp_view_layer
		return self
	
	def __exit__(self, *exc):
		try:
			# _bpy.context.window.scene = self.scene
			# _bpy.context.window.view_layer = self.original_view_layer
			_bpy.context.scene = self.scene
			_bpy.context.view_layer = self.original_view_layer
			self.scene.view_layers.remove(self.temp_view_layer)
		except ReferenceError:
			pass  # this is fine


class SaveSelection(_contextlib.ContextDecorator):
	# TODO
	def __init__(self, name=None):
		self.last_active_object = None  # type: Object
		self.shown = None  # type: List[Object]
		self.selected = None  # type: List[Object]
	
	def __enter__(self):
		self.last_active_object = _bpy.context.view_layer.objects.active
		self.selected = list(_bpy.context.view_layer.objects.selected)
		return self
	
	# def hide_set(self, obj: 'Object', state: 'bool'):
	# 	if self.hide_state is None:
	# 		self.hide_state = dict()
	# 	if obj not in self.hide_state.keys():
	# 		self.hide_state[obj] = obj.hide_get()
	# 	obj.hide_set(state)
	#
	# def select_set(self, obj: 'Object', state: 'bool'):
	# 	if self.select_state is None:
	# 		self.select_state = dict()
	# 	if obj not in self.select_state.keys():
	# 		self.select_state[obj] = obj.select_get()
	# 	obj.select_set(state)
	#
	# def activate_object(self, obj: 'Object'):
	# 	self.hide_set(obj, False)
	# 	self.select_set(obj, True)
	# 	_bpy.context.view_layer.objects.selected = obj
	#
	# def activate_objects(self, objs: 'Iterable[Object]'):
	# 	for obj in objs:
	# 		self.activate_object(obj)
	
	def __exit__(self, *exc):
		for obj in _bpy.context.view_layer.objects:
			obj.select_set(obj in self.selected)
		# if self.hide_state is not None:
		# 	for obj, state in self.hide_state.items():
		# 		try:
		# 			obj.hide_set(state)
		# 		except ReferenceError:
		# 			pass  # object invalid, this is fine
		# if self.select_state is not None:
		# 	for obj, state in self.select_state.items():
		# 		try:
		# 			obj.select_set(state)
		# 		except ReferenceError:
		# 			pass  # object invalid, this is fine
		try:
			_bpy.context.view_layer.objects.active = self.last_active_object
		except ReferenceError:
			pass  # object invalid, this is fine


def any_not_none(*args):
	# Первый не-None, или None
	for v in args:
		if v is not None:
			return v
	return None


def get_mesh_safe(obj: 'Object') -> 'Mesh':
	mesh = obj.data
	if not isinstance(mesh, _bpy.types.Mesh):
		raise ValueError("Object.data is not Mesh!", obj, mesh)
	return mesh


def remove_all_geometry(obj: 'Object'):
	import bmesh
	# Очистка геометрии
	bm = bmesh.new()
	try:
		mesh = get_mesh_safe(obj)
		# Дегенеративные уебки, почему в Mesh нет API для удаления геометрии?
		bm.from_mesh(mesh)
		bm.clear()  # TODO optimize?
		bm.to_mesh(mesh)
	finally:
		bm.free()


def remove_all_vertex_colors(obj: 'Object'):
	mesh = get_mesh_safe(obj)
	while len(mesh.vertex_colors) > 0:
		mesh.vertex_colors.remove(mesh.vertex_colors[0])


def remove_all_material_slots(obj: 'Object', slots=0):
	while len(obj.material_slots) > slots:
		_bpy.context.view_layer.objects.active = obj
		ensure_op_finished(_bpy.ops.object.material_slot_remove(), name='bpy.ops.object.material_slot_remove')


def find_objects_with_material(material: 'Material', where: 'Iterable[Object]' = None) -> 'Set[Object]':
	objects = set()
	if where is None:
		where = _bpy.context.scene.objects
	for obj in where:
		if not isinstance(obj.data, _bpy.types.Mesh):
			continue
		for slot in obj.material_slots:
			if slot.material == material:
				objects.add(obj)
	return objects


def is_mesh_affected_by_armature(arm_obj: 'Object', mesh_obj: 'Object') -> 'bool':
	if arm_obj.type != 'ARMATURE':
		raise ValueError("arm_obj {} is not 'ARMATURE' type ({})".format(repr(arm_obj), repr(arm_obj.type)))
	if mesh_obj.type != 'MESH':
		raise ValueError("mesh_obj {} is not 'MESH' type ({})".format(repr(mesh_obj), repr(mesh_obj.type)))
	for mod in mesh_obj.modifiers:
		if mod.type == 'ARMATURE' and mod.object == arm_obj:
			return True
	return False


def is_mesh_affected_by_any_armature(arm_objs: 'Iterable[Object]', mesh_obj: 'Object') -> 'bool':
	return any(is_mesh_affected_by_armature(arm_obj, mesh_obj) for arm_obj in arm_objs)


def find_meshes_affected_by_armatue(arm_obj: 'Object', where: 'Iterable[Object]' = None) -> 'List[Object]':
	if where is None:
		where = _bpy.data.objects
	return list(obj for obj in where if obj.type == 'MESH' and is_mesh_affected_by_armature(arm_obj, obj))


def is_parent(parent_object: 'Object', child_object: 'Object') -> 'bool':
	obj = child_object
	while obj is not None:
		if parent_object == obj:
			return True
		obj = obj.parent
	return False


def find_all_child_objects(parent_object: 'Object', where: 'Optional[Container[Object]]' = None) -> 'Set[Object]':
	child_objects = set()
	deque = _deque()  # type: Deque[Object]
	deque.append(parent_object)
	while len(deque) > 0:
		child_obj = deque.pop()
		deque.extend(child_obj.children)
		if where is not None and child_obj not in where:
			continue
		child_objects.add(child_obj)
	return child_objects


def merge_same_material_slots(obj: 'Object'):
	# Объединяет слоты с одинаковыми материалами:
	# Сначала объединяет индексы, затем удаляет освободившиеся слоты.
	# Игнорирует пустые слоты
	if len(obj.material_slots) < 2:
		return
	ensure_deselect_all_objects()
	activate_object(obj)
	mesh = get_mesh_safe(obj)
	# Все материалы используемые на объекте
	mats = set()
	run_op = False
	for slot in obj.material_slots:
		if slot is None or slot.material is None:
			continue
		mats.add(slot.material)
	for proc_mat in mats:
		indices = list()
		for slot in range(len(obj.material_slots)):
			if obj.material_slots[slot].material is proc_mat:
				indices.append(slot)
		if len(indices) < 2:
			continue
		run_op = True
		main_idx = indices[0]
		for idx in indices[1:]:
			for poly in mesh.polygons:
				if poly.material_index == idx:
					poly.material_index = main_idx
	if run_op:
		ensure_op_finished_or_cancelled(
			_bpy.ops.object.material_slot_remove_unused(), name='bpy.ops.object.material_slot_remove_unused'
		)
	ensure_deselect_all_objects()


_K = _typing.TypeVar('_K')
_V = _typing.TypeVar('_V')


def dict_get_or_add(_dict: 'Dict[_K,_V]', _key: 'Optional[_K]', _creator: 'Callable[[],_V]') -> '_V':
	value = _dict.get(_key)
	if value is None:
		value = _creator()
		_dict[_key] = value
	return value


classes = (
	KawaApplyParentInverseMatrices,
)
