# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import collections.abc

import bpy as _bpy
import mathutils as _mu

from . import commons as _commons
from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Optional, List
	from bpy.types import Material, Node, NodeTree, NodeSocket, NodeLink, ShaderNode
	from bpy.types import NodeSocket, NodeSocketColor, NodeSocketFloat
	
	from bpy.types import ShaderNodeTexImage, ShaderNodeOutputMaterial, ShaderNodeOutputAOV

KAWA_BAKE_TARGET = 'KAWA_BAKE_TARGET'
KAWA_BAKE_DEFAULT = 'KAWA_BAKE_DEFAULT'
KAWA_BAKE_ALPHA = 'KAWA_BAKE_ALPHA'


def get_node_by_label(mat: 'Material', name: str, _type: type):
	nodes = mat.node_tree.nodes
	sh_default = nodes.get(name)
	if sh_default is not None and not isinstance(sh_default, _type):
		msg = "Has shader node with label {0}, but it has type {1} instead of {2}.".format(name, type(sh_default), _type)
		raise _commons.MaterialConfigurationError(mat, msg)
	if sh_default is None:
		sh_defaults = [n for n in nodes.values() if isinstance(n, _type) and n.label == name]
		if len(sh_defaults) > 1:
			raise _commons.MaterialConfigurationError(mat, "Has {0} shader nodes with label {1}.".format(len(sh_defaults), name))
		if len(sh_defaults) == 1:
			sh_default = sh_defaults[0]
			sh_default.name = name
	return sh_default


def get_socket_input_safe(socket: 'NodeSocket') -> 'Optional[NodeSocket]':
	# TODO
	# Легаси хуйня.
	# Возвращает выходной сокет, который подключено к node во входной сокет с именем name
	# При этом ни node, ни входа, ни подключения может не быть
	if socket is None or len(socket.links) != 1 or socket.links[0] is None:
		return None
	return socket.links[0].from_socket


def get_socket_outputs_safe(socket: 'NodeSocket') -> 'List[NodeSocket]':
	# TODO
	# Легаси хуйня.
	# Возвращает выходной сокет, который подключено к node во входной сокет с именем name
	# При этом ни node, ни входа, ни подключения может не быть
	return [socket.to_socket for link in socket.links]


def get_node_input_safe(node: 'Node', name: str) -> 'Optional[NodeSocket]':
	# Возвращает выходной сокет, который подключено к node во входной сокет с именем name
	# При этом ни node, ни входа, ни подключения может не быть
	if node is None or node.inputs is None:
		return None
	return get_socket_input_safe(node.inputs.get(name))


def prepare_teximage_node(mat: 'Material', name: str) -> 'ShaderNodeTexImage|Node':
	"""
	Gets ShaderNodeTexImage node by its name. Creates if missing.
	"""
	nodes = mat.node_tree.nodes
	n_teximage = get_node_by_label(mat, name, _bpy.types.ShaderNodeTexImage)
	if n_teximage is None:
		n_teximage = nodes.new('ShaderNodeTexImage')
		n_teximage.name = name
		n_teximage.label = name
	return n_teximage


def prepare_node_for_baking(mat: 'Material') -> 'ShaderNodeTexImage|Node':
	"""
	Cycles bakes into active texture node.
	Gets or creates node for baking named `'KAWA_BAKE_TARGET'`, activates it and deselects everything else.
	"""
	nodes = mat.node_tree.nodes
	n_bake = prepare_teximage_node(mat, KAWA_BAKE_TARGET)
	n_bake.interpolation = 'Cubic'
	for node in nodes:
		node.select = False
	n_bake.select = True
	nodes.active = n_bake
	return n_bake


