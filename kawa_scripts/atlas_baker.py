# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

import time
import random
import logging
import typing

import bpy
import bmesh

from mathutils import Vector
from mathutils.geometry import box_pack_2d

from .commons import ensure_deselect_all_objects, ensure_op_finished, activate_object, \
	merge_same_material_slots, get_mesh_safe, find_tex_size, Reporter
from .uv import UVBoxTransform, IslandsBuilder, uv_area
from .shader_nodes import get_material_output, prepare_and_get_node_for_baking, get_node_input_safe

if typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *
	
log = logging.getLogger('kawa.bake')


class BaseAtlasBaker:
	# Тип поиска островов, из чего делаются bboxы:
	# - POLYGON - из каждого полигона
	# - OBJECT - из кусков объектов
	# Возможны доп. режимы в будущем
	ISLAND_TYPES = {'POLYGON', 'OBJECT'}
	
	BAKE_TYPES = {'DIFFUSE', 'EMIT', 'NORMAL', 'ALPHA'}
	
	# Имена UV на ._bake_obj
	UV_ORIGINAL = "UV-Original"
	UV_ATLAS = "UV-Atlas"
	
	PROC_ORIGINAL_UV_NAME = "__AtlasBaker_UV_Main_Original"
	PROC_TARGET_ATLAS_UV_NAME = "__AtlasBaker_UV_Main_Target"
	PROP_ORIGIN_OBJECT = "__AtlasBaker_OriginObject"
	PROP_ORIGIN_MESH = "__AtlasBaker_OriginMesh"
	
	PROC_NAME = "__AtlasBaker_Processing_"
	
	def __init__(self):
		# Меш-объекты, над которыми будет работа по атлассированию
		self.objects = set()  # type: Set[Object]
		# Размер атласа.
		# На самом деле, используется только как aspect_ratio
		self.target_size = (1, 1)  # type: Tuple[int, int]
		self.padding = 4  # type: float
		
		# Минимальное время между строками логов когда выполняются долгие операции
		self.report_time = 5
		
		# # # Внутренее # # #
		
		self._materials = dict()  # type: Dict[Tuple[Object, Material], Material]
		self._matsizes = dict()  # type: Dict[Material, Tuple[float, float]]
		self._bake_types = dict()  # type: Dict[str, Image]
		# Объекты, скопированные для операций по поиску UV развёрток
		self._copies = set()  # type: Set[Object]
		# Группы объектов по материалам из ._copies
		self._groups = dict()  # type: Dict[Material, Set[Object]]
		# Острова UV найденые на материалах из ._groups
		self._islands = dict()  # type: Dict[Material, IslandsBuilder]
		# Острова UV, сконвертированые в формат, который понимает mathutils
		self._mathutils_boxes = list()  # type: List[List[Union[float, Material]]]
		# Преобразования, необходимые для получения нового UV для атласса
		self._transforms = dict()  # type: Dict[Material, List[UVBoxTransform]]
		# Вспомогательный объект, необходимый для запекания атласа
		self._bake_obj = None  # type: Optional[Object]
		self._node_editor_override = False
		
	# # # Переопределяемые методы # # #
	
	def get_material_size(self, src_mat: 'Material') -> 'Optional[Tuple[float, float]]':
		# Функция, которая будет возвращать средний размер тестур материала.
		# Используется для определения размера текстуры на атласе
		# Если не задано или возвращает None, то осуществляется попытка автоопределить размер
		return None
	
	def get_target_material(self, origin: 'Object', src_mat: 'Material') -> 'Material':
		# Функция, которая будет говоорить, на какой материал следует заменить исходный материал,
		# при применении атлассированных материалов
		# Атлассированный материал должен существовать заранее.
		raise NotImplementedError('get_target_material')
		
	def get_target_image(self, bake_type: str) -> 'Optional[Image]':
		# Функция, которая будет возвращать текстуру, на которую будет осуществляться запекание.
		# Для каждого типа из SUPPORTED_TYPES должна вернуть (изображение, путь сохранения).
		# Если текстуры нет, то запекания для данного типа не будет.
		# Путь для сохранения не обязательно указывать.
		raise NotImplementedError('get_target_image')
	
	def get_uv_name(self, obj: 'Object', mat: 'Material') -> 'Opional[str]':
		# Функция, которая будет говоорить, какой UV слой использовать
		# Должна вернуть имя UV слоя
		return  # TODO
	
	def get_island_mode(self, origin: 'Object', mat: 'Material') -> 'str':
		# Функция, которая будет говоорить, в каком режиме ISLAND_SEARCH_TYPES искать острова
		# Режим может меняться в зависимости от исходного объекта и исходного материала
		return 'POLYGON'
	
	def get_epsilon(self, obj: 'Object', mat: 'Material') -> 'Optional[float]':
		# допустимый зазор TODO
		return None
	
	def before_bake(self, bake_type: str, target_image: 'Image'):
		pass
	
	def after_bake(self, bake_type: str, target_image: 'Image'):
		pass
	
	def _get_source_object(self, copy_obj: 'Object'):
		name = copy_obj.get(self.PROP_ORIGIN_OBJECT)
		origin_obj = bpy.data.objects.get(name)
		return origin_obj
	
	def _get_matsize_safe(self, mat: 'Material') -> 'Tuple[float, float]':
		size = None
		try:
			# TODO если размер текстуры не выявлен, нужно отрабатывать чётче
			size = self.get_material_size(mat) or find_tex_size(mat) or (32, 32)
			return size
		except Exception as exc:
			msg = 'Can not get size of material {0}.'.format(mat)
			log.error(msg)
			raise RuntimeError(msg, mat, size) from exc
	
	def _get_epsilon_safe(self, obj: 'Object', mat: 'Material'):
		epsilon = None
		try:
			epsilon = self.get_epsilon(obj, mat) or 1
			return epsilon
		except Exception as exc:
			msg = 'Can not get epsilon for {0} and {1}.'.format(obj, mat)
			log.error(msg)
			raise RuntimeError(msg, obj, mat, epsilon) from exc
	
	def _get_uv_data_safe(self, obj: 'Object', mat: 'Material', mesh: 'Mesh'):
		uv_name = None
		try:
			uv_name = self.get_uv_name(obj, mat) or 0
			uv_data = mesh.uv_layers[uv_name].data  # type: List[MeshUVLoop]
		except Exception as exc:
			msg = 'Can not get uv_layers[{2}] data for {0} and {1}.'.format(obj, mat, uv_name)
			log.error(msg)
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
			log.error(msg)
			raise RuntimeError(msg, bake_type, image) from exc
	
	def _prepare_objects(self):
		objects = set()
		for obj in self.objects:
			if not isinstance(obj.data, bpy.types.Mesh):
				log.warning("%s is not a valid mesh-object!", obj)
				continue
			objects.add(obj)
		self.objects = objects
	
	def _prepare_target_images(self):
		for bake_type in self.BAKE_TYPES:
			target_image = self._get_bake_image_safe(bake_type)
			if target_image is None or target_image is False:
				continue
			self._bake_types[bake_type] = target_image
	
	def _prepare_materials(self):
		for obj in self.objects:
			for slot in obj.material_slots:  # type: MaterialSlot
				if slot is None or slot.material is None:
					log.warning("Empty material slot detected: %s", obj)
					continue
				tmat = self._get_target_material_safe(obj, slot.material)
				if tmat is not None:
					self._materials[(obj, slot.material)] = tmat
		mats = set(x[1] for x in self._materials.keys())
		log.info("Validating %d source materials...", len(mats))
		for mat in mats:
			self._check_material(mat)
		log.info("Validated %d source materials.", len(mats))
	
	def _prepare_matsizes(self):
		mat_i = 0
		smats = set(x[1] for x in self._materials.keys())
		
		class MatSizeReporter(Reporter):
			def do_report(self, time_passed):
				log.info("Preparing material sizes, Materials=%d/%d, Time=%f sec...", mat_i, len(smats), time_passed)
		reporter = MatSizeReporter(self.report_time)
		
		for smat in smats:
			self._matsizes[smat] = self._get_matsize_safe(smat)
			mat_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)
	
	def _make_duplicates(self):
		# Делает дубликаты объектов, сохраняет в ._copies
		log.info("Duplicating temp objects for atlasing...")
		ensure_deselect_all_objects()
		for obj in self.objects:
			if isinstance(obj.data, bpy.types.Mesh):
				obj.hide_set(False)
				obj.select_set(True)
				bpy.context.view_layer.objects.active = obj
			obj[self.PROP_ORIGIN_OBJECT] = obj.name
			obj.data[self.PROP_ORIGIN_MESH] = obj.data.name
		ensure_op_finished(bpy.ops.object.duplicate(
			linked=False
		), name='bpy.ops.object.duplicate')
		self._copies.update(bpy.context.selected_objects)
		# Меченые имена, что бы если скрипт крашнется сразу было их видно
		for obj in self._copies:
			obj_name = obj.get(self.PROP_ORIGIN_OBJECT) or 'None'
			mesh_name = obj.data.get(self.PROP_ORIGIN_MESH) or 'None'
			obj.name = self.PROC_NAME + obj_name
			obj.data.name = self.PROC_NAME + mesh_name
		log.info("Duplicated %d temp objects for atlasing.", len(self._copies))
		ensure_deselect_all_objects()
	
	def _separate_duplicates(self):
		# Разбивает дупликаты по материалам
		log.info("Separating temp objects for atlasing...")
		ensure_deselect_all_objects()
		for obj in self._copies:
			obj.hide_set(False)
			obj.select_set(True)
			bpy.context.view_layer.objects.active = obj
		ensure_op_finished(bpy.ops.mesh.separate(
			type='MATERIAL'
		), name='bpy.ops.mesh.separate')
		count = len(self._copies)
		self._copies.update(bpy.context.selected_objects)
		ensure_deselect_all_objects()
		log.info("Separated %d -> %d temp objects", count, len(self._copies))
	
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
		ensure_deselect_all_objects()
		for cobj in to_delete:
			cobj.hide_set(False)
			cobj.select_set(True)
		ensure_op_finished(bpy.ops.object.delete(
			use_global=True, confirm=True
		), name='bpy.ops.object.delete')
		if len(bpy.context.selected_objects) > 0:  # TODO
			raise RuntimeError("len(bpy.context.selected_objects) > 0", list(bpy.context.selected_objects))
		for cobj in to_delete:
			self._copies.discard(cobj)
		log.info("Removed %d temp objects, left %d objects", len(to_delete), len(self._copies))
	
	def _group_duplicates(self):
		# Группирует self._copies по материалам в self._groups
		for obj in self._copies:
			mat = self._get_single_material(obj)
			group = self._groups.get(mat)
			if group is None:
				group = set()
				self._groups[mat] = group
			group.add(obj)
		log.info("Grouped %d temp objects into %d material groups.", len(self._copies), len(self._groups))
	
	def _find_islands(self):
		mat_i, obj_i = 0, 0
		copies_c = len(self._copies)
		_self = self
		
		class FindIslandsReporter(Reporter):
			def do_report(self, time_passed):
				islands = sum(len(b.bboxes) for _, b in _self._islands.items())
				log.info("Searching UV islands: Objects=%d/%d, Materials=%d/%d, Islands=%d, Time=%f sec...", obj_i, copies_c, mat_i,
					len(_self._groups.keys()), islands, time_passed)
		
		reporter = FindIslandsReporter(self.report_time)
		
		log.info("Searching islands...")
		# Поиск островов, наполнение self._islands
		for mat, group in self._groups.items():
			# log.info("Searching islands of material %s in %d objects...", mat.name, len(group))
			mat_size_x, mat_size_y = self._matsizes.get(mat)
			builder = self._islands.get(mat)
			if builder is None:
				builder = IslandsBuilder()
				self._islands[mat] = builder
			for obj in group:
				origin = self._get_source_object(obj)
				mesh = get_mesh_safe(obj)
				epsilon = self._get_epsilon_safe(origin, mat)
				uv_data = self._get_uv_data_safe(origin, mat, mesh)
				
				polygons = list(mesh.polygons)  # type: List[MeshPolygon]
				# Оптимизация. Сортировка от большей площади к меньшей,
				# что бы сразу сделать большие боксы и реже пере-расширять их.
				polygons.sort(key=lambda p: uv_area(p, uv_data), reverse=True)
				
				mode = self.get_island_mode(origin, mat)
				if mode == 'OBJECT':
					# Режим одного острова: все точки всех полигонов формируют общий bbox
					vec2s = list()
					for poly in polygons:
						for loop in poly.loop_indices:
							vec2 = uv_data[loop].uv.xy  # type: Vector
							# Преобразование в размеры текстуры
							vec2.x *= mat_size_x
							vec2.y *= mat_size_y
							vec2s.append(vec2)
					builder.add_seq(vec2s, epsilon=epsilon)
				elif mode == 'POLYGON':
					# Режим многих островов: каждый полигон формируют свой bbox
					try:
						for poly in polygons:
							vec2s = list()
							for loop in poly.loop_indices:  # type: int
								vec2 = uv_data[loop].uv.xy  # type: Vector
								# Преобразование в размеры текстуры
								vec2.x *= mat_size_x
								vec2.y *= mat_size_y
								vec2s.append(vec2)
							builder.add_seq(vec2s, epsilon=epsilon)
					except Exception as exc:
						raise RuntimeError("Error searching multiple islands!", uv_data, obj, mat, mesh, builder) from exc
				else:
					raise RuntimeError('Invalid mode', mode)
				obj_i += 1
				reporter.ask_report(False)
			mat_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)
		log.info("Done islands search.")
		# for mat, builder in self._islands.items():
		# 	log.info("\tMaterial %s have %d islands:", mat, len(builder.bboxes))
		# 	for bbox in builder.bboxes:
		# 		log.info("\t\t%s", str(bbox))
		pass
	
	def _delete_groups(self):
		count = len(self._copies)
		log.info("Removing %d temp objects...", count)
		ensure_deselect_all_objects()
		for obj in self._copies:
			obj.hide_set(False)
			obj.select_set(True)
		ensure_op_finished(bpy.ops.object.delete(
			use_global=True, confirm=True
		), name='bpy.ops.object.delete')
		if len(bpy.context.selected_objects) > 0:  # TODO
			raise RuntimeError("len(bpy.context.selected_objects) > 0", list(bpy.context.selected_objects))
		log.info("Removed %d temp objects.", count)
	
	def _islands_to_mathutils_boxes(self):
		# Преобразует острава в боксы в формате mathutils.geometry.box_pack_2d
		aspect_target = 1.0 * self.target_size[0] / self.target_size[1]
		for mat, builder in self._islands.items():
			for bbox in builder.bboxes:
				if not bbox.is_valid():
					raise ValueError("box is invalid: ", bbox, mat, builder, builder.bboxes)
				scale_bbox = 1  # TODO
				# две точки -> одна точка + размер
				x, w = bbox.mn.x, (bbox.mx.x - bbox.mn.x)
				y, h = bbox.mn.y, (bbox.mx.y - bbox.mn.y)
				# добавляем отступы
				x, y = x - self.padding, y - self.padding,
				w, h = w + 2 * self.padding, h + 2 * self.padding
				# Для целевого квадарата - пропорция
				bx, by = x * scale_bbox, y * scale_bbox
				bw, bh = w * scale_bbox, h * scale_bbox
				# Для целевого квадарата - корректировка соотнощения сторон
				bx, bw = bx / aspect_target, bw / aspect_target
				self._mathutils_boxes.append([
					bx, by, bw, bh,  # 0:X, 1:Y, 2:W, 3:H - Перобразуемые box_pack_2d (далее) координаты (не нормализованные)
					x, y, w, h,  # 4:X, 5:Y, 6:W, 7:H - Исходные координаты (не нормализованные)
					mat,  # 8
				])
	
	def _pack_islands(self):
		# Несколько итераций перепаковки
		# TODO вернуть систему с раундами
		log.info("Atlas: Packing %d islands...", len(self._mathutils_boxes))
		pack_x, pack_y = box_pack_2d(self._mathutils_boxes)
		log.info("Atlas: Packed size: %f x %f", pack_x, pack_y)
		random.shuffle(self._mathutils_boxes)
		pack_x, pack_y = box_pack_2d(self._mathutils_boxes)
		log.info("Atlas: Packed size: %f x %f", pack_x, pack_y)
		random.shuffle(self._mathutils_boxes)
		pack_x, pack_y = box_pack_2d(self._mathutils_boxes)
		log.info("Atlas: Packed size: %f x %f", pack_x, pack_y)
		pack_mx = max(pack_x, pack_y)
		# for mu_box in self._mathutils_boxes:
		# 	log.info("\t%s", str(mu_box))
		for mu_box in self._mathutils_boxes:
			# Преобразование целевых координат в 0..1
			mu_box[0], mu_box[1] = mu_box[0] / pack_mx, mu_box[1] / pack_mx
			mu_box[2], mu_box[3] = mu_box[2] / pack_mx, mu_box[3] / pack_mx
		# log.info("Atlas: Packed size: %f x %f", pack_x, pack_y)
		pass
	
	def _mathutils_boxes_to_transforms(self):
		mathutils_boxes_groups = dict()  # type: Dict[Material, List[List[Union[float, Material]]]]
		for mu_box in self._mathutils_boxes:
			mat = mu_box[8]
			group = mathutils_boxes_groups.get(mat)
			if group is None:
				group = list()
				mathutils_boxes_groups[mat] = group
			group.append(mu_box)
		for mat, group in mathutils_boxes_groups.items():
			mat_size = self._matsizes.get(mat)
			transforms = self._transforms.get(mat)
			if transforms is None:
				transforms = list()
				self._transforms[mat] = transforms
			for mu_box in group:
				#  Преобразование исходных координат в 0..1
				ax, aw = mu_box[4] / mat_size[0], mu_box[6] / mat_size[0]
				ay, ah = mu_box[5] / mat_size[1], mu_box[7] / mat_size[1]
				transforms.append(UVBoxTransform(ax, ay, aw, ah, mu_box[0], mu_box[1], mu_box[2], mu_box[3]))
		# for mat, transforms in self._transforms.items():
		# 	log.info("\tMaterial %s have %d transforms:", mat, len(transforms))
		# 	for t in transforms:
		# 		log.info("\t\t%s", str(t))
		pass
	
	def _prepare_bake_obj(self):
		ensure_deselect_all_objects()
		mesh = bpy.data.meshes.new("__Kawa_Bake_UV_Mesh")  # type: Mesh
		# Создаем столько полигонов, сколько трансформов
		bm = bmesh.new()
		try:
			for _, transforms in self._transforms.items():
				for _ in range(len(transforms)):
					v0, v1, v2, v3 = bm.verts.new(), bm.verts.new(), bm.verts.new(), bm.verts.new()
					bm.faces.new((v0, v1, v2, v3))
				bm.to_mesh(mesh)
		finally:
			bm.free()
		# Создаем слои для преобразований
		mesh.uv_layers.new(name=self.UV_ORIGINAL)
		mesh.uv_layers.new(name=self.UV_ATLAS)
		mesh.materials.clear()
		for mat in self._transforms.keys():
			mesh.materials.append(mat)
		mat2idx = {m: i for i, m in enumerate(mesh.materials)}
		# Прописываем в полигоны координаты и материалы
		uvl_original = mesh.uv_layers[self.UV_ORIGINAL]  # type: MeshUVLoopLayer
		uvl_atlas = mesh.uv_layers[self.UV_ATLAS]  # type: MeshUVLoopLayer
		uvd_original, uvd_atlas = uvl_original.data, uvl_atlas.data
		poly_idx = 0
		for mat, transforms in self._transforms.items():
			for t in transforms:
				poly = mesh.polygons[poly_idx]
				if len(poly.loop_indices) != 4:
					raise AssertionError("len(poly.loop_indices) != 4", mesh, poly_idx, poly, len(poly.loop_indices))
				if len(poly.vertices) != 4:
					raise AssertionError("len(poly.vertices) != 4", mesh, poly_idx, poly, len(poly.vertices))
				corners = (
					(0, (t.ax, t.ay), (t.bx, t.by)),  # vert 0: left, bottom
					(1, (t.ax + t.aw, t.ay), (t.bx + t.bw, t.by)),  # vert 1: right, bottom
					(2, (t.ax + t.aw, t.ay + t.ah), (t.bx + t.bw, t.by + t.bh)),  # vert 2: right, up
					(3, (t.ax, t.ay + t.ah), (t.bx, t.by + t.bh)),  # vert 3: left, up
				)
				for vert_idx, uv_a, uv_b in corners:
					mesh.vertices[poly.vertices[vert_idx]].co.xy = uv_b
					mesh.vertices[poly.vertices[vert_idx]].co.z = poly_idx * 1.0 / len(mesh.polygons)
					uvd_original[poly.loop_indices[vert_idx]].uv = uv_a
					uvd_atlas[poly.loop_indices[vert_idx]].uv = uv_b
				poly.material_index = mat2idx[mat]
				poly_idx += 1
		
		# Вставляем меш на сцену и активируем
		ensure_deselect_all_objects()
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
		activate_object(self._bake_obj)
	
	def _call_before_bake_safe(self, bake_type: str, target_image: 'Image'):
		try:
			self.before_bake(bake_type, target_image)
		except Exception as exc:
			msg = 'cb_before_bake failed! {0} {1}'.format(bake_type, target_image)
			log.error(msg)
			raise RuntimeError(msg, bake_type, target_image) from exc
	
	def _call_after_bake_safe(self, bake_type: str, target_image: 'Image'):
		try:
			self.after_bake(bake_type, target_image)
		except Exception as exc:
			msg = 'cb_after_bake failed! {0} {1}'.format(bake_type, target_image)
			log.error(msg)
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
			out = get_material_output(mat)
			surface = out.inputs['Surface']  # type: NodeSocket
			src_shader_link = surface.links[0] if len(surface.links) == 1 else None  # type: NodeLink
			src_shader = src_shader_link.from_node  # type: ShaderNode
			if src_shader is None:
				raise RuntimeError('no shader found')
		except Exception as exc:
			msg = "Material {0} is invalid!".format(mat.name)
			log.info(msg)
			raise RuntimeError(msg, mat, node_tree, out, surface, src_shader_s, src_shader) from exc
	
	node_editor_override = False
	
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
							log.info('Using NODE_EDITOR: screen=%s area=#%d region=#%d', screen.name, area_idx, region_idx)
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
		
		surface = get_material_output(mat).inputs['Surface']  # type: NodeSocket
		src_shader_link = surface.links[0]  # type: NodeLink
		src_shader = src_shader_link.from_node  # type: ShaderNode
		
		def replace_shader():
			# Замещает оригинальный шейдер на Emission
			bake_shader = nodes.new('ShaderNodeEmission')  # type: ShaderNode
			if src_shader_link is not None:
				node_tree.links.remove(src_shader_link)
			node_tree.links.new(bake_shader.outputs['Emission'], surface)
			# log.info("Replacing shader %s -> %s on %s", src_shader, bake_shader, mat)
			return bake_shader
		
		def copy_input(from_in_socket: 'NodeSocket', to_in_socket: 'NodeSocket'):
			links = from_in_socket.links
			if len(links) > 0:
				link = links[0]  # type: NodeLink
				node_tree.links.new(link.from_socket, to_in_socket)
		
		def copy_input_color(from_in_socket: 'NodeSocketColor', to_in_socket: 'NodeSocketColor'):
			to_in_socket.default_value = from_in_socket.default_value
			copy_input(from_in_socket, to_in_socket)
		
		if bake_type == 'ALPHA':
			bake_shader = replace_shader()
			src_alpha = get_node_input_safe(src_shader, 'Alpha')
			if src_alpha is not None:  # TODO RGB <-> value
				copy_input(src_alpha, bake_shader.inputs['Color'])
		elif bake_type == 'DIFFUSE':
			bake_shader = replace_shader()
			src_shader_color = src_shader.inputs.get('Base Color') or src_shader.inputs.get('Color')  # type: NodeSocket
			if src_shader_color is not None:
				copy_input_color(src_shader_color, bake_shader.inputs['Color'])
	
	def _edit_mats_for_bake(self, bake_obj: 'Object', bake_type: 'str'):
		ensure_deselect_all_objects()
		activate_object(bake_obj)
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
		log.info(
			"Preparing for bake atlas Image='%s' type='%s' size=%s...",
			target_image, bake_type, tuple(target_image.size)
		)
		
		# Поскольку cycles - ссанина, нам проще сделать копию ._bake_obj
		# Сделать копии материалов на ._bake_obj
		# Кастомизировать материалы, вывести всё через EMIT
		
		ensure_deselect_all_objects()
		activate_object(self._bake_obj)
		ensure_op_finished(bpy.ops.object.duplicate(
			linked=False
		), name='bpy.ops.object.duplicate')
		local_bake_obj = bpy.context.view_layer.objects.active
		self._bake_obj.hide_set(True)
		ensure_deselect_all_objects()
		activate_object(local_bake_obj)
		ensure_op_finished(bpy.ops.object.make_single_user(
			object=True, obdata=True, material=True, animation=False,
		), name='bpy.ops.object.make_single_user')
		
		if bake_type == 'ALPHA':
			self._try_edit_mats_for_bake(local_bake_obj, bake_type)
		if bake_type == 'DIFFUSE':
			self._try_edit_mats_for_bake(local_bake_obj, bake_type)
		
		for slot in local_bake_obj.material_slots:  # type: MaterialSlot
			n_bake = prepare_and_get_node_for_baking(slot.material)
			n_bake.image = target_image
		
		emit_types = {'EMIT', 'ALPHA', 'DIFFUSE'}
		cycles_bake_type = 'EMIT' if bake_type in emit_types else bake_type
		bpy.context.scene.cycles.bake_type = cycles_bake_type
		bpy.context.scene.render.bake.use_pass_direct = False
		bpy.context.scene.render.bake.use_pass_indirect = False
		bpy.context.scene.render.bake.use_pass_color = False
		bpy.context.scene.render.bake.use_pass_emit = bake_type in emit_types
		bpy.context.scene.render.bake.normal_space = 'TANGENT'
		bpy.context.scene.render.bake.margin = 64
		bpy.context.scene.render.bake.use_clear = True
		
		self._call_before_bake_safe(bake_type, target_image)
		
		log.info(
			"Trying to bake atlas Image='%s' type='%s'/'%s' size=%s...",
			target_image, bake_type, cycles_bake_type, tuple(target_image.size)
		)
		ensure_deselect_all_objects()
		activate_object(local_bake_obj)
		bake_start = time.perf_counter()
		ensure_op_finished(bpy.ops.object.bake(type=cycles_bake_type, use_clear=True))
		bake_time = time.perf_counter() - bake_start
		log.info("Baked atlas Texture='%s' type='%s', time spent: %f sec.", target_image.name, bake_type, bake_time)
		
		garbage_materials = set(slot.material for slot in local_bake_obj.material_slots)
		mesh = local_bake_obj.data
		bpy.context.blend_data.objects.remove(local_bake_obj, do_unlink=True)
		bpy.context.blend_data.meshes.remove(mesh, do_unlink=True)
		for mat in garbage_materials:
			bpy.context.blend_data.materials.remove(mat, do_unlink=True)
		
		self._call_after_bake_safe(bake_type, target_image)
	
	def _bake_images(self):
		ensure_deselect_all_objects()
		activate_object(self._bake_obj)
		# Настраиваем UV слои под рендер
		for layer in get_mesh_safe(self._bake_obj).uv_layers:  # type: MeshUVLoopLayer
			layer.active = layer.name == self.UV_ATLAS
			layer.active_render = layer.name == self.UV_ORIGINAL
			layer.active_clone = False
		for bake_type, target_image in self._bake_types.items():
			self._bake_image(bake_type, target_image)
		
		ensure_deselect_all_objects()
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
			log.error(msg)
			raise RuntimeError(msg, smat, tmat) from exc
		return tmat
	
	def _apply_baked_materials(self):
		# TODO нужно как-то оптимизировать это говно
		# Для каждого материала смотрим каждый материала слот
		# Смотрим каждый полигон, если у него верный слот,
		# То берем средню UV и перебераем все transformы,
		# Нашли transform? запоминаем.
		# После обхода всех полигонов материала применяем transform на найденые индексы.
		
		log.info("Applying UV...")
		mat_i, obj_i = 0, 0
		objects = self.objects
		
		class UVTransformReporter(Reporter):
			def do_report(self, time_passed):
				log.info("Transforming UVs: Object=%d/%d, Slots=%d, Time=%f sec...", obj_i, len(objects), mat_i, time_passed)
		
		reporter = UVTransformReporter(self.report_time)
		
		for obj in self.objects:
			mesh = get_mesh_safe(obj)
			for material_index in range(len(mesh.materials)):
				source_mat = mesh.materials[material_index]
				transforms = self._transforms.get(source_mat)
				if transforms is None:
					continue  # Нет преобразований для данного материала
				maps = dict()  # type: Dict[int, UVBoxTransform]
				target_mat = self._materials.get((obj, source_mat))
				uv_data = self._get_uv_data_safe(obj, source_mat, mesh)
				for poly in mesh.polygons:
					if poly.material_index != material_index:
						continue
					mean_uv = Vector((0, 0))
					for loop in poly.loop_indices:
						mean_uv = mean_uv + uv_data[loop].uv
					mean_uv /= len(poly.loop_indices)
					transform = None
					for t in transforms:
						t.match_a(mean_uv)
						transform = t
						break
					if transform is None:
						raise AssertionError("No UV transform", obj, source_mat, poly)
					for loop in poly.loop_indices:
						maps[loop] = transform
				for loop, transform in maps.items():
					vec2 = uv_data[loop].uv  # type: Vector
					vec2 = transform.apply_vec2(vec2)
					uv_data[loop].uv = vec2
				mesh.materials[material_index] = target_mat
				obj.material_slots[material_index].material = target_mat
				mat_i += 1
				reporter.ask_report(False)
			obj_i += 1
			reporter.ask_report(False)
			merge_same_material_slots(obj)
		reporter.ask_report(True)
	
	def bake_atlas(self):
		log.info("Baking atlas!")
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
		self._islands_to_mathutils_boxes()
		self._pack_islands()
		self._mathutils_boxes_to_transforms()
		# Не трогаем исходники, создаем вспомогательный меш-объект для запекания
		self._prepare_bake_obj()
		self._bake_images()
		# После запекания к исходникам применяются новые материалы и преобразования
		self._apply_baked_materials()
		log.info("Woohoo!")
