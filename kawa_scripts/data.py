# Kawashirov's Scripts (c) 2021 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
import typing

import bpy

from ._internals import log

if typing.TYPE_CHECKING:
	from bpy.types import bpy_struct, Object


def orphans_purge_iter(limit=10):
	for i in range(0, limit):
		if bpy.ops.outliner.orphans_purge(do_recursive=True) != 'FINISHED':
			return


def ensure_valid(struct: 'bpy_struct'):
	if not isinstance(struct, bpy.types.bpy_struct):
		log.raise_error(TypeError, f"Invalid data: {type(struct)} {struct!r}")
	try:
		struct.as_pointer()
	except ReferenceError as exc:
		log.error(f"Invalid {type(struct)}: {exc}")
		raise exc
	return True


__all__ = [
	'orphans_purge_iter', 'ensure_valid'
]
