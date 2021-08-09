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

import logging as _logging
_log = _logging.getLogger('kawa.modifiers')


def apply_all_modifiers(obj: 'Object') -> 'int':
	# No context capture here
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


class KawaApplyAllModifiersNoShapeKeys(_bpy.types.Operator):
	bl_idname = "object.kawa_apply_all_modifiers_no_shape_keys"
	bl_label = "Apply All Modifiers (No Shape Keys)"
	bl_description = "Apply all Modifiers on all selected objects, except for Mesh-Objects with Shape Keys."
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
		with _commons.TemporaryViewLayer(name=type(self).__name__):
			counter_objs, counter_mods = 0, 0
			for obj in objs:
				if obj.type == 'MESH' and obj.data.shape_keys is not None:
					continue  # Меш с кейпкеями, пропускаем
				_commons.activate_object(obj)
				modifc = 0
				for mod_i, mod_name in list(enumerate(m.name for m in obj.modifiers)):
					if 'FINISHED' in _bpy.ops.object.modifier_apply(modifier=mod_name):
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
	KawaApplyAllModifiersNoShapeKeys,
)