def socket_copy_input(from_in_socket: 'NodeSocket|NodeSocketColor', to_in_socket: 'NodeSocket|NodeSocketColor', copy_default=False):
	"""
	Copies (single) link and to `from_in_socket` to `to_in_socket` too.
	Copies `default_value` too, but only COLOR->COLOR, VALUE->VALUE and VALUE->COLOR are supported.
	"""
	if from_in_socket.id_data != to_in_socket.id_data:
		raise ValueError(f"Sockets {from_in_socket!r} and {to_in_socket!r} from different node trees!")
	if from_in_socket.is_output:
		raise ValueError(f"Socket {from_in_socket!r} is output socket!")
	if to_in_socket.is_output:
		raise ValueError(f"Socket {to_in_socket!r} is output socket!")
	if to_in_socket.is_linked:
		raise ValueError(f"Socket {to_in_socket!r} already have a links: {to_in_socket.links!r}")
	
	if from_in_socket.is_linked:
		from_in_socket.id_data.links.new(from_in_socket.links[0].from_socket, to_in_socket)
	
	if copy_default:
		if from_in_socket.type == 'COLOR' and to_in_socket.type == 'COLOR':
			to_in_socket.default_value[:] = to_in_socket.default_value
		elif from_in_socket.type == 'VALUE' and to_in_socket.type == 'VALUE':
			to_in_socket.default_value = to_in_socket.default_value
		elif from_in_socket.type == 'VALUE' and to_in_socket.type == 'COLOR':
			value = to_in_socket.default_value
			to_in_socket.default_value[:] = (value, value, value, 1)
		else:
			m_from = f"{from_in_socket!r} ({from_in_socket.default_value!r})"
			m_to = f"{to_in_socket!r} ({to_in_socket.default_value!r})"
			raise ValueError(f"Can't copy default from {m_from} to {m_to}.")


def get_socket_aov(mat: 'Material', aov_name: 'str', aov_type: 'str') -> 'NodeSocket|NodeSocketFloat|NodeSocketColor|None':
	"""
	Finds `NodeSocket` of corresonding type from `ShaderNodeOutputAOV`
	with matching name `aov_name` and `aov_type` (`'VALUE'`, `'COLOR'`).
	Returns `None` if not found, raises `MaterialConfigurationError` if multiple found.
	"""
	if aov_type not in ('VALUE', 'COLOR'):
		raise ValueError(f"Invalid aov_type: {aov_type!r}")
	
	aov_sockets = list()
	for node in mat.node_tree.nodes:
		if node.type != 'OUTPUT_AOV' or not isinstance(node, _bpy.types.ShaderNodeOutputAOV):
			continue
		if node.name != aov_name:
			continue
		socket = node.inputs['Value' if aov_type == 'VALUE' else 'Color']
		links = socket.links  # type: tuple[NodeLink]
		if len(links) > 1:
			raise _commons.MaterialConfigurationError(mat, f"Soket {socket!r} has too many ({len(links)}/{socket.link_limit}) links {links!r}")
		aov_sockets.append(socket)
	
	if len(aov_sockets) > 1:
		raise _commons.MaterialConfigurationError(mat,
			f"Multiple ({len(aov_sockets)}) sockets found for AOV {aov_name!r} of type {aov_type!r}.")
	elif len(aov_sockets) < 1:
		return None
	else:
		return aov_sockets[0]


def create_aov(mat: 'Material', aov_name: 'str', aov_type: 'str', value=None) -> 'NodeSocket':
	"""
	Creates new "AOV Output" `ShaderNodeOutputAOV` with given `aov_name` and `aov_type` (`'VALUE'`, `'COLOR'`).
	If `value` is `NodeSocket`, creates link from given socket to the new "AOV Output" node.
	"""
	
	# Не используется.
	
	if aov_type not in ('VALUE', 'COLOR'):
		raise ValueError(f"Invalid aov_type: {aov_type!r}")
	aov_node = mat.node_tree.nodes.new('ShaderNodeOutputAOV')  # type: Node|ShaderNodeOutputAOV
	aov_node.name = aov_name
	
	aov_socket = aov_node.inputs['Value' if aov_type == 'VALUE' else 'Color']
	
	if isinstance(value, NodeSocket):
		if not value.is_output:
			raise ValueError(f"NodeSocket value must be output type! Got: {value!r}")
		mat.node_tree.links.new(value, aov_socket)
	elif isinstance(value, (int, float)):
		if aov_type == 'VALUE':
			aov_socket.default_value = value
		else:
			aov_socket.default_value[:] = (value, value, value, 1)
	elif isinstance(value, collections.abc.Sequence) and len(value) == 3 and aov_type == 'COLOR':
		aov_socket.default_value[:3] = value
	elif isinstance(value, collections.abc.Sequence) and len(value) == 4 and aov_type == 'COLOR':
		aov_socket.default_value[:] = value
	else:
		raise ValueError(f"Invalid value {value!r} for AOV socket.")
	
	return aov_socket


