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

from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Optional, Tuple, Iterable, Dict, Callable


class ConfigurationError(RuntimeError):
	# Ошибка конфигурации
	pass


class MaterialConfigurationError(ConfigurationError):
	def __init__(self, mat, msg: str):
		self.material = mat
		msg = 'Material={0}: {1}'.format(mat, msg)
		super().__init__(msg)


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


def ensure_op_result(result: 'Iterable[str]', allowed_results: 'Iterable[str]', **kwargs):
	if set(result) >= set(allowed_results):
		raise RuntimeError('Operator has invalid result:', result, allowed_results, list(_bpy.context.selected_objects), kwargs)


def ensure_op_finished(result, **kwargs):
	if 'FINISHED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', result, list(_bpy.context.selected_objects), kwargs)


def ensure_op_finished_or_cancelled(result, **kwargs):
	if 'FINISHED' not in result and 'CANCELLED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', result, list(_bpy.context.selected_objects), kwargs)


def any_not_none(*args):
	# Первый не-None, или None
	for v in args:
		if v is not None:
			return v
	return None


_K = _typing.TypeVar('_K')
_V = _typing.TypeVar('_V')


def dict_get_or_add(_dict: 'Dict[_K,_V]', _key: 'Optional[_K]', _creator: 'Callable[[],_V]') -> '_V':
	value = _dict.get(_key)
	if value is None:
		value = _creator()
		_dict[_key] = value
	return value
