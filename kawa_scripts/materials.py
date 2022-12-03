import bpy
from bpy.types import Object, Material, Image, Node, ShaderNode
from bpy.types import ShaderNodeTexImage, ShaderNodeNormalMap, ShaderNodeBsdfPrincipled, ShaderNodeOutputMaterial

from ._internals import log


class QuickBSDFConstructor:
	def __init__(self, name: str):
		self.name = name
		self._image_nodes = dict()  # type: dict[Image, ShaderNodeTexImage]
		self._material = None  # type: Material|None
		self._shader_node = None  # type: ShaderNode|ShaderNodeBsdfPrincipled|None
	
	def _prepare_node_shader(self):
		output = self._material.node_tree.nodes.new('ShaderNodeOutputMaterial')  # type: Node|ShaderNodeOutputMaterial
		output.location = (500, 0)
		self._shader_node = self._material.node_tree.nodes.new('ShaderNodeBsdfPrincipled')
		self._shader_node.location = (0, 0)
		self._shader_node.width = 400
		shader_output = next((out for out in self._shader_node.outputs if out.type == 'SHADER'), None)
		if shader_output is None:
			msg_node = f"{self._shader_node!r} ({self._shader_node.type!r}, {type(self._shader_node)!r}"
			log.raise_error(RuntimeError, f"Node {msg_node} does not have SHADER output.")
		self._material.node_tree.links.new(shader_output, output.inputs['Surface'])
		self._shader_node.inputs['Specular'].default_value = 0.0
		self._shader_node.inputs['Roughness'].default_value = 1.0
	
	def create_material(self):
		self._material = bpy.data.materials.get(self.name)
		if self._material is None:
			self._material = bpy.data.materials.new(self.name)
		self._material.use_nodes = True
		self._material.node_tree.nodes.clear()
		self._prepare_node_shader()
	
	def _relocate_images(self):
		image_nodes = list(self._image_nodes.values())
		for i in range(len(image_nodes)):
			image_nodes[i].location = (-1000, -300 * (i - len(image_nodes) / 3))
	
	def _prepare_node_shader_image(self, image: 'str|Image'):
		if isinstance(image, str):
			image = bpy.data.images[image]
		if not isinstance(image, Image):
			raise TypeError()
		
		node = self._image_nodes.get(image)
		if node is not None:
			return node
		
		node = self._material.node_tree.nodes.new('ShaderNodeTexImage')  # type: Node|ShaderNodeTexImage
		node.width = 600
		node.image = image
		node.interpolation = 'Cubic'
		
		self._image_nodes[image] = node
		self._relocate_images()
		return node
	
	def bind_image(self, name: 'str', image: 'str|Image', extension: 'str' = None, is_normal=False, is_alpha=False):
		shader_socket = self._shader_node.inputs[name]
		if shader_socket.is_linked:
			raise RuntimeError()
		
		image_node = self._prepare_node_shader_image(image)
		image_socket = image_node.outputs['Alpha' if is_alpha else 'Color']
		
		if extension is not None:
			image_node.extension = extension
		
		if is_normal:
			normal_node = self._material.node_tree.nodes.new('ShaderNodeNormalMap')  # type: Node|ShaderNodeNormalMap
			normal_node.location = (-300, image_node.location[1] - 50)
			self._material.node_tree.links.new(image_socket, normal_node.inputs['Color'])
			self._material.node_tree.links.new(normal_node.outputs['Normal'], shader_socket)
		else:
			self._material.node_tree.links.new(image_socket, shader_socket)
	
	def get_material(self):
		return self._material


__all__ = ['QuickBSDFConstructor']
