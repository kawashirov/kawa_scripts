import logging as _logging

import bpy as _bpy
from bpy import context as _C

import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *
	ContextOverride = Union[Context, Dict[str, Any]]


def _op_report(op: 'Operator', t: 'Set[str]', message: str):
	if op is None:
		op = getattr(_C, 'active_operator', None)
	if op is not None:
		op.report(t, message)


class KawaLogger:
	def __init__(self):
		self.debug = False
		self.py_log = _logging.getLogger('kawashirov')
	
	def is_debug(self):
		return _bpy.app.debug or _bpy.app.debug_python or self.debug
	
	def info(self, message: str, op: 'Operator' = None):
		message = str(message)
		self.py_log.info(message)
		_op_report(op, {'INFO'}, message)
	
	def warning(self, message: str, op: 'Operator' = None):
		message = str(message)
		self.py_log.warning(message)
		_op_report(op, {'INFO'}, message)
	
	def error(self, message: str, op: 'Operator' = None):
		message = str(message)
		self.py_log.error(message)
		_op_report(op, {'ERROR'}, message)
	
	def raise_error(self, exc_type: 'Type', message: str, op: 'Operator' = None):
		message = str(message)
		self.py_log.error(message)
		_op_report(op, {'ERROR'}, message)
		raise exc_type(message)


log = KawaLogger()


def common_str_slots(obj, keys: 'Iterable[str]', exclude: 'Collection[str]' = tuple()) -> 'str':
	return str(type(obj).__name__) + str({
		key: getattr(obj, key, None) for key in keys if key not in exclude and getattr(obj, key, None) is not None
	})


class KawaOperator(_bpy.types.Operator):
	debug = False
	
	@classmethod
	def get_active_obj(cls, context: 'ContextOverride') -> 'Object':
		return context.object or context.active_object or context.view_layer.objects.active
	
	@classmethod
	def get_selected_objs(cls, context: 'ContextOverride') -> 'Union[Sized, Iterable[Object]]':
		return context.selected_objects or context.view_layer.objects.selected

	@classmethod
	def is_debug(cls):
		return cls.debug or log.is_debug()
	
	def info(self, message: str):
		log.info(message, op=self)
	
	def warning(self, message: str):
		log.warning(message, op=self)
	
	def error(self, message: str):
		log.error(message, op=self)
	
	def raise_error(self, exc_type: 'Type', message: str):
		log.raise_error(exc_type, message, op=self)
