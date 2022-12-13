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
import re
from abc import ABC
from pathlib import Path

import bpy
import bmesh
from bpy.types import Scene, Collection, Object
from bpy.types import Armature, Bone, EditBone
from bpy.types import Mesh, VertexGroup, ShapeKey, Attribute, MaterialSlot, Material

from .._internals import log
from .. import commons, objects, data
from .. import armature, meshes, vertex_groups, shapekeys, attributes, instantiator, modifiers
from .. import instantiator, atlas_baker

RE_NAME = re.compile(r'^(_+)?([^%]*%)?(.+)$')


def conversations_rename(original_name: 'str') -> 'str':
	"""
	The Names of objects are unique inside whole .blend file,
	so we can't have the same names even on a different scene.
	
	This function implements following renaming conversations:
	- FooBar -> B-FooBar ('B' is sort for 'Baked'.)
	- __FooBar -> __B-FooBar (all '_' at the beginning are preserved.)
	- Some%Armature -> Armature (Anything before first '%' is cut off.)
	- _Foo%Bar%Baz -> _Bar%Baz ('_' before 'Anything%' are also preserved.)
	- _%Bar%Baz -> _Bar%Baz.001 ('%' got removed, but '_Bar%Baz' already exists. Careful!)
	
	So basicly, if you want to get pretty names like 'Body' on export,
	you should have names like '%Body' on an original scene.
	"""
	under, prefix, new_name = RE_NAME.match(original_name).groups()
	if prefix is None:
		new_name = 'B-' + new_name
	if under:
		new_name = under + new_name
	return new_name


class NamingConversationInstantiator(instantiator.BaseInstantiator):
	"""
	See BaseInstantiator and conversation_rename first.
	This Instantiator uses naming conversations from conversation_rename when chooses name for copies.
	"""
	
	def rename_copy(self, obj: 'Object', original_name: 'str') -> 'str':
		if original_name is None:
			original_name = obj.name
		return conversations_rename(original_name)


