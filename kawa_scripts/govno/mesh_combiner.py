# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

import bmesh
import logging
import typing
import time
import math
import collections

from .commons import *
from .config import *
from .uv import *
from .atlas_baker_shitty import *
from .instantiator import *

if typing.TYPE_CHECKING:
	from typing import *
	
	T = TypeVar('T')
	
	MathUtilsBox = List[Union[float, 'AttachmentPerMaterial']]
	MathUtilsBoxes = List[MathUtilsBox]
	IslandsBuilders = Dict[bpy.types.Material, 'IslandsBuilder']
	OriginalObjectSetups = Dict[bpy.types.Object, 'OriginalObjectSetup']
	OriginalMaterialSetups = Dict[bpy.types.Material, 'OriginalMaterialSetup']
	AtlasTextureSetups = Dict[str, 'AtlasTextureSetup']
	AtlasMaterialSetups = Dict[str, 'AtlasMaterialSetup']
	AttachmentPerObjects = Dict[bpy.types.Object, 'AttachmentPerObject']
	ProcessingObjectSetups = Dict[bpy.types.Object, 'ProcessingObjectSetup']
	
	UVLayerIndex = Union[str, bool, None]  # valid string (layer layer_name) or False (ignore) or None (undefined)

log = logging.getLogger('kawa.mesh_combiner')


# Вспомогательные функции


class ProcessingObjectSetup:
	# Описывает свойства и правила для меш-объекта, на котором идет обработка
	__slots__ = ('parent', 'object', 'original')
	
	def __init__(self, parent: 'KawaMeshCombiner', _object: 'bpy.types.Object', original: 'SourceObjectConfig'):
		self.parent = parent
		self.object = _object  # type: bpy.types.Object
		self.original = original  # type: SourceObjectConfig
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def get_material_bpy(self) -> 'bpy.types.Material':
		if len(self.object.material_slots) != 1:
			raise AssertionError("Processing object have not one material slot!", self.object)
		return self.object.material_slots[0].material
	
	def get_target_object_name(self) -> 'str':
		return self.original.get_target_object_name()
	
	def should_process_altas(self):
		return self.get_material_bpy()
	
	def get_atlas_original_uv(self) -> 'bpy.types.MeshTexturePolyLayer':
		return get_mesh_safe(self.object).uv_layers[self.parent.PROC_ORIGINAL_ATLAS_UV_NAME]
	
	def get_atlas_target_uv(self) -> 'bpy.types.MeshTexturePolyLayer':
		return get_mesh_safe(self.object).uv_layers[self.parent.PROC_TARGET_ATLAS_UV_NAME]
	
	def reassign_material(self):
		# Заменяет original material на target material
		omat = self.get_material_bpy()
		omat_setup = self.parent.original_materials[omat]
		amat_setup = omat_setup.get_atlas_material_setup()
		self.object.material_slots[0].material = amat_setup.prepare_material_bpy()


class AttachmentPerObject:
	# Приклеевается к AttachmentPerMaterial
	__slots__ = ('polys', 'mesh', 'object')
	
	def __init__(self, _object: 'bpy.types.Object', mesh: 'bpy.types.Mesh', polys: 'List[bpy.types.MeshPolygon]'):
		# Материал, на котором находится остров, используется только для проверки совместимости
		self.object = _object  # type: bpy.types.Object
		# Материал, на котором находится остров, используется только для проверки совместимости
		self.mesh = mesh  # type: bpy.types.Mesh
		# имя_объекта -> полигоны, попадающие в данный острав
		self.polys = polys  # type: List[bpy.types.MeshPolygon]
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def is_compatible(self, other: 'AttachmentPerObject'):
		if self.mesh is None or other.mesh is None or self.mesh != other.mesh:
			return False
		if self.object is None or other.object is None or self.object != other.object:
			return False
		return True
	
	def extend_from_other(self, other: 'AttachmentPerObject'):
		if self is other:
			raise ValueError("self is other: ", (self, other))
		if not self.is_compatible(other):
			raise ValueError('Attachments (PerObject) is not compatible!', (self, other))
		self.polys.extend(other.polys)
		other.polys.clear()
		other.polys = None


class AttachmentPerMaterial:
	# Приклеевается к Island:
	# Переносит дполнительную инфу, которая не учасвствует напримую в алгоритме разбивки островов
	# Часть данных избыточна, за то удобна в работе
	__slots__ = ('per_ob', 'material', 'object', 'area')
	
	def __init__(self, material: 'SourceMaterialConfig', per_ob: 'AttachmentPerObjects', area=0.0):
		# Материал, на котором находится остров, используется только для проверки совместимости
		self.material = material  # type: SourceMaterialConfig
		# имя_объекта -> полигоны, попадающие в данный острав
		self.per_ob = per_ob  # type: AttachmentPerObjects
		self.area = area
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def is_compatible(self, other: 'AttachmentPerMaterial'):
		if self.material is None or other.material is None or self.material != other.material:
			return False
		return True
	
	def extend_from_other(self, other: 'AttachmentPerMaterial'):
		if self is other:
			raise ValueError("self is other: ", (self, other))
		if not self.is_compatible(other):
			raise ValueError('Attachments is not compatible!', (self, other))
		for ob_name, other_per_ob in other.per_ob.items():
			self_per_ob = self.per_ob.get(ob_name)
			if self_per_ob is not None:
				self_per_ob.extend_from_other(other_per_ob)
			else:
				self.per_ob[ob_name] = other_per_ob
		other.per_ob.clear()
		other.per_ob = None
		
		self.area += other.area
		other.area = 0.0


