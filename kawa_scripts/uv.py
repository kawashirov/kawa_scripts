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
from bpy import context as _C
from mathutils import Vector as _Vector

from . import commons as _commons
from ._internals import common_str_slots
from ._internals import log as _log

import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *
	from mathutils import Vector


def uv_area(poly: 'MeshPolygon', uv_layer_data: 'Union[bpy_prop_collection, List[MeshUVLoop]]'):
	# tuple чуть-чуть быстрее на малых длинах, тестил через timeit
	return _commons.poly2_area2(tuple(uv_layer_data[loop].uv for loop in poly.loop_indices))


def repack_active_uv(
		obj: 'Object', get_scale: 'Optional[Callable[[Material], float]]' = None,
		rotate: 'bool' = None, margin: 'float' = 0.0
):
	e = _commons.ensure_op_finished
	try:
		_commons.ensure_deselect_all_objects()
		_commons.activate_object(obj)
		# Перепаковка...
		e(_bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'FACE'}), name='object.mode_set_with_submode')
		e(_bpy.ops.mesh.reveal(select=True), name='mesh.reveal')
		e(_bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
		_C.scene.tool_settings.use_uv_select_sync = True
		area_type = _C.area.type
		try:
			_C.area.type = 'IMAGE_EDITOR'
			_C.area.ui_type = 'UV'
			e(_bpy.ops.uv.reveal(select=True), name='uv.reveal')
			e(_bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
			e(_bpy.ops.uv.select_all(action='SELECT'), name='uv.select_all')
			e(_bpy.ops.uv.average_islands_scale(), name='uv.average_islands_scale')
			for index in range(len(obj.material_slots)):
				scale = 1.0
				if get_scale is not None:
					scale = get_scale(obj.material_slots[index].material)
				if scale <= 0 or scale == 1.0:
					continue
				_C.scene.tool_settings.use_uv_select_sync = True
				e(_bpy.ops.mesh.select_all(action='DESELECT'), name='mesh.select_all', index=index)
				e(_bpy.ops.uv.select_all(action='DESELECT'), name='uv.select_all', index=index)
				obj.active_material_index = index
				if 'FINISHED' in _bpy.ops.object.material_slot_select():
					# Может быть не FINISHED если есть не использованые материалы
					e(_bpy.ops.uv.select_linked(), name='uv.select_linked', index=index)
					e(_bpy.ops.transform.resize(value=(scale, scale, scale)), name='transform.resize', value=scale, index=index)
			e(_bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
			e(_bpy.ops.uv.select_all(action='SELECT'), name='uv.select_all')
			e(_bpy.ops.uv.pack_islands(rotate=rotate, margin=margin), name='uv.pack_islands')
			e(_bpy.ops.uv.select_all(action='DESELECT'), name='uv.select_all')
			e(_bpy.ops.mesh.select_all(action='DESELECT'), name='mesh.select_all')
		finally:
			_C.area.type = area_type
	finally:
		e(_bpy.ops.object.mode_set(mode='OBJECT'), name='object.mode_set')


def remove_all_uv_layers(obj: 'Object'):
	mesh = _commons.get_mesh_safe(obj)
	while len(mesh.uv_layers) > 0:
		mesh.uv_layers.remove(mesh.uv_layers[0])


def _remove_uv_layer_by_condition(
		mesh: 'Mesh',
		func_should_delete: 'Callable[str, MeshTexturePolyLayer, bool]',
		func_on_delete: 'Callable[str, MeshTexturePolyLayer, None]'
):
	# TODO лагаси говно переписать
	while True:
		# Удаление таким нелепым образом, потому что после вызова remove()
		# все MeshTexturePolyLayer взятые из uv_textures становтся сломанными и крешат скрипт
		# По этому, после удаления обход начинается заново, до тех пор, пока не кончатся объекты к удалению
		# TODO Проверить баг в 2.83
		to_delete_name = None
		to_delete = None
		for uv_layer_name, uv_layer in mesh.uv_layers.items():
			if func_should_delete(uv_layer_name, uv_layer):
				to_delete_name, to_delete = uv_layer_name, uv_layer
				break
		if to_delete is None: return
		if func_on_delete is not None: func_on_delete(to_delete_name, to_delete)
		mesh.uv_layers.remove(to_delete)


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
		if type(item) != _Vector:
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
		return self.mn, self.mx, _Vector((self.mn.x, self.mx.y)), _Vector((self.mx.x, self.mn.y))
	
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
