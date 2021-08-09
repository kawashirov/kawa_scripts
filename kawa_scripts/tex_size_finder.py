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

import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *

import logging as _logging
_log = _logging.getLogger('kawa.tex_size_finder')


class TexSizeFinder:

	def __init__(self):
		pass
	
	def should_count_image(self, image: 'Image') -> bool:
		return True
	
	def should_count_node(self, node: 'ShaderNodeTexImage') -> bool:
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
		node_trees = _deque()  # type: Deque[ShaderNodeTree]
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
		# Расчёт среднего размера текстур используемых материалом
		# Поиск нодов ShaderNodeTexImage, в которые используются выходы и картинка подключена
		sw, sh, count = 0, 0, 0
		for w, h in self.iterate_sizes(mat.node_tree):
			sw += w
			sh += h
			count += 1
		return (float(sw) / count, float(sh) / count) if count > 0 and sw > 0 and sh > 0 else None
	
	def max_mat_size(self, mat: 'Material') -> 'Optional[Tuple[float, float]]':
		return max((s for s in self.iterate_sizes(mat.node_tree)), key=lambda x: x[0]*x[1], default=None)

	def mat_size(self, mat: 'Material') -> 'Optional[Tuple[float, float]]':
		return self.max_mat_size(mat)  # default
