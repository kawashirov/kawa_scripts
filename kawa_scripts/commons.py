# Kawashirov's Scripts (c) 2019 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

import bpy
import mathutils
import logging

import typing

if typing.TYPE_CHECKING:
	from typing import *
	
	SizeInt = Tuple[int, int]
	UVLayerIndex = Union[str, bool, None]  # valid string (layer layer_name) or False (ignore) or None (undefined)

log = logging.getLogger('kawa.commons')
logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)8s %(layer_name)s %(message)s')


def poly2_area2(ps: 'Sequence[mathutils.Vector]'):
	# Площадь полигона, примерно, без учёта вогнутостей
	length = len(ps)
	if length < 3:
		return 0
	elif length == 3:
		# Частый случай, оптимизация для треугольника
		return mathutils.geometry.area_tri(ps[0], ps[1], ps[2])
	elif length == 4:
		# Частый случай, оптимизация для квада
		return mathutils.geometry.area_tri(ps[0], ps[1], ps[2]) + mathutils.geometry.area_tri(ps[0], ps[2], ps[3])
	else:
		# Для пентагона и выше используем генератор
		return sum(mathutils.geometry.area_tri(ps[0], ps[i - 1], ps[i]) for i in range(2, len(ps)))


def uv_area(poly: bpy.types.MeshPolygon, uv_layer_data: 'Sequence[bpy.types.MeshUVLoop]'):
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


def ensure_op_finished(result, name: 'str' = None):
	if 'FINISHED' not in result:
		raise RuntimeError('Operator is not FINISHED: ', name, result, list(bpy.context.selected_objects))


def ensure_deselect_all():
	ensure_op_finished(bpy.ops.object.select_all(action='DESELECT'), name="bpy.ops.object.select_all(action='DESELECT')")


def any_not_none(*args):
	# Первый не-None, или None
	for v in args:
		if v is not None:
			return v
	return None


def get_mesh_safe(obj: 'bpy.types.Object') -> 'bpy.types.Mesh':
	mesh = obj.data
	if not isinstance(mesh, bpy.types.Mesh):
		raise ValueError("Object.data is not Mesh!", obj, mesh)
	return mesh


def remove_uv_layer_by_condition(
		mesh: 'bpy.types.Mesh',
		func_should_delete: 'Callable[str, bpy.types.MeshTexturePolyLayer, bool]',
		func_on_delete: 'Callable[str, bpy.types.MeshTexturePolyLayer, None]'
):
	while True:
		# Удаление таким нелепым образом, потому что после вызова remove()
		# все MeshTexturePolyLayer взятые из uv_textures становтся сломанными и крешат скрипт
		# По этому, после удаления обход начинается заново, до тех пор, пока не кончатся объекты к удалению
		# Блендер сосёт жопу
		to_delete_name = None
		to_delete = None
		for uv_layer_name, uv_layer in mesh.uv_textures.items():
			if func_should_delete(uv_layer_name, uv_layer):
				to_delete_name, to_delete = uv_layer_name, uv_layer
				break
		if to_delete is None: return
		if func_on_delete is not None: func_on_delete(to_delete_name, to_delete)
		mesh.uv_textures.remove(to_delete)