class KawaMeshCombiner:
	L_TARGET_OBJECT = 'target_object'
	L_UV0_ORIGINAL = 'atlas_original_uv'
	L_UV0_TARGET = 'atlas_target_uv'
	L_UV1_ORIGINAL = 'lightmap_original_uv'
	L_UV1_TARGET = 'lightmap_target_uv'
	L_ATLAS_IGNORE = 'atlas_ignore'
	L_ATLAS_TARGET_MATERIAL = 'atlas_target_material'
	L_ATLAS_COLOR_SIZE = 'atlas_color_size'
	L_ATLAS_SIZE = 'atlas_size'
	L_ATLAS_PADDING = 'atlas_padding'
	L_ATLAS_EPSILON = 'atlas_epsilon'
	L_ATLAS_SINGLE_ISLAND = 'atlas_single_island'
	L_ATLAS_MATERIALS = 'atlas_materials'
	L_ATLAS_TEXTURE_PREFIX = 'atlas_texture_prefix'
	L_ATLAS_TEXTURES = 'atlas_textures'
	L_LM_IGNORE = 'lightmap_ignore'
	L_FAST_MODE = 'fast_mode'
	L_ORIGINAL_OBJECTS = 'original_objects'
	L_ORIGINAL_MATERIALS = 'original_materials'
	
	# Имена временных объектов
	PROC_ORIGINAL_ATLAS_UV_NAME = "__KawaMeshCombiner_UV_Main_Original"
	PROC_ORIGINAL_LM_UV_NAME = "__KawaMeshCombiner_UV_LightMap_Original"
	PROC_TARGET_ATLAS_UV_NAME = "__KawaMeshCombiner_UV_Main_Target"
	PROC_TARGET_LM_UV_NAME = "__KawaMeshCombiner_UV_LightMap_Target"
	PROC_OBJECT_NAME = "__KawaMeshCombiner_Processing_Object"
	PROC_MESH_NAME = "__KawaMeshCombiner_Processing_Mesh"
	
	PROC_OBJECT_TAG = "__KawaMeshCombiner_ProcessingObject"
	
	__slots__ = (
		'target_object_name', 'atlas_material_name', 'fast_mode',
		'atlas_ignore', 'uv0_original', 'uv0_target', 'atlas_texture_prefix',
		'original_size', 'atlas_size', 'atlas_padding', 'atlas_epsilon', 'atlas_single_island', 'atlas_scale_factor_area',
		'lm_ignore', 'uv1_original', 'uv1_target',
		'original_objects', 'original_materials', 'atlas_materials', 'atlas_textures',
		'created_proc_objects', 'instantiator',
	)
	
	def __init__(self):
		self.original_objects = dict()  # type: OriginalObjectSetups
		self.original_materials = dict()  # type: OriginalMaterialSetups
		self.target_object_name = None  # !
		
		self.instantiator = Instantiator()
		
		self.uv0_original = 'UVMap'
		self.uv0_target = 'CombinedAtlas'
		self.uv1_original = 'UVMap'
		self.uv1_target = 'CombinedLightmap'
		
		self.original_size = (32, 32)  # type: SizeInt
		
		self.atlas_ignore = False
		self.atlas_material_name = None  # !
		self.atlas_materials = dict()  # type: AtlasMaterialSetups
		self.atlas_textures = dict()  # type: AtlasTextureSetups
		self.atlas_texture_prefix = 'TextureAtlas'
		self.atlas_size = (2048, 2048)  # type: SizeInt
		self.atlas_padding = 1.0
		self.atlas_epsilon = 1.0
		self.atlas_single_island = False
		self.atlas_scale_factor_area = True
		
		self.lm_ignore = True
		
		self.fast_mode = False
	
	@classmethod
	def from_raw_config(cls, raw_setup: 'Optional[SetupRaw]'):
		general_setup = cls()
		
		general_setup.target_object_name = validate_string(raw_setup.get(cls.L_TARGET_OBJECT), cls.L_TARGET_OBJECT)
		general_setup.atlas_material_name = validate_string(raw_setup.get(cls.L_ATLAS_TARGET_MATERIAL), cls.L_ATLAS_TARGET_MATERIAL)
		
		uv0_original = validate_string(raw_setup.get(cls.L_UV0_ORIGINAL), cls.L_UV0_ORIGINAL)
		general_setup.uv0_original = any_not_none(uv0_original, general_setup.uv0_original)
		
		uv0_target = validate_string(raw_setup.get(cls.L_UV0_TARGET), cls.L_UV0_TARGET)
		general_setup.uv0_target = any_not_none(uv0_target, general_setup.uv0_target)
		
		uv1_original = validate_string(raw_setup.get(cls.L_UV1_ORIGINAL), cls.L_UV1_ORIGINAL)
		general_setup.uv1_original = any_not_none(uv1_original, general_setup.uv1_original)
		
		uv1_target = validate_string(raw_setup.get(cls.L_UV1_TARGET), cls.L_UV1_TARGET)
		general_setup.uv1_target = any_not_none(uv1_target, general_setup.uv1_target)
		
		atlas_ignore = validate_bool(raw_setup.get(cls.L_ATLAS_IGNORE), cls.L_ATLAS_IGNORE)
		general_setup.atlas_ignore = any_not_none(atlas_ignore, general_setup.atlas_ignore)
		
		atlas_color_size = validate_size_int(raw_setup.get(cls.L_ATLAS_COLOR_SIZE), cls.L_ATLAS_COLOR_SIZE)
		general_setup.original_size = any_not_none(atlas_color_size, general_setup.original_size)
		
		atlas_size = validate_size_int(raw_setup.get(cls.L_ATLAS_SIZE), cls.L_ATLAS_SIZE)
		general_setup.atlas_size = any_not_none(atlas_size, general_setup.atlas_size)
		
		atlas_texture_prefix = validate_size_int(raw_setup.get(cls.L_ATLAS_SIZE), cls.L_ATLAS_SIZE)
		general_setup.atlas_texture_prefix = any_not_none(atlas_texture_prefix, general_setup.atlas_texture_prefix)
		
		atlas_padding = validate_int_positive_or_zero(raw_setup.get(cls.L_ATLAS_PADDING), cls.L_ATLAS_PADDING)
		general_setup.atlas_padding = any_not_none(atlas_padding, general_setup.atlas_padding)
		
		atlas_epsilon = validate_int_positive_or_zero(raw_setup.get(cls.L_ATLAS_EPSILON), cls.L_ATLAS_EPSILON)
		general_setup.atlas_epsilon = any_not_none(atlas_epsilon, general_setup.atlas_epsilon)
		
		atlas_single_island = validate_bool(raw_setup.get(cls.L_ATLAS_SINGLE_ISLAND), cls.L_ATLAS_SINGLE_ISLAND)
		general_setup.atlas_single_island = any_not_none(atlas_single_island, general_setup.atlas_single_island)
		
		lm_ignore = validate_bool(raw_setup.get(cls.L_LM_IGNORE), cls.L_LM_IGNORE)
		general_setup.lm_ignore = any_not_none(lm_ignore, general_setup.lm_ignore)
		
		fast_mode = validate_bool(raw_setup.get(cls.L_FAST_MODE), cls.L_FAST_MODE)
		general_setup.fast_mode = any_not_none(fast_mode, general_setup.fast_mode)
		
		general_setup.original_objects.clear()
		raw_original_objects = raw_setup.get(cls.L_ORIGINAL_OBJECTS)
		for oobj_name, oobj_raw_setup in validate_set_or_dict_as_iterator(raw_original_objects):
			general_setup.add_original_object_name(oobj_name, **oobj_raw_setup)
		
		general_setup.original_materials.clear()
		raw_original_materials = raw_setup.get(cls.L_ORIGINAL_MATERIALS)
		for omat_name, omat_raw_setup in validate_set_or_dict_as_iterator(raw_original_materials):
			omat = bpy.context.blend_data.materials.get(omat_name)
			if omat is None:
				log.warning("There is no original material='%s'", omat_name)
				continue
			omat_setup = SourceMaterialConfig.from_raw_config(general_setup, omat, **omat_raw_setup)
			general_setup.original_materials[omat] = omat_setup
		
		general_setup.atlas_materials.clear()
		raw_target_materials = raw_setup.get(cls.L_ATLAS_MATERIALS)
		for amat_name, amat_raw_setup in validate_set_or_dict_as_iterator(raw_target_materials):
			if not is_valid_string(amat_name):
				raise ConfigurationError("Invalid target material name!", amat_name)
			amat_setup = TargetMaterialConfig(general_setup, amat_name, **amat_raw_setup)
			general_setup.atlas_materials[amat_name] = amat_setup
		
		general_setup.atlas_textures.clear()
		raw_target_textures = raw_setup.get(cls.L_ATLAS_TEXTURES)
		for atex_type, atex_raw_setup in validate_set_or_dict_as_iterator(raw_target_textures):
			atex_setup = TargetImageConfig(general_setup, atex_type, **atex_raw_setup)
			general_setup.atlas_textures[atex_type] = atex_setup
		
		general_setup.atlas_materials.clear()
		return general_setup
	
	def add_atlas_texture(self, _type: 'str', **raw_setup):
		atex_setup = self.atlas_textures.get(_type)
		if atex_setup is not None:
			return atex_setup
		if _type in TargetImageConfig.SUPPORTED_TYPES:
			atex_setup = TargetImageConfig(self, _type, **raw_setup)
			self.atlas_textures[_type] = atex_setup
		else:
			raise ConfigurationError("Invalid texture type!", _type, TargetImageConfig.SUPPORTED_TYPES)
		return atex_setup
	
	def add_original_object_bpy(self, oobj: 'bpy.types.Object', **raw_setup) -> 'SourceObjectConfig':
		oobj_setup = self.original_objects.get(oobj)
		if oobj_setup is not None:
			return oobj_setup
		oobj_setup = SourceObjectConfig(self, oobj, **raw_setup)
		self.original_objects[oobj] = oobj_setup
		return oobj_setup
	
	def add_original_object_name(self, oobj_name: 'str', **raw_setup) -> 'SourceObjectConfig':
		oobj = bpy.context.scene.objects[oobj_name]
		if oobj is None:
			log.warning("Original Object='%s' does not exist, skip!", oobj_name)
			return None
		return self.add_original_object_bpy(oobj, **raw_setup)
	
	#
	#
	
	def get_atlas_target_uv(self):
		if not is_valid_string(self.uv0_target):
			raise ConfigurationError("atlas_target_uv is not set!", self.uv0_target)
		return self.uv0_target
	
	def get_lm_target_uv(self):
		if not is_valid_string(self.uv1_target):
			raise ConfigurationError("lm_target_uv is not set!", self.uv1_target)
		return self.uv1_target
	
	def get_original_material_setup(self, omat: 'bpy.types.Material') -> 'SourceMaterialConfig':
		if not isinstance(omat, bpy.types.Material):
			raise TypeError("omat is not Material", omat, type(omat))
		omat_setup = self.original_materials.get(omat)
		if omat_setup is None:
			omat_setup = SourceMaterialConfig(self, omat)
			omat_setup.material = omat
			self.original_materials[omat] = omat_setup
		return omat_setup
	
	def get_atlas_material_setup(self, amat_name: 'str') -> 'TargetMaterialConfig':
		if not is_valid_string(amat_name):
			raise ValueError("amat_name is not valid Material name", amat_name)
		amat_setup = self.atlas_materials.get(amat_name)
		if amat_setup is None:
			amat_setup = TargetMaterialConfig(self, amat_name)
			self.atlas_materials[amat_name] = amat_setup
		return amat_setup
	
	def get_all_original_materials(self) -> 'OriginalMaterialSetups':
		original_materials = dict()
		for oobj_setup in self.original_objects.values():
			for slot in oobj_setup.object.material_slots:
				omat = slot.material
				if omat is None or omat in original_materials.keys():
					continue
				original_materials[omat] = self.get_original_material_setup(omat)
		return original_materials
	
	def prepare_all_atlas_textures(self) -> 'AtlasTextureSetups':
		# копирует self.target_texture и инициализирует текструры
		atlas_textures = dict()
		for atex_setup in self.atlas_textures.values():
			atex_setup.prepare_texture()
			atlas_textures[atex_setup.type] = atex_setup
		return atlas_textures
	
	def prepare_all_atlas_materials(self):
		# Инициализирует self.atlas_materials и AtlasMaterialSetup
		for omat_setup in self.get_all_original_materials().values():
			if omat_setup.get_atlas_ignore():
				continue
			amat_name = omat_setup.get_atlas_material_name()
			try:
				amat_setup = self.get_atlas_material_setup(amat_name)
				amat_setup.prepare_material_bpy()
			except Exception as exc:
				raise RuntimeError("Error preparing atlas material!", amat_name, omat_setup.material.name) from exc
		return self.atlas_materials
	
	def prepare_target_objects(self):
		# Создает объекты, в которые скомбинируются результаты
		target_object_names = set(oobj_setup.get_target_object_name() for oobj_setup in self.original_objects.values())
		for tobj_name in target_object_names:
			try:
				tobj = bpy.context.scene.objects.get(tobj_name)  # type: bpy.types.Object
				if tobj is None:
					raise ConfigurationError("Target object does not exist!", tobj_name)
				tobj.hide_set(False)  # Необходимо, т.к. некоторые операторы не работают на скрытых объектах
				tobj_mesh = get_mesh_safe(tobj)
				
				# Очистка
				remove_all_geometry(tobj)
				remove_all_shape_keys(tobj)
				remove_all_uv_layers(tobj)
				remove_all_vertex_colors(tobj)
				tobj_mesh.materials.clear()  # Очистка Материалов
			except Exception as exc:
				raise RuntimeError("Error preparing target object!", tobj_name) from exc
	
	def prepare_proc_object_final(
			self, pobj: 'bpy.types.Object', oobj_setup: 'SourceObjectConfig', procs: 'Tuple[List[ProcessingObjectSetup],...]'
	):
		pobj_mat = None
		try:
			proc_all, proc_main, proc_lightmap, proc_none = procs
			global_do_atlas = self.atlas_ignore is not True
			global_do_lm = self.lm_ignore is not True
			
			bpy.context.view_layer.objects.active = pobj
			pobj_setup = ProcessingObjectSetup(self, pobj, oobj_setup)
			proc_all.append(pobj_setup)
			pobj_mat = pobj_setup.get_material_bpy()  # test for Exception as well
			# log.info("Preparing Object='%s' Material='%s'...", oobj.name, pobj_mat.name)
			pobj_mat_setup = self.get_original_material_setup(pobj_mat)
			
			mesh = get_mesh_safe(pobj)
			
			mesh.name = KawaMeshCombiner.PROC_MESH_NAME + pobj.name
			pobj.name = KawaMeshCombiner.PROC_OBJECT_NAME + pobj.name
			
			do_atlas = global_do_atlas and pobj_mat_setup.get_atlas_ignore() is not True
			do_lm = global_do_lm and pobj_mat_setup.get_lm_ignore() is not True
			
			# log.debug("Object='%s' Material='%s' do_atlas='%s' do_lm='%s'", oobj.name, pobj_mat.name, do_atlas, do_lm)
			
			# Подготовка UV и всё такое
			
			if global_do_atlas:
				uv0_original_name = oobj_setup.get_uv0_original()
				if is_valid_string(uv0_original_name) and uv0_original_name in mesh.uv_layers.keys():
					# log.debug(
					# 	"Using UV-Layer='%s' as Main (UV0) layer for Object='%s' Material='%s'",
					# 	mesh.uv_layers[uv0_original_name].name, oobj.name, pobj_mat.name
					# )
					# Копия для цели
					bpy.context.view_layer.objects.active = pobj
					mesh.uv_layers[uv0_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_layers.active.name = KawaMeshCombiner.PROC_TARGET_ATLAS_UV_NAME
					# Копия для исходника
					bpy.context.view_layer.objects.active = pobj
					mesh.uv_layers[uv0_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_layers.active.name = KawaMeshCombiner.PROC_ORIGINAL_ATLAS_UV_NAME
			
			if global_do_lm:
				uv1_original_name = oobj_setup.get_uv1_original()
				if is_valid_string(uv1_original_name) and uv1_original_name in mesh.uv_layers.keys():
					# log.debug(
					# 	"Using UV-Layer='%s' as Lightmap (UV1) layer for Object='%s' Material='%s'",
					# 	mesh.uv_layers[uv1_original_name].name, oobj.name, pobj_mat.name
					# )
					# Копия для цели
					bpy.context.view_layer.objects.active = pobj
					mesh.uv_layers[uv1_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_layers.active.name = KawaMeshCombiner.PROC_TARGET_LM_UV_NAME
					# Копия для исходника
					bpy.context.view_layer.objects.active = pobj
					mesh.uv_layers[uv1_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_layers.active.name = KawaMeshCombiner.PROC_ORIGINAL_LM_UV_NAME
			
			if do_atlas:
				proc_main.append(pobj_setup)
			if do_lm:
				proc_lightmap.append(pobj_setup)
			if not do_atlas and not do_lm:
				proc_none.append(pobj_setup)
			
			def should_remove(name, _):
				if name == KawaMeshCombiner.PROC_ORIGINAL_ATLAS_UV_NAME: return False
				if name == KawaMeshCombiner.PROC_TARGET_ATLAS_UV_NAME: return False
				if name == KawaMeshCombiner.PROC_ORIGINAL_LM_UV_NAME: return False
				if name == KawaMeshCombiner.PROC_TARGET_LM_UV_NAME: return False
				if name in oobj_setup.keep_uv_layers: return False
				return True
			
			def log_remove(name, _):
				# nonlocal counter_uv_rm
				# log.debug("Removing UV-Layer='%s' from Object='%s' Material='%s'", name, oobj.name, pobj_mat.name)
				# counter_uv_rm += 1
				pass
			
			remove_uv_layer_by_condition(mesh, should_remove, log_remove)
		
		except Exception as exc:
			raise RuntimeError("Error preparing processing object!", pobj, oobj_setup.object, pobj_mat) from exc
	
	def prepare_proc_object(
			self, oobj_setup: 'SourceObjectConfig', procs: 'Tuple[List[ProcessingObjectSetup],...]'
	):
		new_objs = set()  # созданные, не оригинальные объекты
		deque = collections.deque()
		oobj = oobj_setup.object
		try:
			# Мы никогда не трогаем оригиналы, так что создаем рабочую копиию
			oobj.hide_set(False)  # Необходимо, т.к. некоторые операторы не работают на скрытых объектах
			ensure_deselect_all_objects()
			oobj.select_set(True)
			bpy.context.view_layer.objects.active = oobj
			bpy.ops.object.duplicate(linked=False)
			base_pobj = bpy.context.view_layer.objects.active
			ensure_selected_single(base_pobj, dict(original=oobj))
			deque.append(base_pobj)
			new_objs.add(base_pobj)
			ensure_deselect_all_objects()
			
			while len(deque) > 0:
				tobj = deque.popleft()  # type: bpy.types.Object
				try:
					if tobj.instance_type == 'COLLECTION' and tobj.instance_collection is not None:
						# Обробатываемый объект - дупль-объект: преобразуем его в реальный и одно-пользовательский
						ensure_deselect_all_objects()
						tobj.select_set(True)
						bpy.context.view_layer.objects.active = tobj
						ensure_op_finished(bpy.ops.object.duplicates_make_real(
							use_base_parent=True, use_hierarchy=True
						), name='bpy.ops.object.duplicates_make_real', tobj=tobj.name)
						tobj.select_set(False)
						ensure_op_finished(bpy.ops.object.make_single_user(
							type='SELECTED_OBJECTS', object=True, obdata=True, material=False, animation=False
						), name='bpy.ops.object.make_single_user', tobj=tobj.name)
						for sobj in bpy.context.selected_objects:
							# Все созданные объекты регистрируем
							sobj.hide_set(False)  # Необходимо
							deque.append(sobj)
							new_objs.add(sobj)
							sobj.select_set(False)
							sobj[self.PROC_OBJECT_TAG] = True
					elif isinstance(tobj.data, bpy.types.Mesh):
						# Обрабатываемый объект - меш
						for slot in tobj.material_slots:
							if slot.material is None:
								raise RuntimeError("Material is not set!", tobj, slot)
							if slot.link == 'OBJECT':
								objec_mat = slot.material
								log.info("Object='%s': Switching Material='%s' from OBJECT to DATA...", oobj.name, objec_mat.name)
								slot.link = 'DATA'
								slot.material = objec_mat
						
						# Применение модиферов, прежде, чем резать
						apply_all_modifiers(tobj)
						
						if len(tobj.material_slots) > 1:
							# у меши более одного слота материала - нужно её порезать
							ensure_deselect_all_objects()
							tobj.select_set(True)
							bpy.context.view_layer.objects.active = tobj
							ensure_op_result(
								bpy.ops.mesh.separate(type='MATERIAL'), ('FINISHED', 'CANCELLED'), name="bpy.ops.mesh.separate",
							)
							for sobj in bpy.context.selected_objects:
								# Все созданные объекты регистрируем
								sobj.hide_set(False)  # Необходимо
								deque.append(sobj)
								new_objs.add(sobj)
								sobj.select_set(False)
								sobj[self.PROC_OBJECT_TAG] = True
						else:
							# у меши однин слот материала - можно использовать
							self.prepare_proc_object_final(tobj, oobj_setup, procs)
							new_objs.discard(tobj)
				except Exception as exc:
					raise RuntimeError("Error preparing processing object: (tobj)", tobj) from exc
		except Exception as exc:
			raise RuntimeError("Error preparing processing object: (oobj, new_objs, deque)", oobj, new_objs, deque) from exc
		return new_objs
	
	def prepare_proc_objects(self):
		# Создает рабочую копию оригинального объекта, разбивает её на части, выбирает нужные UV
		log.info("Preparing objects for processing...")
		proc_all = list()  # type: List[ProcessingObjectSetup]
		proc_main = list()  # type: List[ProcessingObjectSetup]
		proc_lightmap = list()  # type: List[ProcessingObjectSetup]
		proc_none = list()  # type: List[ProcessingObjectSetup]
		new_objs = set()  # type: Set[bpy.types.Object]
		
		global_do_atlas = self.atlas_ignore is not True
		global_do_lm = self.lm_ignore is not True
		
		if global_do_atlas:
			log.info("Global atlas_ignore=False: Going to USE Main (UV0) Layers...")
		else:
			log.info("Global atlas_ignore=True: Going to IGNORE Main (UV0) Layers...")
		if global_do_lm:
			log.info("Global lightmap_ignore=False: Going to USE Lightmap (UV1) Layers...")
		else:
			log.info("Global lightmap_ignore=True: Going to IGNORE Lightmap (UV1) Layers...")
		
		counter_oobj, counter_uv_rm = 0, 0
		for oobj_setup in self.original_objects.values():
			oobj_new_objs = self.prepare_proc_object(oobj_setup, (proc_all, proc_main, proc_lightmap, proc_none))
			new_objs.update(oobj_new_objs)
		
		ensure_deselect_all_objects()
		log.info(
			"Prepared %d objects for processing: atlas=%d, lightmap=%d, ignoring=%d, (total=%d); Removed UV layers: %d",
			counter_oobj, len(proc_main), len(proc_lightmap), len(proc_none), len(proc_all), counter_uv_rm
		)
		return proc_all, proc_main, proc_lightmap, proc_none, new_objs
	
	def atlas_find_islands(self, proc_objects: 'Iterable[ProcessingObjectSetup]') -> 'IslandsBuilders':
		# Выполняет поиск островов на заданных объектах и материалах
		builders = dict()  # type: IslandsBuilders
		
		time_begin = time.perf_counter()
		
		time_progress = time.perf_counter()
		counter_pobjs, counter_islands = 0, 0
		
		def report(force: 'bool'):
			nonlocal time_begin, time_progress, counter_pobjs, counter_islands
			now = time.perf_counter()
			if force is False and now - time_progress < 1.0:
				return
			time_progress = now
			log.info(
				"Atlas: Searching UV islands, progress: Objects=%d, Builders=%d, Islands=%d, Time=%f sec...",
				counter_pobjs, len(builders), sum(len(builder.bboxes) for builder in builders.values()), now - time_begin
			)
		
		for pobj_setup in proc_objects:
			counter_pobjs += 1
			find_obj_start = time.perf_counter()
			obj = pobj_setup.object
			mesh = get_mesh_safe(obj)
			mat = pobj_setup.get_material_bpy()
			mat_setup = self.get_original_material_setup(mat)
			# log.debug("Looking for islands in Object='%s', Material='%s'...", pobj_setup.original.object.name, mat_setup.material.name)
			builder = builders.get(mat)
			if builder is None:
				builder = IslandsBuilder()
				builders[mat] = builder
			try:
				uv_data = mesh.uv_layers.get(self.PROC_ORIGINAL_ATLAS_UV_NAME).data  # type: List[bpy.types.MeshUVLoop]
			except Exception as exc:
				# Времянка
				raise RuntimeError("Error", obj, mesh, list(mesh.uv_layers), self.PROC_ORIGINAL_ATLAS_UV_NAME) from exc
			epsilon = mat_setup.get_atlas_epsilon()
			mat_size_x, mat_size_y = mat_setup.get_original_size()
			polygons = list(mesh.polygons)
			if mat_setup.get_atlas_single_island():
				# Режим одного острова: все точки зарасыватся в один bbox
				vec2s, area = list(), 0.0
				for poly in mesh.polygons:
					vec2s_a = list()
					for loop in poly.loop_indices:
						vec2 = uv_data[loop].uv.xy  # type: mathutils.Vector
						# Преобразование в размеры текстуры
						vec2.x *= mat_size_x
						vec2.y *= mat_size_y
						vec2s.append(vec2)
						vec2s_a.append(vec2)
					area += poly2_area2(vec2s_a)
				builder.add_seq(vec2s, AttachmentPerMaterial(mat_setup, {
					pobj_setup.object: AttachmentPerObject(pobj_setup.object, mesh, polygons)
				}, area=area), epsilon=epsilon)
			else:
				try:
					# Оптимизация. Сортировка от большей площади к меньшей,
					# что бы сразу сбелать большие боксы и реже пере-расширять их.
					polygons.sort(key=lambda p: uv_area(p, uv_data), reverse=True)
					
					for poly in polygons:
						# if self.stat_islands_poly % 1000 == 0:
						# 	log.info('Processed polygons: %d', self.stat_islands_poly)
						# 	log.info("Current (original) object='%s' material='%s'", pobj_setup.original_object.name, mat.name)
						vec2s = list()
						for loop in poly.loop_indices:
							vec2 = uv_data[loop].uv.xy  # type: mathutils.Vector
							# Преобразование в размеры текстуры
							vec2.x *= mat_size_x
							vec2.y *= mat_size_y
							vec2s.append(vec2)
						area = poly2_area2(vec2s)
						builder.add_seq(vec2s, AttachmentPerMaterial(
							mat_setup, {obj: AttachmentPerObject(obj, mesh, [poly])}, area=area
						), epsilon=epsilon)
				# self.stat_islands_poly += 1
				except Exception as exc:
					raise RuntimeError("Error searching multiple islands!", mat_setup, uv_data, obj, mesh, builder) from exc
			find_obj_time = time.perf_counter() - find_obj_start
			report(False)
		report(True)
		return builders
	
	def atlas_islands_to_mathutils_boxes(self, builders: 'IslandsBuilders') -> 'MathUtilsBoxes':
		# Преобразует острава в боксы в формате mathutils.geometry.box_pack_2d
		mathutils_boxes = list()  # type: MathUtilsBoxes
		aspect_target = 1.0 * self.atlas_size[0] / self.atlas_size[1]
		for mat, bboxes in builders.items():
			mat_setup = self.get_original_material_setup(mat)
			mat_scale = float(mat_setup.atlas_scale)
			if self.atlas_scale_factor_area:
				area_poly = sum(bbox.attachment.area for bbox in bboxes.bboxes)
				area_bbox = sum(bbox.get_area() for bbox in bboxes.bboxes)
				area_factor = (area_poly / area_bbox) if area_poly > 0 and area_bbox > 0 else 1
				area_factor = math.log(math.sqrt(area_factor) + 1)
				log.info("Material='%s': Average area scale factor = %f", mat.name, area_factor)
			for bbox in bboxes.bboxes:
				if not bbox.is_valid():
					raise ValueError("box is invalid: ", bbox, mat, bboxes, bboxes.bboxes)
				scale_bbox = mat_scale
				if self.atlas_scale_factor_area:
					area_poly = bbox.attachment.area
					area_bbox = bbox.get_area()
					if area_poly <= 0 or area_bbox <= 0:
						log.warning(
							"Invalid area factor in Material='%s', Island='%s': area_poly=%f, area_bbox=%f",
							mat.name, str(bbox), area_poly, area_bbox
						)
					else:
						area_factor = math.log(math.sqrt(area_poly / area_bbox) + 1)
						scale_bbox *= area_factor
				# две точки -> одна точка + размер
				x, w = bbox.mn.x, (bbox.mx.x - bbox.mn.x)
				y, h = bbox.mn.y, (bbox.mx.y - bbox.mn.y)
				# добавляем отступы
				x, y = x - self.atlas_padding, y - self.atlas_padding,
				w, h = w + 2 * self.atlas_padding, h + 2 * self.atlas_padding
				# Для целевого квадарата - пропорция
				bx, by = x * scale_bbox, y * scale_bbox
				bw, bh = w * scale_bbox, h * scale_bbox
				# Для целевого квадарата - корректировка аспекта
				bx, bw = bx / aspect_target, bw / aspect_target
				mathutils_boxes.append([
					bx, by, bw, bh,  # 0:X, 1:Y, 2:W, 3:H - Перобразуемые box_pack_2d (далее) координаты
					x, y, w, h,  # 4:X, 5:Y, 6:W, 7:H - Исходные координаты
					bx, by, bw, bh,  # 8:X, 9:Y, 10:W, 11:H - Перобразованные (далее) координаты, лучный вариант
					bbox.attachment,  # 12
				])
		return mathutils_boxes
	
	@staticmethod
	def atlas_pack_islands(mathutils_boxes: 'MathUtilsBoxes') -> 'MathUtilsBoxes':
		# Несколько итераций перепаковки
		log.info("Atlas: Packing %d islands...", len(mathutils_boxes))
		pack_x, pack_y = mathutils.geometry.box_pack_2d(mathutils_boxes)
		pack_mx = max(pack_x, pack_y)
		# log.debug("Base repacking score: %f", pack_mx)
		for mu_box in mathutils_boxes:
			mu_box[8:12] = mu_box[0:4]
		bad_line, bad_max = 0, 3  # TODO
		score_first, score_last, score_new = pack_mx, pack_mx, pack_mx
		while bad_line < bad_max:
			px, py = mathutils.geometry.box_pack_2d(mathutils_boxes)
			score_new = max(px, py)
			# log.debug("Trying repacking score: %f", score_new)
			if score_new < score_last:
				for mu_box in mathutils_boxes:
					mu_box[8:12] = mu_box[0:4]
					score_last = score_new
					bad_line = 0
			else:
				bad_line += 1
		for mu_box in mathutils_boxes:
			# Преобразование целевых координат в 0..1
			mu_box[8], mu_box[9] = mu_box[8] / score_last, mu_box[9] / score_last
			mu_box[10], mu_box[11] = mu_box[10] / score_last, mu_box[11] / score_last
		log.info("Atlas: Packed %d islands, score: %f", len(mathutils_boxes), score_last)
		return mathutils_boxes
	
	@staticmethod
	def atlas_mathutils_boxes_to_transforms(mathutils_boxes: 'MathUtilsBoxes') -> 'List[UVBoxTransform]':
		transforms = list()  # type: List[UVBoxTransform]
		for mu_box in mathutils_boxes:
			attachment = mu_box[12]
			mat_size = attachment.material.get_original_size()
			
			#  Преобразование исходных координат в 0..1
			ax, aw = mu_box[4] / mat_size[0], mu_box[6] / mat_size[0]
			ay, ah = mu_box[5] / mat_size[1], mu_box[7] / mat_size[1]
			
			transforms.append(UVBoxTransform(
				ax, ay, aw, ah, mu_box[8], mu_box[9], mu_box[10], mu_box[11], attachment
			))
		return transforms

	def atlas_bake_optimized(self, transforms: 'Sequence[UVBoxTransform]'):
		UV_ORIGINAL, UV_ATLAS = "UV-Original", "UV-Atlas"
		stamp = str(round(time.time()))
		
		ensure_deselect_all_objects()
		
		mesh = bpy.data.meshes.new("__Kawa_Bake_UV_Mesh")  # type: bpy.types.Mesh
		
		# Создаем столько полигонов, сколько трансформов
		bm = bmesh.new()
		try:
			for _ in range(len(transforms)):
				v0, v1, v2, v3 = bm.verts.new(), bm.verts.new(), bm.verts.new(), bm.verts.new()
				bm.faces.new((v0, v1, v2, v3))
			bm.to_mesh(mesh)
		finally:
			bm.free()
		# Создаем слои для преобразований
		mesh.uv_layers.new(name=UV_ORIGINAL)
		mesh.uv_layers.new(name=UV_ATLAS)
		# Подключаем используемые материалы
		materials = set(t.attachment.material.material for t in transforms)
		mesh.materials.clear()
		for mat in materials:
			mesh.materials.append(mat)
		mat2idx = {m: i for i, m in enumerate(mesh.materials)}
		# Прописываем в полигоны координаты и мтаериалы
		uvl_original = mesh.uv_layers[UV_ORIGINAL]  # type: bpy.types.MeshUVLoopLayer
		uvl_atlas = mesh.uv_layers[UV_ATLAS]  # type: bpy.types.MeshUVLoopLayer
		uvd_original, uvd_atlas = uvl_original.data, uvl_atlas.data
		for poly_idx, t in enumerate(transforms):
			poly = mesh.polygons[poly_idx]
			if len(poly.loop_indices) != 4:
				raise AssertionError("len(poly.loop_indices) != 4", mesh, poly_idx, poly, len(poly.loop_indices))
			if len(poly.vertices) != 4:
				raise AssertionError("len(poly.vertices) != 4", mesh, poly_idx, poly, len(poly.vertices))
			corners = (
				(0, (t.ax, t.ay), (t.bx, t.by)),  # vert 0: left, bottom
				(1, (t.ax + t.aw, t.ay), (t.bx + t.bw, t.by)),  # vert 1: right, bottom
				(2, (t.ax + t.aw, t.ay + t.ah), (t.bx + t.bw, t.by + t.bh)),  # vert 2: right, up
				(3, (t.ax, t.ay + t.ah), (t.bx, t.by + t.bh)),  # vert 3: left, up
			)
			for vert_idx, uv_a, uv_b in corners:
				mesh.vertices[poly.vertices[vert_idx]].co.xy = uv_b
				mesh.vertices[poly.vertices[vert_idx]].co.z = poly_idx * 0.001
				uvd_original[poly.loop_indices[vert_idx]].uv = uv_a
				uvd_atlas[poly.loop_indices[vert_idx]].uv = uv_b
			poly.material_index = mat2idx[t.attachment.material.material]
		
		# Вставляем меш на сцену
		obj = bpy.data.objects.new("__Kawa_Bake_UV_Object", mesh)  # add a new object using the mesh
		bpy.context.scene.collection.objects.link(obj)
		bpy.context.view_layer.objects.active = obj
		bpy.context.view_layer.objects.active.select_set(True)
		
		if len(mesh.polygons) != len(transforms):
			raise AssertionError("len(mesh.polygons) != len(transforms)", mesh, len(mesh.polygons), len(transforms))
		
		for mat in materials:
			prepare_and_get_node_for_baking(mat)
		
		for atex_setup in self.prepare_all_atlas_textures().values():
			atex_image = None
			try:
				atex_image = atex_setup.prepare_image()
				
				obj = bpy.context.view_layer.objects.active
				obj.hide_set(False)
				obj.hide_render = False
				
				for layer in get_mesh_safe(obj).uv_layers:  # type: bpy.types.MeshUVLoopLayer
					layer.active = layer.name == UV_ATLAS
					layer.active_render = layer.name == UV_ORIGINAL
					layer.active_clone = False

				bake_type = 'EMIT' if atex_setup.type == 'ALPHA' else atex_setup.type
				for mat in materials:
					n_bake = prepare_and_get_node_for_baking(mat)
					n_bake.image = atex_image
					if atex_setup.type == 'ALPHA':
						configure_for_baking_alpha(mat)
					else:
						configure_for_baking_default(mat)
				
				bpy.context.scene.cycles.bake_type = bake_type
				bpy.context.scene.render.bake.use_pass_direct = False
				bpy.context.scene.render.bake.use_pass_indirect = False
				bpy.context.scene.render.bake.use_pass_color = True
				bpy.context.scene.render.bake.use_pass_emit = atex_setup.type == 'EMIT'
				bpy.context.scene.render.bake.normal_space = 'TANGENT'
				bpy.context.scene.render.bake.margin = 64 if not self.fast_mode else 2
				bpy.context.scene.render.bake.use_clear = True
				
				# bpy.context.scene.render.bake_aa_mode = '5' # Bl. R.
				# bpy.context.scene.render.antialiasing_samples = '5' # Bl. R.
				
				log.info(
					"Trying to bake atlas Texture='%s' type='%s' size=%s from %d transforms...",
					atex_image.name, atex_setup.type, tuple(atex_image.size), len(transforms)
				)
				
				# if atex_setup.type == 'ALPHA':
				# 	raise RuntimeError("Debug Boop!")
				
				bake_start = time.perf_counter()
				ensure_op_finished(bpy.ops.object.bake(type=bake_type, use_clear=True))
				bake_time = time.perf_counter() - bake_start
				log.info("Baked atlas Texture='%s' type='%s', time spent: %f sec.", atex_image.name, atex_setup.type, bake_time)
				save_path = bpy.path.abspath('//' + stamp + "_" + atex_image.name + ".png")
				log.info("Saving Texture='%s' type='%s' as '%s'...", atex_image.name, atex_setup.type, save_path)
				atex_image.save_render(save_path)
				log.info("Saved Texture='%s' type='%s' as '%s'...", atex_image.name, atex_setup.type, save_path)
				
				for mat in materials:
					configure_for_baking_default(mat)
			except Exception as exc:
				raise RuntimeError("Error bake!", atex_image.name, atex_setup.type, atex_image, bpy.context.view_layer.objects.active) from exc

		if bpy.context.view_layer.objects.active is not None:
			bpy.context.blend_data.meshes.remove(get_mesh_safe(bpy.context.view_layer.objects.active), do_unlink=True)
		if bpy.context.view_layer.objects.active is not None:
			bpy.context.blend_data.objects.remove(bpy.context.view_layer.objects.active, do_unlink=True)
		ensure_deselect_all_objects()
	
	@classmethod
	def combine_proc_objects(cls, proc_objects: 'Iterable[ProcessingObjectSetup]') -> 'Set[bpy.types.Object]':
		targets = set()
		log.info("Combining processing objects into targets...")
		for pobj_setup in proc_objects:
			pobj = pobj_setup.object
			tobj_name = pobj_setup.get_target_object_name()
			tobj = bpy.context.scene.objects.get(tobj_name)  # type: bpy.types.Object
			targets.add(tobj)
			ensure_deselect_all_objects()
			pobj.select_set(True)
			tobj.select_set(True)
			bpy.context.view_layer.objects.active = tobj
			# log.debug("Combining: %s", str(list(obj.name for obj in bpy.context.selected_objects)))
			ensure_op_finished(bpy.ops.object.join(), name="bpy.ops.object.join")
		ensure_deselect_all_objects()
		for tobj in targets:
			try:
				tobj.hide_select, tobj.hide_render = False, False
				tobj.hide_set(False)
				tobj.select_set(True)
				bpy.context.view_layer.objects.active = tobj
				ensure_op_finished(bpy.ops.object.mode_set(mode='EDIT'), name="bpy.ops.object.mode_set")
				bpy.context.tool_settings.mesh_select_mode = (False, True, False)  # Edge selection
				ensure_op_finished(bpy.ops.mesh.select_all(action='DESELECT'), name="bpy.ops.mesh.select_all")
				ensure_op_finished(bpy.ops.mesh.select_non_manifold(
					extend=True, use_wire=False, use_boundary=True, use_multi_face=False, use_non_contiguous=False, use_verts=False
				), name="bpy.ops.mesh.select_non_manifold")
				ensure_op_finished(bpy.ops.mesh.remove_doubles(threshold=1e-06), name="bpy.ops.mesh.remove_doubles")
			finally:
				ensure_op_finished(bpy.ops.object.mode_set(mode='OBJECT'), name="bpy.ops.object.mode_set")
		ensure_deselect_all_objects()
		log.info("Combined %d processing objects.", len(targets))
		return targets
	
	def rename_proc_uvs(self, target_objects: 'Iterable[bpy.types.Object]'):
		log.info("Renaming and removing UVs on target objects...")
		counter_rm, counter_rn = 0, 0
		for tobj in target_objects:
			tmesh, uv_atlas_original, uv_atlas_target, uv_lm_original, uv_lm_target = None, None, None, None, None
			try:
				tmesh = get_mesh_safe(tobj)
				
				def should_remove(name, _):
					if name == self.PROC_ORIGINAL_ATLAS_UV_NAME: return True
					if name == self.PROC_ORIGINAL_LM_UV_NAME: return True
					return False
				
				def do_remove(name, _):
					nonlocal counter_rm
					# log.info("Removed %s", name)
					counter_rm += 1
				
				remove_uv_layer_by_condition(tmesh, should_remove, do_remove)
				
				uv_atlas_target = tmesh.uv_layers.get(self.PROC_TARGET_ATLAS_UV_NAME)
				if uv_atlas_target is not None:
					uv_atlas_target.name = self.get_atlas_target_uv()
					counter_rn += 1
				uv_lm_target = tmesh.uv_layers.get(self.PROC_TARGET_LM_UV_NAME)
				if uv_lm_target is not None:
					uv_lm_target.name = self.get_lm_target_uv()
					counter_rn += 1
			
			except Exception as exc:
				raise RuntimeError("Error renaming UV!", tobj, tmesh, uv_atlas_original, uv_atlas_target, uv_lm_original, uv_lm_target) from exc
		log.info("Removed=%d, Renamed=%d UVs on target objects!", counter_rm, counter_rn)
	
	def run(self):
		print()
		log.info('Preparing...')
		
		log.info('Using original objects: %s', tuple(x.name for x in self.original_objects.keys()))
		
		log.info('Preparing original materials...')
		original_materials = self.get_all_original_materials()
		log.info('Using original materials: %s', tuple(x.name for x in original_materials.keys()))
		
		log.info('Preparing target textures...')
		target_textures = self.prepare_all_atlas_textures()
		log.info('Using target textures: %s', tuple(x.prepare_texture().name for x in target_textures.values()))
		
		log.info('Preparing target materials...')
		target_materials = self.prepare_all_atlas_materials()
		log.info('Using target materials: %s', list(target_materials.keys()))
		
		log.info('Preparing target objects...')
		self.prepare_target_objects()
		
		log.info('Making copies for processing on...')
		proc_objects, proc_main, proc_lightmap, proc_none, new_objs = self.prepare_proc_objects()
		
		for pobj_setup in proc_none:  # type: ProcessingObjectSetup
			log.info("Ignoring Object='%s' Material='%s'...", pobj_setup.original.object.name, pobj_setup.get_material_bpy().name)
		
		if len(proc_main) > 0:
			log.info('Looking for UV-Main islands...')
			builders = self.atlas_find_islands(proc_main)
			# log.debug('Found UV-Main islands: ')
			for mat, builder in builders.items():
				# log.debug("UV-Main Islands for material '%s': %d", mat.name, len(builder.bboxes))
				for island in builder.bboxes:
					# log.debug("\tUV-Main island: is_valid=%s mn=%s mx=%s", island.is_valid(), island.mn, island.mx)
					pass
				pass
			log.info('Found %d UV-Main islands.', sum(len(builder.bboxes) for builder in builders.values()))
			
			log.info('Re-packing UV-Main islands...')
			mathutils_boxes = self.atlas_islands_to_mathutils_boxes(builders)
			mathutils_boxes = self.atlas_pack_islands(mathutils_boxes)
			
			log.info('Preparing UV-Main transforms...')
			transforms = self.atlas_mathutils_boxes_to_transforms(mathutils_boxes)
			log.info('Prepared UV-Main transforms: %d', len(transforms))
			# for tr in self.transforms:
			# 	log.info("UVBoxTransform: ", (tr.attachment.material.material.layer_name, str(tr)))
			
			log.info('Applying UV-Main transforms...')
			transformed = 0
			for transform in transforms:
				transformed += transform.apply()
			log.info('Transformed UV loops: %d', transformed)
			
			print('Baking Atlas...')
			# self.atlas_bake_legacy(proc_main)
			self.atlas_bake_optimized(transforms)
			
			log.info("Re-assigning materials...")
			for pobj_setup in proc_main: pobj_setup.reassign_material()
		
		else:
			log.warning("There is no objects for UV-Main processing, is it OK?")
		
		if len(proc_lightmap) > 0:
			# log.info('Re-scaling UV-Lightmaps...')
			pass  # TODO
		else:
			log.info("There is no objects for UV-Lightmap processing.")
		
		log.info("Combining meshes...")
		target_objects = self.combine_proc_objects(proc_objects)
		
		for new_obj in new_objs:
			log.info("Unlinking temporary Object='%s'", new_obj.name)
			bpy.context.scene.collection.objects.unlink(new_obj)
		
		for tobj in target_objects:
			log.info("Updating UV1 in Target Object='%s'...", tobj.name)
			tobj_mesh = get_mesh_safe(tobj)
			uv1_target = tobj_mesh.uv_layers.get(self.PROC_TARGET_LM_UV_NAME)  # type: bpy.types.MeshTexturePolyLayer
			if uv1_target is None:
				log.info("Target Object='%s' does not have target uv1 (%s)", tobj.name, tobj_mesh.uv_layers.keys())
				continue
			repack_lightmap_uv(tobj, self.PROC_TARGET_LM_UV_NAME, rotate=True, margin=0.003)
		
		self.rename_proc_uvs(target_objects)
		
		for oobj in self.original_objects.values():
			oobj.object.hide_set(True)
			oobj.object.hide_render = True
			oobj.object.hide_select = False
		
		log.info('Done!')
