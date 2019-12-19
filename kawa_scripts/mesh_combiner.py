# Kawashirov's Scripts (c) 2019 by Sergey V. Kawashirov
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

if typing.TYPE_CHECKING:
	from typing import *
	
	T = TypeVar('T')
	
	SetupRaw = Dict[str, Any]
	SizeInt = Tuple[int, int]
	SizeFloat = Tuple[float, float]
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
logging.basicConfig(level=logging.INFO, format='%(asctime)-15s %(levelname)8s %(layer_name)s %(message)s')


# Вспомогательные функции

def find_uv_layer(
		mesh: 'bpy.types.Mesh', layer_name: 'str', exclude: 'List[bpy.types.MeshTexturePolyLayer]'
) -> 'bpy.types.MeshTexturePolyLayer':
	# Находит UV слой с указанным именем, а если такого нет, то первый, котоырй не указан в exclude:
	if not is_valid_string(layer_name):
		raise ValueError("find_uv_layer: mesh, layer_name, exclude:", mesh, layer_name, exclude)
	uv_layer = mesh.uv_textures.get(layer_name)  # type: Optional[bpy.types.MeshTexturePolyLayer]
	if uv_layer is None:
		for layer in mesh.uv_textures:  # type: bpy.types.MeshTexturePolyLayer
			if layer not in exclude:
				uv_layer = layer
				break
	return uv_layer


def common_str_slots(obj, keys: 'Iterable[str]', exclude: 'Collection[str]' = tuple()) -> 'str':
	return str(type(obj).__name__) + str({
		key: getattr(obj, key, None) for key in keys if key not in exclude and getattr(obj, key, None) is not None
	})


class OriginalMaterialSetup:
	# Описывает свойства и правила для конкретного материала
	
	L_ATLAS_SCALE = 'atlas_scale'
	L_ORIGINAL_SIZE = 'atlas_size'
	
	L_LM_SCALE = 'lightmap_scale'
	
	__slots__ = (
		'parent', 'material',
		'original_size', '_detected_size',
		'atlas_ignore', 'atlas_material_name', 'atlas_single_island', 'atlas_scale', 'atlas_epsilon',
		'lm_ignore', 'lm_scale',
	)
	
	def __init__(self, parent: 'KawaMeshCombiner', material: 'bpy.types.Material'):
		self.parent = parent  # type: KawaMeshCombiner
		self.material = material  # type: bpy.types.Material
		
		self.original_size = None  # type: Optional[SizeFloat]
		# Если False определение не производилось
		self._detected_size = False  # type: Union[SizeFloat, bool, None]
		
		self.atlas_ignore = None  # type: Optional[bool]
		self.atlas_material_name = None  # type: Optional[str]
		self.atlas_single_island = None  # type: Optional[bool]
		self.atlas_scale = 1.0  # type: float
		self.atlas_epsilon = None  # type: Optional[float]
		
		self.lm_ignore = None  # type: Optional[bool]
		self.lm_scale = 1.0  # type: float
	
	@classmethod
	def from_raw_config(
			cls, parent: 'KawaMeshCombiner', material: 'bpy.types.Material', raw_setup: 'Optional[SetupRaw]'
	) -> 'OriginalMaterialSetup':
		omat_setup = cls(parent, material)
		
		if omat_setup is None:
			omat_setup = dict()
		
		prefix = parent.L_ORIGINAL_MATERIALS + '.' + material.name + '.'
		
		atlas_ignore = parent.validate_bool(
			raw_setup.get(KawaMeshCombiner.L_ATLAS_IGNORE), prefix + KawaMeshCombiner.L_ATLAS_IGNORE
		)
		omat_setup.atlas_ignore = any_not_none(atlas_ignore, omat_setup.atlas_ignore)
		if omat_setup.atlas_ignore is not True:
			omat_setup.atlas_material_name = parent.validate_string(
				raw_setup.get(KawaMeshCombiner.L_ATLAS_TARGET_MATERIAL), prefix + KawaMeshCombiner.L_ATLAS_TARGET_MATERIAL
			)
			omat_setup.atlas_single_island = parent.validate_bool(
				raw_setup.get(KawaMeshCombiner.L_ATLAS_SINGLE_ISLAND), prefix + KawaMeshCombiner.L_ATLAS_SINGLE_ISLAND
			)
			omat_setup.atlas_epsilon = parent.validate_int_positive_or_zero(
				raw_setup.get(KawaMeshCombiner.L_ATLAS_EPSILON), prefix + KawaMeshCombiner.L_ATLAS_EPSILON
			)
			atlas_scale = parent.validate_float(raw_setup.get(cls.L_ATLAS_SCALE), prefix + cls.L_ATLAS_SCALE)
			omat_setup.atlas_scale = any_not_none(atlas_scale, omat_setup.atlas_scale)
			
			omat_setup.original_size = parent.validate_size_int(raw_setup.get(cls.L_ORIGINAL_SIZE), prefix + cls.L_ORIGINAL_SIZE)
		
		lm_ignore = parent.validate_bool(raw_setup.get(KawaMeshCombiner.L_LM_IGNORE), prefix + KawaMeshCombiner.L_LM_IGNORE)
		omat_setup.lm_ignore = any_not_none(lm_ignore, omat_setup.lm_ignore)
		if omat_setup.lm_ignore is not True:
			lm_scale = parent.validate_float(raw_setup.get(cls.L_LM_SCALE), prefix + cls.L_LM_SCALE)
			omat_setup.lm_scale = any_not_none(lm_scale, omat_setup.lm_scale)
		return omat_setup
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def find_tex_size(self) -> 'Optional[SizeFloat]':
		tex_sz_x, tex_sz_y, tex_count = 0, 0, 0
		if self.material.texture_slots is not None:
			for slot in self.material.texture_slots:
				if slot is None or not slot.use: continue
				if isinstance(slot.texture, bpy.types.ImageTexture):
					image = slot.texture.image  # type: bpy.types.Image
					tex_sz_x += image.size[0]
					tex_sz_y += image.size[1]
					tex_count += 1
		return (float(tex_sz_x) / tex_count, float(tex_sz_y) / tex_count) if tex_count > 0 and tex_sz_x > 0 and tex_sz_y > 0 else None
	
	def get_atlas_material_name(self) -> 'str':
		return any_not_none(self.atlas_material_name, self.parent.atlas_material_name)
	
	def get_atlas_material_setup(self) -> 'AtlasMaterialSetup':
		atlas_material_name = self.get_atlas_material_name()
		if atlas_material_name is None:
			raise ConfigurationError('atlas_material_name is not set!', self.material, self.atlas_material_name, self.parent.atlas_material_name)
		return self.parent.get_atlas_material_setup(atlas_material_name)
	
	def get_atlas_ignore(self) -> 'bool':
		atlas_ignore = any_not_none(self.atlas_ignore, self.parent.atlas_ignore)
		if atlas_ignore is None:
			raise ConfigurationError('atlas_ignore is not set!', self.material, self.atlas_ignore, self.parent.atlas_ignore)
		return atlas_ignore
	
	def get_original_size(self) -> 'SizeFloat':
		if self.get_atlas_ignore():
			raise RuntimeError('Can not get original_size, because atlas_ignore is set to True!', self.material)
		if self.original_size is not None:
			return self.original_size
		if self._detected_size is False:
			self._detected_size = self.find_tex_size()
		if self._detected_size is not None:
			return self._detected_size
		if self.parent.original_size is not None:
			return self.parent.original_size
		raise ConfigurationError('original_size is not set!', self.material, self.original_size, self.parent.original_size)
	
	def get_atlas_single_island(self) -> 'bool':
		if self.get_atlas_ignore():
			raise RuntimeError('Can not get atlas_single_island, because atlas_ignore is set to True!', self.material)
		if self.parent.fast_mode:
			return True
		atlas_single_island = any_not_none(self.atlas_single_island, self.parent.atlas_single_island)
		if atlas_single_island is None:
			raise ConfigurationError('atlas_single_island is not set!', self.material, self.atlas_single_island, self.parent.atlas_single_island)
		return atlas_single_island
	
	def get_atlas_epsilon(self) -> 'float':
		if self.get_atlas_ignore():
			raise RuntimeError('Can not get atlas_epsilon, because atlas_ignore is set to True!', self.material)
		epsilon = any_not_none(self.atlas_epsilon, self.parent.atlas_epsilon)
		if epsilon is None:
			raise ConfigurationError('atlas_epsilon is not set!', self.material, self.atlas_epsilon, self.parent.atlas_epsilon)
		return epsilon
	
	def get_lm_ignore(self) -> 'bool':
		lm_ignore = any_not_none(self.lm_ignore, self.parent.lm_ignore)
		if lm_ignore is None:
			raise ConfigurationError('lm_ignore is not set!', self.material, self.lm_ignore, self.parent.lm_ignore)
		return lm_ignore
	
	def check_values(self):
		self.get_atlas_material_name()
		if not self.get_atlas_ignore():
			self.get_original_size()
			self.get_atlas_single_island()
			self.get_atlas_epsilon()
		self.get_lm_ignore()


