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
from bpy import data as _D

import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


class BaseMaterialPool:
	def __init__(self):
		self.pool = list()  # type: List[Material]
	
	def __len__(self):
		return len(self.pool)
	
	def select_material(self, mat: 'Material') -> 'bool':
		raise NotImplementedError()
	
	def create_material(self, index: 'int') -> 'Material':
		raise NotImplementedError()
	
	def find_materials(self):
		self.pool.clear()
		for mat in _D.materials:
			if self.select_material(mat):
				self.pool.append(mat)
	
	def get(self, index: 'int') -> 'Material':
		while len(self.pool) <= index:
			mat = self.create_material(len(self.pool))
			self.pool.append(mat)
		return self.pool[index]
		
	def delete_materials(self):
		for mat in self.pool:
			_D.materials.remove(mat)
		self.pool.clear()


class KawaMaterialSlotsPool(BaseMaterialPool):
	def select_material(self, mat: 'Material') -> 'bool':
		return mat is not None and mat.name.startswith('_KawaMaterialSlot')
	
	def create_material(self, index: 'int') -> 'Material':
		return _D.materials.new('_KawaMaterialSlot.000')

