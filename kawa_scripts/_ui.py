# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import logging
import os
import shutil
import subprocess

import bpy

from bpy.types import Context

from . import _internals
from ._internals import log

from . import commons
from . import attributes
from . import shapekeys
from . import vertex_groups
from . import modifiers
from . import armature
from . import objects


def _shape_key_edit_mode_context_menu(self, context):
	self.layout.operator(shapekeys.OperatorSelectVerticesAffectedByShapeKey.bl_idname, icon='VERTEXSEL')
	self.layout.separator()  # MESH_EDIT-mode revert
	self.layout.operator(shapekeys.OperatorRevertSelectedInActiveToBasis.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(shapekeys.OperatorRevertSelectedInAllToBasis.bl_idname, icon='KEY_DEHLT')


def _shape_key_object_mode_context_menu(self, context):
	self.layout.operator(shapekeys.OperatorApplyActive.bl_idname, icon='KEYINGSET')
	self.layout.separator()  # OBJECT-mode clean
	self.layout.operator(shapekeys.OperatorCleanupActive.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(shapekeys.OperatorCleanupAll.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(shapekeys.OperatorRemoveEmpty.bl_idname, icon='KEY_DEHLT')
	self.layout.separator()  # OBJECT-mode fixes
	self.layout.operator(shapekeys.OperatorFixCorrupted.bl_idname, icon='ERROR')


def _selection_menu(self, context):
	# MESH_EDIT-mode selection save/load
	self.layout.operator(attributes.OperatorSaveSelectionToAttribute.bl_idname, icon='SELECT_SET')
	self.layout.operator(attributes.OperatorLoadSelectionFromAttribute.bl_idname, icon='SELECT_SET')
	self.layout.separator()
	# MESH_EDIT-mode selection shapes
	self.layout.operator(shapekeys.OperatorSelectVerticesAffectedByShapeKey.bl_idname, icon='VERTEXSEL')


# # #


class _MESH_MT_shape_key_context_kawa_sub_menu(bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "MESH_MT_shape_key_context_kawa_sub_menu"
	
	def draw(self, context):
		_shape_key_edit_mode_context_menu(self, context)
		self.layout.separator()
		_shape_key_object_mode_context_menu(self, context)


def _MESH_MT_shape_key_context_menu(self, context):
	self.layout.menu(_MESH_MT_shape_key_context_kawa_sub_menu.bl_idname)


# # #


def _MESH_MT_vertex_group_context_menu(self, context):
	self.layout.separator()
	self.layout.operator(vertex_groups.OperatorRemoveEmpty.bl_idname, icon='X')


# # #


class _VIEW3D_MT_object_kawa_sub_menu(bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_object_kawa_sub_menu"
	
	def draw(self, context):
		self.layout.separator()  # transforms
		self.layout.operator(objects.KawaApplyParentInverseMatrices.bl_idname, icon='ORIENTATION_LOCAL')
		self.layout.separator()  # modifiers
		self.layout.operator(modifiers.KawaApplyDeformModifierHighPrecision.bl_idname, icon='MODIFIER')
		self.layout.operator(modifiers.KawaApplyAllModifiersHighPrecision.bl_idname, icon='MODIFIER')
		self.layout.operator(modifiers.KawaApplyArmatureToMeshesHighPrecision.bl_idname, icon='ARMATURE_DATA')
		self.layout.separator()
		_shape_key_object_mode_context_menu(self, context)
		self.layout.separator()  # vertex groups
		self.layout.operator(vertex_groups.OperatorRemoveEmpty.bl_idname, icon='X')


def _VIEW3D_MT_object_kawa_sub_menu_layout(self, context):
	self.layout.menu(_VIEW3D_MT_object_kawa_sub_menu.bl_idname)


# # #

class _VIEW3D_MT_edit_mesh_kawa_sub_menu(bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_edit_mesh_kawa_sub_menu"
	
	def draw(self, context):
		_shape_key_edit_mode_context_menu(self, context)


def _VIEW3D_MT_edit_mesh_kawa_sub_menu_layout(self, context):
	self.layout.menu(_VIEW3D_MT_edit_mesh_kawa_sub_menu.bl_idname)


class _VIEW3D_MT_select_kawa_sub_menu(bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_select_kawa_sub_menu"
	
	def draw(self, context):
		_selection_menu(self, context)


def _VIEW3D_MT_select_kawa_sub_menu_layout(self, context):
	self.layout.menu(_VIEW3D_MT_select_kawa_sub_menu.bl_idname)


# # #

class _VIEW3D_MT_edit_armature_kawa_sub_menu(bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_edit_armature_kawa_sub_menu"
	
	def draw(self, context):
		self.layout.operator(armature.OperatorMergeActiveUniformly.bl_idname, icon='X')
		self.layout.operator(armature.OperatorMergeSelectedToHierarchy.bl_idname, icon='X')


def _VIEW3D_MT_edit_armature_kawa_sub_menu_layout(self, context):
	self.layout.menu(_VIEW3D_MT_edit_armature_kawa_sub_menu.bl_idname)


# # #

class OperatorOpenWatchLog(_internals.KawaOperator):
	bl_idname = "kawa.open_watch_log"
	bl_label = f"Watch {__name__.split('.')[0]} log."
	bl_description = bl_label
	bl_options = {'REGISTER'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		return True
	
	def execute(self, context: 'Context'):
		ps_path = None
		try:
			ps_path = shutil.which('powershell.exe')
		except Exception as exc:
			log.error(f"Failed to find powershell: {exc}", op=self, exc_info=exc)
			return {'CANCELLED'}
		log.info(f"Found powershell.exe: {ps_path!r}")
		
		for handler in _internals.log.py_log.handlers:
			try:
				if isinstance(handler, logging.FileHandler):
					file = os.path.abspath(handler.baseFilename)
					command = f'Get-Content "{file}" -Wait'
					# По какой-то причине никакие creationflags и прочие параметры не могут заспавнить отдельную консоль.
					# По этому создаем окно PS через cmd команду start.
					pid = subprocess.Popen(['start', '/i', '/max', ps_path, '-ExecutionPolicy', 'Unrestricted', '-Command', command],
						close_fds=True, start_new_session=True, shell=True,
						creationflags=subprocess.CREATE_NEW_PROCESS_GROUP | subprocess.DETACHED_PROCESS).pid
					log.info(f"Spawned watch console {pid=!r} for {file!r}")
			except Exception as exc:
				log.error(f"Failed to open log: {exc}", op=self, exc_info=exc)
		
		return {'FINISHED'}


def TOPBAR_MT_blender_menu(self, context):
	self.layout.separator()
	self.layout.operator(OperatorOpenWatchLog.bl_idname)


# # #

def register():
	bpy.utils.register_class(_MESH_MT_shape_key_context_kawa_sub_menu)
	bpy.utils.register_class(_VIEW3D_MT_object_kawa_sub_menu)
	bpy.utils.register_class(_VIEW3D_MT_edit_mesh_kawa_sub_menu)
	bpy.utils.register_class(_VIEW3D_MT_edit_armature_kawa_sub_menu)
	bpy.utils.register_class(_VIEW3D_MT_select_kawa_sub_menu)
	
	bpy.types.VIEW3D_MT_object.append(_VIEW3D_MT_object_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_object_context_menu.append(_VIEW3D_MT_object_kawa_sub_menu_layout)
	
	bpy.types.VIEW3D_MT_edit_mesh.append(_VIEW3D_MT_edit_mesh_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(_VIEW3D_MT_edit_mesh_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_edit_mesh_vertices.append(_VIEW3D_MT_edit_mesh_kawa_sub_menu_layout)
	
	# _bpy.types.VIEW3D_MT_select_object.append(_VIEW3D_MT_select_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_select_edit_mesh.append(_VIEW3D_MT_select_kawa_sub_menu_layout)
	
	bpy.types.VIEW3D_MT_edit_armature.append(_VIEW3D_MT_edit_armature_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_pose.append(_VIEW3D_MT_edit_armature_kawa_sub_menu_layout)
	
	bpy.types.MESH_MT_shape_key_context_menu.append(_MESH_MT_shape_key_context_menu)
	bpy.types.MESH_MT_vertex_group_context_menu.append(_MESH_MT_vertex_group_context_menu)
	
	bpy.utils.register_class(OperatorOpenWatchLog)
	bpy.types.TOPBAR_MT_blender.append(TOPBAR_MT_blender_menu)


def unregister():
	bpy.types.TOPBAR_MT_blender.remove(TOPBAR_MT_blender_menu)
	bpy.utils.unregister_class(OperatorOpenWatchLog)
	
	bpy.types.VIEW3D_MT_object.remove(_VIEW3D_MT_object_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_object_context_menu.remove(_VIEW3D_MT_object_kawa_sub_menu_layout)
	
	bpy.types.VIEW3D_MT_edit_mesh.append(_VIEW3D_MT_edit_mesh_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(_VIEW3D_MT_edit_mesh_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(_VIEW3D_MT_edit_mesh_kawa_sub_menu_layout)
	
	# _bpy.types.VIEW3D_MT_select_object.remove(_VIEW3D_MT_select_kawa_sub_menu_layout)
	bpy.types.VIEW3D_MT_select_edit_mesh.remove(_VIEW3D_MT_select_kawa_sub_menu_layout)
	
	bpy.types.MESH_MT_shape_key_context_menu.remove(_MESH_MT_shape_key_context_menu)
	bpy.types.MESH_MT_vertex_group_context_menu.remove(_MESH_MT_vertex_group_context_menu)
	
	bpy.utils.unregister_class(_MESH_MT_shape_key_context_kawa_sub_menu)
	bpy.utils.unregister_class(_VIEW3D_MT_object_kawa_sub_menu)
	bpy.utils.unregister_class(_VIEW3D_MT_edit_mesh_kawa_sub_menu)
	bpy.utils.unregister_class(_VIEW3D_MT_select_kawa_sub_menu)


__all__ = ['register', 'unregister']
