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

Basically this addon provides powerful tool for making fully-automated script
for preparing, finalizing and baking lots of raw parts (Objects, Meshes, Modifiers, Materials)
into few export-ready assets.

Besides internal API for building, there is a few useful operators,
especially for editing Shape Keys (see `shapekeys`) and applying Modifiers (see `modifiers`).

**Documentation is not yet finished, sorry.**
**My English is not very good, also sorry.**

.. include:: ./documentation.md
"""

from collections import OrderedDict as _OrderedDict

import typing as _typing

if _typing.TYPE_CHECKING:
	from types import ModuleType
	from typing import Dict
	# Эти итак заимпортированы через __import__ но PyCharm их не видит
	from . import _ui

bl_info = {
	"name": "Kawashirov's Scripts",
	"author": "Sergey V. Kawashirov",
	"description": "Kawashirov's Scripts for Unity and VRChat content creation",
	"location": "There is no UI. Use it from scripts or console by `import kawa_scripts` (or whatever)",
	"wiki_url": "https://kawashirov.github.io/kawa_scripts/",
	"doc_url": "https://kawashirov.github.io/kawa_scripts/",
	"version": (2021, 8, 19),
	"blender": (2, 83, 0),
	"category": "Object",
}
addon_name = __name__

if "bpy" in locals() and "_modules_loaded" in locals():
	from importlib import reload
	
	print("Reloading Kawashirov's Scripts...")
	for key, mod in list(_modules_loaded.items()):
		if mod is None:
			print("Skip {0}...".format(repr(key)))
			continue
		print("Reloading {0}...".format(repr(mod)))
		_modules_loaded[key] = reload(mod)
	del reload
	print("Reloaded Kawashirov's Scripts!")

_modules = [
	"_internals",
	"_ui",
	"atlas_baker",
	"combiner",
	"commons",
	"instantiator",
	"modifiers",
	"reporter",
	"shader_nodes",
	"shapekeys",
	"tex_size_finder",
	"uv",
	"vertex_groups",
]

import bpy

__import__(name=__name__, fromlist=_modules)
_namespace = globals()
_modules_loaded = _OrderedDict()  # type: Dict[str, ModuleType]
for _mod_name in _modules:
	_modules_loaded[_mod_name] = _namespace.get(_mod_name)
del _namespace


from ._internals import log


def register():
	print("Hello from {0}!".format(__name__))
	import logging
	from datetime import datetime
	
	log.py_log.setLevel(logging.DEBUG)
	if len(log.py_log.handlers) < 1:
		import tempfile
		print("Updating kawa_scripts log handler!")
		log_file = tempfile.gettempdir() + '/' + datetime.now().strftime("%Y-%m-%d-%H-%M-%S") + '-kawa.log'
		log_formatter = logging.Formatter(fmt='[%(asctime)s][%(levelname)s] %(message)s')
		log_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8', delay=False)
		log_handler.setFormatter(log_formatter)
		log.py_log.addHandler(log_handler)
		log.info("Log handler updated!")
	
	from bpy.utils import register_class
	for mod in _modules_loaded.values():
		if mod is _ui:
			continue
		if mod and hasattr(mod, 'classes'):
			for cls in mod.classes:
				register_class(cls)
	
	_ui.register()
	
	log.info("Hello from {0} once again!".format(__name__))


def unregister():
	from bpy.utils import unregister_class
	
	_ui.unregister()
	
	for mod in reversed(_modules_loaded.values()):
		if mod is _ui:
			continue
		if hasattr(mod, 'classes'):
			for cls in reversed(mod.classes):
				if cls.is_registered:
					unregister_class(cls)
	
	log.info("Goodbye from {0}...".format(__name__))


__pdoc__ = dict()
__pdoc__['register'] = False
__pdoc__['unregister'] = False
