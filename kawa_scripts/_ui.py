# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import bpy as _bpy

from . import commons as _commons
from . import shapekeys as _shapekeys
from . import vertex_groups as _vertex_groups
from . import modifiers as _modifiers
from . import armature as _armature
from . import objects as _objects


def _shape_key_edit_mode_context_menu(self, context):
	self.layout.separator()  # EDIT-mode select
	self.layout.operator(_shapekeys.OperatorSelectVerticesAffectedByShapeKey.bl_idname, icon='VERTEXSEL')
	self.layout.separator()  # EDIT-mode revert
	self.layout.operator(_shapekeys.OperatorRevertSelectedInActiveToBasis.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(_shapekeys.OperatorRevertSelectedInAllToBasis.bl_idname, icon='KEY_DEHLT')
	self.layout.separator()  # EDIT-mode apply
	self.layout.operator(_shapekeys.OperatorApplySelectedInActiveToBasis.bl_idname, icon='KEYINGSET')
	self.layout.operator(_shapekeys.OperatorApplySelectedInActiveToAll.bl_idname, icon='KEYINGSET')


def _shape_key_object_mode_context_menu(self, context):
	self.layout.separator()  # OBJECT-mode apply
	self.layout.operator(_shapekeys.OperatorApplyActiveToBasis.bl_idname, icon='KEYINGSET')
	self.layout.operator(_shapekeys.OperatorApplyActiveToAll.bl_idname, icon='KEYINGSET')
	self.layout.separator()  # OBJECT-mode clean
	self.layout.operator(_shapekeys.OperatorCleanupActive.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(_shapekeys.OperatorCleanupAll.bl_idname, icon='KEY_DEHLT')
	self.layout.operator(_shapekeys.OperatorRemoveEmpty.bl_idname, icon='KEY_DEHLT')
	self.layout.separator()  # OBJECT-mode fixes
	self.layout.operator(_shapekeys.OperatorFixCorrupted.bl_idname, icon='ERROR')


# # #


class _MESH_MT_shape_key_context_kawa_sub_menu(_bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "MESH_MT_shape_key_context_kawa_sub_menu"
	
	def draw(self, context):
		_shape_key_edit_mode_context_menu(self, context)
		_shape_key_object_mode_context_menu(self, context)


def _MESH_MT_shape_key_context_menu(self, context):
	self.layout.menu(_MESH_MT_shape_key_context_kawa_sub_menu.bl_idname)


# # #


def _MESH_MT_vertex_group_context_menu(self, context):
	self.layout.separator()
	self.layout.operator(_vertex_groups.OperatorRemoveEmpty.bl_idname, icon='X')


# # #


class _VIEW3D_MT_object_kawa_sub_menu(_bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_object_kawa_sub_menu"
	
	def draw(self, context):
		self.layout.separator()  # transforms
		self.layout.operator(_objects.KawaApplyParentInverseMatrices.bl_idname, icon='ORIENTATION_LOCAL')
		self.layout.separator()  # modifiers
		self.layout.operator(_modifiers.KawaApplyDeformModifierHighPrecision.bl_idname, icon='MODIFIER')
		self.layout.operator(_modifiers.KawaApplyAllModifiersHighPrecision.bl_idname, icon='MODIFIER')
		self.layout.operator(_modifiers.KawaApplyArmatureToMeshesHighPrecision.bl_idname, icon='ARMATURE_DATA')
		_shape_key_object_mode_context_menu(self, context)
		self.layout.separator()  # vertex groups
		self.layout.operator(_vertex_groups.OperatorRemoveEmpty.bl_idname, icon='X')


def _VIEW3D_MT_object(self, context):
	self.layout.menu(_VIEW3D_MT_object_kawa_sub_menu.bl_idname)


# # #

class _VIEW3D_MT_edit_mesh_kawa_sub_menu(_bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_edit_mesh_kawa_sub_menu"
	
	def draw(self, context):
		_shape_key_edit_mode_context_menu(self, context)


def _VIEW3D_MT_edit_mesh_vertices(self, context):
	self.layout.menu(_VIEW3D_MT_edit_mesh_kawa_sub_menu.bl_idname)


def _VIEW3D_MT_edit_mesh_context_menu(self, context):
	self.layout.menu(_VIEW3D_MT_edit_mesh_kawa_sub_menu.bl_idname)


# # #

class _VIEW3D_MT_edit_armature_kawa_sub_menu(_bpy.types.Menu):
	bl_label = "Kawashirov"
	bl_idname = "VIEW3D_MT_edit_armature_kawa_sub_menu"
	
	def draw(self, context):
		self.layout.operator(_armature.OperatorMergeActiveUniformly.bl_idname, icon='X')
		self.layout.operator(_armature.OperatorMergeSelectedToHierarchy.bl_idname, icon='X')


def _VIEW3D_MT_edit_armature(self, context):
	self.layout.menu(_VIEW3D_MT_edit_armature_kawa_sub_menu.bl_idname)


# # #

def register():
	_bpy.utils.register_class(_MESH_MT_shape_key_context_kawa_sub_menu)
	_bpy.utils.register_class(_VIEW3D_MT_object_kawa_sub_menu)
	_bpy.utils.register_class(_VIEW3D_MT_edit_mesh_kawa_sub_menu)
	_bpy.utils.register_class(_VIEW3D_MT_edit_armature_kawa_sub_menu)
	
	_bpy.types.VIEW3D_MT_object.append(_VIEW3D_MT_object)
	_bpy.types.VIEW3D_MT_object_context_menu.append(_VIEW3D_MT_object)
	
	_bpy.types.VIEW3D_MT_edit_mesh_context_menu.append(_VIEW3D_MT_edit_mesh_context_menu)
	_bpy.types.VIEW3D_MT_edit_mesh_vertices.append(_VIEW3D_MT_edit_mesh_vertices)
	
	_bpy.types.VIEW3D_MT_edit_armature.append(_VIEW3D_MT_edit_armature)
	_bpy.types.VIEW3D_MT_pose.append(_VIEW3D_MT_edit_armature)
	
	_bpy.types.MESH_MT_shape_key_context_menu.append(_MESH_MT_shape_key_context_menu)
	_bpy.types.MESH_MT_vertex_group_context_menu.append(_MESH_MT_vertex_group_context_menu)


def unregister():
	_bpy.types.VIEW3D_MT_object.remove(_VIEW3D_MT_object)
	_bpy.types.VIEW3D_MT_object_context_menu.remove(_VIEW3D_MT_object)
	_bpy.types.VIEW3D_MT_edit_mesh_context_menu.remove(_VIEW3D_MT_edit_mesh_context_menu)
	_bpy.types.VIEW3D_MT_edit_mesh_vertices.remove(_VIEW3D_MT_edit_mesh_vertices)
	_bpy.types.MESH_MT_shape_key_context_menu.remove(_MESH_MT_shape_key_context_menu)
	_bpy.types.MESH_MT_vertex_group_context_menu.remove(_MESH_MT_vertex_group_context_menu)
	
	_bpy.utils.unregister_class(_MESH_MT_shape_key_context_kawa_sub_menu)
	_bpy.utils.unregister_class(_VIEW3D_MT_object_kawa_sub_menu)
	_bpy.utils.unregister_class(_VIEW3D_MT_edit_mesh_kawa_sub_menu)