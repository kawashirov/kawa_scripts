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

from . import _internals
from ._internals import log as _log
from . import commons as _commons
from . import objects as _objects
from . import meshes as _meshes
from . import shapekeys as _shapekeys

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import Object, Modifier, ArmatureModifier, Operator, Mesh, ShapeKey, Context, Event
	from ._internals import ContextOverride

MODIFIER_TYPES_DEFORM = {'ARMATURE', 'CAST', 'CURVE', 'DISPLACE', 'HOOK', 'LAPLACIANDEFORM', 'LATTICE', 'MESH_DEFORM', 'SHRINKWRAP',
	'SIMPLE_DEFORM', 'SMOOTH', 'CORRECTIVE_SMOOTH', 'LAPLACIANSMOOTH', 'SURFACE_DEFORM', 'WARP', 'WAVE'}


def is_deform_modifier(modifier: 'Modifier'):
	return modifier.type in MODIFIER_TYPES_DEFORM


def _get_modifier_index(obj: 'Object', modifier: 'Modifier') -> int:
	for idx in range(len(obj.modifiers)):
		if obj.modifiers[idx] == modifier:
			return idx
	raise RuntimeError()


def _copy_modifier_and_move_up(ctx: 'ContextOverride', obj: 'Object', modifier_name: 'str', op: 'Operator' = None) -> 'Modifier':
	# Создаем копию арматуры
	modifier = obj.modifiers[modifier_name]
	modifier_i = _get_modifier_index(obj, modifier)
	if 'FINISHED' not in _bpy.ops.object.modifier_copy(ctx, modifier=modifier_name):
		_log.raise_error(RuntimeError, 'Huh? Can not copy modifier {0} on {1}!'.format(repr(modifier_name), repr(obj)), op=op)
	copy_modifier = obj.modifiers[modifier_i + 1]  # type: Modifier
	assert copy_modifier.type == modifier.type
	# Двигаем копию арматуры на верх
	while _get_modifier_index(obj, copy_modifier) > 0:
		if 'FINISHED' not in _bpy.ops.object.modifier_move_up(ctx, modifier=copy_modifier.name):
			_log.raise_error(RuntimeError, 'Huh? Can not move up modifier {0} on {1}!'.format(repr(copy_modifier.name), repr(obj)), op=op)
	return copy_modifier


def modifier_apply_compat(obj: 'Object', apply_as: 'str', modifier: 'str', keep_modifier=False, op: 'Operator' = None):
	ctx = _bpy.context.copy()  # type: ContextOverride
	ctx['object'] = obj
	ctx['active_object'] = obj
	ctx['selected_objects'] = [obj]
	ctx['mode'] = 'OBJECT'
	ctx['edit_object'] = None
	if _bpy.app.version >= (2, 90, 0):
		# Blender 2.9x
		if apply_as == 'SHAPE':
			return _bpy.ops.object.modifier_apply_as_shapekey(ctx, modifier=modifier, keep_modifier=keep_modifier)
		else:  # apply_as == 'DATA'
			if keep_modifier:
				copy_modifier = _copy_modifier_and_move_up(ctx, obj, modifier, op=op)
				return _bpy.ops.object.modifier_apply(ctx, modifier=copy_modifier.name)
			else:
				return _bpy.ops.object.modifier_apply(ctx, modifier=modifier)
	else:
		# Blender 2.8x
		if keep_modifier:
			copy_modifier = _copy_modifier_and_move_up(ctx, obj, modifier, op=op)
			return _bpy.ops.object.modifier_apply(ctx, apply_as=apply_as, modifier=copy_modifier)
		else:
			return _bpy.ops.object.modifier_apply(ctx, apply_as=apply_as, modifier=modifier)


def apply_all_modifiers(obj: 'Object', op: 'Operator' = None) -> 'int':
	# No context control
	_objects.deselect_all()
	_objects.activate(obj)
	modifc = 0
	for mod_i, mod_name in list(enumerate(m.name for m in obj.modifiers)):
		if 'FINISHED' in _bpy.ops.object.modifier_apply(modifier=mod_name):
			modifc += 1
		else:
			_log.warning("Can not apply modifier #{0} {1} on {2}!".format(mod_i, repr(mod_name), repr(obj)), op=op)
		modifc += 1
	_objects.deselect_all()
	return modifc