class AtlasTextureSetup:
	# Описывает свойства и правила для текстуры, в которую будет запекаться результат
	
	SUPPORTED_TYPES = {'TEXTURE', 'EMIT', 'NORMALS', 'SPEC_INTENSITY', 'SPEC_COLOR'}
	
	L_TYPE = 'type'
	L_SIZE = 'size'
	
	__slots__ = (
		'parent', 'texture', 'image',
		'type', 'size'
	)
	
	def __init__(self, parent: 'KawaMeshCombiner', _type: 'str', **setup):
		self.parent = parent
		self.texture = None  # type: Optional[bpy.types.ImageTexture]
		self.image = None  # type: Optional[bpy.types.Image]
		
		if _type not in self.SUPPORTED_TYPES:
			raise ConfigurationError("Invalid type of texture!", _type, self.SUPPORTED_TYPES)
		
		if setup is None:
			setup = dict()
		
		prefix = parent.L_ATLAS_TEXTURES + '.' + _type + '.'
		self.type = _type
		self.size = parent.validate_size_int(setup.get(self.L_SIZE), prefix + self.L_SIZE)
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def get_texture_name(self):
		return self.parent.atlas_texture_prefix + '-' + self.type
	
	def get_size(self) -> 'SizeInt':
		return any_not_none(self.size, self.parent.atlas_size)
	
	def prepare_texture(self) -> 'bpy.types.Texture':
		if self.texture is not None:
			return self.texture
		tex = None
		tex_name = None
		try:
			tex_name = self.get_texture_name()
			tex = bpy.context.blend_data.textures.get(tex_name)  # type: Optional[Union[bpy.types.Texture, bpy.types.ImageTexture]]
			if tex is not None and not isinstance(tex, bpy.types.ImageTexture):
				log.warning("Removing atlas texture '%s', because it's not ImageTexture: %s", tex_name, tex, type(tex))
				bpy.context.blend_data.textures.remove(tex)
				tex = None
			if tex is None:
				tex = bpy.context.blend_data.textures.new(tex_name, 'IMAGE')
			tex.image = self.prepare_image()
			self.texture = tex
			return self.texture
		except Exception as exc:
			raise RuntimeError("Error creating atlas texture", tex_name, tex) from exc
	
	def prepare_image(self) -> 'bpy.types.Image':
		if self.image is not None:
			return self.image
		image = None
		image_name = None
		try:
			image_name = self.get_texture_name()
			size = self.get_size()
			image = bpy.context.blend_data.images.get(image_name)  # type: Optional[bpy.types.Image]
			if image is not None and (image.size[0] != size[0] or image.size[1] != size[1]):
				s = image.size
				log.warning("Removing atlas image '%s', because of wrong size: need %s, have %s", image.name, size, (s[0], s[1]))
				bpy.context.blend_data.images.remove(image)
				image = None
			if image is not None and image.channels != 4:
				log.warning("Removing atlas image '%s', because of wrong number of channels: need 4, have %s", image.name, image.channels)
				bpy.context.blend_data.images.remove(image)
				image = None
			if image is None:
				log.info("Creating new atlas image '%s'...", image_name)
				image = bpy.context.blend_data.images.new(image_name, size[0], size[1], alpha=True, float_buffer=False)
			image.colorspace_settings.name = 'Non-Color' if self.type is 'NORMALS' else 'sRGB'
			self.image = image
			return self.image
		except Exception as exc:
			raise RuntimeError("Error creating atlas image!", image_name, image) from exc
	
	def _get_or_create_slot(self, tmat: 'bpy.types.Material') -> 'bpy.types.MaterialTextureSlot':
		# Переиспользование или создание слота с этой текстуре в данном материале
		ttex = self.prepare_texture()
		for slot_index in range(len(tmat.texture_slots)):
			slot = tmat.texture_slots[slot_index]
			if slot is not None and tmat.texture_slots[slot_index].texture == ttex:
				return tmat.texture_slots[slot_index]
		new_slot = tmat.texture_slots.add()  # type: bpy.types.MaterialTextureSlot
		new_slot.texture = ttex
		return new_slot
	
	def attach_to(self, tmat: 'bpy.types.Material'):
		slot = self._get_or_create_slot(tmat)
		slot.use_map_color_diffuse = self.type == 'TEXTURE'
		slot.use_map_alpha = self.type == 'TEXTURE'
		slot.use_map_emission = self.type == 'EMIT'
		slot.use_map_normal = self.type == 'NORMALS'
		slot.use_map_specular = self.type == 'SPEC_INTENSITY'
		slot.use_map_color_spec = self.type == 'SPEC_COLOR'
		slot.use_rgb_to_intensity = self.type == 'EMIT'
		slot.blend_type = 'MULTIPLY'
		if self.type == 'EMIT':
			tmat.emit = 1


