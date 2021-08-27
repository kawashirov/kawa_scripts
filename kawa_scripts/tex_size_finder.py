# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
"""
Tool for figuring out a texture size of material.
See `kawa_scripts.tex_size_finder.TexSizeFinder`.
"""

import collections as _collections

import bpy as _bpy

from ._internals import log as _log

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Optional, Tuple, Iterator, Deque, Set
	from bpy.types import Material, Image, ShaderNodeTree, ShaderNodeTexImage


class TexSizeFinder:
	"""
	Base class for figuring out a texture size of material.
	You must extend this class with required and necessary methods for your case.
	
	Finds all Images used by `ShaderNodeTree` of a given `Material`.
	User can override what is counted for size (`should_count_image` and `should_count_node`)
	or how it's counted (`mat_size`).
	
	This is intended to be used in conjunction with `kawa_scripts.atlas_baker.BaseAtlasBaker`
	(in overridden `kawa_scripts.atlas_baker.BaseAtlasBaker.get_material_size`),
	but not necessary, you can provide material sizes by you self.
	"""
	
	def __init__(self):
		pass
	
	def should_count_image(self, image: 'Image') -> bool:
		"""
		User can override this to tell what used Images should be counted for size. By default all Nodes are counted.
		For example, you can ignore `Non-Color` images.
		"""
		return True
	
	def should_count_node(self, node: 'ShaderNodeTexImage') -> bool:
		"""
		User can override this to tell what Image Nodes should be counted for size. By default all Nodes are counted.
		"""
		return True
	
	def nodeteximage_size(self, node: 'ShaderNodeTexImage') -> 'Optional[Tuple[float, float]]':
		if node is None or node.image is None:
			return None
		if not self.should_count_node(node):
			return None
		# TODO пока что не чётко определяется использование
		# надо сделать поиск нодов, которые привязаны к выходу и искать текстуры среди них
		if not any(output.is_linked for output in node.outputs):
			return None
		image = node.image
		if not self.should_count_image(image):
			return None
		return tuple(image.size)
	
	def iterate_nodes(self, node_tree: 'ShaderNodeTree') -> 'Iterator[ShaderNodeTexImage]':
		node_trees = _collections.deque()  # type: Deque[ShaderNodeTree]
		node_trees.append(node_tree)
		node_trees_history = set()  # type: Set[ShaderNodeTree]
		while len(node_trees) > 0:
			node_tree = node_trees.pop()
			if node_tree is None or node_tree.nodes is None or node_tree in node_trees_history:
				continue
			node_trees_history.add(node_tree)
			for node in node_tree.nodes:
				if isinstance(node, _bpy.types.ShaderNodeTexImage) and node.image is not None:
					yield node
				elif isinstance(node, _bpy.types.ShaderNodeGroup):
					node_trees.append(node.node_tree)
	
	def iterate_sizes(self, node_tree: 'ShaderNodeTree') -> 'Iterator[Tuple[float, float]]':
		for node in self.iterate_nodes(node_tree):
			size = self.nodeteximage_size(node)
			if size is not None:
				yield size
	
	def avg_mat_size(self, mat: 'Material') -> 'Optional[Tuple[float, float]]':
		""" Returns average found size of all counted images in Shader Note Tree of Material or None. """
		# Расчёт среднего размера текстур используемых материалом
		# Поиск нодов ShaderNodeTexImage, в которые используются выходы и картинка подключена
		sw, sh, count = 0, 0, 0
		for w, h in self.iterate_sizes(mat.node_tree):
			sw += w
			sh += h
			count += 1
		return (float(sw) / count, float(sh) / count) if count > 0 and sw > 0 and sh > 0 else None
	
	def max_mat_size(self, mat: 'Material') -> 'Optional[Tuple[float, float]]':
		""" Returns maximum found size of all counted images in Shader Note Tree of Material or None. """
		return max((s for s in self.iterate_sizes(mat.node_tree)), key=lambda x: x[0] * x[1], default=None)
	
	def mat_size(self, mat: 'Material') -> 'Optional[Tuple[float, float]]':
		""" Returns found size of Material or None. By default is `max_mat_size`. User can override this. """
		return self.max_mat_size(mat)  # default
