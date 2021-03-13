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
import bpy
import mathutils

from .commons import MaterialConfigurationError

if typing.TYPE_CHECKING:
	from typing import *
	from bpy import *
	
log = logging.getLogger('kawa.shader_nodes')


KAWA_BAKE_TARGET = 'KAWA_BAKE_TARGET'
KAWA_BAKE_DEFAULT = 'KAWA_BAKE_DEFAULT'
KAWA_BAKE_ALPHA = 'KAWA_BAKE_ALPHA'


def get_shader_node_by_label(mat: 'bpy.types.Material', name: str, _type: type):
	nodes = mat.node_tree.nodes
	sh_default = nodes.get(name)
	if sh_default is not None and not isinstance(sh_default, _type):
		msg = "Has shader node with label {0}, but it has type {1} instead of {2}.".format(name, type(sh_default), _type)
		raise MaterialConfigurationError(mat, msg)
	if sh_default is None:
		sh_defaults = [n for n in nodes.values() if isinstance(n, _type) and n.label == name]
		if len(sh_defaults) > 1:
			raise MaterialConfigurationError(mat, "Has {0} shader nodes with label {1}.".format(len(sh_defaults), name))
		if len(sh_defaults) == 1:
			sh_default = sh_defaults[0]
			sh_default.name = name
	return sh_default


def get_socket_input_safe(socket: 'bpy.types.NodeSocket') -> 'Optional[bpy.types.NodeSocket]':
	# Возвращает выходной сокет, который подключено к node во входной сокет с именем name
	# При этом ни node, ни входа, ни подключения может не быть
	if socket is None or len(socket.links) != 1 or socket.links[0] is None:
		return None
	return socket.links[0].from_socket


def get_socket_outputs_safe(socket: 'bpy.types.NodeSocket') -> 'List[bpy.types.NodeSocket]':
	# Возвращает выходной сокет, который подключено к node во входной сокет с именем name
	# При этом ни node, ни входа, ни подключения может не быть
	return [socket.to_socket for link in socket.links]


def get_node_input_safe(node: 'bpy.types.Node', name: str) -> 'Optional[bpy.types.NodeSocket]':
	# Возвращает выходной сокет, который подключено к node во входной сокет с именем name
	# При этом ни node, ни входа, ни подключения может не быть
	if node is None or node.inputs is None:
		return None
	return get_socket_input_safe(node.inputs.get(name))


def prepare_and_get_teximage_node(mat: 'bpy.types.Material', name: str) -> 'bpy.types.ShaderNodeTexImage':
	nodes = mat.node_tree.nodes
	n_teximage = get_shader_node_by_label(mat, name, bpy.types.ShaderNodeTexImage)
	if n_teximage is None:
		n_teximage = nodes.new('ShaderNodeTexImage')
		n_teximage.name = name
		n_teximage.label = name
	return n_teximage


def prepare_and_get_node_for_baking(mat: 'bpy.types.Material') -> 'bpy.types.ShaderNodeTexImage':
	# Cycles запекает в активный TEX_IMAGE
	# Возвращает или создает новый ShaderNodeTexImage
	# Даёт ему имя KAWA_BAKE_TARGET
	# Делает его выбраным и активным
	nodes = mat.node_tree.nodes
	n_bake = prepare_and_get_teximage_node(mat, KAWA_BAKE_TARGET)
	for node in nodes:
		node.select = False
	n_bake.select = True
	nodes.active = n_bake
	return n_bake


def get_material_output(mat: 'bpy.types.Material') -> 'Optional[bpy.types.ShaderNodeOutputMaterial]':
	# Находит Material Output
	nodes = mat.node_tree.nodes
	outputs = [n for n in nodes if isinstance(n, bpy.types.ShaderNodeOutputMaterial)]
	if len(outputs) != 1:
		return None
	return outputs[0]


def get_material_output_socket(mat: 'bpy.types.Material') -> 'Optional[bpy.types.NodeSocket]':
	# Находит Material Output
	nodes = mat.node_tree.nodes
	outputs = [n for n in nodes if isinstance(n, bpy.types.ShaderNodeOutputMaterial)]
	if len(outputs) != 1:
		return None
	return outputs[0].inputs.get('Surface')


