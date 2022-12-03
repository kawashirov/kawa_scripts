# Kawashirov's Scripts (c) 2019 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

"""
`kawa_scripts` is an addon and package of useful methods for **Blender 2.8x+**
made by Kawashirov.
It's designed to use mostly form Python interactive console or from Python scripts.

Basically, this addon provides a powerful tool for making a fully-automated script
for preparing, finalizing and baking lots of raw parts (Objects, Meshes, Modifiers, Materials)
into few export-ready assets.

Besides internal API for building, there are a few useful operators,
especially for editing Shape Keys (see `shapekeys`) and applying Modifiers (see `modifiers`).

**Documentation is not yet finished, sorry.**
**My English is not very good, also sorry.**

.. include:: ./documentation.md
"""
import sys

# Internals
from . import _internals
from . import _ui

# Modules
from . import armature
from . import atlas_baker
from . import attributes
from . import combiner
from . import commons
from . import data
from . import instantiator
from . import materials
from . import meshes
from . import modifiers
from . import objects
from . import reporter
from . import shader_nodes
from . import shapekeys
from . import uv
from . import vertex_groups

# Packages
from . import building
from . import imagemagick

bl_info = {
	"name": "Kawashirov's Scripts",
	"author": "Sergey V. Kawashirov",
	"description": "Kawashirov's Scripts for Unity and VRChat content creation",
	"location": "There is no UI. Use it from scripts or console by `import kawa_scripts` (or whatever)",
	"wiki_url": "https://kawashirov.github.io/kawa_scripts/",
	"doc_url": "https://kawashirov.github.io/kawa_scripts/",
	"version": (2022, 12, 1),
	"blender": (2, 93, 0),
	"category": "Object",
}
addon_name = __name__

log = _internals.log
log.init_handler_interactive()
log.init_handler_file()


def reload_modules():
	global log
	log.info(f"Reloading {__name__!r}...")
	import types, importlib, collections, bpy
	queue = collections.deque()
	if root_module := sys.modules.get(reload_modules.__module__):
		queue.append(root_module)
	queue.extendleft(globals().values())
	already_reloaded = set()
	is_enabled = __name__ in bpy.context.preferences.addons.keys()
	if is_enabled:
		# Если не отгрузить классы из блендера, то может закораптить весь блендер
		bpy.ops.preferences.addon_disable(module=__name__)
	while len(queue) > 0:
		module = queue.pop()
		if not isinstance(module, types.ModuleType) or module in already_reloaded:
			continue
		if module in already_reloaded or not module.__name__.startswith(__name__ + '.'):
			continue
		log.info(f"Reloading {module.__name__!r}...")
		if log.__module__ in module.__name__:
			# Логгер ломается если им пользоваться, пока пере-импортируется модуль.
			log.drop_handlers()
		importlib.reload(module)
		already_reloaded.add(module)
		if log.__module__ in module.__name__:
			log = _internals.log
			log.init_handler_file()
			log.init_handler_interactive()
		queue.extend(getattr(module, attr, None) for attr in dir(module))
	log.info(f"Reloaded {len(already_reloaded)} modules.")
	if is_enabled:
		bpy.ops.preferences.addon_enable(module=__name__)
	log.info(f"Reloaded {__name__!r}!")


_registered = list()


def register():
	global log
	log.info(f"Hello from {__name__!r}!")
	import types, bpy
	_registered.clear()
	for mod in globals().values():
		if not isinstance(mod, types.ModuleType):
			continue
		if mod is _ui:
			continue
		if mod and hasattr(mod, 'classes'):
			for cls in mod.classes:
				bpy.utils.register_class(cls)
				_registered.append(cls)
	
	_ui.register()
	
	log.info(f"Registered {__name__!r}. Hello once again!")


def unregister():
	global log
	import bpy
	
	_ui.unregister()
	
	for mod in reversed(_registered):
		if mod is _ui:
			continue
		if hasattr(mod, 'classes'):
			for cls in reversed(mod.classes):
				if cls.is_registered:
					bpy.utils.unregister_class(cls)
	_registered.clear()
	
	log.info(f"Unregistered {__name__!r}. Goodbye...")


__pdoc__ = dict()
__pdoc__['register'] = False
__pdoc__['unregister'] = False
