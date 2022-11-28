import logging as _logging

import bpy as _bpy

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Any, Type, Union, Iterable, Collection, Dict, Set, Sized, Callable
	from bpy.types import Object, Operator, Context, ID, Optional
	
	ContextOverride = Dict[str, Any]


def _op_report(op: 'Operator', t: 'Set[str]', message: str):
	if op is None:
		op = getattr(_bpy.context, 'active_operator', None)
	if op is not None:
		op.report(t, message)


class KawaLogger:
	def __init__(self):
		self.debug = False
		self.py_log = _logging.getLogger('kawashirov')
	
	def is_debug(self):
		return _bpy.app.debug or _bpy.app.debug_python or self.debug
	
	def report(self, message: str, report_type: str = None, op: 'Operator' = None):
		if report_type is None:
			report_type = 'INFO'
		message = str(message)
		self.py_log.info(message)
		_op_report(op, {'INFO'}, message)
	
	def info(self, message: str, op: 'Operator' = None):
		message = str(message)
		self.py_log.info(message)
		_op_report(op, {'INFO'}, message)
	
	def warning(self, message: str, op: 'Operator' = None):
		message = str(message)
		self.py_log.warning(message)
		_op_report(op, {'WARNING'}, message)
	
	def error(self, message: str, error_type: str = None, op: 'Operator' = None):
		""" error_type can be 'ERROR', 'ERROR_INVALID_INPUT', 'ERROR_INVALID_CONTEXT', 'ERROR_OUT_OF_MEMORY' """
		if error_type is None:
			error_type = 'ERROR'
		error_type = str(error_type)
		message = str(message)
		self.py_log.error(message)
		_op_report(op, {error_type}, message)
	
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
	def get_active_obj(cls, context: 'Context') -> 'Object':
		return context.object or context.active_object or context.view_layer.objects.active
	
	@classmethod
	def get_selected_objs(cls, context: 'Context') -> 'Union[Sized, Iterable[Object]]':
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
	
	def __init__(self):
		self._progress_counter = 0
	
	def progress_begin(self):
		_bpy.context.window_manager.progress_begin(0, 10000)
	
	def progress_next(self):
		self._progress_counter += 1
		_bpy.context.window_manager.progress_update(self._progress_counter % 10000)


def get_data_safe(obj: 'Object', is_checker: 'Callable[[Object], bool]', data_label: 'str',
		strict: 'bool' = None, op: 'Operator' = None) -> 'Optional[ID]':
	if strict is None:
		strict = True
	
	if obj is None:
		if strict:
			log.raise_error(ValueError, f"{data_label}-Object is None!", op=op)
		return None  # silent none
	
	if not is_checker(obj):
		if strict:
			log.raise_error(ValueError, f"{obj!r} is not {data_label}-Object! ({obj.type!r}, {obj.data!r}, {type(obj.data)!r})", op=op)
		return None  # silent none
	
	return obj.data
