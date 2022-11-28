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
Tool for baking a lots of PBR materials on a lots of Objects into single texture atlas.
See `kawa_scripts.atlas_baker.BaseAtlasBaker`.
"""

from sys import maxsize as _int_maxsize
from gc import collect as _gc_collect
from time import perf_counter as _perf_counter
from random import shuffle as _shuffle

import bpy as _bpy
import bmesh as _bmesh
import mathutils as _mu

from . import commons as _commons
from . import objects as _objects
from . import meshes as _meshes
from . import uv as _uv
from . import shader_nodes as _snodes
from . import reporter as _reporter
from . import _internals
from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Optional, Union, Tuple, List, Set, Dict, Generator
	from bpy.types import Object, Material, MaterialSlot, Image, Mesh, MeshUVLoop, MeshUVLoopLayer
	from bpy.types import ShaderNode, NodeSocket, NodeLink, NodeSocketColor, NodeSocketFloat
	from bmesh.types import BMesh, BMLayerItem
	from mathutils import Vector


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
	
	def iterate_corners(self) -> 'Generator[Tuple[int, Tuple[float, float]]]':
		# Обходу углов: #, оригинальная UV, атласная UV
		pd, pk = self.padded_norm, self.packed_norm
		yield 0, (pd.x, pd.y), (pk.x, pk.y)  # vert 0: left, bottom
		yield 1, (pd.x + pd.z, pd.y), (pk.x + pk.z, pk.y)  # vert 1: right, bottom
		yield 2, (pd.x + pd.z, pd.y + pd.w), (pk.x + pk.z, pk.y + pk.w)  # vert 2: right, up
		yield 3, (pd.x, pd.y + pd.w), (pk.x, pk.y + pk.w)  # vert 2: right, up


class BaseAtlasBaker:
	"""
	Base class for Atlas Baking.
	You must extend this class with required and necessary methods for your case,
	configure variables and then run `bake_atlas`.
	"""
	
	ISLAND_TYPES = ('POLYGON', 'OBJECT')
	"""
	Available types of UV-Islands Searching for reference.
	Set per-Object and per-Material, see `get_island_mode`.
	
	- `'POLYGON'` will try to use every polygon provided to find rectangular UV areas of Material.
	Allows to detect separated UV parts from same material and put it separately and more efficient on atlas.
	Slower, but can result dense and efficient packing.
	
	- `'OBJECT'` will count each Material on each Object as single united island.
	Fast, but can pick large unused areas of Materials for atlasing and final atlas may be packed inefficient.
	"""
	
	BAKE_TYPES = ('DIFFUSE', 'ALPHA', 'EMIT', 'NORMAL', 'ROUGHNESS', 'METALLIC')
	"""
	Available types of baking layers for reference.
	Note, there is no DIFFUSE+ALPHA RGBA (use separate textures) and SMOOTHNESS (use ROUGHNESS instead) yet.
	"""
	
	# Имена UV на ._bake_obj
	_UV_ORIGINAL = "UV-Original"
	_UV_ATLAS = "UV-Atlas"
	
	_PROC_ORIGINAL_UV_NAME = "__AtlasBaker_UV_Main_Original"
	_PROC_TARGET_ATLAS_UV_NAME = "__AtlasBaker_UV_Main_Target"
	_PROP_ORIGIN_OBJECT = "__AtlasBaker_OriginObject"
	_PROP_ORIGIN_MESH = "__AtlasBaker_OriginMesh"
	
	_PROC_NAME = "__AtlasBaker_Processing_"
	
	def __init__(self):
		self.objects = set()  # type: Set[Object]
		""" Mesh-Objects that will be atlassed. """
		
		self.target_size = (1, 1)  # type: Tuple[int, int]
		"""
		Size of atlas. Actually used only as aspect ratio.
		Your target images (See `get_target_image`) must match this ratio.
		"""
		
		self.padding = 4  # type: float
		""" Padding added to each UV Island around to avoid leaks. """
		
		self.report_time = 5
		""" Minimum time between progress reports into logfile when running long and heavy operations.  """
		
		# # # Внутренее # # #
		
		self._materials = dict()  # type: Dict[Tuple[Object, Material], Material]
		self._matsizes = dict()  # type: Dict[Material, Tuple[float, float]]
		self._bake_types = list()  # type: List[Tuple[str, Image]]
		# Объекты, скопированные для операций по поиску UV развёрток
		self._copies = set()  # type: Set[Object]
		# Группы объектов по материалам из ._copies
		self._groups = dict()  # type: Dict[Material, Set[Object]]
		# Острова UV найденые на материалах из ._groups
		self._islands = dict()  # type: Dict[Material, _uv.IslandsBuilder]
		# Преобразования, необходимые для получения нового UV для атласса
		self._transforms = dict()  # type: Dict[Material, List[UVTransform]]
		# Вспомогательный объект, необходимый для запекания атласа
		self._bake_obj = None  # type: Optional[Object]
		self._node_editor_override = False
		# Для _apply_baked_materials_bmesh
		# Используем общий, что бы не пересоздовать его каждый раз
		self._bmesh_loops_mem = set()  # type: Set[int]
		self._bmesh_loops_mem_hits = 0
		# Для _find_islands_obj
		# Используем общий, что бы не пересоздовать его каждый раз
		self._find_islands_vectors = list()
	
	# # # Переопределяемые методы # # #
	
	def get_material_size(self, src_mat: 'Material') -> 'Optional[Tuple[float, float]]':
		"""
		Must return size of material.
		This is relative compared with other Materials to figure out final area of Material on atlas.
		The real size of material will be different anyways.
		
		You can use `kawa_scripts.tex_size_finder.TexSizeFinder` here.
		"""
		raise NotImplementedError('get_material_size')
	
	def get_target_material(self, origin: 'Object', src_mat: 'Material') -> 'Material':
		"""
		Must return target Material for source Material.
		Ths source Material on this Object will be replaced with target Material after baking.
		Atlas Baker does not create final Materials by it's own.
		You should prepare target materials (with target images) and provide it here, so Atlas Baker can use and assign it.
		"""
		raise NotImplementedError('get_target_material')
	
	def get_target_image(self, bake_type: str) -> 'Optional[Image]':
		"""
		Must return target Image for given bake type.
		Atlas Baker will bake atlas onto this Image.
		If Image is not provided (None or False) this bake type will not be baked.
		See `BAKE_TYPES` for available bake types.
		"""
		raise NotImplementedError('get_target_image')
	
	def get_uv_name(self, obj: 'Object', mat: 'Material') -> 'Optional[str]':
		"""
		Should return the name of UV Layer of given Object and Material that will be used for baking.
		If not implemented (or returns None or False) first UV layer will be used.
		This layer will be edited to match Atlas and target Material.
		"""
		return  # TODO
	
	def get_island_mode(self, origin: 'Object', mat: 'Material') -> 'str':
		"""
		Must return one of island search types. See `ISLAND_TYPES` for details.
		"""
		return 'POLYGON'
	
	def get_epsilon(self, obj: 'Object', mat: 'Material') -> 'Optional[float]':
		"""
		Should return precision value in pixel-space for given Object and Material.
		Note, size obtained from `get_material_size` is used for pixel-space.
		"""
		return None
	
	def before_bake(self, bake_type: str, target_image: 'Image'):
		"""
		This method is called before baking given type and Image.
		Note, Image obtained from 'get_target_image' is used for `target_image`.
		You can prepare something here, for example, adjust Blender's baking settings.
		"""
		pass
	
	def after_bake(self, bake_type: str, target_image: 'Image'):
		"""
		This method is called after baking given type and Image.
		Note, Image obtained from 'get_target_image' is used for `target_image`.
		You can post-process something here, for example, save baked Image.
		"""
		pass
	
	def _get_source_object(self, copy_obj: 'Object'):
		name = copy_obj.get(self._PROP_ORIGIN_OBJECT)
		origin_obj = _bpy.data.objects.get(name)
		return origin_obj
	
	def _get_matsize_safe(self, mat: 'Material') -> 'Tuple[float, float]':
		default_size = (16, 16)
		size = None
		try:
			# TODO если размер текстуры не выявлен, нужно отрабатывать чётче
			size = self.get_material_size(mat)
			if not size:
				size = default_size
			if not isinstance(size, tuple) or len(size) != 2 or not isinstance(size[0], (int, float)) or not isinstance(size[1], (int, float)):
				_log.warning("Material {0} have invalid material size: {1}".format(mat, repr(size)))
				size = default_size
			if size[0] <= 0 or size[1] <= 0:
				_log.warning("Material {0} have invalid material size: {1}".format(mat, repr(size)))
				size = default_size
			return size
		except Exception as exc:
			msg = 'Can not get size of material {0}.'.format(mat)
			_log.error(msg)
			raise RuntimeError(msg, mat, size) from exc
	
	def _get_epsilon_safe(self, obj: 'Object', mat: 'Material'):
		epsilon = None
		try:
			epsilon = self.get_epsilon(obj, mat) or 1
			return epsilon
		except Exception as exc:
			msg = 'Can not get epsilon for {0} and {1}.'.format(obj, mat)
			_log.error(msg)
			raise RuntimeError(msg, obj, mat, epsilon) from exc
	
	def _get_uv_data_safe(self, obj: 'Object', mat: 'Material', mesh: 'Mesh'):
		uv_name = None
		try:
			uv_name = self.get_uv_name(obj, mat) or 0
			uv_data = mesh.uv_layers[uv_name].data  # type: List[MeshUVLoop]
		except Exception as exc:
			msg = 'Can not get uv_layers[{2}] data for {0} and {1}.'.format(obj, mat, uv_name)
			_log.error(msg)
			raise RuntimeError(msg, obj, mat, mesh, uv_name) from exc
		return uv_data
	
	def _get_bake_image_safe(self, bake_type: str):
		image = None
		try:
			image = self.get_target_image(bake_type)
			# ...
			return image
		except Exception as exc:
			msg = 'Can not get image for bake type {0}.'.format(bake_type)
			_log.error(msg)
			raise RuntimeError(msg, bake_type, image) from exc
	
	def _prepare_objects(self):
		objects = set()
		for obj in self.objects:
			if not isinstance(obj.data, _bpy.types.Mesh):
				_log.warning("{0} is not a valid mesh-object!".format(obj))
				continue
			objects.add(obj)
		self.objects = objects
	
	def _prepare_target_images(self):
		for bake_type in self.BAKE_TYPES:
			target_image = self._get_bake_image_safe(bake_type)
			if target_image is None or target_image is False:
				continue
			self._bake_types.append((bake_type, target_image))
	
	def _prepare_materials(self):
		for obj in self.objects:
			for slot in obj.material_slots:  # type: MaterialSlot
				if slot is None or slot.material is None:
					_log.warning("Empty material slot detected: {0}".format(obj))
					continue
				tmat = self._get_target_material_safe(obj, slot.material)
				if isinstance(tmat, _bpy.types.Material):
					self._materials[(obj, slot.material)] = tmat
		mats = set(x[1] for x in self._materials.keys())
		_log.info("Validating {0} source materials...".format(len(mats)))
		for mat in mats:
			self._check_material(mat)
		_log.info("Validated {0} source materials.".format(len(mats)))
	
	def _prepare_matsizes(self):
		mat_i = 0
		smats = set(x[1] for x in self._materials.keys())
		
		reporter = _reporter.LambdaReporter(self.report_time)
		reporter.func = lambda r, t: _log.info(
			"Preparing material sizes, Materials={0}/{1}, Time={2:.1f} sec, ETA={3:.1f} sec...".format(
				mat_i, len(smats), t, r.get_eta(1.0 * mat_i / len(smats))))
		
		for smat in smats:
			self._matsizes[smat] = self._get_matsize_safe(smat)
			mat_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)
	
	def _make_duplicates(self):
		# Делает дубликаты объектов, сохраняет в ._copies
		_log.info("Duplicating temp objects for atlasing...")
		_objects.deselect_all()
		for obj in self.objects:
			if isinstance(obj.data, _bpy.types.Mesh):
				_objects.activate(obj)
			obj[self._PROP_ORIGIN_OBJECT] = obj.name
			obj.data[self._PROP_ORIGIN_MESH] = obj.data.name
		_commons.ensure_op_finished(_bpy.ops.object.duplicate(linked=False), name='bpy.ops.object.duplicate')
		self._copies.update(_bpy.context.selected_objects)
		# Меченые имена, что бы если скрипт крашнется сразу было их видно
		for obj in self._copies:
			obj_name = obj.get(self._PROP_ORIGIN_OBJECT) or 'None'
			mesh_name = obj.data.get(self._PROP_ORIGIN_MESH) or 'None'
			obj.name = self._PROC_NAME + obj_name
			obj.data.name = self._PROC_NAME + mesh_name
		_log.info("Duplicated {0} temp objects for atlasing.".format(len(self._copies)))
		_objects.deselect_all()
	
	def _separate_duplicates(self):
		# Разбивает дупликаты по материалам
		_log.info("Separating temp objects for atlasing...")
		_objects.deselect_all()
		_objects.activate(self._copies)
		_commons.ensure_op_finished(_bpy.ops.mesh.separate(type='MATERIAL'), name='bpy.ops.mesh.separate')
		count = len(self._copies)
		self._copies.update(_bpy.context.selected_objects)
		_objects.deselect_all()
		_log.info("Separated {0} -> {1} temp objects".format(count, len(self._copies)))
	
	def _get_single_material(self, obj: 'Object') -> 'Material':
		ms_c = len(obj.material_slots)
		if ms_c != 1:  # TODO
			raise RuntimeError("ms_c != 1", obj)
		slot = obj.material_slots[0]  # type: MaterialSlot
		mat = slot.material if slot is not None else None
		if mat is None:  # TODO
			raise RuntimeError("mat is None", obj)
		return mat
	
	def _cleanup_duplicates(self):
		# Удаляет те материалы, которые не будут атлассироваться
		source_materials = list(x[1] for x in self._materials.keys())
		to_delete = set()
		for cobj in self._copies:
			sobj = self._get_source_object(cobj)
			smat = self._get_single_material(cobj)
			tmat = self._materials.get((sobj, smat))
			if tmat is None or tmat is False:
				to_delete.add(cobj)
		if len(to_delete) < 1:
			return
		_objects.deselect_all()
		for cobj in to_delete:
			cobj.hide_set(False)
			cobj.select_set(True)
		_commons.ensure_op_finished(_bpy.ops.object.delete(use_global=True, confirm=True), name='bpy.ops.object.delete')
		if len(_bpy.context.selected_objects) > 0:  # TODO
			raise RuntimeError("len(bpy.context.selected_objects) > 0", list(_bpy.context.selected_objects))
		for cobj in to_delete:
			self._copies.discard(cobj)
		_log.info("Removed {0} temp objects, left {1} objects.".format(len(to_delete), len(self._copies)))
	
	def _group_duplicates(self):
		# Группирует self._copies по материалам в self._groups
		for obj in self._copies:
			mat = self._get_single_material(obj)
			group = self._groups.get(mat)
			if group is None:
				group = set()
				self._groups[mat] = group
			group.add(obj)
		_log.info("Grouped {0} temp objects into {1} material groups.".format(len(self._copies), len(self._groups)))
	
	def _find_islands(self):
		mat_i, obj_i = 0, 0
		
		def do_report(r, t):
			islands = sum(len(x.bboxes) for x in self._islands.values())
			merges = sum(x.merges for x in self._islands.values())
			_log.info("Searching UV islands: Objects={0}/{1}, Materials={2}/{3}, Islands={4}, Merges={5}, Time={6:.1f} sec, ETA={7:.1f} sec..."
				.format(obj_i, len(self._copies), mat_i, len(self._groups), islands, merges, t, r.get_eta(1.0 * obj_i / len(self._copies))))
		
		reporter = _reporter.LambdaReporter(self.report_time)
		reporter.func = do_report
		
		_log.info("Searching islands...")
		# Поиск островов, наполнение self._islands
		for mat, group in self._groups.items():
			# log.info("Searching islands of material %s in %d objects...", mat.name, len(group))
			mat_size = self._matsizes.get(mat)
			builder = _commons.dict_get_or_add(self._islands, mat, _uv.IslandsBuilder)
			for obj in group:
				bm, mesh = None, None
				try:
					mesh = _meshes.get_safe(obj)
					bm = _bmesh.new()
					bm.from_mesh(mesh)
					self._find_islands_obj(obj, mesh, bm, mat, builder, mat_size)
					obj_i += 1
				except Exception as exc:
					msg = "Can not find islands on {0}: {1}, {2}, {3}, {4}: {5}".format(
						repr(obj), repr(mesh), repr(bm), repr(mat), repr(builder), repr(mat_size), repr(exc))
					_log.error(msg)
					raise RuntimeError(msg) from exc
				finally:
					if bm is not None:
						bm.free()
				reporter.ask_report(False)
			mat_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)
		
		# for mat, builder in self._islands.items():
		# 	log.info("\tMaterial %s have %d islands:", mat, len(builder.bboxes))
		# 	for bbox in builder.bboxes:
		# 		log.info("\t\t%s", str(bbox))
		# В процессе работы с остравами мы могли настрать много мусора,
		# можно явно от него избавиться
		_gc_collect()
		pass
	
	def _find_islands_obj(self, obj: 'Object', mesh: 'Mesh', bm: 'BMesh', mat: 'Material', builder: '_uv.IslandsBuilder',
			mat_size: 'Tuple[float,float]'):
		mat_size_x, mat_size_y = mat_size
		origin = self._get_source_object(obj)
		epsilon = self._get_epsilon_safe(origin, mat)
		
		uv_name = self.get_uv_name(origin, mat) or 0
		bm_uv_layer = bm.loops.layers.uv[uv_name]  # type: BMLayerItem
		
		bm.faces.ensure_lookup_table()
		faces = list(bm_face.index for bm_face in bm.faces)  # type: List[int]
		# Оптимизация. Сортировка от большей площади к меньшей,
		# что бы сразу сделать большие боксы и реже пере-расширять их.
		faces.sort(key=lambda index: _uv.uv_area_bmesh(bm.faces[index], bm_uv_layer), reverse=True)
		
		mode = self.get_island_mode(origin, mat)
		if mode == 'OBJECT':
			# Режим одного острова: все точки всех полигонов формируют общий bbox
			self._find_islands_vectors.clear()
			for bm_face_index in faces:
				bm_face = bm.faces[bm_face_index]
				for bm_loop in bm_face.loops:
					vec2 = bm_loop[bm_uv_layer].uv.copy()
					# Преобразование в размеры текстуры
					vec2.x *= mat_size_x
					vec2.y *= mat_size_y
					self._find_islands_vectors.append(vec2)
			builder.add_seq(self._find_islands_vectors, epsilon=epsilon)
		elif mode == 'POLYGON':
			# Режим многих островов: каждый полигон формируют свой bbox
			try:
				for bm_face_index in faces:
					bm_face = bm.faces[bm_face_index]
					self._find_islands_vectors.clear()
					for bm_loop in bm_face.loops:
						vec2 = bm_loop[bm_uv_layer].uv.copy()  # type: Vector
						# Преобразование в размеры текстуры
						vec2.x *= mat_size_x
						vec2.y *= mat_size_y
						self._find_islands_vectors.append(vec2)
					builder.add_seq(self._find_islands_vectors, epsilon=epsilon)
			except Exception as exc:
				raise RuntimeError("Error searching multiple islands!", bm_uv_layer, obj, mat, mesh, builder) from exc
		else:
			raise RuntimeError('Invalid mode', mode)
	
	def _delete_groups(self):
		count = len(self._copies)
		_log.info("Removing {0} temp objects...".format(count))
		_objects.deselect_all()
		for obj in self._copies:
			obj.hide_set(False)
			obj.select_set(True)
		_commons.ensure_op_finished(_bpy.ops.object.delete(use_global=True, confirm=True), name='bpy.ops.object.delete')
		if len(_bpy.context.selected_objects) > 0:  # TODO
			raise RuntimeError("len(bpy.context.selected_objects) > 0", list(_bpy.context.selected_objects))
		_log.info("Removed {0} temp objects.".format(count))
	
	def _create_transforms_from_islands(self):
		# Преобразует острава в боксы в формате mathutils.geometry.box_pack_2d
		for mat, builder in self._islands.items():
			for bbox in builder.bboxes:
				if not bbox.is_valid():
					raise ValueError("box is invalid: ", bbox, mat, builder, builder.bboxes)
				origin_w, origin_h = self._matsizes[mat]
				t = UVTransform()
				t.material = mat
				# две точки -> одна точка + размер
				x, w = bbox.mn.x, (bbox.mx.x - bbox.mn.x)
				y, h = bbox.mn.y, (bbox.mx.y - bbox.mn.y)
				# t.origin_tex = (x, y, w, h)
				t.origin_norm = _mu.Vector((x / origin_w, y / origin_h, w / origin_w, h / origin_h))
				# добавляем отступы
				xp, yp = x - self.padding, y - self.padding,
				wp, hp = w + 2 * self.padding, h + 2 * self.padding
				# meta.padded_tex = (xp, yp, wp, hp)
				t.padded_norm = _mu.Vector((xp / origin_w, yp / origin_h, wp / origin_w, hp / origin_h))
				# Координаты для упаковки
				# Т.к. box_pack_2d пытается запаковать в квадрат, а у нас может быть текстура любой формы,
				# то необходимо скорректировать пропорции
				xb, yb = xp / self.target_size[0], yp / self.target_size[1]
				wb, hb = wp / self.target_size[0], hp / self.target_size[1]
				t.packed_norm = _mu.Vector((xb, yb, wb, hb))
				metas = _commons.dict_get_or_add(self._transforms, mat, list)
				metas.append(t)
	
	def _pack_islands(self):
		# Несколько итераций перепаковки
		# TODO вернуть систему с раундами
		boxes = list()  # type: List[List[Union[float, UVTransform]]]
		for metas in self._transforms.values():
			for meta in metas:
				boxes.append([*meta.packed_norm, meta])
		_log.info("Packing {0} islands...".format(len(boxes)))
		best = _int_maxsize
		rounds = 15  # TODO
		while rounds > 0:
			rounds -= 1
			# Т.к. box_pack_2d псевдослучайный и может давать несколько результатов,
			# то итеративно отбираем лучшие
			_shuffle(boxes)
			pack_x, pack_y = _mu.geometry.box_pack_2d(boxes)
			score = max(pack_x, pack_y)
			_log.info("Packing round: {0}, score: {1}...".format(rounds, score))
			if score >= best:
				continue
			for box in boxes:
				box[4].packed_norm = _mu.Vector(tuple(box[i] / score for i in range(4)))
			best = score
		if best == _int_maxsize:
			raise AssertionError()
	
	def _prepare_bake_obj(self):
		_objects.deselect_all()
		mesh = _bpy.data.meshes.new("__Kawa_Bake_UV_Mesh")  # type: Mesh
		# Создаем столько полигонов, сколько трансформов
		bm = _bmesh.new()
		try:
			for transforms in self._transforms.values():
				for _ in range(len(transforms)):
					v0, v1, v2, v3 = bm.verts.new(), bm.verts.new(), bm.verts.new(), bm.verts.new()
					bm.faces.new((v0, v1, v2, v3))
				bm.to_mesh(mesh)
		finally:
			bm.free()
		# Создаем слои для преобразований
		mesh.uv_layers.new(name=self._UV_ORIGINAL)
		mesh.uv_layers.new(name=self._UV_ATLAS)
		mesh.materials.clear()
		for mat in self._transforms.keys():
			mesh.materials.append(mat)
		mat2idx = {m: i for i, m in enumerate(mesh.materials)}
		# Прописываем в полигоны координаты и материалы
		uvl_original = mesh.uv_layers[self._UV_ORIGINAL]  # type: MeshUVLoopLayer
		uvl_atlas = mesh.uv_layers[self._UV_ATLAS]  # type: MeshUVLoopLayer
		uvd_original, uvd_atlas = uvl_original.data, uvl_atlas.data
		poly_idx = 0
		for mat, transforms in self._transforms.items():
			for t in transforms:
				poly = mesh.polygons[poly_idx]
				if len(poly.loop_indices) != 4:
					raise AssertionError("len(poly.loop_indices) != 4", mesh, poly_idx, poly, len(poly.loop_indices))
				if len(poly.vertices) != 4:
					raise AssertionError("len(poly.vertices) != 4", mesh, poly_idx, poly, len(poly.vertices))
				for vert_idx, uv_a, uv_b in t.iterate_corners():
					mesh.vertices[poly.vertices[vert_idx]].co.xy = uv_b
					mesh.vertices[poly.vertices[vert_idx]].co.z = poly_idx * 1.0 / len(mesh.polygons)
					uvd_original[poly.loop_indices[vert_idx]].uv = uv_a
					uvd_atlas[poly.loop_indices[vert_idx]].uv = uv_b
				poly.material_index = mat2idx[mat]
				poly_idx += 1
		
		# Вставляем меш на сцену и активируем
		_objects.deselect_all()
		for obj in _bpy.context.scene.objects:
			obj.hide_render = True
			obj.hide_set(True)
		self._bake_obj = _bpy.data.objects.new("__Kawa_Bake_UV_Object", mesh)  # add a new object using the mesh
		_bpy.context.scene.collection.objects.link(self._bake_obj)
		# Debug purposes
		for area in _bpy.context.screen.areas:
			if area.type == 'VIEW_3D':
				for region in area.regions:
					if region.type == 'WINDOW':
						override = {'area': area, 'region': region}
						_bpy.ops.view3d.view_axis(override, type='TOP', align_active=True)
						_bpy.ops.view3d.view_selected(override, use_all_regions=False)
		self._bake_obj.hide_render = False
		self._bake_obj.show_wire = True
		self._bake_obj.show_in_front = True
		#
		_objects.activate(self._bake_obj)
	
	def _call_before_bake_safe(self, bake_type: str, target_image: 'Image'):
		try:
			self.before_bake(bake_type, target_image)
		except Exception as exc:
			msg = 'cb_before_bake failed! {0} {1}'.format(bake_type, target_image)
			_log.error(msg)
			raise RuntimeError(msg, bake_type, target_image) from exc
	
	def _call_after_bake_safe(self, bake_type: str, target_image: 'Image'):
		try:
			self.after_bake(bake_type, target_image)
		except Exception as exc:
			msg = 'cb_after_bake failed! {0} {1}'.format(bake_type, target_image)
			_log.error(msg)
			raise RuntimeError(msg, bake_type, target_image) from exc
	
	def _check_material(self, mat: 'Material'):
		node_tree, out, surface, src_shader_s, src_shader = None, None, None, None, None
		try:
			node_tree = mat.node_tree
			nodes = node_tree.nodes
			# groups = list(n for n in nodes if n.type == 'GROUP')
			# if len(groups) > 0:
			# 	# Нужно убедиться, что node editor доступен.
			# 	self._get_node_editor_override()
			out = _snodes.get_material_output(mat)
			surface = out.inputs['Surface']  # type: NodeSocket
			src_shader_link = surface.links[0] if len(surface.links) == 1 else None  # type: NodeLink
			src_shader = src_shader_link.from_node  # type: ShaderNode
			if src_shader is None:
				raise RuntimeError('no shader found')
		except Exception as exc:
			msg = "Material {0} is invalid!".format(mat.name)
			_log.info(msg)
			raise RuntimeError(msg, mat, node_tree, out, surface, src_shader_s, src_shader) from exc
	
	def _get_node_editor_override(self):
		if self._node_editor_override is not False:
			return self._node_editor_override
		self._node_editor_override = None
		for screen in _bpy.data.screens:
			for area_idx in range(len(screen.areas)):
				area = screen.areas[area_idx]
				if area.type == 'NODE_EDITOR':
					for region_idx in range(len(area.regions)):
						region = area.regions[region_idx]
						if region.type == 'WINDOW':
							self._node_editor_override = {'screen': screen, 'area': area, 'region': region}
							_log.info('Using NODE_EDITOR: screen={0} area=#{1} region=#{2}'.format(screen.name, area_idx, region_idx))
							return self._node_editor_override  # break
		if self._node_editor_override is None:
			raise RuntimeError('Can not find NODE_EDITOR')
	
	def _ungroup_nodes_for_bake(self, mat: 'Material'):
		override = None
		count = 0
		try:
			pass
		# TODO unpacking just doesnt work
		#
		# if not any(True for n in mat.node_tree.nodes if n.type == 'GROUP'):
		# 	return
		# log.info("group_ungroup begin: %s", mat.name)
		# ignore = set()
		# override = self._get_node_editor_override()
		# while True:
		# 	log.info("group_ungroup repeat: %s - %d %d", mat.name, count, len(mat.node_tree.nodes))
		# 	# Итеративное вскрытие групп
		# 	mat.node_tree.nodes.active = None
		#
		# 	groups = list()
		# 	for nidx in range(len(mat.node_tree.nodes)):
		# 		mat.node_tree.nodes[nidx].select = False
		# 		if mat.node_tree.nodes[nidx].type == 'GROUP' and mat.node_tree.nodes[nidx] not in ignore:
		# 			# mat.node_tree.nodes[nidx].select = True
		# 			# mat.node_tree.nodes.active = mat.node_tree.nodes[nidx]
		# 			groups.append(mat.node_tree.nodes[nidx])
		# 	if len(groups) == 0:
		# 		log.info("no groups in %s", mat.name)
		# 		break
		#
		# 	from .node_ungroup import ungroup_nodes
		# 	log.info("before danielenger's ungroup_nodes: %s - %s", mat.name, list(mat.node_tree.nodes))
		# 	ungroup_nodes(mat, groups)
		# 	log.info("after danielenger's ungroup_nodes: %s - %s", mat.name, list(mat.node_tree.nodes))
		#
		# 	count += 1
		# log.info("group_ungroup end: %s - %s", mat.name, count)
		except Exception as exc:
			raise RuntimeError('_ungroup_nodes_for_bake', mat, override, count, mat.node_tree.nodes.active) from exc
	
	def _edit_mat_for_bake(self, mat: 'Material', bake_type: 'str'):
		# Подключает alpha-emission шейдер на выход материала
		# Если не найден выход, DEFAULT или ALPHA, срёт ошибками
		# Здесь нет проверок на ошибки
		node_tree = mat.node_tree
		nodes = node_tree.nodes
		
		surface = _snodes.get_material_output(mat).inputs['Surface']  # type: NodeSocket
		src_shader_link = surface.links[0]  # type: NodeLink
		src_shader = src_shader_link.from_node  # type: ShaderNode
		
		def replace_shader():
			# Замещает оригинальный шейдер на Emission
			bake_shader = nodes.new('ShaderNodeEmission')  # type: ShaderNode
			bake_shader.label = '__KAWA_BAKE_SHADER'
			bake_shader.name = bake_shader.label
			if src_shader_link is not None:
				node_tree.links.remove(src_shader_link)
			node_tree.links.new(bake_shader.outputs['Emission'], surface)
			# log.info("Replacing shader %s -> %s on %s", src_shader, bake_shader, mat)
			bake_color = bake_shader.inputs['Color']  # type: NodeSocketColor
			return bake_shader, bake_color
		
		def copy_input(from_in_socket: 'NodeSocket', to_in_socket: 'NodeSocket'):
			links = from_in_socket.links
			if len(links) > 0:
				link = links[0]  # type: NodeLink
				node_tree.links.new(link.from_socket, to_in_socket)
		
		def copy_input_color(from_in_socket: 'NodeSocketColor', to_in_socket: 'NodeSocketColor'):
			to_in_socket.default_value[:] = from_in_socket.default_value[:]
			copy_input(from_in_socket, to_in_socket)
		
		def copy_input_value(from_in_socket: 'NodeSocketFloat', to_in_socket: 'NodeSocketColor'):
			v = float(from_in_socket.default_value)
			to_in_socket.default_value[:] = (v, v, v, 1.0)
			copy_input(from_in_socket, to_in_socket)
		
		if bake_type == 'ALPHA':
			bake_shader, bake_color = replace_shader()
			src_alpha = src_shader.inputs.get('Alpha')
			if src_alpha is not None:
				copy_input_value(src_alpha, bake_color)
			else:
				# По умолчанию непрозрачность
				bake_color.default_value[:] = (1, 1, 1, 1.0)
		elif bake_type == 'DIFFUSE':
			bake_shader, bake_color = replace_shader()
			src_shader_color = src_shader.inputs.get('Base Color') or src_shader.inputs.get('Color')  # type: NodeSocket
			if src_shader_color is not None:
				copy_input_color(src_shader_color, bake_color)
			else:
				# По умолчанию 75% отражаемости
				bake_color.default_value[:] = (0.75, 0.75, 0.75, 1.0)
		elif bake_type == 'METALLIC':
			bake_shader, bake_color = replace_shader()
			src_metallic = src_shader.inputs.get('Metallic')  # or src_shader.inputs.get('Specular')  # type: NodeSocket
			if src_metallic is not None:  # TODO RGB <-> value
				copy_input_value(src_metallic, bake_color)
			else:
				# По умолчанию 10% металличности
				bake_color.default_value[:] = (0.1, 0.1, 0.1, 1.0)
		elif bake_type == 'ROUGHNESS':
			bake_shader, bake_color = replace_shader()
			src_roughness = src_shader.inputs.get('Roughness')  # type: NodeSocket
			if src_roughness is not None:  # TODO RGB <-> value
				copy_input_value(src_roughness, bake_color)
			else:
				# По умолчанию 90% шершавости
				bake_color.default_value[:] = (0.9, 0.9, 0.9, 1.0)
	
	def _edit_mats_for_bake(self, bake_obj: 'Object', bake_type: 'str'):
		_objects.deselect_all()
		_objects.activate(bake_obj)
		for slot_idx in range(len(bake_obj.material_slots)):
			bake_obj.active_material_index = slot_idx
			mat = bake_obj.material_slots[slot_idx].material
			try:
				self._ungroup_nodes_for_bake(mat)
				self._edit_mat_for_bake(mat, bake_type)
			except Exception as exc:
				msg = 'Error editing material {0} (#{1}) for {2} bake object {3}' \
					.format(mat, slot_idx, bake_type, bake_obj)
				raise RuntimeError(msg, mat, slot_idx, bake_type, bake_obj) from exc
	
	def _try_edit_mats_for_bake(self, bake_obj: 'Object', bake_type: 'str'):
		try:
			self._edit_mats_for_bake(bake_obj, bake_type)
		except Exception as exc:
			raise RuntimeError("_edit_mats_for_bake", bake_obj, bake_type) from exc
	
	def _bake_image(self, bake_type: 'str', target_image: 'Image'):
		_log.info("Preparing for bake atlas Image={0} type={1} size={2}...".format(
			repr(target_image.name), bake_type, tuple(target_image.size)))
		
		# Поскольку cycles - ссанина, нам проще сделать копию ._bake_obj
		# Сделать копии материалов на ._bake_obj
		# Кастомизировать материалы, вывести всё через EMIT
		
		_objects.deselect_all()
		_objects.activate(self._bake_obj)
		_commons.ensure_op_finished(_bpy.ops.object.duplicate(linked=False), name='bpy.ops.object.duplicate')
		local_bake_obj = _bpy.context.view_layer.objects.active
		self._bake_obj.hide_set(True)
		_objects.deselect_all()
		_objects.activate(local_bake_obj)
		_commons.ensure_op_finished(_bpy.ops.object.make_single_user(
			object=True, obdata=True, material=True, animation=False,
		), name='bpy.ops.object.make_single_user')
		
		if bake_type in ('ALPHA', 'DIFFUSE', 'METALLIC', 'ROUGHNESS'):
			self._try_edit_mats_for_bake(local_bake_obj, bake_type)
		
		for slot in local_bake_obj.material_slots:  # type: MaterialSlot
			n_bake = _snodes.prepare_and_get_node_for_baking(slot.material)
			n_bake.image = target_image
		
		_bpy.context.scene.render.engine = 'CYCLES'
		_bpy.context.scene.cycles.feature_set = 'SUPPORTED'
		_bpy.context.scene.cycles.device = 'GPU'  # can be overriden in before_bake
		_bpy.context.scene.cycles.use_adaptive_sampling = True
		_bpy.context.scene.cycles.adaptive_threshold = 0
		_bpy.context.scene.cycles.adaptive_min_samples = 0
		
		emit_types = ('EMIT', 'ALPHA', 'DIFFUSE', 'METALLIC', 'ROUGHNESS')
		cycles_bake_type = 'EMIT' if bake_type in emit_types else bake_type
		_bpy.context.scene.cycles.bake_type = cycles_bake_type
		_bpy.context.scene.render.bake.use_pass_direct = False
		_bpy.context.scene.render.bake.use_pass_indirect = False
		_bpy.context.scene.render.bake.use_pass_color = False
		_bpy.context.scene.render.bake.use_pass_emit = bake_type in emit_types
		_bpy.context.scene.render.bake.normal_space = 'TANGENT'
		_bpy.context.scene.render.bake.margin = 64
		_bpy.context.scene.render.bake.use_clear = True
		_bpy.context.scene.render.use_lock_interface = True
		_bpy.context.scene.render.use_persistent_data = False
		
		self._call_before_bake_safe(bake_type, target_image)
		
		_log.info("Trying to bake atlas Image={0} type={1}/{2} size={3}...".format(
			repr(target_image.name), bake_type, cycles_bake_type, tuple(target_image.size)))
		_objects.deselect_all()
		_objects.activate(local_bake_obj)
		_gc_collect()  # Подчищаем память прямо перед печкой т.к. оно моного жрёт.
		_bpy.ops.wm.memory_statistics()
		bake_start = _perf_counter()
		_commons.ensure_op_finished(_bpy.ops.object.bake(type=cycles_bake_type, use_clear=True), name='bpy.ops.object.bake')
		bake_time = _perf_counter() - bake_start
		_bpy.ops.wm.memory_statistics()
		_log.info("Baked atlas Image={0} type={1}, time spent: {2:.1f} sec.".format(repr(target_image.name), bake_type, bake_time))
		
		garbage_materials = set(slot.material for slot in local_bake_obj.material_slots)
		mesh = local_bake_obj.data
		_bpy.context.blend_data.objects.remove(local_bake_obj, do_unlink=True)
		_bpy.context.blend_data.meshes.remove(mesh, do_unlink=True)
		for mat in garbage_materials:
			_bpy.context.blend_data.materials.remove(mat, do_unlink=True)
		if _bpy.app.version >= (2, 93, 0):
			_bpy.data.orphans_purge(do_recursive=True)
		
		self._call_after_bake_safe(bake_type, target_image)
	
	def _bake_images(self):
		_objects.deselect_all()
		_objects.activate(self._bake_obj)
		# Настраиваем UV слои под рендер
		for layer in _meshes.get_safe(self._bake_obj).uv_layers:  # type: MeshUVLoopLayer
			layer.active = layer.name == self._UV_ATLAS
			layer.active_render = layer.name == self._UV_ORIGINAL
			layer.active_clone = False
		for bake_type, target_image in self._bake_types:
			for _, image in self._bake_types:
				# Для экономии памяти выгружаем целевые картинки если они прогружены
				if image is target_image and not image.has_data:
					target_image.gl_free()
					target_image.buffers_free()
			self._bake_image(bake_type, target_image)
			# Сразу после рендера целевая картинка скорее всего не нужна
			if target_image.has_data:
				target_image.gl_free()
				target_image.buffers_free()
			_gc_collect()
		_bpy.ops.wm.memory_statistics()
		
		_objects.deselect_all()
		if self._bake_obj is not None:
			# mesh = self._bake_obj.data
			# bpy.context.blend_data.objects.remove(self._bake_obj, do_unlink=True)
			# bpy.context.blend_data.meshes.remove(mesh, do_unlink=True)
			pass
	
	def _get_target_material_safe(self, obj: 'Object', smat: 'Material'):
		tmat = None
		try:
			tmat = self.get_target_material(obj, smat)
		# ...
		except Exception as exc:
			msg = 'Can not get target material for {0} and {1}.'.format(obj, smat)
			_log.error(msg)
			raise RuntimeError(msg, smat, tmat) from exc
		return tmat
	
	def _apply_baked_materials(self):
		_log.info("Applying UV...")
		mat_i, obj_i = 0, 0
		reporter = _reporter.LambdaReporter(self.report_time)
		reporter.func = lambda r, t: _log.info(
			"Transforming UVs: Object={}/{}, Slots={}, Time={:.1f} sec, ETA={:.1f} sec...".format(
				obj_i, len(self.objects), mat_i, t, r.get_eta(1.0 * obj_i / len(self.objects))))
		
		self._perf_find_transform = 0
		self._perf_apply_transform = 0
		self._perf_iter_polys = 0
		
		for obj in self.objects:
			bm = None
			try:
				mesh = _meshes.get_safe(obj)
				bm = _bmesh.new()
				bm.from_mesh(mesh)
				self._apply_baked_materials_bmesh(obj, mesh, bm)
				bm.to_mesh(mesh)
			finally:
				if bm is not None:
					bm.free()
			obj_i += 1
			mat_i += len(obj.material_slots)
			reporter.ask_report(False)
			_meshes.merge_same_material_slots(obj)
		reporter.ask_report(True)
		_log.info("Perf: find_transform: {0}, apply_transform: {1}, iter_polys: {2}".format(
			self._perf_find_transform, self._perf_apply_transform, self._perf_iter_polys))
	
	def _apply_baked_materials_bmesh(self, obj: 'Object', mesh: 'Mesh', bm: 'BMesh'):
		# Через BMesh редактировать UV намного быстрее.
		# Прямой доступ к UV слоям через bpy.types.Mesh раза в 4 медленее.
		self._bmesh_loops_mem.clear()
		self._bmesh_loops_mem_hits = 0
		for material_index in range(len(mesh.materials)):
			source_mat = mesh.materials[material_index]
			transforms = self._transforms.get(source_mat)
			if transforms is None:
				continue  # Нет преобразований для данного материала
			# Дегенеративная геометрия вызывает проблемы, по этому нужен epsilon.
			# Зазор между боксами не менее epsilon материала, по этому возьмём половину.
			epsilon = self._get_epsilon_safe(obj, source_mat)
			src_size_x, src_size_y = self._matsizes[source_mat]
			epsilon_x, epsilon_y = epsilon / src_size_x / 2, epsilon / src_size_y / 2
			target_mat = self._materials.get((obj, source_mat))
			uv_name = self.get_uv_name(obj, source_mat) or 0
			bm_uv_layer = bm.loops.layers.uv[uv_name]  # type: BMLayerItem
			# Здесь мы, получается, обходм все фейсы по несколько раз (на каждый материал)
			# Но это лучше, чем проходить один раз, но каждый раз дёргать
			# dict.get(bm_face.material_index) и распаковывать метаданные
			_t3 = _perf_counter()
			bm.faces.ensure_lookup_table()
			for bm_face in bm.faces:
				if bm_face.material_index != material_index:
					continue
				# Среднее UV фейса. По идее можно брать любую точку для теста принадлежности,
				# но я не хочу проблем с пограничными случаями.
				# Нужно тестировать, скорее всего тут можно ускорить.
				mean_uv = _mu.Vector((0, 0))
				for bm_loop in bm_face.loops:
					mean_uv += bm_loop[bm_uv_layer].uv
				mean_uv /= len(bm_face.loops)
				transform = None
				# Поиск трансформа для данного полигона
				_t1 = _perf_counter()
				for t in transforms:
					# Должно работать без эпсилонов
					if t.is_match(mean_uv, epsilon_x=epsilon_x, epsilon_y=epsilon_y):
						transform = t
						break
				self._perf_find_transform += _perf_counter() - _t1
				if transform is None:
					# Такая ситуация не должна случаться:
					# Если материал подлежал запеканию, то все участки должны были ранее покрыты трансформами.
					msg = 'No UV transform for Obj={0}, Mesh={1}, SMat={2}, Poly={3}, UV={4}, Transforms:' \
						.format(repr(obj.name), repr(mesh.name), repr(source_mat.name), repr(bm_face), repr(mean_uv))
					_log.error(msg)
					for transform in transforms:
						_log.error('\t- {}'.format(repr(transform)))
					raise AssertionError(msg, obj, source_mat, repr(bm_face), mean_uv, transforms)
				_t2 = _perf_counter()
				for bm_loop in bm_face.loops:
					if bm_loop.index in self._bmesh_loops_mem:
						# Что бы не применить трансформ дважды к одному loop
						# Хотя как я понял в bmesh они не переиспользуются
						# Нужно изучать, возможно можно убрать self._already_processed_loops вовсе
						self._bmesh_loops_mem_hits += 1
						continue
					self._bmesh_loops_mem.add(bm_loop.index)
					vec2 = bm_loop[bm_uv_layer].uv
					vec2 = transform.apply(vec2)
					bm_loop[bm_uv_layer].uv = vec2
				self._perf_apply_transform += _perf_counter() - _t2
			self._perf_iter_polys += _perf_counter() - _t3
			# Внимание! Меняем меш, хотя потом она будет перезаписана из bmesh.
			# Но это ОК, т.к. bmesh похуй на материалы, там хранятся только индексы.
			mesh.materials[material_index] = target_mat
			obj.material_slots[material_index].material = target_mat
		if _log.is_debug():
			_log.info("BMesh loops hits for {} = {}".format(repr(obj.name), repr(self._bmesh_loops_mem_hits)))
		self._bmesh_loops_mem.clear()
	
	def bake_atlas(self):
		"""
		Run the baking process!
		"""
		_log.info("Baking atlas!")
		self._prepare_objects()
		self._prepare_target_images()
		self._prepare_materials()
		self._prepare_matsizes()
		# Создайм вспомогательные дупликаты, они нужны только для
		# поиска UV островов
		self._make_duplicates()
		# Разбивка вспомогательные дупликатов по материалам
		self._separate_duplicates()
		# Может оказаться так, что не все материалы подлежат запеканию
		# Вспомогательные дупликаты с не нужными материалами удаляются
		self._cleanup_duplicates()
		# Оставщиеся вспомогательные дупликаты группируются по материалам
		self._group_duplicates()
		# Для каждого материала выполняем поиск островов
		self._find_islands()
		# После того, как острова найдены, вспомогательные дупликаты более не нужны, удаляем их
		self._delete_groups()
		# Острава нужно разместить на атласе.
		# Для этого используется mathutils.geometry.box_pack_2d
		# Для этого нужно сконвертировать
		self._create_transforms_from_islands()
		self._pack_islands()
		# Не трогаем исходники, создаем вспомогательный меш-объект для запекания
		self._prepare_bake_obj()
		self._bake_images()
		# После запекания к исходникам применяются новые материалы и преобразования
		self._apply_baked_materials()
		_log.info("Woohoo!")


__pdoc__ = dict()
for _n in dir(UVTransform):
	if hasattr(UVTransform, _n):
		__pdoc__[UVTransform.__name__ + '.' + _n] = False
