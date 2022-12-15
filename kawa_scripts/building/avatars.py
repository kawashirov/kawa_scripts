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
from abc import ABC
from collections import deque

import bpy
from bpy.types import Scene, Object, Mesh, ShapeKey, Attribute

from .._internals import log
from .. import objects, armature, meshes
from . import common as b_common


class CommonAvatarBuilder(b_common.CommonBuilder, ABC):
	def _find_root_armature(self):
		arms = list(obj for obj in self.ensure_processing_scene().objects if armature.is_armature_object(obj))
		if len(arms) < 1:
			raise RuntimeError("Armatures not found!")
		if len(arms) > 1:
			raise RuntimeError(f"Multiple armatures not found: {arms!r}")
		return arms[0]
	
	def _join_submeshes(self):
		joins = list()
		_root_aramture = self._find_root_armature()
		for mesh in _root_aramture.children:  # type: Object
			if mesh.name.startswith('_'):
				continue
			if not meshes.is_mesh_object(mesh):
				continue
			submeshes = list(submesh.name for submesh in mesh.children if meshes.is_mesh_object(submesh))
			if len(submeshes) > 0:
				joins.append((submeshes, mesh.name))
		for submeshes, mesh in joins:
			objects.join(submeshes, mesh)
	
	def build_avatar(self):
		self.clear_processing_scene()
		
		self._instantiate()
		
		self._find_root_armature()
		self._reveal_hidden()
		
		self._merge_weights()
		self._process_shapekeys()
		self._process_attributes()
		self._remove_by_material_if_necessary()
		self._remove_unused_materials_slots()
		self._finalize_geometry()
		self._remove_empty_vertexgroups()
		
		self._remove_unused_bones()
		
		self._join_submeshes()


class VariantAvatarBuilder(CommonAvatarBuilder, ABC):
	def get_variant(self) -> 'str':
		raise NotImplementedError()
	
	def is_mobile(self) -> 'bool':
		return False
	
	def is_fallback(self) -> 'bool':
		return False
	
	def _parse_special_name(self, any_name) -> 'tuple[str, dict[str, set[str]]]':
		# 'base_name:foo:bar=baz,qux' -> 'base_name', {'foo': {}, 'bar': {'baz', 'qux'}}
		parts = (str(any_name).strip()).split(':')
		base_name = parts[0].strip()
		options = dict()
		for option in parts[1:]:
			split = option.strip().split('=', 1)
			key = split[0].strip()
			if not key:
				continue
			values = set()
			options[key] = values
			if len(split) < 2:
				continue
			for value in split[1].split(','):
				value = value.strip()
				if value:
					values.add(value)
		return base_name, options
	
	def match_mobile_filter(self, options: 'dict[str, set[str]]'):
		if self.is_mobile():
			if 'Desktop' in options.keys():
				return False
		else:
			if 'Mobile' in options.keys():
				return False
		return True
	
	def match_fallback_filter(self, options: 'dict[str, set[str]]'):
		if self.is_fallback():
			if 'Full' in options.keys():
				return False
		else:
			if 'Fallback' in options.keys():
				return False
		return True
	
	def match_variant_filter(self, options: 'dict[str, set[str]]'):
		variants = options.get('V')
		if variants is None:
			return True
		if self.get_variant() not in variants:
			return False
		return True
	
	def match_filter(self, options: 'dict[str, set[str]]'):
		if not self.match_mobile_filter(options):
			return False
		if not self.match_fallback_filter(options):
			return False
		if not self.match_variant_filter(options):
			return False
		return True
	
	def shapekey_action(self, obj: 'Object', mesh: 'Mesh', key: 'ShapeKey'):
		if key.name.startswith('_'):
			return key.value
		base_name, options = self._parse_special_name(key.name)
		match = self.match_filter(options)
		# log.info(f"Object {obj.name!r} ShapeKey {key.name!r} action match: {match}")
		return None if match else key.value
	
	def shapekey_new_name(self, obj: 'Object', mesh: 'Mesh', key: 'ShapeKey') -> 'str|None':
		base_name, options = self._parse_special_name(key.name)
		return base_name
	
	def attribute_action(self, obj: 'Object', mesh: 'Mesh', attribute: 'Attribute') -> 'str|None':
		if attribute.name.startswith('_'):
			return None
		base_name, options = self._parse_special_name(attribute.name)
		match = self.match_filter(options)
		log.info(f"Object {obj.name!r} Attribute {attribute.name!r} action match: {match}")
		if not match:
			return None
		if base_name.startswith('DeleteVerts'):
			return 'DELETE_VERTS'
		if base_name.startswith('DissolveEdges'):
			return 'DISSOLVE_EDGES'
		if base_name.startswith('CollapseEdges'):
			return 'COLLAPSE_EDGES'
		return None


class VRChatAvatarBuilder(CommonAvatarBuilder, ABC):
	def allow_remove_shapekey(self, obj, mesh, key):
		return not key.name.startswith('vrc')


__all__ = ['CommonAvatarBuilder', 'VariantAvatarBuilder', 'VRChatAvatarBuilder']