def get_link_surface(mat: 'Material', target='ANY') -> 'NodeLink|None':
	"""
	Finds `NodeLink` that connacts `ShaderNode` and `ShaderNodeOutputMaterial`
	with matching `target` type: 'ANY' (not 'ALL'), 'CYCLES' and 'EEVEE'.
	Returns `None` if not found, raises `MaterialConfigurationError` if multiple found.
	
	You can get nodes by `NodeLink.from_node`, `NodeLink.to_node` and sockets by `NodeLink.from_socket`, `NodeLink.to_socket`.
	"""
	surf_links = list()
	for node in mat.node_tree.nodes:
		# print(f'1: {node!r}')
		if node.type != 'OUTPUT_MATERIAL' or not isinstance(node, _bpy.types.ShaderNodeOutputMaterial):
			continue
		if target != 'ANY' and node.target != target and node.target != 'ALL':
			continue
		# print(f'2: {node!r}')
		socket = node.inputs['Surface']
		links = socket.links  # type: tuple[NodeLink]
		if len(links) < 1:
			continue
		if len(links) > socket.link_limit:
			raise _commons.MaterialConfigurationError(mat, f"Soket {socket!r} has too many ({len(links)}/{socket.link_limit}) links {links!r}")
		surf_links.append(links[0])
	
	if len(surf_links) > 1:
		raise _commons.MaterialConfigurationError(mat, f"Multiple ({len(surf_links)}) Surface Shader Output links found.")
	elif len(surf_links) < 1:
		return None
	else:
		return surf_links[0]


def get_output(mat: 'Material', strict=True, target=None) -> 'ShaderNodeOutputMaterial|None':
	# TODO
	# Не используется.
	# Находит Material Output
	nodes = mat.node_tree.nodes
	
	outputs = list()
	for node in mat.node_tree.nodes:
		if not isinstance(node, _bpy.types.ShaderNodeOutputMaterial):
			continue
		if target is not None and target != node.target:
			continue
		outputs.append(node)
	
	if len(outputs) > 1:
		if not strict:
			return None
		raise RuntimeError(f"Multiple ({len(outputs)}) shader output nodes in material {mat.name!r}.")
	elif len(outputs) < 1:
		return None
	else:
		return outputs[0]


def get_aov_output(mat: 'Material', name: 'str', strict=True) -> 'Optional[ShaderNodeOutputAOV]':
	# TODO
	# Не используется.
	# Находит Material Output
	nodes = mat.node_tree.nodes
	outputs = [n for n in nodes if isinstance(n, _bpy.types.ShaderNodeOutputAOV) and n.name == name]
	if len(outputs) > 1:
		if not strict:
			return None
		raise RuntimeError(f"Multiple ({len(outputs)}) AOV {name!r} nodes in material {mat.name!r}.")
	elif len(outputs) < 1:
		return None
	else:
		return outputs[0]


def get_material_output_socket(mat: 'Material') -> 'Optional[NodeSocket]':
	# TODO
	# Не используется.
	# Находит Material Output
	nodes = mat.node_tree.nodes
	outputs = [n for n in nodes if isinstance(n, _bpy.types.ShaderNodeOutputMaterial)]
	if len(outputs) != 1:
		return None
	return outputs[0].inputs.get('Surface')


def get_material_output_surface(mat: 'Material') -> 'Optional[ShaderNode]':
	# TODO
	# Не используется.
	# Находит node, который подключен как Surface Material Output
	# Срёт ошибкой, если нету или несколько ShaderNodeOutputMaterial или там кривые связи
	n_out = get_material_output_socket(mat)
	if n_out is None:
		raise _commons.MaterialConfigurationError(mat, "Can not find output socket.")
	n_sh_s = n_out.links[0].from_socket if len(n_out.links) == 1 else None
	if n_sh_s is None:
		raise _commons.MaterialConfigurationError(mat, "Can not find connected 'Surface' output shader.")
	return n_sh_s.node


