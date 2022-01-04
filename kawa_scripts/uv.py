# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
"""
Useful tools for UV Layers
"""

import bpy as _bpy
import mathutils as _mu

from . import _internals
from . import commons as _commons
from . import objects as _objects
from . import meshes as _meshes
from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Union, Optional, Iterable, Sequence, List, Callable
	from bpy.types import Object, Mesh, Material, bpy_prop_collection, MeshPolygon, MeshUVLoop
	from mathutils import Vector
	from bmesh.types import BMFace, BMLayerItem


def uv_area(poly: 'MeshPolygon', uv_layer_data: 'Union[bpy_prop_collection, List[MeshUVLoop]]'):
	""" Returns area of given polygon on given UV Layer in normalized (0..1) space (for bpy.types.Mesh). """
	# tuple чуть-чуть быстрее на малых длинах, тестил через timeit
	return _meshes.poly2_area2(list(uv_layer_data[loop].uv for loop in poly.loop_indices))


def uv_area_bmesh(bm_face: 'BMFace', bm_uv_layer: 'BMLayerItem'):
	""" Returns area of given polygon on given UV Layer in normalized (0..1) space (for besh.types.BMesh). """
	return _meshes.poly2_area2(list(bm_loop[bm_uv_layer].uv for bm_loop in bm_face.loops))


def repack_active_uv(
		obj: 'Object', get_scale: 'Optional[Callable[[Material], float]]' = None,
		rotate: 'bool' = None, margin: 'float' = 0.0, aspect_1: 'bool' = True,
):
	"""
	Repack active UV Layer of a given Object with some adjustments:
	- Runs `bpy.ops.uv.average_islands_scale`
	- Rescales islands according to `get_scale` per material
	- Runs `bpy.ops.uv.pack_islands` with given `rotate` and `margin`
	"""
	e = _commons.ensure_op_finished
	materials = None
	try:
		_objects.deselect_all()
		_objects.activate(obj)
		if aspect_1:
			# Оператор uv.pack_islands использует активную текстуру в материале как референс соотношения сторон
			# и это никак не переопределяется. Проще всего отключить материалы, тогда соотношение становится 1:1
			materials = list()
			for i in range(len(obj.material_slots)):
				slot = obj.material_slots[i]
				materials.append(slot.material)
				slot.material = None
		# Перепаковка...
		e(_bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'FACE'}), name='object.mode_set_with_submode')
		e(_bpy.ops.mesh.reveal(select=True), name='mesh.reveal')
		e(_bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
		_bpy.context.scene.tool_settings.use_uv_select_sync = True
		area_type = _bpy.context.area.type
		try:
			_bpy.context.area.type = 'IMAGE_EDITOR'
			_bpy.context.area.ui_type = 'UV'
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
				_bpy.context.scene.tool_settings.use_uv_select_sync = True
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
			_bpy.context.area.type = area_type
	finally:
		e(_bpy.ops.object.mode_set(mode='OBJECT'), name='object.mode_set')
		if materials is not None:
			for i in range(len(materials)):
				obj.material_slots[i].material = materials[i]


def remove_all_uv_layers(obj: 'Object', strict: 'Optional[bool]' = None):
	"""
	Remove all UV Layers from Mesh-Object.
	"""
	mesh = _meshes.get_mesh_safe(obj, strict=strict)
	while len(mesh.uv_layers) > 0:
		mesh.uv_layers.remove(mesh.uv_layers[0])


def _remove_uv_layer_by_condition(
		mesh: 'Mesh',
		func_should_delete: 'Callable[[str, MeshTexturePolyLayer], bool]',
		func_on_delete: 'Callable[[str, MeshTexturePolyLayer], None]'
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
	"""
	Internal class of `IslandsBuilder`.
	Describes rectangle region of UV Layer.
	"""
	__slots__ = ('mn', 'mx', 'extends')
	
	def __init__(self, mn: 'Optional[Vector]', mx: 'Optional[Vector]'):
		self.mn = mn  # type: Optional[Vector]
		self.mx = mx  # type: Optional[Vector]
		self.extends = 0  # Для диагностических целей
	
	def __str__(self) -> str: return _internals.common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return _internals.common_str_slots(self, self.__slots__)
	
	def is_valid(self):
		return self.mn is not None and self.mx is not None
	
	def is_inside_vec2(self, item: 'Vector', epsilon: 'float' = 0):
		if not isinstance(item, _mu.Vector):
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
		return self.mn, self.mx, _mu.Vector((self.mn.x, self.mx.y)), _mu.Vector((self.mx.x, self.mn.y))
	
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
	"""
	Internal class of `kawa_scripts.atlas_baker.BaseAtlasBaker`, but can be used standalone.
	Finds non-overlapping bounding boxes on UV Layer of UV polygons.
	Just provide UV coords of all your polygons into `add_seq` or `add_bbox`,
	`bboxes` will contain all found non-overlapping rectangle regions.
	
	`epsilon` is a search precision in normalized (0..1) space.
	If distance between two Islands is less than epsilon these two Islands will be merged into single one.
	Be careful with `epsilon = 0`, It can result a lots of small islands touching each others but don't intersect.
	Also very small `epsilon` can result poor performance without good output.
	`epsilon` about 1..3 of pixel-space recommended (normalize it by you self).
	"""
	# Занимается разбиением множества точек на прямоугольные непересекающиеся подмноджества
	__slots__ = ('bboxes', 'merges')
	
	def __init__(self):
		self.bboxes = list()  # type: List[Island]
		""" All found non-overlapping `Islands`. """
		self.merges = 0  # Для диагностических целей
		""" For diagnostic and debug purposes. Number of Island merges happened. """
	
	def __str__(self) -> str: return _internals.common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return _internals.common_str_slots(self, self.__slots__)
	
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
