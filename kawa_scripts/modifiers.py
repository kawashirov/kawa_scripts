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
import typing as _typing

from . import commons as _commons

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


def apply_all_modifiers(obj: 'Object') -> 'int':
	_commons.ensure_deselect_all_objects()
	modifc = 0
	while len(obj.modifiers) > 0:
		modifier = next(iter(obj.modifiers))
		_commons.activate_object(obj)
		if _bpy.app.version >= (2, 90, 0):
			_bpy.ops.object.modifier_apply(modifier=modifier.name)
		else:
			_bpy.ops.object.modifier_apply(apply_as='DATA', modifier=modifier.name)
		modifc += 1
	_commons.ensure_deselect_all_objects()
	return modifc


class KawaApplyAllModifiers(_bpy.types.Operator):
	bl_idname = "object.kawa_apply_all_modifiers"
	bl_label = "Apply All Modifiers"
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if len(context.selected_objects) < 1:
			return False  # Должны быть выбраны какие-то объекты
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def execute(self, context: 'Context'):
		last_active = context.view_layer.objects.active
		try:
			counter_objs, counter_mods = 0, 0
			for obj in context.selected_objects:
				modifc = 0
				while len(obj.modifiers) > 0:
					modifier = next(iter(obj.modifiers))
					context.view_layer.objects.active = obj
					_bpy.ops.object.modifier_apply(modifier=modifier.name)
					modifc += 1
				counter_mods += modifc
				counter_objs += 1 if modifc > 0 else 0
			self.report({'INFO'}, "Applied {0} modifiers on {1} objects!".format(counter_mods, counter_objs))
			return {'FINISHED'} if counter_mods > 0 else {'CANCELLED'}
		finally:  # TODO overrides dont work here
			context.view_layer.objects.active = last_active
	
	def invoke(self, context: 'Context', event: 'Event'):
		return self.execute(context)


classes = (
	KawaApplyAllModifiers,
)