class CommonBuilder(ABC):
	def __init__(self, **kwargs):
		# not crash because of kwargs
		super().__init__()
	
	def get_source_scene(self) -> 'Scene':
		raise NotImplementedError()
	
	def ensure_source_scene(self) -> 'Scene':
		_source_scene = self.get_source_scene()
		data.ensure_valid(_source_scene)
		return _source_scene
	
	def get_source_collection(self) -> 'Collection|None':
		return None
	
	def ensure_source_collection(self) -> 'Collection|None':
		collection = self.get_source_collection()
		if collection is None:
			return None
		if not isinstance(collection, bpy.types.Collection):
			raise TypeError()
		data.ensure_valid(collection)
		return collection
	
	def get_processing_scene(self) -> 'Scene|str':
		raise NotImplementedError()
	
	def ensure_processing_scene(self) -> 'Scene':
		_processing_scene = self.get_processing_scene()
		if isinstance(_processing_scene, bpy.types.Scene):
			data.ensure_valid(_processing_scene)
			return _processing_scene
		elif isinstance(_processing_scene, str):
			_processing_scene = bpy.data.scenes.get(_processing_scene) or bpy.data.scenes.new(_processing_scene)
			return _processing_scene
		else:
			raise TypeError()
	
	def get_export_dir(self) -> 'Path|str':
		raise NotImplementedError()
	
	def ensure_export_dir(self) -> 'Path':
		path = self.get_export_dir()
		if isinstance(path, str):
			path = Path(path)
		elif not isinstance(path, Path):
			raise TypeError()
		if not path.exists():
			path.mkdir(parents=True, exist_ok=True)
		return path
	
	def get_originals(self) -> 'list[Object]':
		_source_scene = self.ensure_source_scene()
		_source_collection = self.ensure_source_collection()
		_originals = list()
		if _source_collection is not None:
			for obj in _source_collection.objects:
				if obj.name in _source_scene.objects:
					_originals.append(obj)
		else:
			for obj in _source_scene.objects:
				_originals.append(obj)
		return _originals
	
	# def add_original(self, name: 'str', children=True):
	# 	obj = bpy.data.objects[name]
	# 	source_scene = self.ensure_source_scene()
	# 	source_collection = self.get_source_collection()
	# 	if obj not in source_scene.objects:
	# 		raise RuntimeError(f"Object {obj!r} does not belong to Scene {source_scene!r}!")
	# 	if source_collection and obj not in source_collection.objects:
	# 		raise RuntimeError(f"Object {obj!r} does not belong to Collection {source_collection!r}!")
	# 	queue = collections.deque()
	# 	queue.append(obj)
	# 	while len(queue) > 0:
	# 		obj = queue.popleft()
	# 		if obj not in source_scene.objects:
	# 			continue
	# 		if source_collection and obj not in source_collection.objects:
	# 			continue
	# 		self.originals.add(obj)
	# 		if children:
	# 			# TODO optimize O(len(bpy.data.objects))
	# 			queue.extend(obj.children)
	
	def clear_processing_scene(self):
		scene = self.ensure_processing_scene()
		objs = list(scene.collection.objects)
		log.info(f'Removing everything ({len(objs)} objects) from processing scene...')
		for obj in objs:
			scene.collection.objects.unlink(obj)
		data.orphans_purge_iter()
		log.info(f'Removed everything ({len(objs)} objects) from processing scene.')
	
	def get_instantiator(self):
		return NamingConversationInstantiator()
	
	def _instantiate(self):
		inst = self.get_instantiator()
		inst.instantiate_collections = False
		inst.original_scene = self.ensure_source_scene()
		inst.working_scene = self.ensure_processing_scene()
		inst.apply_modifiers = False
		inst.originals = self.get_originals()
		inst.run()
		data.orphans_purge_iter()
	
	def _reveal_hidden_single(self, obj: 'Object', mesh: 'Mesh'):
		obj.active_shape_key_index = 0
		obj.use_shape_key_edit_mode = False
		objects.deselect_all()
		objects.activate(obj)
		bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT', 'EDGE', 'FACE'})
		bpy.ops.mesh.reveal(select=False)
		bpy.ops.mesh.select_all(action='DESELECT')
		bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
	
	def _reveal_hidden(self):
		"""
		Some pre-export operations may require geometry to be visible, so let's reveal hidden geometry inside meshes.
		"""
		for obj in self.ensure_processing_scene().objects:
			mesh = meshes.get_safe(obj, strict=False)
			if mesh is not None:
				self._reveal_hidden_single(obj, mesh)
	
	def _find_armature_links(self) -> 'dict[Object, set[Object]]':
		links = dict()  # type: dict[Object, set[Object]]
		for obj in self.ensure_processing_scene().objects:
			mesh = meshes.get_safe(obj, strict=False)
			if mesh is None:
				continue
			for modifier in obj.modifiers:
				arm_m = modifiers.as_armature(modifier, strict=False)
				if arm_m and arm_m.object:
					link = commons.dict_get_or_add(links, arm_m.object, set)
					link.add(obj)
		return links
	
	def merge_weights_action(self, arm_obj: 'Object', mesh_obj: 'Object') -> 'dict[str, dict[str, float]]|None':
		"""
		Action for merging bone weights on given Mesh-type Object for it's given deforming Armature-type Object.
		Must return mapping rule for vertex_groups.merge_weights or None if no any merging is needed.
		By default, no any merging, returns None.
		"""
		return None
	
	def _merge_weights(self):
		links = self._find_armature_links()
		for arm_obj, mesh_objs in links.items():
			for mesh_obj in mesh_objs:
				action = None
				try:
					action = self.merge_weights_action(arm_obj, mesh_obj)
					if action is not None:
						vertex_groups.WeightsMerger(mesh_obj, mapping=action, strict=True).merge_weights()
				except Exception as exc:
					log.error(f"Failed to merge weights on {arm_obj=!r}, {mesh_obj=!r}, {action=!r}: {exc}", exc_info=exc)
					raise exc
	
	def shapekey_action(self, obj: 'Object', mesh: 'Mesh', key: 'ShapeKey') -> 'float|None':
		"""
		Action for applying/removing Shape Key, must return:
		- float 0.0 to remove Shape Key.
		- float 0.0 .. 1.0 to apply Shape Key to the Mesh with given value.
		- None to leave given shape key as is unchanged.
		It Can be useful for removing unnecessary Shape Keys for some asset variants.
		By default, removes any Shape Key with '_' at the beginning of its name.
		"""
		if key.name.startswith('_'):
			return key.value
		return None
	
	def _apply_shapekeys(self, obj: 'Object', mesh: 'Mesh', key_blocks: 'list[ShapeKey]'):
		"""
		Applies or removes Shape Keys according to shapekey_action rule.
		"""
		obj.active_shape_key_index = 0
		obj.use_shape_key_edit_mode = False
		
		actions = dict()  # type: dict[str, float|None]
		for key in key_blocks:
			actions[key.name] = self.shapekey_action(obj, mesh, key)
		
		objects.deselect_all()
		for key_name, key_action in actions.items():
			if key_action is None or key_action is False:
				continue
			key_id = next((i for i in range(len(key_blocks)) if key_blocks[i].name == key_name), None)
			objects.activate(obj)
			obj.active_shape_key_index = key_id
			if key_action != 0.0:
				log.info(f"Applying shapekey on {obj.name!r}, name={key_name!r} with value={key_action!r} ...")
				shapekeys.apply_active(obj, 'ALL', value=key_action, keep_reverted=False)
			else:
				log.info(f"Removing shapekey from {obj.name!r}, name={key_name!r}...")
				bpy.ops.object.shape_key_remove(all=False)
	
	def shapekey_new_name(self, obj: 'Object', mesh: 'Mesh', key: 'ShapeKey') -> 'str|None':
		"""
		Suggest renaming given Shape Key. Can be overriden to provide custom names.
		Must return a new name or None if no rename needed.
		It Can be useful for providing a different Shape Key for different asset variants.
		By default, all names are as is unchanged, returns None.
		"""
		return None
	
	def _rename_shapekeys(self, obj: 'Object', mesh: 'Mesh', key_blocks: 'list[ShapeKey]'):
		"""
		Rename Shape Keys according to shapekey_new_name rule.
		"""
		for key in key_blocks:
			old_name = key.name
			new_name = self.shapekey_new_name(obj, mesh, key)
			if not new_name:
				continue
			new_name = new_name.strip()
			if old_name != new_name:
				log.info(f"Renaming shape key: {obj.name=!r}, {old_name!r} -> {new_name}")
				key.name = new_name
			if key.name != new_name:
				log.warning(f"Renaming shape key failed: {obj.name=!r}, {key.name!r} -> {new_name}")
	
	def allow_remove_shapekey(self, obj: 'Object', mesh: 'Mesh', key: 'ShapeKey') -> 'bool':
		"""
		Allow removal of given empty (contains no deformation data) Shape Key.
		By default, all empty shapekeys are removed, but can be customized conditionally here.
		"""
		return True
	
	def _process_shapekeys(self):
		for obj in self.ensure_processing_scene().objects:
			mesh = meshes.get_safe(obj, strict=False)
			if mesh is None:
				continue
			key_blocks = mesh.shape_keys.key_blocks if (mesh.shape_keys is not None) else None
			if key_blocks is None:
				continue
			shapekeys.remove_empty(obj, epsilon=0.1 / 1000, allow_remove_predicate=self.allow_remove_shapekey, strict=True)
			self._apply_shapekeys(obj, mesh, key_blocks)
			self._rename_shapekeys(obj, mesh, key_blocks)
	
	def attribute_action(self, obj: 'Object', mesh: 'Mesh', attribute: 'Attribute') -> 'str|None':
		"""
		Action for applying Attribute:
		- 'DELETE_VERTS' to apply bpy.ops.mesh.delete(type='VERT')
		on vertices marked with given Point-type Attribute.
		- 'DISSOLVE_EDGES' to apply bpy.ops.mesh.dissolve_edges(use_verts=True, use_face_split=True)
		on edges marked with given Edge-type Attribute.
		- 'COLLAPSE_EDGES' to apply bpy.ops.mesh.merge(type='COLLAPSE', uvs=True)
		on edges marked with given Edge-type Attribute.
		- None to ignore given Attribute.
		
		This can be useful to decimate/simplify/remove some geometry for different variants of assets.
		Save selection of necessary geometry into attribute and use there to apply conditionally.
		
		By default, applies corresponding rules for attributes with names beginning
		with 'DeleteVerts', 'DissolveEdges', 'CollapseEdges'. Do nothing for other attributes.
		"""
		if attribute.name.startswith('_'):
			return None
		
		if attribute.name.startswith('DeleteVerts'):
			return 'DELETE_VERTS'
		if attribute.name.startswith('DissolveEdges'):
			return 'DISSOLVE_EDGES'
		if attribute.name.startswith('CollapseEdges'):
			return 'COLLAPSE_EDGES'
		
		return None
	
	def _process_attributes_prepare(self, obj: 'Object'):
		objects.deselect_all()
		objects.activate(obj)
		bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT', 'EDGE', 'FACE'})
		bpy.ops.mesh.reveal(select=False)
		bpy.ops.mesh.select_all(action='DESELECT')
		bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
	
	def _process_attributes_delete_verts(self, obj: 'Object', mesh: 'Mesh', attribute_name: 'str'):
		if (domain := mesh.attributes[attribute_name].domain) != 'POINT':
			log.raise_error(ValueError, f"Can't delete verts using {domain!r} domain!")
		self._process_attributes_prepare(obj)
		attributes.load_selection_from_attribute_mesh(
			mesh, attribute=attribute_name, mode='SET', only_visible=False, strict=True)
		bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'VERT'})
		bpy.ops.mesh.delete(type='VERT')
		bpy.ops.mesh.select_all(action='DESELECT')
		bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
	
	def _process_attributes_dissolve_edges(self, obj: 'Object', mesh: 'Mesh', attribute_name: 'str'):
		if (domain := mesh.attributes[attribute_name].domain) != 'EDGE':
			log.raise_error(ValueError, f"Can't dissolve edges using {domain!r} domain!")
		self._process_attributes_prepare(obj)
		attributes.load_selection_from_attribute_mesh(
			mesh, attribute=attribute_name, mode='SET', only_visible=False, strict=True)
		bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'EDGE'})
		bpy.ops.mesh.dissolve_edges(use_verts=True, use_face_split=True)
		bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
	
	def _process_attributes_collapse_edges(self, obj: 'Object', mesh: 'Mesh', attribute_name: 'str'):
		if (domain := mesh.attributes[attribute_name].domain) != 'EDGE':
			log.raise_error(ValueError, f"Can't collapse edges using {domain!r} domain!")
		self._process_attributes_prepare(obj)
		attributes.load_selection_from_attribute_mesh(
			mesh, attribute=attribute_name, mode='SET', only_visible=False, strict=True)
		bpy.ops.object.mode_set_with_submode(mode='EDIT', toggle=False, mesh_select_mode={'EDGE'})
		bpy.ops.mesh.merge(type='COLLAPSE', uvs=True)
		bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
	
	def _process_attributes_single(self, obj: 'Object', mesh: 'Mesh', name: 'str'):
		# Attribute умирает после смены режима объекта, по этому не храним его далее и работаем по имени.
		if (action := self.attribute_action(obj, mesh, mesh.attributes[name])) is None:
			return
		domain = mesh.attributes[name].domain
		try:
			log.info(f"Processing attribute: {obj.name=!r}, {mesh.name=!r}, {name=!r}, {domain=!r}, {action=!r}")
			if action == 'DELETE_VERTS':
				self._process_attributes_delete_verts(obj, mesh, name)
			elif action == 'DISSOLVE_EDGES':
				self._process_attributes_dissolve_edges(obj, mesh, name)
			elif action == 'COLLAPSE_EDGES':
				self._process_attributes_collapse_edges(obj, mesh, name)
			else:
				log.raise_error(RuntimeError, f"Unknown action: {action!r}!")
		except Exception as exc:
			msg_c = f"{obj.name=!r}, {mesh.name=!r}, {name=!r}, {domain=!r}, {action=!r}"
			log.error(f"Failed to process attribute {msg_c}: {exc}", exc_info=exc)
			raise exc
		log.info(f"Processed attribute: {obj.name=!r}, {mesh.name=!r}, {name=!r}, {domain=!r}, {action!r}")
	
	def _process_attributes(self):
		for obj in self.ensure_processing_scene().objects:
			mesh = meshes.get_safe(obj, strict=False)
			if mesh is None:
				continue
			bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
			objects.deselect_all()
			objects.activate(obj)
			obj.active_shape_key_index = 0
			obj.use_shape_key_edit_mode = False
			for a_name in list(a.name for a in mesh.attributes):
				self._process_attributes_single(obj, mesh, a_name)
	
	def should_remove_by_material(self, obj: 'Object', mesh: 'Mesh', idx: 'int', slot: 'MaterialSlot'):
		"""
		Action for removing geometry by material.
		May be useful for removing different geometry for different asset variants.
		For example, it's possible to remove non-opaque geometry or details for mobile platforms.
		By default, removes slots with no materials assigned.
		"""
		return slot.material is None
	
	def _remove_by_material_if_necessary_single(self, obj: 'Object', mesh: 'Mesh') -> 'int':
		objects.deselect_all()
		objects.activate(obj)
		mat_ids = set()
		for idx in range(len(obj.material_slots)):
			slot = obj.material_slots[idx]
			if self.should_remove_by_material(obj, mesh, idx, slot):
				mat_ids.add(idx)
		if len(mat_ids) < 1:
			return 0
		
		log.info(f"Removing {mat_ids!r} materials from {obj.name!r}...")
		bm = bmesh.new()
		removed = 0
		try:
			bm.from_mesh(mesh)
			bm.faces.ensure_lookup_table()
			for face in list(bm.faces):
				if face.material_index in mat_ids:
					bm.faces.remove(face)
					removed += 1
			if removed > 0:
				bm.to_mesh(mesh)
		finally:
			bm.free()
		log.info(f"Removed {removed!r} faces from {obj.name!r}!")
		return removed
	
	def _remove_by_material_if_necessary(self):
		"""
		Remove geometry, using should_remove_by_material rule.
		"""
		for obj in self.ensure_processing_scene().objects:
			mesh = meshes.get_safe(obj, strict=False)
			if mesh is not None:
				self._remove_by_material_if_necessary_single(obj, mesh)
	
	def _remove_unused_materials_slots(self):
		objects.deselect_all()
		for obj in self.ensure_processing_scene().objects:
			if meshes.is_mesh_object(obj):
				objects.activate(obj)
		bpy.ops.object.material_slot_remove_unused()  # Может быть не FINISHED
		objects.deselect_all()
	
	def _remove_empty_vertexgroups(self):
		objs = self.ensure_processing_scene().objects
		vertex_groups.remove_empty(objs, limit=1.0 / 100, strict=False)
	
	def _finalize_geometry_editmode(self, obj: 'Object', mesh: 'Mesh'):
		bpy.ops.mesh.select_all(action='SELECT')
		bpy.ops.mesh.dissolve_degenerate()
		bpy.ops.mesh.select_all(action='SELECT')
		bpy.ops.mesh.delete_loose(use_verts=True, use_edges=True, use_faces=False)
		bpy.ops.mesh.select_all(action='SELECT')
		bpy.ops.mesh.quads_convert_to_tris(quad_method='BEAUTY', ngon_method='BEAUTY')
		bpy.ops.mesh.select_all(action='DESELECT')
	
	def _finalize_geometry_objectmode(self, obj: 'Object', mesh: 'Mesh'):
		mesh.use_auto_smooth = False
		bpy.ops.mesh.customdata_custom_splitnormals_clear()  # can be CANCELLED
		bpy.ops.mesh.customdata_custom_splitnormals_add()
		mesh.use_auto_smooth = True
	
	def _finalize_geometry_single(self, obj: 'Object', mesh: 'Mesh'):
		# dissolve_degenerate + delete_loose + quads_convert_to_tris
		objects.deselect_all()
		objects.activate(obj)
		commons.ensure_op_finished(bpy.ops.object.mode_set_with_submode(
			mode='EDIT', toggle=False, mesh_select_mode={'VERT', 'EDGE', 'FACE'}))
		self._finalize_geometry_editmode(obj, mesh)
		commons.ensure_op_finished(bpy.ops.object.mode_set(mode='OBJECT', toggle=False))
		self._finalize_geometry_objectmode(obj, mesh)
		objects.deselect_all()
	
	def _finalize_geometry(self):
		for obj in self.ensure_processing_scene().objects:
			mesh = meshes.get_safe(obj, strict=False)
			if mesh is not None:
				self._finalize_geometry_single(obj, mesh)
	
	def is_bone_used(self, arm_obj: 'Object', arm: 'Armature', bone: 'Bone', mesh_obj: 'Object', mesh: 'Mesh'):
		return bone.name in mesh_obj.vertex_groups.keys()
	
	def _remove_unused_bones_single(self, arm_obj: 'Object', mesh_objs: 'set[Object]') -> 'int':
		arm = armature.get_safe(arm_obj, strict=True)
		used_bones = set()  # type: set[str]
		for mesh_obj in mesh_objs:
			mesh = meshes.get_safe(mesh_obj, strict=True)
			for bone in arm.bones:  # type: Bone
				if self.is_bone_used(arm_obj, arm, bone, mesh_obj, mesh):
					used_bones.add(bone.name)
		
		if len(used_bones) < 1:
			log.warning(f"No used bones detected in Object {arm_obj.name!r}, Armature {arm.name!r}! All bones will be deleted!")
		if len(used_bones) >= len(arm.bones):
			log.info(f"No unused bones detected in Object {arm_obj.name!r}, Armature {arm.name!r}. All bones will be preserved!")
			return 0
		
		bones_before = len(arm.bones)
		
		objects.deselect_all()
		objects.activate(arm_obj)
		commons.ensure_op_finished(bpy.ops.object.mode_set(mode='EDIT', toggle=False))
		bpy.ops.armature.reveal(select=False)
		bpy.ops.armature.select_all(action='DESELECT')
		
		while True:
			for bone in arm.edit_bones:  # type: EditBone
				bone.select = (len(bone.children) < 1) and (bone.name not in used_bones)
			if len(bpy.context.selected_bones) < 1:
				break
			s = list(bone.name for bone in arm.edit_bones)
			log.info(f"Removing {len(s)!r} bones {s!r} form {arm_obj!r}, {arm!r}...")
			commons.ensure_op_finished(bpy.ops.armature.delete())
		
		commons.ensure_op_finished(bpy.ops.object.mode_set(mode='OBJECT', toggle=False))
		objects.deselect_all()
		
		removed = len(arm.bones) - bones_before
		if removed > 0:
			log.info(f"Removed {removed} bones from Object {arm_obj.name!r}, Armature {arm.name!r}.")
		return removed
	
	def _remove_unused_bones(self):
		links = self._find_armature_links()
		for arm_obj, mesh_objs in links.items():
			self._remove_unused_bones_single(arm_obj, mesh_objs)


__all__ = [
	'conversations_rename',
	'NamingConversationInstantiator', 'CommonBuilder'
]