class AtlasMaterialSetup:
	# Описывает свойства и правила для конечного материала
	
	L_ORDER = 'order'
	L_USE_TRANSPARENCY = 'use_transparency'
	L_ALPHA = 'alpha'
	
	__slots__ = (
		'parent', 'name', 'material',
		'order', 'use_transparency', 'alpha',
	)
	
	def __init__(self, parent: 'KawaMeshCombiner', name: 'str', **setup):
		self.parent = parent
		self.name = name
		self.material = None  # type: Optional[bpy.types.Material]
		
		if setup is None: setup = dict()
		
		prefix = parent.L_ORIGINAL_MATERIALS + '.' + name + '.'
		self.order = parent.validate_float(setup.get(self.L_ORDER), prefix + self.L_ORDER)
		self.use_transparency = parent.validate_bool(setup.get(self.L_USE_TRANSPARENCY), prefix + self.L_USE_TRANSPARENCY)
		self.alpha = parent.validate_bool(setup.get(self.L_ALPHA), prefix + self.L_ALPHA)
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def prepare_material_bpy(self) -> 'bpy.types.Material':
		if self.material is not None:
			return self.material
		try:
			tmat = bpy.context.blend_data.materials.get(self.name)  # type: bpy.types.Material
			if tmat is None:
				log.info("Target material='%s' does not exist, creating new one...", self.name)
				tmat = bpy.context.blend_data.materials.new(self.name)
			self.material = tmat
			for slot_index in range(len(tmat.texture_slots)):
				if tmat.texture_slots[slot_index] is not None:
					tmat.texture_slots.clear(slot_index)
			tmat.diffuse_intensity = 1
			tmat.diffuse_color = (1, 1, 1)
			for atex_name, atex_setup in self.parent.prepare_all_atlas_textures().items():
				atex_setup.attach_to(tmat)
			return self.material
		except Exception as exc:
			raise RuntimeError("Error creating material!", self.name, self.material) from exc


class OriginalObjectSetup:
	# Описывает свойства и правила для исходного меш-объекта
	
	L_KEEP_UV_LAYERS = 'keep_uv_layers'
	
	__slots__ = (
		'parent', 'object', '_target_object_name', 'keep_uv_layers',
		'_uv0_original',
		'_uv1_original',
	)
	
	def __init__(self, parent: 'KawaMeshCombiner', _object: 'bpy.types.Object', **setup):
		self.parent = parent
		self.object = _object  # type: bpy.types.Object
		
		if setup is None:
			setup = dict()
		
		prefix = parent.L_ORIGINAL_OBJECTS + '.' + _object.name + '.'
		self._target_object_name = parent.validate_string(setup.get(parent.L_TARGET_OBJECT), prefix + parent.L_TARGET_OBJECT)
		self._uv0_original = parent.validate_uv_index(setup.get(parent.L_UV0_ORIGINAL), prefix + parent.L_UV0_ORIGINAL)
		self._uv1_original = parent.validate_uv_index(setup.get(parent.L_UV1_ORIGINAL), prefix + parent.L_UV1_ORIGINAL)
		
		self.keep_uv_layers = set()
		for entry in KawaMeshCombiner.validate_seq_as_iterator(setup.get(self.L_KEEP_UV_LAYERS)):
			if not is_valid_string(entry):
				raise ConfigurationError("Invalid entry in config!", prefix, entry)
			self.keep_uv_layers.add(entry)
		pass
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__, ('parent',))
	
	def get_target_object_name(self) -> 'str':
		tobj_name = any_not_none(self._target_object_name, self.parent.target_object_name)
		if not is_valid_string(tobj_name):
			raise ConfigurationError("target_object_name is not set!", self.object.name, self._target_object_name, self.parent.target_object_name)
		return tobj_name
	
	def get_uv0_original(self) -> 'UVLayerIndex':
		return any_not_none(self._uv0_original, self.parent.uv0_original)
	
	def get_uv0_original_safe(self) -> 'str':
		uv0_original = self.get_uv0_original()
		if not is_valid_string(uv0_original):
			raise ConfigurationError("uv0_original is not set!", self.object.name, self._uv0_original, self.parent.uv0_original)
		return uv0_original
	
	def get_uv1_original(self) -> 'UVLayerIndex':
		return any_not_none(self._uv1_original, self.parent.uv1_original)
	
	def get_uv1_original_safe(self) -> 'str':
		uv1_original = self.get_uv1_original()
		if not is_valid_string(uv1_original):
			raise ConfigurationError("uv1_original is not set!", self.object.name, self._uv1_original, self.parent.uv1_original)
		return uv1_original
	
	pass


class ProcessingObjectSetup:
	# Описывает свойства и правила для меш-объекта, на котором идет обработка
	__slots__ = ('parent', 'object', 'original')
	
	def __init__(self, parent: 'KawaMeshCombiner', _object: 'bpy.types.Object', original: 'OriginalObjectSetup'):
		self.parent = parent
		self.object = _object  # type: bpy.types.Object
		self.original = original  # type: OriginalObjectSetup
	
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
		return get_mesh_safe(self.object).uv_textures[self.parent.PROC_ORIGINAL_ATLAS_UV_NAME]
	
	def get_atlas_target_uv(self) -> 'bpy.types.MeshTexturePolyLayer':
		return get_mesh_safe(self.object).uv_textures[self.parent.PROC_TARGET_ATLAS_UV_NAME]
	
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
	
	def __init__(self, material: 'OriginalMaterialSetup', per_ob: 'AttachmentPerObjects', area=0.0):
		# Материал, на котором находится остров, используется только для проверки совместимости
		self.material = material  # type: OriginalMaterialSetup
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


