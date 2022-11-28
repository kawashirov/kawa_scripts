import bpy as _bpy
from collections.abc import Sequence as _Sequence
from collections.abc import Set as _Set
from . import commons as _commons
from . import objects as _objects
from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Dict, Union, Tuple, Set
	from bpy.types import Object, Material, Image, ShaderNodeOutputMaterial, ShaderNodeTexImage


def quick_create_principled_bsdf_material(
		name: str, images: 'Dict[str, Union[Image, Tuple[Image, Set[str]]]]', shader_type='ShaderNodeBsdfPrincipled'
) -> 'Material':
	material = _bpy.data.materials.get(name)
	if material is None:
		material = _bpy.data.materials.new(name)
	if material.name != name:
		material.name = name
	material.use_nodes = True
	
	nodes = material.node_tree.nodes
	links = material.node_tree.links
	nodes.clear()
	
	output = nodes.new('ShaderNodeOutputMaterial')  # type: ShaderNodeOutputMaterial
	output.location = (500, 0)
	shader = nodes.new(shader_type)
	shader.location = (0, 0)
	shader.width = 400
	shader_output = next((out for out in shader.outputs if out.type == 'SHADER'), None)
	if shader_output is None:
		raise RuntimeError(f"Node {shader!r} ({shader.type!r}, {type(shader)!r} does not have SHADER output. Is it shader-node?")
	links.new(shader_output, output.inputs['Surface'])
	
	for i, (key, value) in enumerate(images.items()):
		if key not in shader.inputs:
			raise RuntimeError(f"Node {shader!r} ({shader.type!r}, {type(shader)!r} does not have input {key!r}.")
		shader_input = shader.inputs[key]
		
		image, flags = None, None  # type: Image, Set[str]
		if isinstance(value, _bpy.types.Image):
			image, flags = value, set()
		elif isinstance(value, _Sequence) and len(value) == 2:
			image, flags = value
			if not isinstance(image, _bpy.types.Image) or not isinstance(flags, _Set):
				raise RuntimeError(f"Invalid value for key {key!r}: {value!r}")
		else:
			raise RuntimeError(f"Invalid value for key {key!r}: {value!r}")
		
		texture = nodes.new('ShaderNodeTexImage')  # type: ShaderNodeTexImage
		texture.location = (-1000, -300 * (i - len(images) / 3))
		texture.width = 600
		texture.image = image
		texture.interpolation = 'Cubic'
		
		if 'REPEAT' in flags:
			texture.extension = 'REPEAT'
		elif 'EXTEND' in flags:
			texture.extension = 'EXTEND'
		elif 'CLIP' in flags:
			texture.extension = 'CLIP'
		
		if 'NORMAL' in flags:
			normal_map = nodes.new('ShaderNodeNormalMap')  # type: ShaderNodeNormalMap
			normal_map.location = (-300, -300 * (i - len(images) / 3) - 100)
			links.new(texture.outputs['Color'], normal_map.inputs['Color'])
			links.new(normal_map.outputs['Normal'], shader_input)
		elif 'ALPHA' in flags:
			links.new(texture.outputs['Alpha'], shader_input)
		else:
			links.new(texture.outputs['Color'], shader_input)
	
	return material
