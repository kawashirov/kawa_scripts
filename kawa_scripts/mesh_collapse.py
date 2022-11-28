# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
"""
Useful tools for Vertex Groups
"""

import bpy as _bpy
from bmesh import new as _bmesh_new
import mathutils as _mu

from ._internals import log as _log
from ._internals import KawaOperator as _KawaOperator
from . import _doc

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *
	from bmesh.types import *
	from mathutils import *


def write_aramture_collapse(obj: 'Object', target_shapekey: 'Union[int, str]', fallback_weight_sum: 'Union[int, str]'):
	armatures = list(m.object for m in obj.modifiers if (
			m.type == 'ARMATURE' and m.object is not None and m.object.type == 'ARMATURE' and m.object.data is not None
	))  # type: List[Object]
	print(armatures)
	bm = _bmesh_new()
	try:
		bm.from_mesh(obj.data)
		deform_layer = bm.verts.layers.deform.active  # type: BMLayerItem
		target_layer = bm.verts.layers.shape.get(target_shapekey)  # type: BMLayerItem
		fallback_layer = bm.verts.layers.shape.get(target_shapekey)  # type: BMLayerItem
		bm.verts.ensure_lookup_table()
		matrix_obj = obj.matrix_world.inverted()  # type: Matrix
		pos_a, pos_b = _mu.Vector((0, 0, 0)), _mu.Vector((0, 0, 0))
		for v in bm.verts:
			dv = v[deform_layer]  # type: BMDeformVert
			pos_b.zero()
			weight_sum = 0
			bones = list()
			for group_index, weight in dv.items():  # type: int, float
				if weight <= 0.0:
					continue
				group = obj.vertex_groups[group_index]  # type: VertexGroup
				pos_a.zero()
				bone_c = 0
				for arm_obj in armatures:
					bone = arm_obj.data.bones.get(group.name)
					if bone is None:
						continue
					p = (arm_obj.matrix_world @ bone.head_local)
					# bones.append('{}.{}({})'.format(arm_obj.name, bone.name, p))
					pos_a += p
					bone_c += 1
				if bone_c > 0:
					pos_a /= bone_c
					pos_a *= weight
					pos_b += pos_a
					weight_sum += weight
			# _log.info("#{}: {} -> {} -> {} ({})".format(v.index, v[fallback_layer], bones, pos_b, weight_sum))
			if weight_sum <= 0.0:
				# fallback
				v[target_layer] = v[fallback_layer].copy()
				continue
			v[target_layer] = (matrix_obj @ pos_b) / weight_sum  # copy of Vector
		bm.to_mesh(obj.data)
	finally:
		if bm is not None:
			bm.free()
