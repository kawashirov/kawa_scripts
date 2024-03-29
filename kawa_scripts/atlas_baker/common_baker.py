# Kawashirov's Scripts (c) 2022 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import math
from pathlib import Path

import bpy
from bpy.types import Scene, Object, Material, Image, ShaderNodeTexImage

from .._internals import log
from .. import materials
from .. import meshes
from .. import imagemagick

from . import tex_size_finder
from . import base_baker
from .aov import AOV


class ProxyTexSizeFinder(tex_size_finder.TexSizeFinder):
	def __init__(self, baker: 'CommonAtlasBaker'):
		super().__init__()
		self._baker = baker
	
	def should_count_node(self, node: 'ShaderNodeTexImage') -> bool:
		return self._baker.should_count_node(node)
	
	def should_count_image(self, image: 'Image') -> bool:
		return self._baker.should_count_image(image)


class CommonAtlasBaker(base_baker.BaseAtlasBaker):
	"""
	Extended BaseAtlasBaker with common features.
	BaseAtlasBaker has only a minimal working set of features,
	CommonAtlasBaker has extra features and helper methods for common operations.
	"""
	
	def __init__(self, name: 'str'):
		super().__init__()
		self.atlas_name = name
		self.fast_mode = False
		self.padding = 8
		self._texsizefinder = None  # type: tex_size_finder.TexSizeFinder|None
		self._prepared_images = dict()  # type: dict[str, Image]
		self._prepared_materials = dict()  # type: dict[str, Material]
		self.objects = self.get_source_objects()
		self.export_path = None  # type: Path|None
		self.join_diffuse_and_alpha = False
	
	def get_scene(self) -> 'Scene':
		return bpy.context.scene
	
	def get_source_objects(self) -> 'set[Object]':
		return set(obj for obj in self.get_scene().objects if meshes.is_mesh_object(obj))
	
	def get_export_path(self) -> 'Path':
		if self.export_path is None:
			log.raise_error(RuntimeError, f"Export path was not set!")
		return self.export_path
	
	def get_texsizefinder(self):
		if self._texsizefinder is None:
			self._texsizefinder = ProxyTexSizeFinder(self)
		return self._texsizefinder
	
	def should_count_node(self, node: 'ShaderNodeTexImage') -> bool:
		return 'IgnoreSize' not in node.label
	
	def should_count_image(self, image: 'Image') -> bool:
		return True  # image.colorspace_settings.name != 'Non-Color'
	
	def get_material_scale(self, src_mat: 'Material') -> 'float':
		return src_mat.get('atlas_scale', 1.0)
	
	def get_material_size(self, src_mat: 'Material') -> 'tuple[float, float]|None':
		default_szie = (32, 32)
		width, height = self.get_texsizefinder().mat_size(src_mat) or default_szie
		scale = self.get_material_scale(src_mat)
		if not isinstance(scale, (int, float)):
			log.raise_error(TypeError, f"Got invalid custom scale for Material {src_mat.name!r}: {type(scale)!r} {scale!r}")
		if scale <= 0:
			return default_szie
		size = (width * scale, height * scale)
		return size
	
	def get_target_image_name(self, bake_type: str, aov: 'AOV|None'):
		return f'{self.atlas_name}-{bake_type}'
	
	def get_target_image_size(self, bake_type: str, aov: 'AOV|None') -> 'tuple[int, int]':
		return 2048, 2048
	
	def prepare_target_image(self, bake_type: str) -> 'Image':
		image = self._prepared_images.get(bake_type)
		if image is not None:
			return image
		
		log.info(f"Preparing target image for {bake_type!r}...")
		
		aov = self._aovs.get(bake_type)
		name = self.get_target_image_name(bake_type, aov)
		size = self.get_target_image_size(bake_type, aov)
		size = round(size[0]), round(size[1])
		
		image = bpy.data.images.get(name)
		if image is None:
			image = bpy.data.images.new(name, size[0], size[1], alpha=False, float_buffer=False)
		image.generated_width, image.generated_height = size[0], size[1]
		if aov is not None:
			image.generated_color = aov.default_rgba
		elif bake_type == 'NORMAL':
			image.generated_color = (0.5, 0.5, 1, 1)
		else:
			image.generated_color = (0, 0, 0, 1)
		image.colorspace_settings.name = 'Non-Color' if bake_type in ('METALLIC', 'ROUGHNESS', 'NORMAL', 'ALPHA') else 'sRGB'
		image.use_view_as_render = True
		image.use_half_precision = True
		image.use_generated_float = False
		image.generated_type = 'COLOR_GRID' if bake_type == 'DIFFUSE' else 'BLANK'
		image.source = 'GENERATED'
		
		depth = round(image.depth / image.channels)
		image.use_fake_user = True
		self._prepared_images[bake_type] = image
		size = tuple(image.size)
		log.info(f"Prepared target image for {bake_type!r}: {image.name!r} {size[0]} x {size[1]} {depth}bpp.")
		return image
	
	def get_target_image(self, bake_type: str) -> 'Image|None':
		return self.prepare_target_image(bake_type)
	
	def prepare_target_material(self, blend_method: str):
		if blend_method not in ('OPAQUE', 'BLEND', 'HASHED', 'CLIP'):
			raise ValueError()
		mat = self._prepared_materials.get(blend_method)
		if mat is not None:
			return mat
		
		log.info(f"Preparing target material for {blend_method!r}...")
		name = f'{self.atlas_name}-{blend_method}'
		
		bsdf = materials.QuickBSDFConstructor(name)
		bsdf.create_material()
		if im_diffuse := self.get_target_image('DIFFUSE'):
			bsdf.bind_image('Base Color', im_diffuse, extension='EXTEND')
		if (blend_method != 'OPAQUE') and (im_alpha := self.get_target_image('ALPHA')):
			bsdf.bind_image('Alpha', im_alpha, extension='EXTEND')
		if im_normal := self.get_target_image('NORMAL'):
			bsdf.bind_image('Normal', im_normal, extension='EXTEND', is_normal=True)
		if im_metal := self.get_target_image('METALLIC'):
			bsdf.bind_image('Metallic', im_metal, extension='EXTEND')
		if im_roughness := self.get_target_image('ROUGHNESS'):
			bsdf.bind_image('Roughness', im_roughness, extension='EXTEND')
		if im_emit := self.get_target_image('EMIT'):
			bsdf.bind_image('Emission', im_emit, extension='EXTEND')
		mat = bsdf.get_material()
		log.info(f'Created new target material {mat.name!r}.')
		
		mat.blend_method = blend_method
		mat.use_fake_user = True
		self._prepared_materials[blend_method] = mat
		log.info(f"Prepared target material for {blend_method!r}: {mat.name}")
		return mat
	
	def get_target_material(self, origin: 'Object', src_mat: 'Material') -> 'Material|None':
		if src_mat is None or src_mat.node_tree is None or src_mat.node_tree.nodes is None:
			return None
		if origin.name.startswith('_'):
			return None
		if src_mat.name.startswith('_'):
			return None
		return self.prepare_target_material(src_mat.blend_method)
	
	def get_island_mode(self, _origin: 'Object', _mat: 'Material') -> 'str':
		return 'POLYGON' if not self.fast_mode else 'OBJECT'
	
	def get_epsilon(self, _obj: 'Object', _mat: 'Material') -> 'float':
		return 0.5 if not self.fast_mode else 2.0
	
	def before_bake(self, bake_type: str, target_image: 'Image'):
		"""
		Some common rendering settings adjust.
		
		**Adjust Cycles texture size limit:**
		In most cases, we do not need to use textures larger than atlas itself.
		Seems to be increasing the speed of rendering a little without noticeable blurring or quality drops.
		
		**Adjust Cycles noise threshold:**
		In most situations, we are baking to export assets into game engines (like Unity),
		where textures will be LOSSY compressed anyway to DXT5, BC7, or whatever.
		So we don't need very high quality here: adaptive_threshold = 0.1 and adaptive_min_samples = 4
		should be fine as with automatic 0, it will be chosen around 0.03 and 42.
		If NORMAL, reduce twice, as NORMAL seems to be more sensitive for quality when used around contrast shadows.
		This significantly increases the speed of rendering without noticeable artefacts or quality drops.
		"""
		scene = self.get_scene()
		cycles = scene.cycles
		
		scene.render.bake.margin = 1 if self.fast_mode else 64
		
		image_size = target_image.size
		avg_size = image_size[0] * 0.5 + image_size[1] * 0.5  # type: float|int|str
		avg_size = 1 << round(math.log2(max(2, avg_size)))
		avg_size = max(128, min(8192, avg_size))
		avg_size = str(avg_size)
		cycles.texture_limit = avg_size
		cycles.texture_limit_render = avg_size
		
		cycles.adaptive_threshold = 0.1
		cycles.adaptive_min_samples = 4
		if bake_type == 'NORMAL':
			cycles.adaptive_threshold /= 2
			cycles.adaptive_min_samples *= 2
	
	def export_image(self, bake_type: str, image: 'Image', is_exr=False):
		aov = self._aovs.get(bake_type)
		scene = self.get_scene()
		
		file_format, save_ext, color_depth = 'PNG', 'png', '8'
		if is_exr:
			scene.render.image_settings.exr_codec = 'ZIP'
			file_format, save_ext, color_depth = 'OPEN_EXR', 'exr', '16'
		
		save_path = str(self.get_export_path() / f'{image.name}.{save_ext}')
		log.info(f"Saving Image {image.name!r} {bake_type!r} as {save_path!r}...")
		
		rgb_type = (aov.type == 'COLOR') if aov is not None else (bake_type in ('DIFFUSE', 'EMIT', 'NORMAL'))
		non_color_space = (aov.type == 'VALUE') if aov is not None else (bake_type in ('METALLIC', 'ROUGHNESS', 'NORMAL', 'ALPHA'))
		
		depth = round(image.depth / image.channels)
		scene.render.image_settings.quality = 100
		scene.render.image_settings.compression = 80  # 100 is too slow
		scene.render.image_settings.color_mode = 'RGB' if rgb_type else 'BW'
		scene.render.image_settings.file_format = file_format
		scene.render.image_settings.color_depth = '16' if depth >= 16 else '8'
		scene.view_settings.look = 'None'
		scene.view_settings.exposure = 0
		scene.view_settings.gamma = 1
		scene.view_settings.view_transform = 'Standard'  # 'Raw' if raw_type else
		
		image.file_format = file_format
		image.save_render(save_path)
		log.info(f"Saved Image {image.name!r} {bake_type!r} as {save_path!r}...")
		image.filepath_raw = save_path
		image.filepath = save_path  # trigger reloading
		image.source = 'FILE'
		if non_color_space:
			image.colorspace_settings.name = 'Non-Color'
		elif is_exr:
			image.colorspace_settings.name = 'Linear'
		else:
			image.colorspace_settings.name = 'sRGB'
		# target_image.save()
		log.info(f"Reloaded Image {image.name!r} {bake_type!r} from {save_path!r}...")
	
	def ensure_scene_settings(self):
		scene = self.get_scene()
		scene.render.image_settings.color_mode = 'RGB'
		scene.view_settings.look = 'None'
		scene.view_settings.exposure = 0
		scene.view_settings.gamma = 1
		scene.view_settings.view_transform = 'Standard'
		scene.sequencer_colorspace_settings.name = 'sRGB'
		scene.display_settings.display_device = 'sRGB'
	
	def after_bake(self, bake_type: str, image: 'Image'):
		is_exr = round(image.depth / image.channels) >= 16
		self.export_image(bake_type, image, is_exr=is_exr)
		self.ensure_scene_settings()
	
	def join_diffuse_and_alpha_if_necessary_check(self, im: Image, bake_type: 'str'):
		if not isinstance(im, Image):
			log.raise_error(TypeError, f"No valid {bake_type!r} texture: {im!r}")
	
	def join_diffuse_and_alpha_if_necessary(self):
		if not self.join_diffuse_and_alpha:
			return
		try:
			im_diffuse = self.get_target_image('DIFFUSE')
			self.join_diffuse_and_alpha_if_necessary_check(im_diffuse, 'DIFFUSE')
			im_alpha = self.get_target_image('ALPHA')
			self.join_diffuse_and_alpha_if_necessary_check(im_alpha, 'ALPHA')
			joined_name = self.get_target_image_name('DIFFUSE+ALPHA', None)
			joined_path = Path(im_diffuse.filepath)
			joined_path = joined_path.with_name(f"{joined_name}{joined_path.suffix}")
			imagemagick.join_rgb_and_alpha(im_diffuse.filepath, im_alpha.filepath, joined_path)
		except Exception as exc:
			log.error(f"Can't join DIFFUSE+ALPHA: {exc}", exc_info=exc)
	
	def _apply_baked_materials(self):
		super()._apply_baked_materials()
	
	def bake_atlas(self):
		super().bake_atlas()
		self.join_diffuse_and_alpha_if_necessary()


__all__ = ['CommonAtlasBaker']
