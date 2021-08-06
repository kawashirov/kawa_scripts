# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import collections
import logging
import typing

import bpy

from .commons import ensure_deselect_all_objects, ensure_op_finished, select_set_all, \
	apply_all_modifiers, LambdaReporter, activate_object, activate_objects

if typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *
	Collection = bpy.types.Collection

log = logging.getLogger('kawa.instantiator')


class BaseInstantiator:
	ORIGINAL_NAME = '__KawaInstantiator_OriginalName'
	
	# Создаёт рабочию копию оригинальных объектов (для запекания):
	# - Копирует объекты и их меши
	# - Превращает инстансы коллекций в объекты
	# - Заменяет OBJECT текстуры на DATA
	# - Применяет все модификаторы
	# -
	# - TODO переименования
	#
	# Как использовать:
	# - Задать сцены: .original_scene и .working_scene
	# - Положить оригиналы в .originals
	# - Запустить .run()
	# - Копии будут лежать в copy2original и original2copy
	# - Все новые объекты сохранятся в .copies
	# Не стоит запускать run() повторно или изменять что-либо после run()
	
	def __init__(self):
		self.original_scene = None  # type: Scene
		self.working_scene = None  # type: Scene
		self.instantiate_collections = True
		self.instantiate_material_slots = True
		self.apply_modifiers = True
		self.apply_scales = False
		self.report_time = 5
		
		self.originals = set()  # type: Set[Object]
		self.copies = set()  # type: Set[Object]
		
		self._original_names = set()  # type: Set[Object]
	
	def rename_copy(self, obj: 'Object', original_name: 'str', ) -> 'str':
		return NotImplemented
	
	def rename_object_from_collection(self,
			parent_obj: 'Object', parent_obj_orig_name: 'str',
			inst_obj: 'Object', inst_obj_orig_name: 'str',
			collection: 'Collection'
	) -> 'str':
		return NotImplemented
	
	def _check_originals(self):
		wrong_scene = set()
		for original in self.originals:
			if self.original_scene not in original.users_scene:
				wrong_scene.add(original)
		if len(wrong_scene) > 0:
			wrong_scene_str = ', '.join(repr(x.name) for x in wrong_scene)
			msg = '{0} of {1} original objects does not belong to original_scene={2}: {3}'.format(
				len(wrong_scene), len(self.originals), repr(self.original_scene.name), wrong_scene_str)
			log.error(msg)
			raise RuntimeError(msg, wrong_scene)

	def _register_original_names(self):
		original_names_q = collections.deque()
		original_names_q.extend(self.originals)
		self._original_names.clear()
		while len(original_names_q) > 0:
			obj = original_names_q.pop()  # type: Object
			self._original_names.add(obj)
			if obj.instance_type == 'COLLECTION' and obj.instance_collection is not None:
				original_names_q.extend(obj.instance_collection.objects)
		for obj in self._original_names:
			obj[self.ORIGINAL_NAME] = obj.name
			
	def _put_originals_on_working(self):
		ensure_deselect_all_objects()
		for original in self.originals:
			if original.name not in self.working_scene.collection.objects:
				self.working_scene.collection.objects.link(original)
			activate_object(original)
	
	def _duplicate(self):
		ensure_op_finished(bpy.ops.object.duplicate(linked=False), name='bpy.ops.object.duplicate')
		self.copies.update(bpy.context.selected_objects)
		log.info('Basic copies created: %d', len(self.copies))
		ensure_deselect_all_objects()
		
	def _unlink_originals_from_working(self):
		for original in self.originals:
			if original.name in self.working_scene.collection.objects:
				self.working_scene.collection.objects.unlink(original)
	
	def _rename_copies(self):
		log.info('Renaming copies...')
		for copy in self.copies:
			original_name = copy.get(self.ORIGINAL_NAME)
			if original_name is not None:
				new_name = None
				try:
					new_name = self.rename_copy(copy, original_name)
				except Exception as exc:
					# TODO
					raise RuntimeError('rename', copy, original_name, new_name) from exc
				if isinstance(new_name, str):
					copy.name = new_name

	def _instantiate_collections(self):
		log.info('Instantiating collections...')
		
		created, obj_i, inst_i = 0, 0, 0
		reporter = LambdaReporter(self.report_time)
		reporter.func = lambda r, t: log.info(
			"Instantiating collections: Objects=%d/%d, Instantiated=%d, Created=%d, Time=%.1f sec...",
			obj_i, len(self.copies), inst_i, created, t
		)
		
		queue = collections.deque()
		queue.extend(self.copies)
		while len(queue) > 0:
			obj = queue.pop()  # type: Object
			obj_i += 1
			if obj.type != 'EMPTY' or obj.instance_type != 'COLLECTION' or obj.instance_collection is None:
				continue
			inst_i += 1
			ensure_deselect_all_objects()
			activate_object(obj)
			collection = obj.instance_collection
			ensure_op_finished(bpy.ops.object.duplicates_make_real(
				use_base_parent=True, use_hierarchy=True
			), name='bpy.ops.object.duplicates_make_real')
			self.copies.update(bpy.context.selected_objects)
			queue.extend(bpy.context.selected_objects)
			created += len(bpy.context.selected_objects)
			obj_orignal_name = obj.get(self.ORIGINAL_NAME)
			for inst_obj in list(bpy.context.selected_objects):
				inst_obj_orignal_name = inst_obj.get(self.ORIGINAL_NAME)
				new_name = self.rename_object_from_collection(obj, obj_orignal_name, inst_obj, inst_obj_orignal_name, collection)
				if isinstance(new_name, str):
					inst_obj.name = new_name
				elif isinstance(inst_obj_orignal_name, str):
					inst_obj.name = obj.name + '-' + inst_obj_orignal_name
			reporter.ask_report(False)
			
		ensure_deselect_all_objects()
		reporter.ask_report(True)
	
	def _convert_curves_to_meshes(self):
		log.info('Converting curves to meshes...')
		curves = list(obj for obj in self.copies if isinstance(obj.data, bpy.types.Curve))
		if len(curves) < 1:
			return
		ensure_deselect_all_objects()
		activate_objects(curves)
		self.copies.difference_update(curves)
		ensure_op_finished(bpy.ops.object.convert(target='MESH'), name='bpy.ops.object.convert')
		self.copies.update(bpy.context.selected_objects)
		ensure_deselect_all_objects()
		log.info('Converted %d curves to meshes.', len(curves))
	
	def _make_single_user(self):
		log.info('Making data blocks single-users...')
		ensure_deselect_all_objects()
		select_set_all(self.copies, True)
		before = len(set(obj.data for obj in self.copies if obj.data is not None))
		ensure_op_finished(bpy.ops.object.make_single_user(
			object=False, obdata=True, material=False, animation=False,
		), name='bpy.ops.object.make_single_user')
		after = len(set(obj.data for obj in self.copies if obj.data is not None))
		self.copies.update(bpy.context.selected_objects)
		ensure_deselect_all_objects()
		log.info('make_single_user, data blocks: %d +%d -> %d', before, (after - before), after)
	
	def _instantiate_material_slots(self):
		obj_i, slot_i = 0, 0
		
		reporter = LambdaReporter(self.report_time)
		reporter.func = lambda r, t: log.info(
			"Instantiating material slots: Objects=%d/%d, Slots=%d, Time=%.1f sec, ETA=%.1f sec...",
			obj_i, len(self.copies), slot_i, t, r.get_eta(1.0 * obj_i / len(self.copies))
		)
		
		log.info('Instantiating material slots...')
		for copy in self.copies:
			if not isinstance(copy.data, bpy.types.Mesh):
				continue
			for slot in copy.material_slots:
				if slot.material is None or slot.link == 'DATA':
					continue  # Пропуск пустых или DATA материалов
				mat = slot.material
				# log.info("Object='%s': Switching Material='%s' from OBJECT to DATA...", copy, mat)
				slot.link = 'DATA'
				slot.material = mat
				slot_i += 1
			obj_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)
	
	def _apply_modifiers(self):
		obj_n, obj_i, mod_i = len(self.copies), 0, 0
		
		reporter = LambdaReporter(self.report_time)
		reporter.func = lambda r, t: log.info(
			"Applying modifiers: Objects=%d/%d, Modifiers=%d, Time=%.1f sec, ETA=%.1f sec...",
			obj_i, obj_n, mod_i, t, r.get_eta(1.0 * obj_i / obj_n)
		)
		
		log.info('Applying modifiers...')
		for copy in self.copies:
			mod_i += apply_all_modifiers(copy)
			obj_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)

	def _clean_original_names(self):
		for original in self._original_names:
			if self.ORIGINAL_NAME in original:
				del original[self.ORIGINAL_NAME]

	def run(self) -> 'None':
		if self.original_scene is None:
			raise RuntimeError("original_scene is not set")
		if self.working_scene is None:
			raise RuntimeError("working_scene is not set")
		
		self._check_originals()
		log.info('Instantiating %d objects from scene %s to %s... ',
			len(self.originals), repr(self.original_scene.name), repr(self.working_scene.name))
		self._register_original_names()
		bpy.context.window.scene = self.working_scene
		self._put_originals_on_working()
		self._duplicate()
		self._unlink_originals_from_working()
		self._rename_copies()
		
		if self.instantiate_collections:
			self._instantiate_collections()
			
		self._make_single_user()
		self._convert_curves_to_meshes()
		
		if self.instantiate_material_slots:
			self._instantiate_material_slots()

		if self.apply_modifiers:
			self._apply_modifiers()
		
		if self.apply_scales:
			log.info('Applying scales...')
			select_set_all(self.copies, True)
			bpy.ops.object.transform_apply(location=False, rotation=False, scale=self.apply_scales, properties=False)
			select_set_all(self.copies, False)
			log.info('Applied scales.')
		
		invalids = list(obj for obj in self.copies if obj.name not in self.working_scene.collection.objects)
		if len(invalids) > 0:
			log.info("Discarding %d invalid objects...", len(invalids))
			for invalid in invalids:
				self.copies.discard(invalid)

		self._clean_original_names()
		
		log.info("Instantiation done: %d original -> %d copies.", len(self.originals), len(self.copies))