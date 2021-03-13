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
import time

import bpy

from .commons import ensure_deselect_all_objects, ensure_op_finished, select_set_all, apply_all_modifiers, Reporter

if typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *

log = logging.getLogger('kawa.instantiator')


class Instantiator:
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
	
	@classmethod
	def from_raw_config(cls, raw_setup: 'Optional[SetupRaw]'):
		i10r = cls()
		return i10r
	
	def __init__(self):
		self.original_scene = None  # type: Optional[Scene]
		self.working_scene = None  # type: Optional[Scene]
		self.renamer = None  # type: Optional[Callable[[Object, str], str]]
		
		self.instantiate_collections = True
		self.instantiate_material_slots = True
		self.apply_modifiers = True
		self.apply_scales = False
		self.report_time = 5
		
		self.originals = set()  # type: Set[Object]
		self.copies = set()  # type: Set[Object]

	def _instantiate_material_slots(self):
		obj_n, obj_i, slot_i = len(self.copies), 0, 0
		
		class MatSlotsReporter(Reporter):
			def do_report(self, time_passed):
				log.info("Instantiating material slots: Objects=%d/%d, Slots=%d, Time=%f sec...", obj_i, obj_n, slot_i, time_passed)
		
		reporter = MatSlotsReporter(self.report_time)
		
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
		
		class ModifiersReporter(Reporter):
			def do_report(self, time_passed):
				log.info("Applying modifiers: Objects=%d/%d, Modifiers=%d, Time=%f sec...", obj_i, obj_n, mod_i, time_passed)
		
		reporter = ModifiersReporter(self.report_time)
		
		log.info('Applying modifiers...')
		for copy in self.copies:
			mod_i += apply_all_modifiers(copy)
			obj_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)

	def run(self) -> 'None':
		if self.working_scene is None:
			raise RuntimeError("working_scene is not set")

		for original in self.originals:
			if self.original_scene is not None:
				if self.original_scene not in original.users_scene:
					raise RuntimeError("original={0} is not member of original_scene={1}".format(original, self.original_scene))
	
		bpy.context.window.scene = self.working_scene
		ensure_deselect_all_objects()
		
		# Помещаем все оригиналы на working_scene и выбираем
		for original in self.originals:
			if self.working_scene not in original.users_scene:
				self.working_scene.collection.objects.link(original)
			original.hide_set(False)  # Необходимо, т.к. некоторые операторы не работают на скрытых объектах
			original.select_set(True)
			bpy.context.view_layer.objects.active = original
			if self.renamer is not None:
				original[self.ORIGINAL_NAME] = original.name

		log.info('Instantiating %d objects from %s to %s... ', len(self.originals), self.original_scene, self.working_scene)
		ensure_op_finished(bpy.ops.object.duplicate(
			linked=False
		), name='bpy.ops.object.duplicate')
		self.copies.update(bpy.context.selected_objects)
		log.info('Basic copies: %d', len(self.copies))
		ensure_deselect_all_objects()
		
		# Убираем оригиналы с working_scene
		for original in self.originals:
			if self.working_scene in original.users_scene:
				self.working_scene.collection.objects.unlink(original)
				
		if self.instantiate_collections:
			log.info('Instantiating collections...')
			before = len(self.copies)
			select_set_all(self.copies, True)
			ensure_op_finished(bpy.ops.object.duplicates_make_real(
				use_base_parent=True, use_hierarchy=True
			), name='bpy.ops.object.duplicates_make_real')
			self.copies.update(bpy.context.selected_objects)
			select_set_all(self.copies, False)
			log.info('Instantiated collections: %d -> %d', before, len(self.copies))
			
		if self.renamer is not None:
			log.info('Renaming copies...')
			for copy in self.copies:
				original_name = copy.get(self.ORIGINAL_NAME)
				if original_name is not None:
					new_name = self.renamer(copy, original_name)
					# log.info('Renamer: %s %s -> %s', copy, original_name, new_name)
					if new_name is not None:
						copy.name = new_name
			for original in self.originals:
				if self.ORIGINAL_NAME in original:
					del original[self.ORIGINAL_NAME]
			
		log.info('Making single-user meshes...')
		select_set_all(self.copies, True)
		before = len(bpy.data.meshes)
		ensure_op_finished(bpy.ops.object.make_single_user(
			object=False, obdata=True, material=False, animation=False,
		), name='bpy.ops.object.make_single_user')
		self.copies.update(bpy.context.selected_objects)
		select_set_all(self.copies, False)
		log.info('single-user meshes, bpy.data.meshes: %d -> %d', before, len(bpy.data.meshes))
		
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
		
		invalids = list(x for x in self.copies if self.working_scene not in x.users_scene)
		if len(invalids) > 0:
			log.info("Discarding %d invalid objects...", len(invalids))
			for invalid in invalids:
				self.copies.discard(invalid)
	
		log.info("Instantiation done: %d original -> %d copies.", len(self.originals), len(self.copies))