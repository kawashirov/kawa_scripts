# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import typing
import logging

from ..commons import *

if typing.TYPE_CHECKING:
	from typing import *
	SetupRaw = Dict[str, Any]
	SizeInt = Tuple[int, int]
	SizeFloat = Tuple[float, float]

log = logging.getLogger('kawa.config')


def validate_uv_index(value: 'UVLayerIndex', field_name: 'str') -> 'UVLayerIndex':
	if value is not False and not is_none_or_valid_string(value):
		log.warning("Invalid config value for for %s='%s'", field_name, value)
		return None
	return value


def validate_string(value: 'str', field_name: 'str') -> 'Optional[str]':
	if not is_none_or_valid_string(value):
		log.warning("Invalid config value for %s='%s'", field_name, value)
		return None
	return value


def validate_bool(value: 'bool', field_name: 'str') -> 'Optional[bool]':
	if value is not None and not isinstance(value, bool):
		log.warning("Invalid config value for %s='%s'", field_name, value)
		return None
	return value


def validate_float(value: 'float', field_name: 'str') -> 'Optional[float]':
	if value is not None and not (isinstance(value, float) or isinstance(value, int)):
		log.warning("Invalid config value for %s='%s'", field_name, value)
		return None
	return value


def validate_size_int(value: 'SizeInt', field_name: 'str') -> 'Optional[SizeInt]':
	if value is not None and is_valid_size_int(value):
		log.warning("Invalid config value for %s='%s'", field_name, value)
		return None
	return value


def validate_int_positive_or_zero(value: 'int', field_name: 'str') -> 'Optional[int]':
	# Значение должно быть int >= 0
	if value is not None and not (isinstance(value, int) and value >= 0):
		log.warning("Invalid config value for %s='%s'", field_name, value)
		return None
	return value


def validate_seq_as_iterator(config: 'SetupRaw') -> 'Iterable[Any]':
	if isinstance(config, set) or isinstance(config, tuple) or isinstance(config, list):
		return iter(config)
	else:
		return iter(())  # empty


def validate_set_or_dict_as_iterator(config: 'SetupRaw') -> 'Iterable[Tuple[str, Any]]':
	if isinstance(config, dict):
		return ((k, v) for k, v in config.items())
	elif isinstance(config, set) or isinstance(config, tuple) or isinstance(config, list):
		return ((x, None) for x in config)
	else:
		return iter(())  # empty

