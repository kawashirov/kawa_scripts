# Kawashirov's Scripts (c) 2019 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

from collections import OrderedDict as _OrderedDict

import typing as _typing
if _typing.TYPE_CHECKING:
	from types import ModuleType
	from typing import Dict
	# Эти итак заимпортированы через __import__ но PyCharm их не видит
	from . import shapekeys, commons, modifiers

bl_info = {
	"name": "Kawashirov's Scripts",
	"author": "Sergey V. Kawashirov",
	"description": "Kawashirov's Scripts for Unity and VRChat content creation",
	"location": "There is no UI. Use it from scripts or console by `import kawa_scripts` (or whatever)",
	"wiki_url": "",
	"version": (0, 2),
	"blender": (2, 83, 0),
	"category": "Object",
}
addon_name = __name__

if "bpy" in locals() and "_modules_loaded" in locals():
	from importlib import reload

	print("Reloading Kawashirov's Scripts...")
	for key, mod in list(_modules_loaded.items()):
		print("Reloading {0}...".format(repr(mod)))
		_modules_loaded[key] = reload(mod)
	del reload
	print("Reloaded Kawashirov's Scripts!")

_modules = [
	"_internals",
	"atlas_baker",
	"combiner",
	"commons",
	"instantiator",
	"modifiers",
	"reporter",
	"shader_nodes",
	"shapekeys",
	"tex_size_finder",
	"uv",
]

import bpy

__import__(name=__name__, fromlist=_modules)
_namespace = globals()
_modules_loaded = _OrderedDict()  # type: Dict[str, ModuleType]
for _mod_name in _modules:
	_modules_loaded[_mod_name] = _namespace.get(_mod_name)
del _namespace


from ._internals import log


def _MESH_MT_shape_key_context_menu(self, context):
	self.layout.separator()  # EDIT-mode
	self.layout.operator(shapekeys.KawaSelectVerticesAffectedByShapeKey.bl_idname, icon='VERTEXSEL')
	self.layout.operator(shapekeys.KawaApplySelectedInActiveToAll.bl_idname, icon='KEYINGSET')
	self.layout.operator(shapekeys.KawaRevertSelectedInActiveToBasis.bl_idname, icon='KEYINGSET')
	self.layout.operator(shapekeys.KawaRevertSelectedInAllToBasis.bl_idname, icon='KEYINGSET')
	self.layout.separator()  # OBJECT-mode
	self.layout.operator(shapekeys.KawaRemoveEmpty.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(shapekeys.KawaApplyActiveToAll.bl_idname, icon='KEY_DEHLT')


def _VIEW3D_MT_object(self, context):
	self.layout.separator()
	self.layout.operator(shapekeys.KawaRemoveEmpty.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(shapekeys.KawaApplyActiveToAll.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(commons.KawaApplyParentInverseMatrices.bl_idname, icon='ORIENTATION_LOCAL')
	self.layout.operator(modifiers.KawaApplyDeformModifierHighPrecision.bl_idname, icon='MODIFIER')
	self.layout.operator(modifiers.KawaApplyAllModifiersHighPrecision.bl_idname, icon='MODIFIER')
	self.layout.operator(modifiers.KawaApplyArmatureToMeshesHighPrecision.bl_idname, icon='ARMATURE_DATA')


def _VIEW3D_MT_edit_mesh_vertices(self, context):
	self.layout.separator()
	self.layout.operator(shapekeys.KawaSelectVerticesAffectedByShapeKey.bl_idname, icon='VERTEXSEL')
	self.layout.operator(shapekeys.KawaApplySelectedInActiveToAll.bl_idname, icon='KEYINGSET')
	self.layout.operator(shapekeys.KawaRevertSelectedInActiveToBasis.bl_idname, icon='KEYINGSET')
	self.layout.operator(shapekeys.KawaRevertSelectedInAllToBasis.bl_idname, icon='KEYINGSET')


def _VIEW3D_MT_edit_mesh_context_menu(self, context):
	self.layout.separator()
	self.layout.operator(shapekeys.KawaSelectVerticesAffectedByShapeKey.bl_idname, icon='VERTEXSEL')
	self.layout.operator(shapekeys.KawaApplySelectedInActiveToAll.bl_idname, icon='KEYINGSET')
	self.layout.operator(shapekeys.KawaRevertSelectedInActiveToBasis.bl_idname, icon='KEYINGSET')
	self.layout.operator(shapekeys.KawaRevertSelectedInAllToBasis.bl_idname, icon='KEYINGSET')


def register():
	print("Hello from {0}!".format(__name__))
	import logging
	from datetime import datetime
	
	log.py_log.setLevel(logging.DEBUG)
	if len(log.py_log.handlers) < 1:
		import tempfile
		print("Updating kawa_scripts log handler!")
		log_file = tempfile.gettempdir() + '/' + datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + '-kawa.log'
		log_formatter = logging.Formatter(fmt='[%(asctime)s][%(levelname)s] %(message)s')
		log_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8', delay=False)
		log_handler.setFormatter(log_formatter)
		log.py_log.addHandler(log_handler)
		log.info("Log handler updated!")
	
	from bpy.utils import register_class
	for mod in _modules_loaded.values():
		if mod and hasattr(mod, 'classes'):
			for cls in mod.classes:
				register_class(cls)

	bpy.types.VIEW3D_MT_object.append(_VIEW3D_MT_object)
	bpy.types.VIEW3D_MT_object_context_menu.append(_VIEW3D_MT_object)
	bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(_VIEW3D_MT_edit_mesh_context_menu)
	bpy.types.VIEW3D_MT_edit_mesh_vertices.append(_VIEW3D_MT_edit_mesh_vertices)
	bpy.types.MESH_MT_shape_key_context_menu.append(_MESH_MT_shape_key_context_menu)
	
	log.info("Hello from {0} once again!".format(__name__))


def unregister():
	from bpy.utils import unregister_class

	bpy.types.VIEW3D_MT_object.remove(_VIEW3D_MT_object)
	bpy.types.VIEW3D_MT_object_context_menu.remove(_VIEW3D_MT_object)
	bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(_VIEW3D_MT_edit_mesh_context_menu)
	bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(_VIEW3D_MT_edit_mesh_vertices)
	bpy.types.MESH_MT_shape_key_context_menu.remove(_MESH_MT_shape_key_context_menu)
	
	for mod in reversed(_modules_loaded.values()):
		if hasattr(mod, 'classes'):
			for cls in reversed(mod.classes):
				if cls.is_registered:
					unregister_class(cls)
	
	log.info("Goodbye from {0}...".format(__name__))