class Island:
	# Описывает остров текстуры материала, ограничивающий подмножество UV
	# Координаты - в размерах текстур
	__slots__ = ('mn', 'mx', 'attachment', 'extends')
	
	def __init__(
			self, mn: 'Optional[mathutils.Vector]', mx: 'Optional[mathutils.Vector]',
			attachment: 'Optional[AttachmentPerMaterial]'
	):
		self.mn = mn  # type: Optional[mathutils.Vector]
		self.mx = mx  # type: Optional[mathutils.Vector]
		self.attachment = attachment  # type: Optional[AttachmentPerMaterial]
		self.extends = 0  # Для диагностических целей
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def is_valid(self):
		return self.mn is not None and self.mx is not None and self.attachment is not None
	
	def is_inside_vec2(self, item: mathutils.Vector, epsilon: 'float' = 0):
		if type(item) != mathutils.Vector:
			raise ValueError("type(item) != mathutils.Vector")
		if len(item) != 2:
			raise ValueError("len(item) != 2")
		if self.mn is None or self.mx is None:
			return False
		mnx, mny = self.mn.x - epsilon, self.mn.y - epsilon
		mxx, mxy = self.mx.x + epsilon, self.mx.y + epsilon
		return mnx <= item.x <= mxx and mny <= item.y <= mxy
	
	def is_inside_bbox(self, inner: 'Island', epsilon: 'float' = 0) -> bool:
		# Проверяет лежит ли inner внутри self
		if self.mn is None or self.mx is None or inner.mn is None or inner.mx is None:
			return False
		if inner.mx.x + epsilon >= self.mx.x or inner.mx.y + epsilon >= self.mx.y:
			return False
		if inner.mn.x - epsilon <= self.mn.x or inner.mn.y - epsilon <= self.mn.y:
			return False
		return True
	
	def get_points(self) -> 'Sequence[mathutils.Vector]':
		return self.mn, self.mx, mathutils.Vector((self.mn.x, self.mx.y)), mathutils.Vector((self.mx.x, self.mn.y))
	
	def any_inside_vec2(self, items: 'Iterable[mathutils.Vector]', epsilon: 'float' = 0):
		return any(self.is_inside_vec2(x, epsilon=epsilon) for x in items)
	
	def is_intersect(self, other: 'Island', epsilon: 'float' = 0):
		return any(self.is_inside_vec2(x, epsilon=epsilon) for x in other.get_points())
	
	def extend_by_vec2(self, vec2: 'mathutils.Vector'):
		if self.mn is None:
			self.mn = vec2.xy
		else:
			self.mn.x = min(self.mn.x, vec2.x)
			self.mn.y = min(self.mn.y, vec2.y)
		if self.mx is None:
			self.mx = vec2.xy
		else:
			self.mx.x = max(self.mx.x, vec2.x)
			self.mx.y = max(self.mx.y, vec2.y)
		self.extends += 1
	
	def extend_by_vec2s(self, vec2s: 'Iterable[mathutils.Vector]'):
		for vec2 in vec2s:
			self.extend_by_vec2(vec2)
	
	def extend_by_bbox(self, other: 'Island'):
		if self is other:
			raise ValueError("self is other ", self, other)
		if not other.is_valid():
			raise ValueError("other bbox is not valid", self, other, other.attachment)
		self.extend_by_vec2s(other.get_points())
		if self.attachment is not None:
			if not self.attachment.is_compatible(other.attachment):
				raise ValueError('Attachments is not compatible', self, other, self.attachment, other.attachment)
			self.attachment.extend_from_other(other.attachment)
		else:
			# Перенос на себя
			self.attachment = other.attachment
		other.attachment = None  # Т.к. мы забрали данные, делаем другой не-валидным
		if not self.is_valid():
			raise ValueError("Invalid after extend_by_bbox", self, other, self.attachment, other.attachment)
	
	def get_area(self) -> 'float':
		if not self.is_valid():
			raise ValueError("bbox is not valid", self)
		return (self.mx.x - self.mn.x) * (self.mx.y - self.mn.y)


class IslandsBuilder:
	# Занимается разбиением множества точек на прямоугольные непересекающиеся подмноджества
	__slots__ = ('bboxes', 'merges')
	
	def __init__(self):
		self.bboxes = list()  # type: List[Island]
		self.merges = 0  # Для диагностических целей
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def add_bbox(self, bbox: 'Island', epsilon: 'float' = 0):
		# Добавляет набор точек
		if not bbox.is_valid():
			raise ValueError("Invalid bbox!")
		
		bbox_to_add = bbox
		while bbox_to_add is not None:
			target_idx = -1
			# Поиск первго бокса с которым пересекается текущий
			for i in range(len(self.bboxes)):
				if self.bboxes[i] is bbox_to_add:
					raise ValueError("bbox already in bboxes:", (bbox_to_add, self.bboxes[i], self.bboxes))
				# Эта оптимизация больше не прокатывает, т.к. есть обмен метаданными
				# if self.bboxes[i].is_inside_bbox(bbox_to_add, epsilon=epsilon):
				#     return  # Если втавляемый bbox внутри существующего, то ничего не надо делать
				if self.bboxes[i].is_intersect(bbox_to_add, epsilon=epsilon):
					target_idx = i
					break
			if target_idx == -1:
				# Пересечение не найдено, добавляем
				self.bboxes.append(bbox_to_add)
				bbox_to_add = None
			else:
				# Пересечение найдено - вытаскиваем, соединяем, пытаемся добавить еще раз
				ejected = self.bboxes[target_idx]
				del self.bboxes[target_idx]
				# print("add_bbox: extending: ", (ejected, bbox_to_add))
				# print("add_bbox: merges: ", self.merges)
				# print("add_bbox: len(bboxes): ", len(self.bboxes))
				ejected.extend_by_bbox(bbox_to_add)
				bbox_to_add = ejected
				self.merges += 1
	
	def add_seq(
			self, vec2s: 'Iterable[mathutils.Vector]',
			attachment: 'AttachmentPerMaterial', epsilon: 'float' = 0
	):
		vec2s = list(vec2s)
		if len(vec2s) != 0:
			newbbox = Island(None, None, attachment)
			newbbox.extend_by_vec2s(vec2s)
			# print("add_seq: add_bbox: ", newbbox)
			self.add_bbox(newbbox, epsilon=epsilon)
		else:
			print("Warn: add_seq: empty vec2s!")
	
	def get_extends(self):
		return sum(bbox.extends for bbox in self.bboxes)


