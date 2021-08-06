# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import logging
import typing

from .commons import *
from mathutils import Vector

if typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *

log = logging.getLogger('kawa.uv')


class Island:
	# Описывает остров текстуры материала, ограничивающий подмножество UV
	# Координаты - в размерах текстур
	__slots__ = ('mn', 'mx', 'extends')
	
	def __init__(self, mn: 'Optional[Vector]', mx: 'Optional[Vector]'):
		self.mn = mn  # type: Optional[Vector]
		self.mx = mx  # type: Optional[Vector]
		self.extends = 0  # Для диагностических целей
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def is_valid(self):
		return self.mn is not None and self.mx is not None
	
	def is_inside_vec2(self, item: 'Vector', epsilon: 'float' = 0):
		if type(item) != Vector:
			raise ValueError("type(item) != Vector")
		if len(item) != 2:
			raise ValueError("len(item) != 2")
		if self.mn is None or self.mx is None:
			return False
		mnx, mny = self.mn.x - epsilon, self.mn.y - epsilon
		mxx, mxy = self.mx.x + epsilon, self.mx.y + epsilon
		return mnx <= item.x <= mxx and mny <= item.y <= mxy
	
	def is_inside_bbox(self, inner: 'Island', epsilon: 'float' = 0) -> bool:
		# Проверяет лежит ли inner внутри self
		if self.mn is None or self.mx is None or inner.mn is None or inner.mx is None:
			return False
		if inner.mx.x + epsilon >= self.mx.x or inner.mx.y + epsilon >= self.mx.y:
			return False
		if inner.mn.x - epsilon <= self.mn.x or inner.mn.y - epsilon <= self.mn.y:
			return False
		return True
	
	def get_points(self) -> 'Sequence[Vector]':
		return self.mn, self.mx, Vector((self.mn.x, self.mx.y)), Vector((self.mx.x, self.mn.y))
	
	def any_inside_vec2(self, items: 'Iterable[Vector]', epsilon: 'float' = 0):
		return any(self.is_inside_vec2(x, epsilon=epsilon) for x in items)
	
	def is_intersect(self, other: 'Island', epsilon: 'float' = 0):
		return any(self.is_inside_vec2(x, epsilon=epsilon) for x in other.get_points())
	
	def extend_by_vec2(self, vec2: 'Vector'):
		if self.mn is None:
			self.mn = vec2.xy
		else:
			self.mn.x = min(self.mn.x, vec2.x)
			self.mn.y = min(self.mn.y, vec2.y)
		if self.mx is None:
			self.mx = vec2.xy
		else:
			self.mx.x = max(self.mx.x, vec2.x)
			self.mx.y = max(self.mx.y, vec2.y)
		self.extends += 1
	
	def extend_by_vec2s(self, vec2s: 'Iterable[Vector]'):
		for vec2 in vec2s:
			self.extend_by_vec2(vec2)
	
	def extend_by_bbox(self, other: 'Island'):
		if self is other:
			raise ValueError("self is other", self, other)
		if not other.is_valid():
			raise ValueError("other bbox is not valid", self, other)
		self.extend_by_vec2s(other.get_points())
		if not self.is_valid():
			raise ValueError("Invalid after extend_by_bbox", self, other)
	
	def get_area(self) -> 'float':
		if not self.is_valid():
			raise ValueError("bbox is not valid", self)
		return (self.mx.x - self.mn.x) * (self.mx.y - self.mn.y)


class IslandsBuilder:
	# Занимается разбиением множества точек на прямоугольные непересекающиеся подмноджества
	__slots__ = ('bboxes', 'merges')
	
	def __init__(self):
		self.bboxes = list()  # type: List[Island]
		self.merges = 0  # Для диагностических целей
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def add_bbox(self, bbox: 'Island', epsilon: 'float' = 0):
		# Добавляет набор точек
		if not bbox.is_valid():
			raise ValueError("Invalid bbox!")
		
		bbox_to_add = bbox
		while bbox_to_add is not None:
			target_idx = -1
			# Поиск первго бокса с которым пересекается текущий
			for i in range(len(self.bboxes)):
				if self.bboxes[i] is bbox_to_add:
					raise ValueError("bbox already in bboxes:", (bbox_to_add, self.bboxes[i], self.bboxes))
				# TODO
				if self.bboxes[i].is_inside_bbox(bbox_to_add, epsilon=epsilon):
					return  # Если вставляемый bbox внутри существующего, то ничего не надо делать
				if self.bboxes[i].is_intersect(bbox_to_add, epsilon=epsilon):
					target_idx = i
					break
			if target_idx == -1:
				# Пересечение не найдено, добавляем
				self.bboxes.append(bbox_to_add)
				bbox_to_add = None
			else:
				# Пересечение найдено - вытаскиваем, соединяем, пытаемся добавить еще раз
				ejected = self.bboxes[target_idx]
				del self.bboxes[target_idx]
				# print("add_bbox: extending: ", (ejected, bbox_to_add))
				# print("add_bbox: merges: ", self.merges)
				# print("add_bbox: len(bboxes): ", len(self.bboxes))
				ejected.extend_by_bbox(bbox_to_add)
				bbox_to_add = ejected
				self.merges += 1
	
	def add_seq(self, vec2s: 'Iterable[Vector]', epsilon: 'float' = 0):
		vec2s = list(vec2s)
		if len(vec2s) != 0:
			newbbox = Island(None, None)
			newbbox.extend_by_vec2s(vec2s)
			# print("add_seq: add_bbox: ", newbbox)
			self.add_bbox(newbbox, epsilon=epsilon)
		else:
			print("Warn: add_seq: empty vec2s!")
	
	def get_extends(self):
		return sum(bbox.extends for bbox in self.bboxes)
