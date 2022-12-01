# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import typing
from collections import deque

import bpy
from bpy.types import Scene, Object

from .._internals import log
from .. import objects, armature, meshes
from . import common as b_common


class CommonAvatarBuilder(b_common.CommonBuilder):
	def __init__(self):
		super().__init__()
		self.roots = set()  # type: set[Object]
		self._root_aramture = None  # type: Object|None
	
	def _merge_submeshes(self):
		pass
	
	def _find_root_armature(self):
		arms = list(obj for obj in self.ensure_processing_scene().objects if armature.is_armature_object(obj))
		if len(arms) < 1:
			raise RuntimeError("Armatures not found!")
		if len(arms) > 1:
			raise RuntimeError(f"Multiple armatures not found: {arms!r}")
		self._root_aramture = arms[0]
	
	def _join_submeshes(self):
		joins = list()
		for mesh in self._root_aramture.children:  # type: Object
			if mesh.name.startswith('_'):
				continue
			if not meshes.is_mesh_object(mesh):
				continue
			submeshes = list(submesh.name for submesh in mesh.children if meshes.is_mesh_object(submesh))
			if len(submeshes) > 0:
				joins.append((submeshes, mesh.name))
		for submeshes, mesh in joins:
			objects.join(submeshes, mesh)
	
	def build_objects(self):
		self.clear_processing_scene()
		
		self._instantiate()
		
		self._find_root_armature()
		self._reveal_hidden()
		
		self._merge_weights()
		self._process_shapekeys()
		self._process_attributes()
		self._remove_nonopaque_if_necessary()
		self._remove_unused_materials_slots()
		self._remove_empty_vertexgroups()
		self._finalize_geometry()
		
		self._remove_unused_bones()
		
		self._join_submeshes()


__all__ = ['CommonAvatarBuilder']