def apply_deform_modifier_to_mesh_high_precision(modifier: 'Modifier', keep_modifier=False, ignore_other_modifies=True, op: 'Operator' = None):
	if _log.is_debug():
		_log.info(f"Applying Modifier {modifier} on Object {modifier.id_data} with keep_modifier={keep_modifier}, ignore_other_modifies={ignore_other_modifies}", op=op)
	if not modifier:
		_log.raise_error(ValueError, f"Modifier is None", op=op)
	mobj = modifier.id_data
	if not mobj:
		_log.raise_error(ValueError, f"Modifier {modifier.name!r} id_data is None", op=op)
	if not is_deform_modifier(modifier):
		_log.raise_error(ValueError, f"Modifier {modifier.name!r} on {mobj!r} has non-deform type {modifier.type!r}", op=op)
	if mobj.data.shape_keys is None:
		# Простой режим применения, когда нет шейп-кеев на объекте
		return modifier_apply_compat(mobj, 'DATA', modifier.name, keep_modifier=True)
	#
	# Сложный режим применения, когда есть шейп кеи на объекте
	# Здесь были контекст-оверрайды но они вызывают какие-то странные багули
	# По этому просто нагло редактируем контекст под себя
	if _bpy.context.mode != 'OBJECT':
		_commons.ensure_op_finished(_bpy.ops.object.mode_set(mode='OBJECT'))
	#
	# Создание временной копии основного объекта
	# Новые объекты сохраняются в глобальный контекст, по этому нужно отлавливать их от туда
	cobj = None
	try:
		_objects.deselect_all()
		_objects.activate(mobj, op=op)
		_commons.ensure_op_finished(_bpy.ops.object.duplicate(linked=True), op=op)
		assert len(_bpy.context.selected_objects) == 1
		assert _bpy.context.selected_objects[0] == _bpy.context.active_object
		cobj = _bpy.context.active_object  # type: Object
		# Из-за странного бага duplicate копирует объект, но изменяет оригинал,
		# но если сделать linked копию, а потом инстанциировать ее через make_single_user,
		# то все работает нормально. Беды с башкой блендера.
		_commons.ensure_op_finished(_bpy.ops.object.make_single_user(type='SELECTED_OBJECTS', obdata=True), op=op)
		assert mobj.data != cobj.data  # Странный баг
		# Удаление всего лишнего с копии
		cobj.shape_key_clear()
		if ignore_other_modifies:
			for cobj_modifier in list(m.name for m in cobj.modifiers if m.name != modifier.name):
				_commons.ensure_op_finished(_bpy.ops.object.modifier_remove(modifier=cobj_modifier), op=op)
		# Пересчет шейпкеев на копии
		mobj_mesh = _meshes.get_safe(mobj)  # type: Mesh
		cobj_mesh = _meshes.get_safe(cobj)  # type: Mesh
		for key in list(mobj.data.shape_keys.key_blocks):  # type: ShapeKey
			if _log.is_debug():
				_log.info(f"Transforming {key!r} on original {mobj!r} and copy {cobj!r}", op=op)
			if not _shapekeys.ensure_mesh_shape_len_match(mobj_mesh, key, op=op):
				continue
			if not _shapekeys.ensure_mesh_shape_len_match(cobj_mesh, key, op=op):
				continue
			# Копирование данных шейпкея в копию
			for i in range(len(key.data)):
				cobj_mesh.vertices[i].co = key.data[i].co
			# Деформирование копии
			modifier_apply_compat(cobj, 'DATA', modifier.name, keep_modifier=True, op=op)
			# Возврат данных из копии в шейпкей
			for i in range(len(key.data)):
				key.data[i].co = cobj_mesh.vertices[i].co
	finally:
		cmesh = _meshes.get_safe(cobj, strict=False)
		if cobj:
			_bpy.data.objects.remove(cobj, do_unlink=True, do_ui_user=True)
		if cmesh:
			_bpy.data.meshes.remove(cmesh, do_unlink=True, do_ui_user=True)
	if not keep_modifier:
		mobj.modifiers.remove(modifier)
	return {'FINISHED'}


