# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import contextlib as _contextlib
import collections as _collections

import bpy as _bpy
import mathutils as _mu

from . import commons as _commons
from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Union, Iterable, List, Optional, Container, Set, Deque, Generator
	from bpy.types import Object, Context, Operator, Scene, ViewLayer
	HandyObject = Union[str, Object]
	HandyMultiObject = Union[HandyObject, Iterable['HandyObject']]


def resolve_object(obj: 'HandyObject') -> 'Generator[Object]':
	if isinstance(obj, _bpy.types.Object):
		yield obj
	elif isinstance(obj, str):
		return _bpy.data.objects[obj]
	else:
		raise ValueError('Can not resolve {!r}.'.format(obj))


def resolve_objects(objs: 'HandyMultiObject') -> 'Generator[Object]':
	if isinstance(objs, _bpy.types.Object):
		yield objs
	elif isinstance(objs, str):
		yield _bpy.data.objects[objs]
	else:
		try:
			for subobj in objs:
				yield from resolve_objects(subobj)
		except Exception as exc:
			raise ValueError('Can not resolve {!r}.'.format(objs)) from exc


def select(objs: 'HandyMultiObject', state: 'bool' = True, view_layer: 'ViewLayer' = None, op: 'Operator' = None):
	try:
		for obj in resolve_objects(objs):
			if state:  # Если выбираем, то нужно также отобразить
				obj.hide_set(False, view_layer=view_layer)
			obj.select_set(state, view_layer=view_layer)
	except Exception as exc:
		_log.error("Can not select {!r}: {!r}".format(objs, exc), op=op)
		raise exc


def activate(objs: 'HandyMultiObject', view_layer: 'ViewLayer' = None, op: 'Operator' = None):
	try:
		for obj in resolve_objects(objs):
			if view_layer is None:
				view_layer = _bpy.context.view_layer
			obj.hide_set(False, view_layer=view_layer)
			obj.select_set(True, view_layer=view_layer)
			view_layer.objects.active = obj
	except Exception as exc:
		_log.error("Can not activate {!r}: {!r}".format(objs, exc), op=op)
		raise exc


def deselect_all(view_layer: 'ViewLayer' = None):
	if view_layer is None:
		view_layer = _bpy.context.view_layer
	# ensure_op_finished(bpy.ops.object.select_all(action='DESELECT'), name="bpy.ops.object.select_all(action='DESELECT')")
	# Это быстрее, чем оператор, и позволяет отжать скрытые объекты
	while len(view_layer.objects.selected) > 0:
		view_layer.objects.selected[0].select_set(False, view_layer=view_layer)
	view_layer.objects.active = None
	

def mode_set(mode: 'str', context: 'Context' = None, op: 'Operator' = None):
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


def identity_transform(obj: 'Object'):
	obj.location = _mu.Vector.Fill(3, 0.0)
	obj.rotation_mode = 'QUATERNION'
	obj.rotation_quaternion = _mu.Quaternion()
	obj.scale = _mu.Vector.Fill(3, 1.0)


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
	child.matrix_parent_inverse = _mu.Matrix.Identity(4)
	child.matrix_world = m


def apply_parent_inverse_matrix(obj: 'Object'):
	identity = _mu.Matrix.Identity(4)
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


def is_parent(parent_object: 'Object', child_object: 'Object') -> 'bool':
	obj = child_object
	while obj is not None:
		if parent_object == obj:
			return True
		obj = obj.parent
	return False


def find_all_child_objects(parent_object: 'Object', where: 'Optional[Container[Object]]' = None) -> 'Set[Object]':
	child_objects = set()
	deque = _collections.deque()  # type: Deque[Object]
	deque.append(parent_object)
	while len(deque) > 0:
		child_obj = deque.pop()
		deque.extend(child_obj.children)
		if where is not None and child_obj not in where:
			continue
		child_objects.add(child_obj)
	return child_objects


def join(obj_from: 'HandyMultiObject', obj_to: 'HandyObject'):
	deselect_all()
	select(obj_from)
	activate(obj_to)
	_commons.ensure_op_finished_or_cancelled(_bpy.ops.object.join(), name='bpy.ops.object.join')
	deselect_all()


classes = (
	KawaApplyParentInverseMatrices,
)

