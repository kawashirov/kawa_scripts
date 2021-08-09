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
from bpy import context as _C
import typing as _typing

from . import commons as _commons
from . import shapekeys as _shapekeys

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *

import logging as _logging

_log = _logging.getLogger('kawa.modifiers')


def modifier_apply_compat(obj: 'Object', apply_as: 'str', modifier: 'str'):
	context = _C.copy()
	context['object'] = obj
	context['active_object'] = obj
	context['selected_objects'] = [obj]
	context['mode'] = 'OBJECT'
	context['edit_object'] = None
	if _bpy.app.version >= (2, 90, 0):
		if apply_as == 'SHAPE':
			return _bpy.ops.object.modifier_apply_as_shapekey(context, modifier=modifier)
		else:
			return _bpy.ops.object.modifier_apply(context, modifier=modifier)
	else:
		return _bpy.ops.object.modifier_apply(context, apply_as=apply_as, modifier=modifier)


def modifier_apply_with_shape_key_supported(obj: 'Object', modifier: 'str'):
	# Приминить шейп как DATA, но при этом рботает на меше, где есть шейпы
	if obj.type != 'MESH' or obj.data.shape_keys is None:
		return modifier_apply_compat(obj, 'DATA', modifier)
	# Далее применение модификатора через шейпы
	mesh = obj.data  # type: Mesh
	prev_key_count = len(mesh.shape_keys.key_blocks)
	assert prev_key_count > 0
	modifier_apply_result = modifier_apply_compat(obj, 'SHAPE', modifier)
	if 'FINISHED' not in modifier_apply_result:
		return modifier_apply_result
	key_count = len(mesh.shape_keys.key_blocks)
	assert key_count == prev_key_count + 1
	obj.active_shape_key_index = key_count - 1
	if not _shapekeys.apply_active_to_all(obj):
		raise RuntimeError()
	assert len(mesh.shape_keys.key_blocks) == prev_key_count
	return {'FINISHED'}


def apply_all_modifiers(obj: 'Object') -> 'int':
	# No context control
	_commons.ensure_deselect_all_objects()
	modifc = 0
	for mod_i, mod_name in list(enumerate(m.name for m in obj.modifiers)):
		if 'FINISHED' in _bpy.ops.object.modifier_apply(modifier=mod_name):
			modifc += 1
		else:
			_log.warning("Can not apply modifier #{0} {1} on {2}!".format(mod_i, repr(mod_name), repr(obj)))
		modifc += 1
	_commons.ensure_deselect_all_objects()
	return modifc


class KawaApplyAllModifiersShapeKeysSupported(_bpy.types.Operator):
	bl_idname = "object.kawa_apply_all_modifiers_shape_keys_supported"
	bl_label = "Apply All Modifiers (Shape Keys Support for Deform-Only)"
	bl_description = "\n".join((
		"Try to apply all Modifiers as DATA on all selected objects.",
		"Deform-only Modifiers should be also applicable on Mesh-objects with Shape Keys."
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if len(context.selected_objects) < 1:
			return False  # Должны быть выбраны какие-то объекты
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def execute(self, context: 'Context'):
		objs = list(context.selected_objects)  # type: List[Object]
		counter_objs, counter_mods = 0, 0
		for obj in objs:
			# if obj.type == 'MESH' and obj.data.shape_keys is not None:
			# 	continue  # Меш с кейпкеями, пропускаем
			modifc = 0
			for mod_i, mod_name in list(enumerate(m.name for m in obj.modifiers)):
				if 'FINISHED' in modifier_apply_with_shape_key_supported(obj, mod_name):
					modifc += 1
				else:
					self.report({'WARNING'}, "Can not apply modifier #{0} {1} on {2}!".format(mod_i, repr(mod_name), repr(obj)))
			counter_mods += modifc
			counter_objs += 1 if modifc > 0 else 0
		self.report({'INFO'}, "Applied {0} modifiers on {1} objects!".format(counter_mods, counter_objs))
		return {'FINISHED'} if counter_mods > 0 else {'CANCELLED'}
	
	def invoke(self, context: 'Context', event: 'Event'):
		return self.execute(context)


classes = (
	KawaApplyAllModifiersShapeKeysSupported,
)