def prepare_and_get_default_shader_node(mat: 'Material') -> 'ShaderNode':
	# TODO
	# Не используется.
	# Находет ShaderNode с именем KAWA_BAKE_DEFAULT
	# Если такого нет, то ищет с меткой KAWA_BAKE_DEFAULT
	# Если такого нет, то пытается понять что подключено в Surface
	# Если найдено, то убеждается, что имя и метка = KAWA_BAKE_DEFAULT
	# Срёт ошибками если метки выставлены не верно.
	sh_default = get_node_by_label(mat, KAWA_BAKE_DEFAULT, _bpy.types.ShaderNode)
	if sh_default is None:
		sh_default = get_material_output_surface(mat)
		if sh_default is None:
			raise _commons.MaterialConfigurationError(mat, "Can not find KAWA_BAKE_DEFAULT shader node.")
		sh_default.name = KAWA_BAKE_DEFAULT
		sh_default.label = KAWA_BAKE_DEFAULT
	return sh_default


def prepare_and_get_alpha_shader_node(mat: 'Material'):
	# TODO
	# Не используется.
	# Находет ShaderNode с именем KAWA_BAKE_ALPHA
	# Если такого нет, то ищет с меткой KAWA_BAKE_ALPHA
	try:
		nodes = mat.node_tree.nodes
		sh_default = prepare_and_get_default_shader_node(mat)
		sh_alpha = get_node_by_label(mat, KAWA_BAKE_ALPHA, _bpy.types.ShaderNodeEmission)
		if sh_alpha is None:
			sh_alpha = nodes.new('ShaderNodeEmission')
			sh_alpha.name = KAWA_BAKE_ALPHA
			sh_alpha.label = KAWA_BAKE_ALPHA
		sh_alpha_in = sh_alpha.inputs['Color']
		if sh_default is not None:
			# Если есть default шейдер, то размещаем новый над ним и пытаемся своровать 'Alpha'
			sh_alpha.location = sh_default.location + _mu.Vector((0, 200))
			n_alpha = get_node_input_safe(sh_default, 'Alpha')
			if n_alpha is not None and get_socket_input_safe(sh_alpha_in) is None:
				# Если ничего не забинджено в ALPHA шедер, то подрубаем из DEFAULT
				mat.node_tree.links.new(n_alpha, sh_alpha.inputs['Color'])
		return sh_alpha
	except Exception as exc:
		raise _commons.MaterialConfigurationError(mat, "Can not prepare ALPHA shader node") from exc
	
	sh_default = prepare_and_get_default_shader_node(mat)
	if sh_default is None:
		raise RuntimeError(mat, "There is no DEFAULT shader node, can not switch to ALPHA.")
	
	sh_alpha = prepare_and_get_alpha_shader_node(mat)
	if sh_alpha is None:
		raise RuntimeError(mat, "There is no ALPHA shader node, can not switch to ALPHA.")
	
	while len(output_s.links) > 0:
		mat.node_tree.links.remove(output_s.links[0])
	mat.node_tree.links.new(sh_alpha.outputs['Emission'], output_s)


def configure_for_baking_default(mat: 'Material'):
	# TODO broken
	# Подключает default шейдер на выход материала
	# Если не найден выход или DEFAULT, срёт ошибками
	
	n_out_s = get_material_output_socket(mat)
	if n_out_s is None:
		raise _commons.MaterialConfigurationError(mat, "Can not find output socket.")
	
	sh_default = prepare_and_get_default_shader_node(mat)
	if sh_default is None:
		raise _commons.MaterialConfigurationError(mat, "There is no DEFAULT shader node, can not switch to ALPHA.")
	
	sockets = [s for s in sh_default.outputs if s.type == 'SHADER']
	
	while len(n_out_s.links) > 0:
		mat.node_tree.links.remove(n_out_s.links[0])
	
	mat.node_tree.links.new(sockets[0], n_out_s)
