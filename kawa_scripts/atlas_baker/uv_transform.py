# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
from typing import Generator
from bpy.types import Material
from mathutils import Vector

from .. import _internals


class UVTransform:
	"""
	Internal class used by `BaseAtlasBaker` as mapping between UV areas on original Materials and UV areas on atlas.
	"""
	__slots__ = ('material', 'origin_norm', 'padded_norm', 'packed_norm')
	
	def __init__(self):
		# Хранить множество вариантов координат затратно по памяти,
		# но удобно в отладке и избавляет от велосипедов
		self.material = None  # type: Material
		# Оригинальная uv в нормальных координатах и в пикселях текстуры
		self.origin_norm = None  # type: Vector # len == 4
		# self.origin_tex = None  # type: Vector # len == 4
		# Оригинальная uv c отступами в нормальных и в пикселях текстуры
		self.padded_norm = None  # type: Vector # len == 4
		# self.padded_tex = None  # type: Vector # len == 4
		# packed использует промежуточные координаты во время упаковки,
		# использует нормализованные координаты после упаковки
		self.packed_norm = None  # type: Vector # len == 4
	
	def __str__(self) -> str: return _internals.common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return _internals.common_str_slots(self, self.__slots__)
	
	def is_match(self, vec2_norm: 'Vector', epsilon_x: 'float' = 0, epsilon_y: 'float' = 0):
		v = self.origin_norm
		x1, x2 = v.x - epsilon_x, v.x + v.z + epsilon_x
		y1, y2 = v.y - epsilon_y, v.y + v.w + epsilon_y
		return x1 <= vec2_norm.x <= x2 and y1 <= vec2_norm.y <= y2
	
	@staticmethod
	def _in_box(v2: 'Vector', box: 'Vector'):
		# Координаты vec2 внутри box как 0..1
		v2.x = (v2.x - box.x) / box.z
		v2.y = (v2.y - box.y) / box.w
	
	@staticmethod
	def _out_box(v2: 'Vector', box: 'Vector'):
		# Координаты 0..1 внутри box вне его
		v2.x = v2.x * box.z + box.x
		v2.y = v2.y * box.w + box.y
	
	def apply(self, vec2_norm: 'Vector') -> 'Vector':
		# Преобразование padded_norm -> packed_norm
		uv = vec2_norm.xy  # копирование
		self._in_box(uv, self.padded_norm)
		self._out_box(uv, self.packed_norm)
		return uv
	
	def iterate_corners(self) -> 'Generator[tuple[int, tuple[float, float]]]':
		# Обходу углов: #, оригинальная UV, атласная UV
		pd, pk = self.padded_norm, self.packed_norm
		yield 0, (pd.x, pd.y), (pk.x, pk.y)  # vert 0: left, bottom
		yield 1, (pd.x + pd.z, pd.y), (pk.x + pk.z, pk.y)  # vert 1: right, bottom
		yield 2, (pd.x + pd.z, pd.y + pd.w), (pk.x + pk.z, pk.y + pk.w)  # vert 2: right, up
		yield 3, (pd.x, pd.y + pd.w), (pk.x, pk.y + pk.w)  # vert 2: right, up


__all__ = ['UVTransform']

__pdoc__ = dict()
for _n in dir(UVTransform):
	if hasattr(UVTransform, _n):
		__pdoc__[UVTransform.__name__ + '.' + _n] = False
