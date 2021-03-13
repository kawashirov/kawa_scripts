import bmesh
import logging
import typing
import time

from .commons import *

if typing.TYPE_CHECKING:
	from typing import *

log = logging.getLogger('kawa.collider_combiner')


def combinde_colliders_raw(**kwargs):
	raw_original = kwargs.get('original')
	if not isinstance(raw_original, (set, list, tuple)):
		raise ConfigurationError("'original' is not a set/list/tuple!")
	
	raw_target = kwargs.get('target')
	if not is_valid_string(raw_target):
		raise ConfigurationError("'original' is not valid string!")
	
	raw_material = kwargs.get('material')
	if not is_none_or_valid_string(raw_material):
		raise ConfigurationError("'material' is not valid string!")
	
	tobj = bpy.context.scene.objects.get(raw_target)
	if tobj is None:
		raise RuntimeError("Target Object does not exist!", raw_target)
	
	tmat = None
	if raw_material is not None:
		tmat = bpy.context.blend_data.materials.get(raw_material)
		if tmat is None:
			raise RuntimeError("Target Material does not exist!", raw_material)
	
	oobjs = set()
	for oobj_name in raw_original:
		oobj = bpy.context.scene.objects.get(oobj_name)
		if oobj is None:
			log.warning("There is no original Object='%s'! Skip.", oobj_name)
			continue
		oobjs.add(oobj)
	
	combinde_colliders_bpy(oobjs, tobj, material=tmat)


def combinde_colliders_bpy(originals: 'Iterable[bpy.types.Object]', target: 'bpy.types.Object', material: 'bpy.types.Material'):
	dobjs = set()
	for oobj in originals:
		oobj.hide_set(False)
		oobj.hide_select = False
		ensure_deselect_all_objects()
		oobj.select_set(True)
		ensure_selected_single(oobj)
		ensure_op_finished(bpy.ops.object.duplicate(), name='bpy.ops.object.duplicate')
		ensure_selected_single(None, oobj)
		dobj = bpy.context.selected_objects[0]
		dobj.hide_set(False)  # Необходимо, т.к. некоторые операторы не работают на скрытых объектах
		apply_all_modifiers(dobj)
		remove_all_material_slots(dobj)
		dobjs.add(dobj)
	
	ensure_deselect_all_objects()
	target.hide_set(False)
	target.hide_select = False
	target.select_set(True)
	bpy.context.view_layer.objects.active = target
	remove_all_geometry(target)
	remove_all_shape_keys(target)
	remove_all_uv_layers(target)
	remove_all_vertex_colors(target)
	if material is not None:
		remove_all_material_slots(target)
		bpy.ops.object.material_slot_add()
		target.material_slots[0].material = material
	else:
		remove_all_material_slots(target)
	
	target.select_set(True)
	bpy.context.view_layer.objects.active = target
	for dobj in dobjs:
		dobj.select_set(True)
	ensure_op_finished(bpy.ops.object.join(), name="bpy.ops.object.join")
