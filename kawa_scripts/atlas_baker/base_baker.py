# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#

"""
Tool for baking a lots of PBR materials on a lots of Objects into single texture atlas.
See `kawa_scripts.atlas_baker.BaseAtlasBaker`.
"""

import gc
import sys
from random import shuffle
from time import perf_counter

import bmesh
import bpy
import mathutils
from bmesh.types import BMesh, BMLayerItem
from bpy.types import Object, Material, MaterialSlot, Image, Mesh, MeshUVLoop, MeshUVLoopLayer
from bpy.types import ShaderNode, NodeSocket, NodeLink, NodeSocketFloat, NodeSocketColor, Node
from mathutils import Vector

from .._internals import log
from .. import data
from .. import commons
from .. import meshes
from .. import objects
from .. import reporter
from .. import shader_nodes
from .. import uv

from .aov import AOV
from .uv_transform import UVTransform


class BaseAtlasBaker:
	"""
	Base class for Atlas Baking.
	You must extend this class with required and necessary methods for your case,
	configure variables and then run `bake_atlas`.
	"""
	
	ISLAND_TYPES = ('POLYGON', 'OBJECT')
	"""
	Available types of UV-Islands Searching for reference.
	set per-Object and per-Material, see `get_island_mode`.

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
		self.objects = set()  # type: set[Object]
		""" Mesh-Objects that will be atlassed. """
		
		self.target_size = (1, 1)  # type: tuple[int, int]
		"""
		Size of atlas. Actually used only as aspect ratio.
		Your target images (See `get_target_image`) must match this ratio.
		"""
		
		self.padding = 4  # type: float
		""" Padding added to each UV Island around to avoid leaks. """
		
		self.report_time = 5
		""" Minimum time between progress reports into logfile when running long and heavy operations.  """
		
		# # # Внутренее # # #
		
		self._materials = dict()  # type: dict[tuple[Object, Material], Material]
		self._matsizes = dict()  # type: dict[Material, tuple[float, float]]
		self._bake_types = list()  # type: list[tuple[str, Image]]
		self._aovs = dict()  # type: dict[str, AOV]
		# Объекты, скопированные для операций по поиску UV развёрток
		self._copies = set()  # type: set[Object]
		# Группы объектов по материалам из ._copies
		self._groups = dict()  # type: dict[Material, set[Object]]
		# Острова UV найденые на материалах из ._groups
		self._islands = dict()  # type: dict[Material, uv.IslandsBuilder]
		# Преобразования, необходимые для получения нового UV для атласса
		self._transforms = dict()  # type: dict[Material, list[UVTransform]]
		# Вспомогательный объект, необходимый для запекания атласа
		self._bake_obj = None  # type: Object|None
		self._node_editor_override = False
		# Для _apply_baked_materials_bmesh
		# Используем общий, что бы не пересоздовать его каждый раз
		self._bmesh_loops_mem = set()  # type: set[int]
		self._bmesh_loops_mem_hits = 0
		# Для _find_islands_obj
		# Используем общий, что бы не пересоздовать его каждый раз
		self._find_islands_vectors = list()
	
	# # # Переопределяемые методы # # #
	
	def get_material_size(self, src_mat: 'Material') -> 'tuple[float, float]|None':
		"""
		Must return size of material.
		This is relative compared with other Materials to figure out final area of Material on atlas.
		The real size of material will be different anyways.

		You can use `kawa_scripts.tex_size_finder.TexSizeFinder` here.
		"""
		raise NotImplementedError('get_material_size')
	
	def get_target_material(self, origin: 'Object', src_mat: 'Material') -> 'Material|None':
		"""
		Must return target Material for source Material.
		Ths source Material on this Object will be replaced with target Material after baking.
		Atlas Baker does not create final Materials by its own.
		You should prepare target materials (with target images) and provide it here, so Atlas Baker can use and assign it.
		"""
		raise NotImplementedError('get_target_material')
	
	def get_target_image(self, bake_type: str) -> 'Image|None':
		"""
		Must return target Image for a given bake type.
		Atlas Baker will bake atlas onto this Image.
		If the Image is not provided (None or False) this bake type will not be baked.
		`bake_type` maybe one of common bake types (See `BAKE_TYPES` for available bake types)
		or maybe name of some AOV (Arbitrary Output Variables).
		"""
		raise NotImplementedError('get_target_image')
	
	def get_uv_name(self, obj: 'Object', mat: 'Material') -> 'str|int|None':
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
	
	def get_epsilon(self, obj: 'Object', mat: 'Material') -> 'float|None':
		"""
		Should return precision value in pixel-space for given Object and Material.
		Note, the size obtained from `get_material_size` is used for pixel-space.
		"""
		return None
	
	def before_bake(self, bake_type: str, target_image: 'Image'):
		"""
		This method is called before baking a given type and Image.
		Note, the Image obtained from 'get_target_image' is used for `target_image`.
		You can prepare something here, for example, adjust Blender's baking settings.
		"""
		pass
	
	def after_bake(self, bake_type: str, target_image: 'Image'):
		"""
		This method is called after baking a given type and Image.
		Note, the Image obtained from 'get_target_image' is used for `target_image`.
		You can post-process something here, for example, save baked Image.
		"""
		pass
	
	def add_aov(self, _name: 'str', _type: 'str', _default: 'float|tuple[float,float,float]' = 0):
		"""
		See `AOV`.
		"""
		self._aovs[_name] = AOV(_name, _type, _default)
	
	def _get_source_object(self, copy_obj: 'Object'):
		name = copy_obj.get(self._PROP_ORIGIN_OBJECT)
		origin_obj = bpy.data.objects.get(name)
		return origin_obj
	
	def _get_matsize_safe(self, mat: 'Material') -> 'tuple[float, float]':
		default_size = (16, 16)
		size = None
		try:
			# TODO если размер текстуры не выявлен, нужно отрабатывать чётче
			size = self.get_material_size(mat)
			if not size:
				size = default_size
			if not isinstance(size, tuple) or len(size) != 2 or not isinstance(size[0], (int, float)) or not isinstance(size[1], (int, float)):
				log.warning(f"Material {mat} have invalid material size: {size!r}")
				size = default_size
			if size[0] <= 0 or size[1] <= 0:
				log.warning(f"Material {mat} have invalid material size: {size!r}")
				size = default_size
			return size
		except Exception as exc:
			msg = f'Can not get size of material {mat!r}.'
			log.error(msg)
			raise RuntimeError(msg, mat, size) from exc
	
	def _get_epsilon_safe(self, obj: 'Object', mat: 'Material'):
		epsilon = None
		try:
			epsilon = self.get_epsilon(obj, mat) or 1
			return epsilon
		except Exception as exc:
			msg = f'Can not get epsilon for {obj!r} and {mat!r}.'
			log.error(msg)
			raise RuntimeError(msg, obj, mat, epsilon) from exc
	
	def _get_uv_data_safe(self, obj: 'Object', mat: 'Material', mesh: 'Mesh'):
		uv_name = None
		try:
			uv_name = self.get_uv_name(obj, mat) or 0
			uv_data = mesh.uv_layers[uv_name].data  # type: list[MeshUVLoop]
		except Exception as exc:
			log.raise_error(RuntimeError, f'Can not get uv_layers[{uv_name!r}] data for {obj!r} and {mat!r}.', cause=exc)
		return uv_data
	
	def _get_bake_image_safe(self, bake_type: str):
		image = None
		try:
			image = self.get_target_image(bake_type)
			# ...
			return image
		except Exception as exc:
			log.raise_error(RuntimeError, f'Can not get image for bake type {bake_type!r}.', cause=exc)
	
	def _prepare_objects(self):
		objs = set()
		for obj in self.objects:
			if not meshes.is_mesh_object(obj):
				log.warning(f"{obj!r} is not a valid mesh-object!")
				continue
			objs.add(obj)
		self.objects = objs
	
	def _prepare_target_images(self):
		for bake_type in self.BAKE_TYPES:
			target_image = self._get_bake_image_safe(bake_type)
			if target_image is None or target_image is False:
				continue
			self._bake_types.append((bake_type, target_image))
		for aov_name in self._aovs.keys():
			target_image = self._get_bake_image_safe(aov_name)
			if target_image is None or target_image is False:
				continue
			self._bake_types.append((aov_name, target_image))
	
	def _prepare_materials(self):
		if len(self.objects) < 1:
			log.raise_error(RuntimeError, f"No source objects? {self.objects!r}")
		for obj in self.objects:
			for slot in obj.material_slots:  # type: MaterialSlot
				if slot is None or slot.material is None:
					log.warning(f"Empty material slot detected: {obj}")
					continue
				tmat = self._get_target_material_safe(obj, slot.material)
				if isinstance(tmat, bpy.types.Material):
					self._materials[(obj, slot.material)] = tmat
		mats = set(x[1] for x in self._materials.keys())
		log.info(f"Validating {len(mats)} source materials...")
		if len(mats) < 1:
			log.raise_error(RuntimeError, f"No source materials? {self._materials!r}")
		for mat in mats:
			self._check_material(mat)
		log.info(f"Validated {len(mats)} source materials.")
	
	def _prepare_matsizes(self):
		mat_i = 0
		smats = set(x[1] for x in self._materials.keys())
		
		if len(smats) < 1:
			log.raise_error(RuntimeError, f"No source materials? {self._materials!r}")
		
		def do_report(r, t):
			eta = r.get_eta(1.0 * mat_i / len(smats))
			log.info(f"Preparing material sizes, Materials={mat_i}/{len(smats)}, Time={t:.1f} sec, ETA={eta:.1f} sec...")
		
		lr = reporter.LambdaReporter(report_time=self.report_time, func=do_report)
		
		for smat in smats:
			self._matsizes[smat] = self._get_matsize_safe(smat)
			mat_i += 1
			lr.ask_report(False)
		lr.ask_report(True)
	
	def _make_duplicates(self):
		# Делает дубликаты объектов, сохраняет в ._copies
		log.info("Duplicating temp objects for atlasing...")
		objects.deselect_all()
		for obj in self.objects:
			if isinstance(obj.data, bpy.types.Mesh):
				objects.activate(obj)
			obj[self._PROP_ORIGIN_OBJECT] = obj.name
			obj.data[self._PROP_ORIGIN_MESH] = obj.data.name
		commons.ensure_op_finished(bpy.ops.object.duplicate(linked=False), name='bpy.ops.object.duplicate')
		self._copies.update(bpy.context.selected_objects)
		# Меченые имена, что бы если скрипт крашнется сразу было их видно
		for obj in self._copies:
			obj_name = obj.get(self._PROP_ORIGIN_OBJECT) or 'None'
			mesh_name = obj.data.get(self._PROP_ORIGIN_MESH) or 'None'
			obj.name = self._PROC_NAME + obj_name
			obj.data.name = self._PROC_NAME + mesh_name
		log.info(f"Duplicated {len(self._copies)} temp objects for atlasing.")
		objects.deselect_all()
	
	def _separate_duplicates(self):
		# Разбивает дупликаты по материалам
		log.info("Separating temp objects for atlasing...")
		objects.deselect_all()
		objects.activate(self._copies)
		commons.ensure_op_finished(bpy.ops.mesh.separate(type='MATERIAL'), name='bpy.ops.mesh.separate')
		count = len(self._copies)
		self._copies.update(bpy.context.selected_objects)
		objects.deselect_all()
		log.info(f"Separated {count} -> {len(self._copies)} temp objects")
	
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
		objects.deselect_all()
		for cobj in to_delete:
			cobj.hide_set(False)
			cobj.select_set(True)
		commons.ensure_op_finished(bpy.ops.object.delete(use_global=True, confirm=True), name='bpy.ops.object.delete')
		if len(bpy.context.selected_objects) > 0:  # TODO
			raise RuntimeError("len(bpy.context.selected_objects) > 0", list(bpy.context.selected_objects))
		for cobj in to_delete:
			self._copies.discard(cobj)
		log.info(f"Removed {len(to_delete)} temp objects, left {len(self._copies)} objects.")
	
	def _group_duplicates(self):
		# Группирует self._copies по материалам в self._groups
		for obj in self._copies:
			mat = self._get_single_material(obj)
			group = self._groups.get(mat)
			if group is None:
				group = set()
				self._groups[mat] = group
			group.add(obj)
		log.info(f"Grouped {len(self._copies)} temp objects into {len(self._groups)} material groups.")
	
	def _find_islands(self):
		mat_i, obj_i = 0, 0
		
		def do_report(r, t):
			islands = f'Islands={sum(len(x.bboxes) for x in self._islands.values())}'
			merges = f'Merges={sum(x.merges for x in self._islands.values())}'
			eta = r.get_eta(1.0 * obj_i / len(self._copies))
			objs = f'Objects={obj_i}/{len(self._copies)}'
			mats = f'Materials={mat_i}/{len(self._groups)}'
			log.info(f"Searching UV islands: {objs}, {mats}, {islands}, {merges}, Time={t:.1f} sec, ETA={eta:.1f} sec...")
		
		lr = reporter.LambdaReporter(report_time=self.report_time, func=do_report)
		log.info("Searching islands...")
		# Поиск островов, наполнение self._islands
		for mat, group in self._groups.items():
			# log.info("Searching islands of material %s in %d objects...", mat.name, len(group))
			mat_size = self._matsizes.get(mat)
			builder = commons.dict_get_or_add(self._islands, mat, uv.IslandsBuilder)
			for obj in group:
				bm, mesh = None, None
				try:
					mesh = meshes.get_safe(obj)
					bm = bmesh.new()
					bm.from_mesh(mesh)
					self._find_islands_obj(obj, mesh, bm, mat, builder, mat_size)
					obj_i += 1
				except Exception as exc:
					msg = f"Can not find islands on {obj!r}: {mesh!r}, {bm!r}, {mat!r}, {builder!r}: {mat_size!r}"
					log.raise_error(RuntimeError, msg, cause=exc)
				finally:
					if bm is not None:
						bm.free()
				lr.ask_report(False)
			mat_i += 1
			lr.ask_report(False)
		lr.ask_report(True)
		
		# for mat, builder in self._islands.items():
		# 	log.info("\tMaterial %s have %d islands:", mat, len(builder.bboxes))
		# 	for bbox in builder.bboxes:
		# 		log.info("\t\t%s", str(bbox))
		# В процессе работы с остравами мы могли настрать много мусора,
		# можно явно от него избавиться
		gc.collect()
		pass
	
	def _find_islands_obj(self, obj: 'Object', mesh: 'Mesh', bm: 'BMesh', mat: 'Material', builder: '_uv.IslandsBuilder',
			mat_size: 'tuple[float,float]'):
		mat_size_x, mat_size_y = mat_size
		origin = self._get_source_object(obj)
		epsilon = self._get_epsilon_safe(origin, mat)
		
		uv_name = self.get_uv_name(origin, mat) or 0
		bm_uv_layer = bm.loops.layers.uv[uv_name]  # type: BMLayerItem
		
		bm.faces.ensure_lookup_table()
		faces = list(bm_face.index for bm_face in bm.faces)  # type: list[int]
		# Оптимизация. Сортировка от большей площади к меньшей,
		# что бы сразу сделать большие боксы и реже пере-расширять их.
		faces.sort(key=lambda index: uv.uv_area_bmesh(bm.faces[index], bm_uv_layer), reverse=True)
		
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
		log.info(f"Removing {count} temp objects...")
		objects.deselect_all()
		for obj in self._copies:
			obj.hide_set(False)
			obj.select_set(True)
		commons.ensure_op_finished(bpy.ops.object.delete(use_global=True, confirm=True), name='bpy.ops.object.delete')
		if len(bpy.context.selected_objects) > 0:  # TODO
			raise RuntimeError("len(bpy.context.selected_objects) > 0", list(bpy.context.selected_objects))
		log.info(f"Removed {count} temp objects.")
	
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
				t.origin_norm = Vector((x / origin_w, y / origin_h, w / origin_w, h / origin_h))
				# добавляем отступы
				xp, yp = x - self.padding, y - self.padding,
				wp, hp = w + 2 * self.padding, h + 2 * self.padding
				# meta.padded_tex = (xp, yp, wp, hp)
				t.padded_norm = Vector((xp / origin_w, yp / origin_h, wp / origin_w, hp / origin_h))
				# Координаты для упаковки
				# Т.к. box_pack_2d пытается запаковать в квадрат, а у нас может быть текстура любой формы,
				# то необходимо скорректировать пропорции
				xb, yb = xp / self.target_size[0], yp / self.target_size[1]
				wb, hb = wp / self.target_size[0], hp / self.target_size[1]
				t.packed_norm = Vector((xb, yb, wb, hb))
				metas = commons.dict_get_or_add(self._transforms, mat, list)
				metas.append(t)
	
	def _pack_islands(self):
		# Несколько итераций перепаковки
		# TODO вернуть систему с раундами
		boxes = list()  # type: list[list[float|UVTransform]]
		for metas in self._transforms.values():
			for meta in metas:
				boxes.append([*meta.packed_norm, meta])
		log.info(f"Packing {len(boxes)} islands...")
		best = sys.maxsize
		rounds = 15  # TODO
		while rounds > 0:
			rounds -= 1
			# Т.к. box_pack_2d псевдослучайный и может давать несколько результатов,
			# то итеративно отбираем лучшие
			shuffle(boxes)
			pack_x, pack_y = mathutils.geometry.box_pack_2d(boxes)
			score = max(pack_x, pack_y)
			log.info(f"Packing round: {rounds}, score: {score}...")
			if score >= best:
				continue
			for box in boxes:
				box[4].packed_norm = Vector(tuple(box[i] / score for i in range(4)))
			best = score
		if best == sys.maxsize:
			raise AssertionError()
	
	def _prepare_bake_obj(self):
		objects.deselect_all()
		mesh = bpy.data.meshes.new("__Kawa_Bake_UV_Mesh")  # type: Mesh
		# Создаем столько полигонов, сколько трансформов
		bm = bmesh.new()
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
		objects.deselect_all()
		for obj in bpy.context.scene.objects:
			obj.hide_render = True
			obj.hide_set(True)
		self._bake_obj = bpy.data.objects.new("__Kawa_Bake_UV_Object", mesh)  # add a new object using the mesh
		bpy.context.scene.collection.objects.link(self._bake_obj)
		# Debug purposes
		for area in bpy.context.screen.areas:
			if area.type == 'VIEW_3D':
				for region in area.regions:
					if region.type == 'WINDOW':
						override = {'area': area, 'region': region}
						bpy.ops.view3d.view_axis(override, type='TOP', align_active=True)
						bpy.ops.view3d.view_selected(override, use_all_regions=False)
		self._bake_obj.hide_render = False
		self._bake_obj.show_wire = True
		self._bake_obj.show_in_front = True
		#
		objects.activate(self._bake_obj)
	
	def _call_before_bake_safe(self, bake_type: str, target_image: 'Image'):
		try:
			self.before_bake(bake_type, target_image)
		except Exception as exc:
			log.raise_error(RuntimeError, f'before_bake failed! {bake_type!r} {target_image!r}', cause=exc)
	
	def _call_after_bake_safe(self, bake_type: str, target_image: 'Image'):
		try:
			self.after_bake(bake_type, target_image)
		except Exception as exc:
			log.raise_error(RuntimeError, f'after_bake failed! {bake_type} {target_image}', cause=exc)
	
	def _check_material(self, mat: 'Material'):
		node_tree, out, surface, src_shader_s, src_shader = None, None, None, None, None
		try:
			node_tree = mat.node_tree
			nodes = node_tree.nodes
			# groups = list(n for n in nodes if n.type == 'GROUP')
			# if len(groups) > 0:
			# 	# Нужно убедиться, что node editor доступен.
			# 	self._get_node_editor_override()
			surface_link = shader_nodes.get_link_surface(mat)
			src_shader = surface_link.from_node  # type: Node|ShaderNode|None
			if src_shader is None:
				# TODO deeper check
				raise RuntimeError(f"No main shader found in material {mat.name!r}")
			
			for aov_name, aov in self._aovs.items():
				aov_socket = shader_nodes.get_socket_aov(mat, aov_name, aov.type)
				# TODO deeper check
				pass
		
		except Exception as exc:
			log.raise_error(RuntimeError, f"Material {mat.name!r} is invalid!", cause=exc)
	
	def _get_node_editor_override(self):
		if self._node_editor_override is not False:
			return self._node_editor_override
		self._node_editor_override = None
		for screen in bpy.data.screens:
			for area_idx in range(len(screen.areas)):
				area = screen.areas[area_idx]
				if area.type == 'NODE_EDITOR':
					for region_idx in range(len(area.regions)):
						region = area.regions[region_idx]
						if region.type == 'WINDOW':
							self._node_editor_override = {'screen': screen, 'area': area, 'region': region}
							log.info(f'Using NODE_EDITOR: screen={screen.name} area=#{area_idx} region=#{region_idx}')
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
	
	def _edit_mat_replace_shader(self, mat: 'Material'):
		# Замещает оригинальный шейдер на Emission
		# Возвращает: оригинальный шейдер, новый шейдер, сокет нового шейдера, в который подрубать выводы для рендера
		
		link_surface = shader_nodes.get_link_surface(mat, target='CYCLES')
		src_shader = link_surface.from_node
		
		bake_shader = mat.node_tree.nodes.new('ShaderNodeEmission')  # type: ShaderNode|Node
		bake_shader.label = '__KAWA_BAKE_SHADER'
		bake_shader.name = bake_shader.label
		bake_color = bake_shader.inputs['Color']  # type: NodeSocket|NodeSocketColor
		
		# mat.node_tree.links.remove(link_surface)
		mat.node_tree.links.new(bake_shader.outputs['Emission'], link_surface.to_socket)
		
		return src_shader, bake_shader, bake_color
	
	def _edit_mat_for_aov(self, mat: 'Material', aov: 'AOV|None'):
		_, bake_shader, bake_color = self._edit_mat_replace_shader(mat)
		aov_socket = shader_nodes.get_socket_aov(mat, aov.name, aov.type)
		
		if aov_socket is None:
			# Если AOV сокет не найден, то просто создаем новую ноду с нужными дэфолтами.
			bake_color.default_value[:] = aov.default_rgba
			return
		
		if aov_socket.is_linked:
			# Если AOV сокет есть, то нужно проверить подключение
			mat.node_tree.links.new(aov_socket.links[0].from_socket, bake_color)
		elif aov.is_value:
			for i in range(3):
				bake_color.default_value[i] = float(aov_socket.default_value)
			bake_color.default_value[3] = 1.0
		elif aov.is_color:
			bake_color.default_value = aov_socket.default_value
			bake_color.default_value[3] = 1.0
	
	def _edit_mat_for_bake(self, mat: 'Material', bake_type: 'str'):
		# Подключает alpha-emission шейдер на выход материала
		# Если не найден выход, DEFAULT или ALPHA, срёт ошибками
		# Здесь нет проверок на ошибки
		node_tree = mat.node_tree
		nodes = node_tree.nodes
		
		if bake_type == 'ALPHA':
			src_shader, bake_shader, bake_color = self._edit_mat_replace_shader(mat)
			src_alpha = src_shader.inputs.get('Alpha')
			if src_alpha is not None:
				shader_nodes.socket_copy_input(src_alpha, bake_color)
			else:
				# По умолчанию непрозрачность
				bake_color.default_value[:] = (1, 1, 1, 1.0)
		elif bake_type == 'DIFFUSE':
			src_shader, bake_shader, bake_color = self._edit_mat_replace_shader(mat)
			src_shader_color = src_shader.inputs.get('Base Color') or src_shader.inputs.get('Color')  # type: NodeSocket
			if src_shader_color is not None:
				shader_nodes.socket_copy_input(src_shader_color, bake_color)
			else:
				# По умолчанию 75% отражаемости
				bake_color.default_value[:] = (0.75, 0.75, 0.75, 1.0)
		elif bake_type == 'METALLIC':
			src_shader, bake_shader, bake_color = self._edit_mat_replace_shader(mat)
			src_metallic = src_shader.inputs.get('Metallic')  # or src_shader.inputs.get('Specular')  # type: NodeSocket
			if src_metallic is not None:  # TODO RGB <-> value
				shader_nodes.socket_copy_input(src_metallic, bake_color)
			else:
				# По умолчанию 10% металличности
				bake_color.default_value[:] = (0.1, 0.1, 0.1, 1.0)
		elif bake_type == 'ROUGHNESS':
			src_shader, bake_shader, bake_color = self._edit_mat_replace_shader(mat)
			src_roughness = src_shader.inputs.get('Roughness')  # type: NodeSocket
			if src_roughness is not None:  # TODO RGB <-> value
				shader_nodes.socket_copy_input(src_roughness, bake_color)
			else:
				# По умолчанию 90% шершавости
				bake_color.default_value[:] = (0.9, 0.9, 0.9, 1.0)
		elif bake_type == 'NORMAL':
			# Normal baked as-is in its own NORMAL pass,
			# but need to turn off Alpha to avoid gray zones on final render.
			src_shader = shader_nodes.get_link_surface(mat, target='CYCLES').from_node
			src_alpha = src_shader.inputs.get('Alpha')  # type: NodeSocket|NodeSocketFloat
			if src_alpha:
				src_alpha.default_value = 1.0
				for link in src_alpha.links:  # type: NodeLink
					# log.info(f"Removing alpha link from {link.from_node!r} to {link.to_node!r} in {mat!r} for NORMAL pass.")
					node_tree.links.remove(link)
		else:
			pass
	
	def _edit_mats_for_bake(self, bake_obj: 'Object', bake_type: 'str', aov: 'AOV|None'):
		objects.deselect_all()
		objects.activate(bake_obj)
		for slot_idx in range(len(bake_obj.material_slots)):
			bake_obj.active_material_index = slot_idx
			mat = bake_obj.material_slots[slot_idx].material
			try:
				self._ungroup_nodes_for_bake(mat)
				if aov is not None:
					self._edit_mat_for_aov(mat, aov)
				else:
					self._edit_mat_for_bake(mat, bake_type)
			except Exception as exc:
				msg = f'Error editing {mat=!r} ({slot_idx=!r}) for {bake_type=!r} {aov=!r} {bake_obj=!r}: {exc}'
				log.raise_error(RuntimeError, msg, cause=exc)
	
	def _try_edit_mats_for_bake(self, bake_obj: 'Object', bake_type: 'str', aov: 'AOV|None'):
		try:
			self._edit_mats_for_bake(bake_obj, bake_type, aov)
		except Exception as exc:
			msg = f'Error editing materials for {bake_type} bake object {bake_obj}'
			log.raise_error(RuntimeError, msg, cause=exc)
	
	def _bake_image(self, bake_type: 'str', target_image: 'Image'):
		aov = self._aovs.get(bake_type)
		target_size = tuple(target_image.size)
		log.info(f"Preparing for bake atlas Image={target_image.name!r} type={bake_type!r} aov={aov!r} size={target_size}...")
		
		# Поскольку cycles - ссанина, нам проще сделать копию ._bake_obj
		# Сделать копии материалов на ._bake_obj
		# Кастомизировать материалы, вывести всё через EMIT
		
		emit_types = ('EMIT', 'ALPHA', 'DIFFUSE', 'METALLIC', 'ROUGHNESS')
		use_emit = (aov is not None) or (bake_type in emit_types)
		cycles_bake_type = 'EMIT' if use_emit else bake_type
		
		objects.deselect_all()
		objects.activate(self._bake_obj)
		commons.ensure_op_finished(bpy.ops.object.duplicate(linked=False), name='bpy.ops.object.duplicate')
		local_bake_obj = bpy.context.view_layer.objects.active
		self._bake_obj.hide_set(True)
		objects.deselect_all()
		objects.activate(local_bake_obj)
		commons.ensure_op_finished(bpy.ops.object.make_single_user(
			object=True, obdata=True, material=True, animation=False,
		), name='bpy.ops.object.make_single_user')
		
		self._try_edit_mats_for_bake(local_bake_obj, bake_type, aov)
		
		for slot in local_bake_obj.material_slots:  # type: MaterialSlot
			n_bake = shader_nodes.prepare_node_for_baking(slot.material)
			n_bake.image = target_image
		
		bpy.context.scene.render.engine = 'CYCLES'
		bpy.context.scene.cycles.feature_set = 'SUPPORTED'
		bpy.context.scene.cycles.device = 'GPU'  # can be overriden in before_bake
		bpy.context.scene.cycles.use_adaptive_sampling = True
		bpy.context.scene.cycles.adaptive_threshold = 0
		bpy.context.scene.cycles.adaptive_min_samples = 0
		bpy.context.scene.cycles.bake_type = cycles_bake_type
		bpy.context.scene.render.bake.use_pass_direct = False
		bpy.context.scene.render.bake.use_pass_indirect = False
		bpy.context.scene.render.bake.use_pass_color = False
		bpy.context.scene.render.bake.use_pass_emit = use_emit
		bpy.context.scene.render.bake.normal_space = 'TANGENT'
		bpy.context.scene.render.bake.margin = 64
		bpy.context.scene.render.bake.use_clear = True
		bpy.context.scene.render.use_lock_interface = True
		bpy.context.scene.render.use_persistent_data = False
		
		self._call_before_bake_safe(bake_type, target_image)
		
		log.info(f"Trying to bake atlas Image={target_image.name!r} type={bake_type!r}/{cycles_bake_type!r} aov={aov!r} size={target_size}...")
		objects.deselect_all()
		objects.activate(local_bake_obj)
		gc.collect()  # Подчищаем память прямо перед печкой т.к. оно моного жрёт.
		bpy.ops.wm.memory_statistics()
		bake_start = perf_counter()
		commons.ensure_op_finished(bpy.ops.object.bake(type=cycles_bake_type, use_clear=True), name='bpy.ops.object.bake')
		bake_time = perf_counter() - bake_start
		bpy.ops.wm.memory_statistics()
		log.info(f"Baked atlas Image={target_image.name!r} type={bake_type!r} aov={aov!r}, time spent: {bake_time:.1f} sec.")
		
		garbage_materials = set(slot.material for slot in local_bake_obj.material_slots)
		mesh = meshes.get_safe(local_bake_obj, strict=True)
		bpy.context.blend_data.objects.remove(local_bake_obj, do_unlink=True)
		bpy.context.blend_data.meshes.remove(mesh, do_unlink=True)
		for mat in garbage_materials:
			bpy.context.blend_data.materials.remove(mat, do_unlink=True)
		data.orphans_purge_iter()
		
		self._call_after_bake_safe(bake_type, target_image)
	
	def _bake_images(self):
		objects.deselect_all()
		objects.activate(self._bake_obj)
		# Настраиваем UV слои под рендер
		for layer in meshes.get_safe(self._bake_obj).uv_layers:  # type: MeshUVLoopLayer
			layer.active = layer.name == self._UV_ATLAS
			layer.active_render = layer.name == self._UV_ORIGINAL
			layer.active_clone = False
		for bake_type, target_image in self._bake_types:
			for _, other_image in self._bake_types:
				# Для экономии памяти выгружаем целевые картинки если они прогружены
				if other_image is not target_image and other_image.has_data:
					target_image.gl_free()
					target_image.buffers_free()
			self._bake_image(bake_type, target_image)
			# Сразу после рендера целевая картинка скорее всего не нужна
			if target_image.has_data:
				target_image.gl_free()
				target_image.buffers_free()
			gc.collect()
		bpy.ops.wm.memory_statistics()
		
		objects.deselect_all()
		if self._bake_obj is not None:
			# mesh = self._bake_obj.data
			# bpy.context.blend_data.objects.remove(self._bake_obj, do_unlink=True)
			# bpy.context.blend_data.meshes.remove(mesh, do_unlink=True)
			pass
	
	def _get_target_material_safe(self, obj: 'Object', smat: 'Material'):
		tmat = None
		try:
			tmat = self.get_target_material(obj, smat)
			if tmat is not None and not isinstance(tmat, Material):
				raise TypeError(f"{type(tmat)} {tmat!r}")
		except Exception as exc:
			log.raise_error(RuntimeError, f'Can not get target material for {obj} and {smat}.', cause=exc)
		return tmat
	
	def _apply_baked_materials(self):
		log.info("Applying UV...")
		mat_i, obj_i = 0, 0
		
		def do_report(r, t):
			eta = r.get_eta(1.0 * obj_i / len(self.objects))
			log.info(f"Transforming UVs: Object={obj_i}/{len(self.objects)}, Slots={mat_i}, Time={t:.1f} sec, ETA={eta:.1f} sec...")
		
		lr = reporter.LambdaReporter(report_time=self.report_time, func=do_report)
		
		self._perf_find_transform = 0
		self._perf_apply_transform = 0
		self._perf_iter_polys = 0
		
		for obj in self.objects:
			bm = None
			try:
				mesh = meshes.get_safe(obj)
				bm = bmesh.new()
				bm.from_mesh(mesh)
				self._apply_baked_materials_bmesh(obj, mesh, bm)
				bm.to_mesh(mesh)
			finally:
				if bm is not None:
					bm.free()
			obj_i += 1
			mat_i += len(obj.material_slots)
			lr.ask_report(False)
			meshes.merge_same_material_slots(obj)
		lr.ask_report(True)
		log.info(
			f'Perf: find_transform: {self._perf_find_transform} '
			f'apply_transform: {self._perf_apply_transform} iter_polys: {self._perf_iter_polys}'
		)
	
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
			_t3 = perf_counter()
			bm.faces.ensure_lookup_table()
			for bm_face in bm.faces:
				if bm_face.material_index != material_index:
					continue
				# Среднее UV фейса. По идее можно брать любую точку для теста принадлежности,
				# но я не хочу проблем с пограничными случаями.
				# Нужно тестировать, скорее всего тут можно ускорить.
				mean_uv = Vector((0, 0))
				for bm_loop in bm_face.loops:
					mean_uv += bm_loop[bm_uv_layer].uv
				mean_uv /= len(bm_face.loops)
				transform = None
				# Поиск трансформа для данного полигона
				_t1 = perf_counter()
				for t in transforms:
					# Должно работать без эпсилонов
					if t.is_match(mean_uv, epsilon_x=epsilon_x, epsilon_y=epsilon_y):
						transform = t
						break
				self._perf_find_transform += perf_counter() - _t1
				if transform is None:
					# Такая ситуация не должна случаться:
					# Если материал подлежал запеканию, то все участки должны были ранее покрыты трансформами.
					msg = f'No UV transform for Obj={obj.name!r}, Mesh={mesh.name!r}, SMat={source_mat.name!r}, Poly={bm_face!r}, UV={mean_uv!r}, Transforms:'
					log.error(msg)
					for transform in transforms:
						log.error(f'\t- {transform !r}')
					raise AssertionError(msg, obj, source_mat, repr(bm_face), mean_uv, transforms)
				_t2 = perf_counter()
				for bm_loop in bm_face.loops:
					if bm_loop.index in self._bmesh_loops_mem:
						# Что бы не применить трансформ дважды к одному loop.
						# Хотя как я понял в bmesh они не пере-используются
						# Нужно изучать, возможно можно убрать self._already_processed_loops вовсе
						self._bmesh_loops_mem_hits += 1
						continue
					self._bmesh_loops_mem.add(bm_loop.index)
					vec2 = bm_loop[bm_uv_layer].uv
					vec2 = transform.apply(vec2)
					bm_loop[bm_uv_layer].uv = vec2
				self._perf_apply_transform += perf_counter() - _t2
			self._perf_iter_polys += perf_counter() - _t3
			# Внимание! Меняем меш, хотя потом она будет перезаписана из bmesh.
			# Но это ОК, т.к. bmesh похуй на материалы, там хранятся только индексы.
			mesh.materials[material_index] = target_mat
			obj.material_slots[material_index].material = target_mat
		if log.is_debug():
			log.info(f"BMesh loops hits for {obj.name!r} = {self._bmesh_loops_mem_hits!r}")
		self._bmesh_loops_mem.clear()
	
	def bake_atlas(self):
		"""
		Run the baking process!
		"""
		log.info("Baking atlas!")
		self._prepare_objects()
		self._prepare_target_images()
		self._prepare_materials()
		self._prepare_matsizes()
		# Создай м вспомогательные дубликаты, они нужны только для
		# поиска UV островов
		self._make_duplicates()
		# Разбивка вспомогательных дубликатов по материалам
		self._separate_duplicates()
		# Может оказаться так, что не все материалы подлежат запеканию
		# Вспомогательные дубликаты с не нужными материалами удаляются
		self._cleanup_duplicates()
		# Остающиеся вспомогательные дубликаты группируются по материалам
		self._group_duplicates()
		# Для каждого материала выполняем поиск островов
		self._find_islands()
		# После того как острова найдены, вспомогательные дубликаты более не нужны, удаляем их
		self._delete_groups()
		# Острова нужно разместить на атласе.
		# Для этого используется mathutils.geometry.box_pack_2d
		# Для этого нужно сконвертировать
		self._create_transforms_from_islands()
		self._pack_islands()
		# Не трогаем исходники, создаем вспомогательный меш-объект для запекания
		self._prepare_bake_obj()
		self._bake_images()
		# После запекания к исходникам применяются новые материалы и преобразования
		self._apply_baked_materials()
		log.info("Woohoo!")


__all__ = ['BaseAtlasBaker']
