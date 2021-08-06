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
import time

import bpy
from mathutils import Vector, Quaternion, Matrix
from mathutils.geometry import area_tri

if typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *
	
log = logging.getLogger('kawa.commons')


class ConfigurationError(RuntimeError):
	# Ошибка конфигурации
	pass


class MaterialConfigurationError(ConfigurationError):
	def __init__(self, mat, msg: str):
		self.material = mat
		msg = 'Material={0}: {1}'.format(mat, msg)
		super().__init__(msg)


def common_str_slots(obj, keys: 'Iterable[str]', exclude: 'Collection[str]' = tuple()) -> 'str':
	return str(type(obj).__name__) + str({
		key: getattr(obj, key, None) for key in keys if key not in exclude and getattr(obj, key, None) is not None
	})


def poly2_area2(ps: 'Sequence[Vector]'):
	# Площадь полигона, примерно, без учёта вогнутостей
	length = len(ps)
	if length < 3:
		return 0
	elif length == 3:
		# Частый случай, оптимизация для треугольника
		return area_tri(ps[0], ps[1], ps[2])
	elif length == 4:
		# Частый случай, оптимизация для квада
		return area_tri(ps[0], ps[1], ps[2]) + area_tri(ps[0], ps[2], ps[3])
	else:
		# Для пентагона и выше - Формула Гаусса
		s = ps[length - 1].x * ps[0].y - ps[0].x * ps[length - 1].y
		for i in range(length - 1):
			s += ps[i].x * ps[i + 1].y
			s -= ps[i + 1].x * ps[i].y
		return 0.5 * abs(s)


def uv_area(poly: 'MeshPolygon', uv_layer_data: 'Sequence[MeshUVLoop]'):
	# tuple чуть-чуть быстрее на малых длинах, тестил через timeit
	return poly2_area2(tuple(uv_layer_data[loop].uv for loop in poly.loop_indices))


def is_none_or_bool(value: 'Optional[bool]') -> 'bool':
	return value is None or isinstance(value, bool)


def is_positive_int(pint: 'int') -> 'bool':
	return isinstance(pint, int) and pint > 0