def get_material_output_surface(mat: 'bpy.types.Material') -> 'Optional[bpy.types.ShaderNode]':
	# Находит node, который подключен как Surface Material Output
	# Срёт ошибкой, если нету или несколько ShaderNodeOutputMaterial или там кривые связи
	n_out = get_material_output_socket(mat)
	if n_out is None:
		raise MaterialConfigurationError(mat, "Can not find output socket.")
	n_sh_s = n_out.links[0].from_socket if len(n_out.links) == 1 else None
	if n_sh_s is None:
		raise MaterialConfigurationError(mat, "Can not find connected 'Surface' output shader.")
	return n_sh_s.node


def prepare_and_get_default_shader_node(mat: 'bpy.types.Material') -> 'bpy.types.ShaderNode':
	# Находет ShaderNode с именем KAWA_BAKE_DEFAULT
	# Если такого нет, то ищет с меткой KAWA_BAKE_DEFAULT
	# Если такого нет, то пытается понять что подключено в Surface
	# Если найдено, то убеждается, что имя и метка = KAWA_BAKE_DEFAULT
	# Срёт ошибками если метки выставлены не верно.
	sh_default = get_shader_node_by_label(mat, KAWA_BAKE_DEFAULT, bpy.types.ShaderNode)
	if sh_default is None:
		sh_default = get_material_output_surface(mat)
		if sh_default is None:
			raise MaterialConfigurationError(mat, "Can not find KAWA_BAKE_DEFAULT shader node.")
		sh_default.name = KAWA_BAKE_DEFAULT
		sh_default.label = KAWA_BAKE_DEFAULT
	return sh_default


def prepare_and_get_alpha_shader_node(mat: 'bpy.types.Material'):
	# Находет ShaderNode с именем KAWA_BAKE_ALPHA
	# Если такого нет, то ищет с меткой KAWA_BAKE_ALPHA
	try:
		nodes = mat.node_tree.nodes
		sh_default = prepare_and_get_default_shader_node(mat)
		sh_alpha = get_shader_node_by_label(mat, KAWA_BAKE_ALPHA, bpy.types.ShaderNodeEmission)
		if sh_alpha is None:
			sh_alpha = nodes.new('ShaderNodeEmission')
			sh_alpha.name = KAWA_BAKE_ALPHA
			sh_alpha.label = KAWA_BAKE_ALPHA
		sh_alpha_in = sh_alpha.inputs['Color']
		if sh_default is not None:
			# Если есть default шейдер, то размещаем новый над ним и пытаемся своровать 'Alpha'
			sh_alpha.location = sh_default.location + mathutils.Vector((0, 200))
			n_alpha = get_node_input_safe(sh_default, 'Alpha')
			if n_alpha is not None and get_socket_input_safe(sh_alpha_in) is None:
				# Если ничего не забинджено в ALPHA шедер, то подрубаем из DEFAULT
				mat.node_tree.links.new(n_alpha, sh_alpha.inputs['Color'])
		return sh_alpha
	except Exception as exc:
		raise MaterialConfigurationError(mat, "Can not prepare ALPHA shader node") from exc
	
	sh_default = prepare_and_get_default_shader_node(mat)
	if sh_default is None:
		raise RuntimeError(mat, "There is no DEFAULT shader node, can not switch to ALPHA.")
	
	sh_alpha = prepare_and_get_alpha_shader_node(mat)
	if sh_alpha is None:
		raise RuntimeError(mat, "There is no ALPHA shader node, can not switch to ALPHA.")
	
	while len(output_s.links) > 0:
		mat.node_tree.links.remove(output_s.links[0])
	mat.node_tree.links.new(sh_alpha.outputs['Emission'], output_s)


def configure_for_baking_default(mat: 'bpy.types.Material'):
	# TODO broken
	# Подключает default шейдер на выход материала
	# Если не найден выход или DEFAULT, срёт ошибками
	
	n_out_s = get_material_output_socket(mat)
	if n_out_s is None:
		raise MaterialConfigurationError(mat, "Can not find output socket.")
	
	sh_default = prepare_and_get_default_shader_node(mat)
	if sh_default is None:
		raise MaterialConfigurationError(mat, "There is no DEFAULT shader node, can not switch to ALPHA.")
	
	sockets = [s for s in sh_default.outputs if s.type == 'SHADER']
	
	while len(n_out_s.links) > 0:
		mat.node_tree.links.remove(n_out_s.links[0])
	
	mat.node_tree.links.new(sockets[0], n_out_s)
