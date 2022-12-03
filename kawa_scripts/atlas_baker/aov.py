# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

class AOV:
	"""
	Configuration of named AOV (Arbitrary Output Variable) pass.
	Must not be mutated.

	- `_name` must be any name for AOV variable.
	`BaseAtlasBaker` will look for "AOV Output" nodes with given name and use it as source.
	This name also will be passed to `BaseAtlasBaker.get_target_image` as `bake_type`.
	- `_type` must be `'VALUE'` or `'COLOR'`
	- `_default` must be number (or tuple of 3 (RGB) numbers for color-type).
	This value will be used as default for materials with no "AOV Output" node.
	If "AOV Output" exist, but have no inputs connected,
	values of 'Color' or 'Value' input sockets will be used, same as in shaders.
	"""
	__slots__ = ('_name', '_type', '_default')
	
	def __init__(self, _name: 'str', _type: 'str', _default: 'float|tuple[float,float,float]' = 0):
		self._name = _name
		
		if _type not in ('VALUE', 'COLOR'):
			raise ValueError(f"Invalid type of AOV {_name!r}: {_type!r}")
		
		if isinstance(_default, (int, float)):
			pass
		elif isinstance(_default, tuple):
			if len(_default) != 3:
				raise ValueError(f"Invalid length of default value of AOV {_name!r}: {len(_default)}, must be 3 (RGB).")
			for i in range(3):
				if not isinstance(_default[i], (int, float)):
					raise ValueError(f"Invalid default[{i}] value of AOV {_name!r}: {type(_default[i])!r} {_default[i]!r}")
		else:
			raise ValueError(f"Invalid default value of AOV {_name!r}: {type(_default)!r} {_default!r}")
		
		self._type = _type
		self._default = _default
	
	@property
	def name(self):
		return self._name
	
	@property
	def type(self):
		return self._type
	
	@property
	def is_value(self):
		return self._type == 'VALUE'
	
	@property
	def is_color(self):
		return self._type == 'COLOR'
	
	@property
	def default(self):
		return self._default
	
	@property
	def default_rgb(self) -> 'tuple[float, float, float]':
		if isinstance(self._default, (int, float)):
			return self._default, self._default, self._default
		if isinstance(self._default, tuple):
			return self._default
	
	@property
	def default_rgba(self) -> 'tuple[float, float, float, float]':
		if isinstance(self._default, (int, float)):
			return self._default, self._default, self._default, 1.0
		if isinstance(self._default, tuple):
			return (*self._default, 1.0)


__all__ = ['AOV']