def is_positive_float(pfloat: 'float') -> 'bool':
	return (isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat > 0


def is_none_or_positive_float(pfloat: 'float') -> 'bool':
	return pfloat is None or ((isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat > 0)


def is_positive_or_zero_float(pfloat: 'float') -> 'bool':
	return (isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat >= 0


def is_none_or_positive_or_zero_float(pfloat: 'float') -> 'bool':
	return pfloat is None or ((isinstance(pfloat, int) or isinstance(pfloat, float)) and pfloat >= 0)


def is_valid_size_int(size: 'Tuple[int, int]') -> 'bool':
	return isinstance(size, tuple) and len(size) == 2 and is_positive_int(size[0]) and is_positive_int(size[1])


def is_valid_size_float(size: 'Tuple[float, float]') -> 'bool':
	return isinstance(size, tuple) and len(size) == 2 and is_positive_float(size[0]) and is_positive_float(size[1])


def is_valid_string(string: 'str') -> 'bool':
	return isinstance(string, str) and len(string) > 0


def is_none_or_valid_string(string: 'str') -> 'bool':
	return string is None or (isinstance(string, str) and len(string) > 0)


def identity_transform(obj: 'Object'):
	obj.location = Vector.Fill(3, 0.0)
	obj.rotation_mode = 'QUATERNION'
	obj.rotation_quaternion = Quaternion()
	obj.scale = Vector.Fill(3, 1.0)


def copy_transform(from_obj: 'Object', to_obj: 'Object'):
	to_obj.location = from_obj.location
	to_obj.rotation_mode = from_obj.rotation_mode
	to_obj.rotation_axis_angle = from_obj.rotation_axis_angle
	to_obj.rotation_euler = from_obj.rotation_euler
	to_obj.rotation_quaternion = from_obj.rotation_quaternion
	to_obj.scale = from_obj.scale


def move_children_to_grandparent(obj: 'Object'):
	for child in obj.children:
		set_parent_keep_world(child, obj.parent)


def set_parent_keep_world(child: 'Object', parent: 'Object'):
	m = child.matrix_world.copy()
	child.parent = parent
	child.parent_type = 'OBJECT'
	child.matrix_parent_inverse = Matrix.Identity(4)
	child.matrix_world = m


def fix_matrix(obj: 'Object'):
	identity = Matrix.Identity(4)
	if obj.parent_type != 'OBJECT' or obj.matrix_parent_inverse == identity:
		return False
	mw = obj.matrix_world.copy()
	obj.matrix_parent_inverse = identity
	obj.parent_type = 'OBJECT'
	obj.matrix_world = mw
	return True


def ensure_op_result(result: 'Iterable[str]', allowed_results: 'Iterable[str]', **kwargs):
	if set(result) >= set(allowed_results):
		raise RuntimeError('Operator has invalid result:', result, allowed_results, list(bpy.context.selected_objects), kwargs)


def ensure_op_finished(result, **kwargs):
	if 'FINISHED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', result, list(bpy.context.selected_objects), kwargs)


def ensure_op_finished_or_cancelled(result, **kwargs):
	if 'FINISHED' not in result and 'CANCELLED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', result, list(bpy.context.selected_objects), kwargs)


def select_set_all(objects: 'Iterable[Object]', state: bool):
	for obj in objects:
		try:
			obj.hide_set(False)
			obj.select_set(state)
		except Exception as exc:
			log.error("%s", exc)
			log.error("%s", repr(objects))
			raise exc
		

def activate_object(obj: 'Object'):
	obj.hide_set(False)
	obj.select_set(True)
	bpy.context.view_layer.objects.active = obj


def activate_objects(objs: 'Iterable[Object]'):
	for obj in objs:
		activate_object(obj)


def ensure_deselect_all_objects():
	# ensure_op_finished(bpy.ops.object.select_all(action='DESELECT'), name="bpy.ops.object.select_all(action='DESELECT')")
	# Это быстрее, чем оператор, и позволяет отжать скрытые объекты
	while len(bpy.context.selected_objects) > 0:
		bpy.context.selected_objects[0].select_set(False)


def ensure_selected_single(selected_object, *args):
	if len(bpy.context.selected_objects) != 1:
		raise AssertionError(
			"len(bpy.context.selected_objects) != 1 or selected_object not in bpy.context.selected_objects",
			len(bpy.context.selected_objects), bpy.context.selected_objects, selected_object, args
		)
	if selected_object is not None and selected_object not in bpy.context.selected_objects:
		raise AssertionError(
			"selected_object not in bpy.context.selected_objects",
			bpy.context.selected_objects, selected_object, args
		)


def repack_active_uv(
		obj: 'Object', get_scale: 'Optional[Callable[[Material], float]]' = None,
		rotate: 'bool' = None, margin: 'float' = 0.0
):
	e = ensure_op_finished
	try:
		ensure_deselect_all_objects()
		activate_object(obj)
		# Перепаковка...
		e(bpy.ops.object.mode_set_with_submode(mode='EDIT', mesh_select_mode={'FACE'}), name='object.mode_set_with_submode')
		e(bpy.ops.mesh.reveal(select=True), name='mesh.reveal')
		e(bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
		bpy.context.scene.tool_settings.use_uv_select_sync = True
		area_type = bpy.context.area.type
		try:
			bpy.context.area.type = 'IMAGE_EDITOR'
			bpy.context.area.ui_type = 'UV'
			e(bpy.ops.uv.reveal(select=True), name='uv.reveal')
			e(bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
			e(bpy.ops.uv.select_all(action='SELECT'), name='uv.select_all')
			e(bpy.ops.uv.average_islands_scale(), name='uv.average_islands_scale')
			for index in range(len(obj.material_slots)):
				scale = 1.0
				if get_scale is not None:
					scale = get_scale(obj.material_slots[index].material)
				if scale <= 0 or scale == 1.0:
					continue
				bpy.context.scene.tool_settings.use_uv_select_sync = True
				e(bpy.ops.mesh.select_all(action='DESELECT'), name='mesh.select_all', index=index)
				e(bpy.ops.uv.select_all(action='DESELECT'), name='uv.select_all', index=index)
				obj.active_material_index = index
				if 'FINISHED' in bpy.ops.object.material_slot_select():
					# Может быть не FINISHED если есть не использованые материалы
					e(bpy.ops.uv.select_linked(), name='uv.select_linked', index=index)
					e(bpy.ops.transform.resize(value=(scale, scale, scale)), name='transform.resize', value=scale, index=index)
			e(bpy.ops.mesh.select_all(action='SELECT'), name='mesh.select_all')
			e(bpy.ops.uv.select_all(action='SELECT'), name='uv.select_all')
			e(bpy.ops.uv.pack_islands(rotate=rotate, margin=margin), name='uv.pack_islands')
			e(bpy.ops.uv.select_all(action='DESELECT'), name='uv.select_all')
			e(bpy.ops.mesh.select_all(action='DESELECT'), name='mesh.select_all')
		finally:
			bpy.context.area.type = area_type
	finally:
		e(bpy.ops.object.mode_set(mode='OBJECT'), name='object.mode_set')


def any_not_none(*args):
	# Первый не-None, или None
	for v in args:
		if v is not None:
			return v
	return None


def get_mesh_safe(obj: 'Object') -> 'Mesh':
	mesh = obj.data
	if not isinstance(mesh, bpy.types.Mesh):
		raise ValueError("Object.data is not Mesh!", obj, mesh)
	return mesh


def remove_all_geometry(obj: 'Object'):
	import bmesh
	# Очистка геометрии
	bm = bmesh.new()
	try:
		mesh = get_mesh_safe(obj)
		# Дегенеративные уебки, почему в Mesh нет API для удаления геометрии?
		bm.from_mesh(mesh)
		bm.clear()  # TODO optimize?
		bm.to_mesh(mesh)
	finally:
		bm.free()


def apply_all_modifiers(obj: 'Object') -> 'int':
	prev_active = bpy.context.view_layer.objects.active
	modifc = len(obj.modifiers)
	while len(obj.modifiers) > 0:
		modifier = next(iter(obj.modifiers))
		# log.info("Applying Modifier='%s' on Object='%s'...", modifier.name, obj.name)
		obj.select_set(True)
		obj.hide_set(False)
		bpy.context.view_layer.objects.active = obj
		if bpy.app.version >= (2, 90, 0):
			bpy.ops.object.modifier_apply(modifier=modifier.name)
		else:
			bpy.ops.object.modifier_apply(apply_as='DATA', modifier=modifier.name)
	bpy.context.view_layer.objects.active = prev_active
	return modifc


def remove_all_shape_keys(obj: 'Object'):
	mesh = get_mesh_safe(obj)
	while mesh.shape_keys is not None and len(mesh.shape_keys.key_blocks) > 0:
		sk = mesh.shape_keys.key_blocks[0]
		# Я ебал в рот того, кто придумал удалять шейпкеи из меши через интерфейс объекта
		obj.shape_key_remove(sk)


def remove_all_uv_layers(obj: 'Object'):
	mesh = get_mesh_safe(obj)
	while len(mesh.uv_layers) > 0:
		mesh.uv_layers.remove(mesh.uv_layers[0])


def remove_all_vertex_colors(obj: 'Object'):
	mesh = get_mesh_safe(obj)
	while len(mesh.vertex_colors) > 0:
		mesh.vertex_colors.remove(mesh.vertex_colors[0])


def remove_all_material_slots(obj: 'Object', slots=0):
	while len(obj.material_slots) > slots:
		bpy.context.view_layer.objects.active = obj
		ensure_op_finished(bpy.ops.object.material_slot_remove(), name='bpy.ops.object.material_slot_remove')


def remove_uv_layer_by_condition(
		mesh: 'Mesh',
		func_should_delete: 'Callable[str, MeshTexturePolyLayer, bool]',
		func_on_delete: 'Callable[str, MeshTexturePolyLayer, None]'
):
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


def find_objects_with_material(material: 'Material', where: 'Iterable[Object]' = None) -> 'Set[Object]':
	objects = set()
	if where is None:
		where = bpy.context.scene.objects
	for obj in where:
		if not isinstance(obj.data, bpy.types.Mesh):
			continue
		for slot in obj.material_slots:
			if slot.material == material:
				objects.add(obj)
	return objects


def is_parent(parent_object: 'Object', child_object: 'Object') -> 'bool':
	obj = child_object
	while obj is not None:
		if parent_object == obj:
			return True
		obj = obj.parent
	return False


def find_all_child_objects(parent_object: 'Object', where: 'Optional[Container[Object]]' = None) -> 'Set[Object]':
	child_objects = set()
	deque = collections.deque()  # type: Deque[Object]
	deque.append(parent_object)
	while len(deque) > 0:
		child_obj = deque.pop()
		deque.extend(child_obj.children)
		if where is not None and child_obj not in where:
			continue
		child_objects.add(child_obj)
	return child_objects


def merge_same_material_slots(obj: 'Object'):
	# Объединяет слоты с одинаковыми материалами:
	# Сначала объединяет индексы, затем удаляет освободившиеся слоты.
	# Игнорирует пустые слоты
	ensure_deselect_all_objects()
	activate_object(obj)
	mesh = get_mesh_safe(obj)
	# Все материалы используемые на объекте
	mats = set()
	run_op = False
	for slot in obj.material_slots:
		if slot is None or slot.material is None:
			continue
		mats.add(slot.material)
	for proc_mat in mats:
		indices = list()
		for slot in range(len(obj.material_slots)):
			if obj.material_slots[slot].material is proc_mat:
				indices.append(slot)
		if len(indices) < 2:
			continue
		run_op = True
		main_idx = indices[0]
		for idx in indices[1:]:
			for poly in mesh.polygons:
				if poly.material_index == idx:
					poly.material_index = main_idx
	if run_op:
		ensure_op_finished_or_cancelled(
			bpy.ops.object.material_slot_remove_unused(), name='bpy.ops.object.material_slot_remove_unused'
		)
	ensure_deselect_all_objects()


_K = typing.TypeVar('_K')
_V = typing.TypeVar('_V')


def dict_get_or_add(_dict: 'Dict[_K,_V]', _key: 'Optional[_K]', _creator: 'Callable[[],_V]') -> '_V':
	value = _dict.get(_key)
	if value is None:
		value = _creator()
		_dict[_key] = value
	return value


class AbstractReporter:
	def __init__(self, report_time=5.0):
		self.report_time = report_time
		self.time_begin = time.perf_counter()
		self.time_progress = time.perf_counter()
	
	def get_eta(self, progress) -> 'float':
		time_passed = self.time_progress - self.time_begin
		time_total = time_passed / progress
		return time_total - time_passed
	
	def do_report(self, time_passed):
		raise NotImplementedError('do_report')
	
	def ask_report(self, force=False):
		now = time.perf_counter()
		if force is False and now - self.time_progress < self.report_time:
			return
		self.time_progress = now
		self.do_report(now - self.time_begin)


class LambdaReporter(AbstractReporter):
	def __init__(self, *args, **kwargs):
		super().__init__(*args, **kwargs)
		self.func = None  # type: Callable[[LambdaReporter, float], None]
		
	def do_report(self, time_passed):
		self.func(self, time_passed)