class KawaApplyDeformModifierHighPrecision(_internals.KawaOperator):
	bl_idname = "kawa.apply_deform_modifier_high_precision"
	bl_label = "Apply Deform Modifier (Shape Keys High Precision)"
	bl_description = "\n".join((
		"Apply active Deform-type Modifier of selected Mesh-object.",
		"Works on Meshes with Shape Keys with high precision.",
		"Shape Keys should not break."
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		obj = cls.get_active_obj(context)
		if obj.type != 'MESH':
			return False  # Требуется тип объекта MESH
		modifier = obj.modifiers.active
		if modifier is None or not is_deform_modifier(modifier):
			return False  # Требуется активный Deform Modifier
		return True
	
	def execute(self, context: 'Context'):
		obj = self.get_active_obj(context)
		apply_deform_modifier_to_mesh_high_precision(obj.modifiers.active)
		return {'FINISHED'}


class KawaApplyAllModifiersHighPrecision(_internals.KawaOperator):
	bl_idname = "kawa.apply_all_modifiers_high_precision"
	bl_label = "Apply All Modifiers (Shape Keys High Precision for Deform-Only)"
	bl_description = "\n".join((
		"Try to apply all Modifiers on all selected objects.",
		"For Deform-type modifiers works on Meshes with Shape Keys with high precision.",
		"Any non-Deform modifiers on Meshes with Shape Keys will be ignored with warning."
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		if len(cls.get_selected_objs(context)) < 1:
			return False  # Должны быть выбраны какие-то объекты
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		return True
	
	def _execute_obj(self, context: 'Context', obj) -> int:
		modifc = 0
		for mod_i, mod_name in list(enumerate(m.name for m in obj.modifiers)):
			# Численый индекс меняется при итерации
			mod = obj.modifiers[mod_name]  # type: Modifier
			if is_deform_modifier(mod):
				# Деформирующий модификатор - применим и не шейпкеии
				result = apply_deform_modifier_to_mesh_high_precision(mod, keep_modifier=False, op=self)
				if 'FINISHED' in result:
					modifc += 1
				else:
					self.warning("Can not apply modifier #{0} {1} on {2}: {3}!".format(
						mod_i, repr(mod_name), repr(obj), repr(result)))
			elif obj.type == 'MESH' and obj.data.shape_keys is not None:
				# не-деформирующий модификатор не применим на шейпкеи
				self.warning("Can not apply non-deform-type modifier #{0} {1} on {2} with shape keys!".format(
					mod_i, repr(mod_name), repr(obj)))
			else:
				# Другое: либо это вообще не меш, либо это простая меш без шейпкеев
				result = modifier_apply_compat(obj, 'DATA', mod.name, keep_modifier=False)
				if 'FINISHED' in result:
					modifc += 1
				else:
					self.warning("Can not apply modifier #{0} {1} on {2}: {3}!".format(
						mod_i, repr(mod_name), repr(obj), repr(result)))
		return modifc
	
	def execute(self, context: 'Context'):
		objs = list(self.get_selected_objs(context))
		counter_objs, counter_mods = 0, 0
		for obj in objs:
			if len(obj.modifiers) < 1:
				continue
			self.info("Applying {0} modifiers on {1}...".format(len(obj.modifiers), repr(obj)))
			modifc = self._execute_obj(context, obj)
			counter_mods += modifc
			counter_objs += 1 if modifc > 0 else 0
		self.info("Applied {0} modifiers on {1} objects!".format(counter_mods, counter_objs))
		return {'FINISHED'} if counter_mods > 0 else {'CANCELLED'}


class KawaApplyArmatureToMeshesHighPrecision(_internals.KawaOperator):
	bl_idname = "kawa.apply_armature_to_meshes_high_precision"
	bl_label = "Apply Armature Poses to Meshes (Shape Keys High Precision)"
	bl_description = "\n".join((
		"Apply current poses of selected Armature-objects to selected Mesh-objects as Rest poses.",
		"Armatures and Meshes that is not selected are ignored.",
		"Works on Meshes with Shape Keys with high precision.",
		"Shape Keys should not break."
	))
	bl_options = {'REGISTER', 'UNDO'}
	
	@classmethod
	def poll(cls, context: 'Context'):
		selected = cls.get_selected_objs(context)
		if len(selected) < 1:
			return False  # Должны быть выбраны какие-то объекты
		if context.mode != 'OBJECT':
			return False  # Требуется режим OBJECT
		if not any(obj for obj in selected if obj.type == 'ARMATURE'):
			return False  # Требуется что бы была выбрана хотя бы одна арматура
		if not any(obj for obj in selected if obj.type == 'MESH'):
			return False  # Требуется что бы была выбрана хотя бы одна меш
		return True
	
	def execute(self, context: 'Context'):
		selected = self.get_selected_objs(context)
		# Отбор арматур
		armatures = dict()  # type: Dict[Object, List[ArmatureModifier]]
		for obj in selected:  # type: Object
			if obj.type != 'ARMATURE':
				continue
			armatures[obj] = list()
		if len(armatures) < 1:
			self.warning("No Armature-objects selected!")
			return {'CANCELLED'}
		# Отбор модификатров
		modifc = 0
		for obj in selected:  # type: Object
			if obj.type != 'MESH':
				continue
			for modifier in obj.modifiers:  # type: ArmatureModifier
				if modifier.type != 'ARMATURE':
					continue
				list_ = armatures.get(modifier.object)
				if list_ is None:
					continue
				list_.append(modifier)
				modifc += 1
		if modifc < 1:
			self.warning("No Mesh-objects bound to given Armature-objects selected!")
			return {'CANCELLED'}
		self.info("Applying poses from {0} armatures to {1} meshes...".format(len(armatures), modifc))
		
		aobjc, modifc, i = 0, 0, 0
		wm = _bpy.context.window_manager
		try:
			wm.progress_begin(0, 9999)
			for aobj, modifiers in armatures.items():
				for modifier in modifiers:
					i += 1
					wm.progress_update(i % 10000)
					if 'FINISHED' in apply_deform_modifier_to_mesh_high_precision(modifier, keep_modifier=True, op=self):
						modifc += 1
				try:
					_objects.activate(aobj)
					_bpy.ops.object.mode_set(mode='POSE', toggle=False)
					_bpy.ops.pose.armature_apply(selected=False)
				finally:
					_bpy.ops.object.mode_set(mode='OBJECT', toggle=False)
				aobjc += 1
			self.info("Applied poses from {0} armatures to {1} meshes.".format(aobjc, modifc))
		finally:
			wm.progress_end()
		return {'FINISHED'}


classes = (
	KawaApplyDeformModifierHighPrecision,
	KawaApplyAllModifiersHighPrecision,
	KawaApplyArmatureToMeshesHighPrecision,
)
