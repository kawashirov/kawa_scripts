# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

from collections import deque as _deque

import bpy as _bpy
from bpy import data as _D
from bpy import context as _C

from . import commons as _commons
from .reporter import LambdaReporter as _LambdaReporter

import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *

import logging as _logging
_log = _logging.getLogger('kawa.combiner')


class BaseMeshCombiner:
	def __init__(self):
		self.roots_names = set()  # type: Set[str]
		
		self.report_time = 5
		
		# Если указано, ограничивает работу скрипта только этой сценой.
		# Иначе, рассматривается активная сцена.
		self.scene = None  # type: Optional[Scene]
		
		# Объекты, которые были замешены во время работы этого скрипта.
		self.created_objects = set()  # type: Set[str]
		self.replaced_objects = set()  # type: Set[str]
		
		# Если root-объект - не меш-объект, то следует ли пересоздать его?
		# - False - в иерархии root-объекта создается новый меш-объект, для None-группы.
		# Объект будет иметь суффикс .default_group.
		# - True - root-объект будет заменён на новый меш-объект, для None-группы.
		# Пара объектов (заменённый, заменивший) будет сохранена в .recreated
		self.force_mesh_root = False  # type: bool
		
		self.default_group = 'Default'  # type: str

	def before_group(self, root: 'str', children: 'Set[str]'):
		# Функция, вызываемая перед группировкой детей.
		pass
	
	def group_child(self, root: 'str', child: 'str') -> 'Union[None, str, bool]':
		# Функция, которая говорит, как объединять меши.
		# Аргументы:
		# - объект из root, в который предлагается подсоединить меш
		# - предлагаемый дочерний меш-объект, который предлагается подсоединить к первому
		# Функция должна вернуть одно из:
		# - False если предлагаемый объект объединять не нужно
		# - строку с именем группы объединения
		# - None, что бы объединить в группу по-молчанию / без группы
		# Если root-объект - меш-объект, то объекты с группой None вольются в него.
		# Если root-объект - не меш-объект, то поведение зависит от .force_mesh_root
		return None
	
	def before_join(self, root: 'str', join_to: 'str', group_name: 'Optional[str]', group_objs: 'Set[str]'):
		# Функция, вызываемая после создания нового меш-объекта, к которому будет присоединение.
		# Аргументы:
		# - root - исходный объект из root
		# - join_to - куда будет происходить присоединения.
		# - group_name - группа, т.е. то, что вернул .selector
		# - group_objs - объекты (которые выбраны .selector-ом) для присоеднинения
		# Может быть root is join_to
		# Ничего возвращать не нужно.
		# Можно использовать, например, для применения/переноса какх-то свойств объекта
		# или для правки UV для корректного сведения.
		pass
	
	def after_join(self, root: 'str', join_to: 'str', group_name: 'Optional[str]'):
		# Функция, вызываемая после присоединения.
		# Аргументы:
		# - root - исходный объект из root
		# - join_to - куда было выполнено присоединение.
		# - group_name - группа, т.е. то, что вернул .selector
		# Может быть root is join_to
		# Ничего возвращать не нужно.
		# Можно использовать, например, для починки lightmap UV.
		pass
	
	def _check_roots(self):
		scene = self.scene or _C.scene
		wrong = list()
		for root_name in self.roots_names:
			if root_name not in scene.collection.objects:
				wrong.append(root_name)
		if len(wrong) > 0:
			wrongstr = ', '.join('"' + r + '"' for r in wrong)
			msg = 'There is {0} root-objects not from scene "{1}": {2}.' \
				.format(len(wrong), scene.name, wrongstr)
			_log.error(msg)
			raise RuntimeError(msg, wrong)
		
		# Проверяем, что бы объекты в .roots были независимы друг от друга,
		# а именно не были детьми/родителями друг друга.
		# TODO Довольно много итераций, можно ли это как-то ускорить?
		related = list()
		for obja_n in self.roots_names:
			obja = _D.objects[obja_n]
			for objb_n in self.roots_names:
				objb = _D.objects[objb_n]
				if obja is objb:
					continue
				objc = obja
				while objc is not None:
					if objc is objb:
						related.append((obja_n, objb_n))
						break
					objc = objc.parent
		if len(related) > 0:
			pairs = ', '.join('"{0}" is child of "{1}"'.format(a, b) for a, b in related)
			msg = 'There is {0} objects pairs have child-parent relations between each other: {1}.'\
				.format(len(related), pairs)
			_log.error(msg)
			raise RuntimeError(msg, related)

	def _call_before_group(self, root_name: 'str', child_name: 'Set[str]'):
		try:
			self.before_group(root_name, child_name)
		except Exception as exc:
			raise RuntimeError(root_name, child_name) from exc

	def _call_group_child(self, root_name: 'str', child_name: 'str') -> 'Union[False, None, str]':
		group_name = None
		try:
			group_name = self.group_child(root_name, child_name)
			if not isinstance(group_name, (type(None), str)) and group_name is not False:
				msg = 'Group should be None, False or str, got ({0}) "{1}" from .group_child'.format(type(group_name), str(group_name))
				_log.error(msg)
				raise RuntimeError(msg, group_name)
			return group_name
		except Exception as exc:
			msg = 'Can not group object "{0}" in object "{1}" ({2})'.format(child_name, root_name, repr(group_name))
			_log.error(msg)
			raise RuntimeError(msg, root_name, child_name, group_name) from exc

	def _join_objects(self, target: 'Object', children: 'Iterable[str]'):
		# log.info("Joining: %s <- %s", target.name, children)
		_commons.ensure_deselect_all_objects()
		for child_name in children:
			obj = _D.objects[child_name]
			obj.hide_set(False)
			obj.select_set(True)
			_commons.move_children_to_grandparent(obj)
		_commons.activate_object(target)
		_commons.ensure_op_finished(_bpy.ops.object.join(), name='bpy.ops.object.join')
		_commons.ensure_deselect_all_objects()
		# log.info("Joined: %s <- %s", target, children)
		pass
	
	def _call_before_join(self, root: 'str', join_to: 'str', group_name: 'Optional[str]', group_objs: 'Set[str]'):
		try:
			self.before_join(root, join_to, group_name, group_objs)
		except Exception as exc:
			msg = 'Error before_join: root={0}, join_to={1}, group_name={2}, group_objs={3}'.\
				format(root, join_to, group_name, group_objs)
			raise RuntimeError(msg, root, join_to, group_name, group_objs) from exc
	
	def _call_after_join(self, root: 'str', join_to: 'str', group_name: 'Optional[str]'):
		try:
			self.after_join(root, join_to, group_name)
		except Exception as exc:
			msg = 'Error after_join: root={0}, join_to={1}, group_name={2}'. \
				format(root, join_to, group_name)
			raise RuntimeError(msg, root, join_to, group_name) from exc
	
	def _process_root(self, root_name: 'str') -> 'int':
		# Поиск меш-объектов-детей root на этой же сцене.
		scene_objs = (self.scene or _C.scene).collection.objects
		children_queue = _deque()  # type: Deque[str]
		children = set()  # type: Set[str]
		children_queue.extend(x.name for x in _D.objects[root_name].children)
		while len(children_queue) > 0:
			child_name = children_queue.pop()
			child = _D.objects[child_name]
			children_queue.extend(x.name for x in child.children)
			if child_name not in scene_objs:
				continue
			if not isinstance(child.data, _bpy.types.Mesh):
				continue
			children.add(child_name)

		self._call_before_group(root_name, children)
		
		groups = dict()  # type: Dict[Optional[str], Set[str]]
		for child_name in children:
			group_name = self._call_group_child(root_name, child_name)
			if group_name is False:
				continue  # skip
			group = groups.get(group_name)
			if group is None:
				group = set()
				groups[group_name] = group
			group.add(child_name)
		
		# log.info('%s %s', root_name, repr(groups))
	
		def create_mesh_obj(name):
			new_mesh = _D.meshes.new(name + '-Mesh')
			new_obj = _D.objects.new(name, object_data=new_mesh)
			new_obj.name = name  # force rename
			scene_objs.link(new_obj)
			return new_obj
		
		# Далее намерено избегаем ссылок на root объект, т.к. объекты меняются
		# и можно отхватить ошибку StructRNA of type Object has been removed
		obj_group_count = 0
		for group_name, obj_group in groups.items():
			join_to = None
			if group_name is None:
				if isinstance(_D.objects[root_name].data, _bpy.types.Mesh):
					# root - Это меш, приклееваем к нему.
					join_to = _D.objects[root_name]
				elif self.force_mesh_root:
					# root - Это НЕ меш, но force_mesh_root.
					base_name = root_name
					old_root = _D.objects[root_name]
					old_root.name = base_name + '-Replaced'
					self.replaced_objects.add(old_root.name)
					join_to = create_mesh_obj(base_name)
					root_name = join_to.name  # Фактическое новое имя
					self.created_objects.add(root_name)
					join_to.parent = old_root.parent
					join_to.parent_type = 'OBJECT'
					join_to.location = old_root.location
					join_to.rotation_mode = old_root.rotation_mode
					join_to.rotation_axis_angle = old_root.rotation_axis_angle
					join_to.rotation_euler = old_root.rotation_euler
					join_to.rotation_quaternion = old_root.rotation_quaternion
					join_to.scale = old_root.scale
					for sub_child in old_root.children:  # type: Object
						sub_child.parent = join_to
				else:
					# root - Это НЕ меш, создаём подгруппу.
					join_to = create_mesh_obj(root_name + '-' + self.default_group)
					self.created_objects.add(join_to.name)
					join_to.parent = _D.objects[root_name]
					join_to.parent_type = 'OBJECT'
					_commons.identity_transform(join_to)
			else:
				join_to = create_mesh_obj(root_name + '-' + group_name)
				self.created_objects.add(join_to.name)
				join_to.parent = _D.objects[root_name]
				join_to.parent_type = 'OBJECT'
				_commons.identity_transform(join_to)
			self._call_before_join(root_name, join_to.name, group_name, obj_group)
			self._join_objects(join_to, obj_group)
			self._call_after_join(root_name, join_to.name, group_name)
			obj_group_count += len(obj_group)
		return obj_group_count
			
	def combine_meshes(self):
		self._check_roots()
		
		obj_n, obj_i, joins = len(self.roots_names), 0, 0
		reporter = _LambdaReporter(self.report_time)
		reporter.func = lambda r, t: _log.info(
			"Joining meshes: Roots=%d/%d, Joined=%d, Time=%.1f sec, ETA=%.1f sec...",
			obj_i, obj_n, joins, t, r.get_eta(1.0 * obj_i / obj_n)
		)
		
		for root_name in self.roots_names:
			joins += self._process_root(root_name)
			obj_i += 1
			reporter.ask_report(False)
		reporter.ask_report(True)