class UVBoxTransform:
	# Описывает преобразование UV, а так же хранит связанные полигоны
	__slots__ = (
		'ax', 'ay', 'aw', 'ah',
		'bx', 'by', 'bw', 'bh',
		'attachment',
	)
	
	def __init__(self, ax, ay, aw, ah, bx, by, bw, bh, attachment):
		self.ax, self.ay, self.aw, self.ah = ax, ay, aw, ah
		self.bx, self.by, self.bw, self.bh = bx, by, bw, bh
		self.attachment = attachment  # type: Optional[AttachmentPerMaterial]
	
	def __str__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def __repr__(self) -> str: return common_str_slots(self, self.__slots__)
	
	def match_a(self, vec2: 'mathutils.Vector', epsilon: 'Optional[float]' = None):
		e = any_not_none(epsilon, 0)
		return self.ax - e <= vec2.x <= self.ax + self.aw + e and self.ay - e <= vec2.y <= self.ay + self.ah + e
	
	def apply_vec2(self, vec2: 'mathutils.Vector'):
		uv = vec2.xy  # копирование
		uv.x = (uv.x - self.ax) / self.aw if self.aw != 0 else 0.5
		uv.y = (uv.y - self.ay) / self.ah if self.ah != 0 else 0.5
		uv.x = uv.x * self.bw + self.bx
		uv.y = uv.y * self.bh + self.by
		return uv
	
	def apply(self):
		counter = 0
		for ob_name, per_ob in self.attachment.per_ob.items():
			uv_layer_original = per_ob.mesh.uv_layers[KawaMeshCombiner.PROC_ORIGINAL_ATLAS_UV_NAME]  # type: bpy.types.MeshUVLoopLayer
			uv_layer_target = per_ob.mesh.uv_layers[KawaMeshCombiner.PROC_TARGET_ATLAS_UV_NAME]  # type: bpy.types.MeshUVLoopLayer
			uv_data_original = uv_layer_original.data
			uv_data_target = uv_layer_target.data
			for poly in per_ob.polys:
				for loop in poly.loop_indices:
					vec2 = uv_data_original[loop].uv
					vec2 = self.apply_vec2(vec2)
					uv_data_target[loop].uv = vec2
					counter += 1
		return counter
	
	def get_area_a(self):
		return self.aw * self.ah


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
	
	@staticmethod
	def validate_uv_index(value: 'UVLayerIndex', field_name: 'str') -> 'UVLayerIndex':
		if value is not False and not is_none_or_valid_string(value):
			log.warning("Invalid config value for for %s='%s'", field_name, value)
			return None
		return value
	
	@staticmethod
	def validate_string(value: 'str', field_name: 'str') -> 'Optional[str]':
		if not is_none_or_valid_string(value):
			log.warning("Invalid config value for %s='%s'", field_name, value)
			return None
		return value
	
	@staticmethod
	def validate_bool(value: 'bool', field_name: 'str') -> 'Optional[bool]':
		if value is not None and not isinstance(value, bool):
			log.warning("Invalid config value for %s='%s'", field_name, value)
			return None
		return value
	
	@staticmethod
	def validate_float(value: 'float', field_name: 'str') -> 'Optional[float]':
		if value is not None and not (isinstance(value, float) or isinstance(value, int)):
			log.warning("Invalid config value for %s='%s'", field_name, value)
			return None
		return value
	
	@staticmethod
	def validate_size_int(value: 'SizeInt', field_name: 'str') -> 'Optional[SizeInt]':
		if value is not None and is_valid_size_int(value):
			log.warning("Invalid config value for %s='%s'", field_name, value)
			return None
		return value
	
	@staticmethod
	def validate_int_positive_or_zero(value: 'int', field_name: 'str') -> 'Optional[int]':
		# Значение должно быть int >= 0
		if value is not None and not (isinstance(value, int) and value >= 0):
			log.warning("Invalid config value for %s='%s'", field_name, value)
			return None
		return value
	
	@staticmethod
	def validate_seq_as_iterator(config: 'SetupRaw') -> 'Iterable[Any]':
		if isinstance(config, set) or isinstance(config, tuple) or isinstance(config, list):
			return iter(config)
		else:
			return iter(())  # empty
	
	@staticmethod
	def validate_set_or_dict_as_iterator(config: 'SetupRaw') -> 'Iterable[Tuple[str, Any]]':
		if isinstance(config, dict):
			return ((k, v) for k, v in config.items())
		elif isinstance(config, set) or isinstance(config, tuple) or isinstance(config, list):
			return ((x, None) for x in config)
		else:
			return iter(())  # empty
	
	__slots__ = (
		'target_object_name', 'atlas_material_name', 'fast_mode',
		'atlas_ignore', 'uv0_original', 'uv0_target', 'atlas_texture_prefix',
		'original_size', 'atlas_size', 'atlas_padding', 'atlas_epsilon', 'atlas_single_island', 'atlas_scale_factor_area',
		'lm_ignore', 'uv1_original', 'uv1_target',
		'original_objects', 'original_materials', 'atlas_materials', 'atlas_textures',
		'created_proc_objects'
	)
	
	def __init__(self):
		self.original_objects = dict()  # type: OriginalObjectSetups
		self.original_materials = dict()  # type: OriginalMaterialSetups
		self.target_object_name = None  # !
		
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
		
		general_setup.target_object_name = cls.validate_string(raw_setup.get(cls.L_TARGET_OBJECT), cls.L_TARGET_OBJECT)
		general_setup.atlas_material_name = cls.validate_string(raw_setup.get(cls.L_ATLAS_TARGET_MATERIAL), cls.L_ATLAS_TARGET_MATERIAL)
		
		uv0_original = cls.validate_string(raw_setup.get(cls.L_UV0_ORIGINAL), cls.L_UV0_ORIGINAL)
		general_setup.uv0_original = any_not_none(uv0_original, general_setup.uv0_original)
		
		uv0_target = cls.validate_string(raw_setup.get(cls.L_UV0_TARGET), cls.L_UV0_TARGET)
		general_setup.uv0_target = any_not_none(uv0_target, general_setup.uv0_target)
		
		uv1_original = cls.validate_string(raw_setup.get(cls.L_UV1_ORIGINAL), cls.L_UV1_ORIGINAL)
		general_setup.uv1_original = any_not_none(uv1_original, general_setup.uv1_original)
		
		uv1_target = cls.validate_string(raw_setup.get(cls.L_UV1_TARGET), cls.L_UV1_TARGET)
		general_setup.uv1_target = any_not_none(uv1_target, general_setup.uv1_target)
		
		atlas_ignore = cls.validate_bool(raw_setup.get(cls.L_ATLAS_IGNORE), cls.L_ATLAS_IGNORE)
		general_setup.atlas_ignore = any_not_none(atlas_ignore, general_setup.atlas_ignore)
		
		atlas_color_size = cls.validate_size_int(raw_setup.get(cls.L_ATLAS_COLOR_SIZE), cls.L_ATLAS_COLOR_SIZE)
		general_setup.original_size = any_not_none(atlas_color_size, general_setup.original_size)
		
		atlas_size = cls.validate_size_int(raw_setup.get(cls.L_ATLAS_SIZE), cls.L_ATLAS_SIZE)
		general_setup.atlas_size = any_not_none(atlas_size, general_setup.atlas_size)
		
		atlas_texture_prefix = cls.validate_size_int(raw_setup.get(cls.L_ATLAS_SIZE), cls.L_ATLAS_SIZE)
		general_setup.atlas_texture_prefix = any_not_none(atlas_texture_prefix, general_setup.atlas_texture_prefix)
		
		atlas_padding = cls.validate_int_positive_or_zero(raw_setup.get(cls.L_ATLAS_PADDING), cls.L_ATLAS_PADDING)
		general_setup.atlas_padding = any_not_none(atlas_padding, general_setup.atlas_padding)
		
		atlas_epsilon = cls.validate_int_positive_or_zero(raw_setup.get(cls.L_ATLAS_EPSILON), cls.L_ATLAS_EPSILON)
		general_setup.atlas_epsilon = any_not_none(atlas_epsilon, general_setup.atlas_epsilon)
		
		atlas_single_island = cls.validate_bool(raw_setup.get(cls.L_ATLAS_SINGLE_ISLAND), cls.L_ATLAS_SINGLE_ISLAND)
		general_setup.atlas_single_island = any_not_none(atlas_single_island, general_setup.atlas_single_island)
		
		lm_ignore = cls.validate_bool(raw_setup.get(cls.L_LM_IGNORE), cls.L_LM_IGNORE)
		general_setup.lm_ignore = any_not_none(lm_ignore, general_setup.lm_ignore)
		
		fast_mode = cls.validate_bool(raw_setup.get(cls.L_FAST_MODE), cls.L_FAST_MODE)
		general_setup.fast_mode = any_not_none(fast_mode, general_setup.fast_mode)
		
		general_setup.original_objects.clear()
		raw_original_objects = raw_setup.get(cls.L_ORIGINAL_OBJECTS)
		for oobj_name, oobj_raw_setup in general_setup.validate_set_or_dict_as_iterator(raw_original_objects):
			general_setup.add_original_object_name(oobj_name, **oobj_raw_setup)
		
		general_setup.original_materials.clear()
		raw_original_materials = raw_setup.get(cls.L_ORIGINAL_MATERIALS)
		for omat_name, omat_raw_setup in general_setup.validate_set_or_dict_as_iterator(raw_original_materials):
			omat = bpy.context.blend_data.materials.get(omat_name)
			if omat is None:
				log.warning("There is no original material='%s'", omat_name)
				continue
			omat_setup = OriginalMaterialSetup.from_raw_config(general_setup, omat, **omat_raw_setup)
			general_setup.original_materials[omat] = omat_setup
		
		general_setup.atlas_materials.clear()
		raw_target_materials = raw_setup.get(cls.L_ATLAS_MATERIALS)
		for amat_name, amat_raw_setup in general_setup.validate_set_or_dict_as_iterator(raw_target_materials):
			if not is_valid_string(amat_name):
				raise ConfigurationError("Invalid target material name!", amat_name)
			amat_setup = AtlasMaterialSetup(general_setup, amat_name, **amat_raw_setup)
			general_setup.atlas_materials[amat_name] = amat_setup
		
		general_setup.atlas_textures.clear()
		raw_target_textures = raw_setup.get(cls.L_ATLAS_TEXTURES)
		for atex_type, atex_raw_setup in general_setup.validate_set_or_dict_as_iterator(raw_target_textures):
			atex_setup = AtlasTextureSetup(general_setup, atex_type, **atex_raw_setup)
			general_setup.atlas_textures[atex_type] = atex_setup
		
		general_setup.atlas_materials.clear()
		return general_setup
	
	def add_atlas_texture(self, _type: 'str', **raw_setup):
		atex_setup = self.atlas_textures.get(_type)
		if atex_setup is not None:
			return atex_setup
		if _type in AtlasTextureSetup.SUPPORTED_TYPES:
			atex_setup = AtlasTextureSetup(self, _type, **raw_setup)
			self.atlas_textures[_type] = atex_setup
		else:
			raise ConfigurationError("Invalid texture type!", _type, AtlasTextureSetup.SUPPORTED_TYPES)
		return atex_setup
	
	def add_original_object_bpy(self, oobj: 'bpy.types.Object', **raw_setup) -> 'OriginalObjectSetup':
		oobj_setup = self.original_objects.get(oobj)
		if oobj_setup is not None:
			return oobj_setup
		oobj_setup = OriginalObjectSetup(self, oobj, **raw_setup)
		self.original_objects[oobj] = oobj_setup
		return oobj_setup
	
	def add_original_object_name(self, oobj_name: 'str', **raw_setup) -> 'OriginalObjectSetup':
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
	
	def get_original_material_setup(self, omat: 'bpy.types.Material') -> 'OriginalMaterialSetup':
		if not isinstance(omat, bpy.types.Material):
			raise TypeError("omat is not Material", omat, type(omat))
		omat_setup = self.original_materials.get(omat)
		if omat_setup is None:
			omat_setup = OriginalMaterialSetup(self, omat)
			omat_setup.material = omat
			self.original_materials[omat] = omat_setup
		return omat_setup
	
	def get_atlas_material_setup(self, amat_name: 'str') -> 'AtlasMaterialSetup':
		if not is_valid_string(amat_name):
			raise ValueError("amat_name is not valid Material name", amat_name)
		amat_setup = self.atlas_materials.get(amat_name)
		if amat_setup is None:
			amat_setup = AtlasMaterialSetup(self, amat_name)
			self.atlas_materials[amat_name] = amat_setup
		return amat_setup
	
	def get_all_original_materials(self) -> 'OriginalMaterialSetups':
		original_materials = dict()
		for oobj_setup in self.original_objects.values():
			for slot in oobj_setup.object.material_slots:
				omat = slot.material
				if omat is None: continue
				if omat in original_materials.keys(): continue
				mat_setup = self.get_original_material_setup(omat)
				original_materials[omat] = mat_setup
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
			if omat_setup.get_atlas_ignore(): continue
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
				tobj.hide = False  # Необходимо, т.к. некоторые операторы не работают на скрытых объектах
				tobj_mesh = get_mesh_safe(tobj)
				
				# Очистка
				remove_all_geometry(tobj)
				remove_all_shape_keys(tobj)
				remove_all_uv_layers(tobj)
				remove_all_vertex_colors(tobj)
				tobj_mesh.materials.clear(update_data=True)  # Очистка Материалов
			except Exception as exc:
				raise RuntimeError("Error preparing target object!", tobj_name) from exc
	
	def prepare_proc_object_final(
			self, pobj: 'bpy.types.Object', oobj_setup: 'OriginalObjectSetup', procs: 'Tuple[List[ProcessingObjectSetup],...]'
	):
		pobj_mat = None
		try:
			proc_all, proc_main, proc_lightmap, proc_none = procs
			global_do_atlas = self.atlas_ignore is not True
			global_do_lm = self.lm_ignore is not True
			
			bpy.context.scene.objects.active = pobj
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
				if is_valid_string(uv0_original_name) and uv0_original_name in mesh.uv_textures.keys():
					# log.debug(
					# 	"Using UV-Layer='%s' as Main (UV0) layer for Object='%s' Material='%s'",
					# 	mesh.uv_textures[uv0_original_name].name, oobj.name, pobj_mat.name
					# )
					# Копия для цели
					bpy.context.scene.objects.active = pobj
					mesh.uv_textures[uv0_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_textures.active.name = KawaMeshCombiner.PROC_TARGET_ATLAS_UV_NAME
					# Копия для исходника
					bpy.context.scene.objects.active = pobj
					mesh.uv_textures[uv0_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_textures.active.name = KawaMeshCombiner.PROC_ORIGINAL_ATLAS_UV_NAME
			
			if global_do_lm:
				uv1_original_name = oobj_setup.get_uv1_original()
				if is_valid_string(uv1_original_name) and uv1_original_name in mesh.uv_textures.keys():
					# log.debug(
					# 	"Using UV-Layer='%s' as Lightmap (UV1) layer for Object='%s' Material='%s'",
					# 	mesh.uv_textures[uv1_original_name].name, oobj.name, pobj_mat.name
					# )
					# Копия для цели
					bpy.context.scene.objects.active = pobj
					mesh.uv_textures[uv1_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_textures.active.name = KawaMeshCombiner.PROC_TARGET_LM_UV_NAME
					# Копия для исходника
					bpy.context.scene.objects.active = pobj
					mesh.uv_textures[uv1_original_name].active = True
					ensure_op_finished(bpy.ops.mesh.uv_texture_add(), name='bpy.ops.mesh.uv_texture_add')
					mesh.uv_textures.active.name = KawaMeshCombiner.PROC_ORIGINAL_LM_UV_NAME
			
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
			self, oobj_setup: 'OriginalObjectSetup', procs: 'Tuple[List[ProcessingObjectSetup],...]'
	):
		new_objs = set()  # созданные, не оригинальные объекты
		deque = collections.deque()
		oobj = oobj_setup.object
		try:
			# Мы никогда не трогаем оригиналы, так что создаем рабочую копиию
			oobj.hide = False  # Необходимо, т.к. некоторые операторы не работают на скрытых объектах
			ensure_deselect_all_objects()
			oobj.select = True
			bpy.context.scene.objects.active = oobj
			bpy.ops.object.duplicate(linked=False)
			base_pobj = bpy.context.scene.objects.active
			ensure_selected_single(base_pobj, dict(original=oobj))
			deque.append(base_pobj)
			new_objs.add(base_pobj)
			ensure_deselect_all_objects()
			
			while len(deque) > 0:
				tobj = deque.popleft()  # type: bpy.types.Object
				try:
					if tobj.dupli_type == 'GROUP' and tobj.dupli_group is not None:
						# Обробатываемый объект - дупль-объект: преобразуем его в реальный и одно-пользовательский
						ensure_deselect_all_objects()
						tobj.select = True
						bpy.context.scene.objects.active = tobj
						ensure_op_finished(bpy.ops.object.duplicates_make_real(
							use_base_parent=True, use_hierarchy=True
						), name='bpy.ops.object.duplicates_make_real', tobj=tobj.name)
						tobj.select = False
						ensure_op_finished(bpy.ops.object.make_single_user(
							type='SELECTED_OBJECTS', object=True, obdata=True, material=False, texture=False, animation=False
						), name='bpy.ops.object.make_single_user', tobj=tobj.name)
						for sobj in bpy.context.selected_objects:
							# Все созданные объекты регистрируем
							sobj.hide = False  # Необходимо
							deque.append(sobj)
							new_objs.add(sobj)
							sobj.select = False
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
							tobj.select = True
							bpy.context.scene.objects.active = tobj
							ensure_op_result(
								bpy.ops.mesh.separate(type='MATERIAL'), ('FINISHED', 'CANCELLED'), name="bpy.ops.mesh.separate",
							)
							for sobj in bpy.context.selected_objects:
								# Все созданные объекты регистрируем
								sobj.hide = False  # Необходимо
								deque.append(sobj)
								new_objs.add(sobj)
								sobj.select = False
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
			uv_data = mesh.uv_layers.get(self.PROC_ORIGINAL_ATLAS_UV_NAME).data  # type: List[bpy.types.MeshUVLoop]
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
		mesh.uv_textures.new(name=UV_ORIGINAL)
		mesh.uv_textures.new(name=UV_ATLAS)
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
				uvd_original[poly.loop_indices[vert_idx]].uv = uv_a
				uvd_atlas[poly.loop_indices[vert_idx]].uv = uv_b
			poly.material_index = mat2idx[t.attachment.material.material]
		
		# Вставляем меш на сцену
		obj = bpy.data.objects.new("__Kawa_Bake_UV_Object", mesh)  # add a new object using the mesh
		bpy.context.scene.objects.link(obj)
		bpy.context.scene.objects.active = obj
		bpy.context.scene.objects.active.select = True
		
		if len(mesh.polygons) != len(transforms):
			raise AssertionError("len(mesh.polygons) != len(transforms)", mesh, len(mesh.polygons), len(transforms))
		for atex_setup in self.prepare_all_atlas_textures().values():
			atex_image = None
			try:
				atex_image = atex_setup.prepare_image()
				
				obj = bpy.context.scene.objects.active
				obj.hide = False
				obj.hide_render = False
				for layer in get_mesh_safe(obj).uv_textures:  # type: bpy.types.MeshTexturePolyLayer
					layer.active = layer.name == UV_ATLAS
					layer.active_render = layer.name == UV_ORIGINAL
					layer.active_clone = False
					for data in layer.data:  # type: bpy.types.MeshTexturePoly
						data.image = atex_image
				
				# Bl. R.
				bpy.context.scene.render.bake_type = atex_setup.type
				bpy.context.scene.render.bake_margin = 64 if not self.fast_mode else 2
				bpy.context.scene.render.bake_aa_mode = '5'
				bpy.context.scene.render.use_bake_clear = True
				bpy.context.scene.render.antialiasing_samples = '5'
				log.info(
					"Trying to bake atlas Texture='%s' type='%s' size=%s from %d transforms...",
					atex_image.name, atex_setup.type, tuple(atex_image.size), len(transforms)
				)
				# raise RuntimeError("Debug Boop!")
				bake_start = time.perf_counter()
				ensure_op_finished(bpy.ops.object.bake_image())
				# ensure_op_finished(bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, margin=64, use_clear=True))
				bake_time = time.perf_counter() - bake_start
				log.info("Baked atlas Texture='%s' type='%s', time spent: %f sec.", atex_image.name, atex_setup.type, bake_time)
				save_path = bpy.path.abspath('//' + stamp + "_" + atex_image.name + ".png")
				log.info("Saving Texture='%s' type='%s' as '%s'...", atex_image.name, atex_setup.type, save_path)
				atex_image.save_render(save_path)
				log.info("Saved Texture='%s' type='%s' as '%s'...", atex_image.name, atex_setup.type, save_path)
			except Exception as exc:
				raise RuntimeError("Error bake!", atex_image.name, atex_setup.type, atex_image, bpy.context.scene.objects.active) from exc

		if bpy.context.scene.objects.active is not None:
			bpy.context.blend_data.meshes.remove(get_mesh_safe(bpy.context.scene.objects.active), do_unlink=True)
		if bpy.context.scene.objects.active is not None:
			bpy.context.blend_data.objects.remove(bpy.context.scene.objects.active, do_unlink=True)
		ensure_deselect_all_objects()
	
	def atlas_bake_legacy(self, proc_objects: 'Iterable[ProcessingObjectSetup]'):
		stamp = str(round(time.time()))
		for atex_type, atex_setup in self.prepare_all_atlas_textures().items():
			log.info("Preparing to bake atlas type='%s'...", atex_setup.type)
			ensure_deselect_all_objects()
			atex_image = atex_setup.prepare_image()
			polys_assigns = 0
			for pobj_setup in proc_objects:
				pobj_setup.object.select = True
				pobj_setup.object.hide = False
				pobj_setup.object.hide_render = False
				# bpy.context.scene.objects.active = pobj_setup.object
				for layer in get_mesh_safe(pobj_setup.object).uv_textures:  # type: bpy.types.MeshTexturePolyLayer
					layer.active = layer.name == self.PROC_TARGET_ATLAS_UV_NAME
					layer.active_render = layer.name == self.PROC_ORIGINAL_ATLAS_UV_NAME
					layer.active_clone = False
					if layer.active:
						for data in layer.data:  # type: bpy.types.MeshTexturePoly
							data.image = atex_image
							polys_assigns += 1
			# Bl. R.
			bpy.context.scene.render.bake_type = atex_setup.type
			bpy.context.scene.render.bake_margin = 64 if not self.fast_mode else 2
			# bpy.context.scene.render.bake_aa_mode = '16' if not self.fast_mode else '5'
			bpy.context.scene.render.bake_aa_mode = '5'
			bpy.context.scene.render.use_bake_clear = True
			# bpy.context.scene.render.antialiasing_samples = '16' if not self.fast_mode else '5'
			bpy.context.scene.render.antialiasing_samples = '5'
			# Cycles
			# bpy.context.scene.cycles.bake_type = 'DIFFUSE'
			# bpy.context.scene.render.bake.use_pass_direct = False
			# bpy.context.scene.render.bake.use_pass_indirect = False
			# bpy.context.scene.render.bake.use_pass_color = True
			#
			log.info(
				"Trying to bake atlas Texture='%s' type='%s' size=%s from %d polygons...",
				atex_image.name, atex_setup.type, tuple(atex_image.size), polys_assigns
			)
			# raise RuntimeError("Boop!")
			bake_start = time.perf_counter()
			ensure_op_finished(bpy.ops.object.bake_image())
			# ensure_op_finished(bpy.ops.object.bake(type='DIFFUSE', pass_filter={'COLOR'}, margin=64, use_clear=True))
			bake_time = time.perf_counter() - bake_start
			log.info("Baked atlas Texture='%s' type='%s', time spent: %f sec.", atex_image.name, atex_setup.type, bake_time)
			save_path = bpy.path.abspath('//' + stamp + "_" + atex_image.name + ".png")
			log.info("Saving Texture='%s' type='%s' as '%s'...", atex_image.name, atex_setup.type, save_path)
			atex_image.save_render(save_path)
			log.info("Saved Texture='%s' type='%s' as '%s'...", atex_image.name, atex_setup.type, save_path)
	
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
			pobj.select = True
			tobj.select = True
			bpy.context.scene.objects.active = tobj
			# log.debug("Combining: %s", str(list(obj.name for obj in bpy.context.selected_objects)))
			ensure_op_finished(bpy.ops.object.join(), name="bpy.ops.object.join")
		ensure_deselect_all_objects()
		for tobj in targets:
			try:
				tobj.hide, tobj.hide_select, tobj.hide_render = False, False, False
				tobj.select = True
				bpy.context.scene.objects.active = tobj
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
				
				uv_atlas_target = tmesh.uv_textures.get(self.PROC_TARGET_ATLAS_UV_NAME)
				if uv_atlas_target is not None:
					uv_atlas_target.name = self.get_atlas_target_uv()
					counter_rn += 1
				uv_lm_target = tmesh.uv_textures.get(self.PROC_TARGET_LM_UV_NAME)
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
			bpy.context.scene.objects.unlink(new_obj)
		
		for tobj in target_objects:
			log.info("Updating UV1 in Target Object='%s'...", tobj.name)
			tobj_mesh = get_mesh_safe(tobj)
			uv1_target = tobj_mesh.uv_textures.get(self.PROC_TARGET_LM_UV_NAME)  # type: bpy.types.MeshTexturePolyLayer
			if uv1_target is None:
				log.info("Target Object='%s' does not have target uv1 (%s)", tobj.name, tobj_mesh.uv_textures.keys())
				continue
			repack_lightmap_uv(tobj, self.PROC_TARGET_LM_UV_NAME, rotate=True, margin=0.003)
		
		self.rename_proc_uvs(target_objects)
		
		for oobj in self.original_objects.values():
			oobj.object.hide = True
			oobj.object.hide_render = True
			oobj.object.hide_select = False
		
		log.info('Done!')
