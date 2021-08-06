# Kawashirov's Scripts (c) 2019 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

import typing

if typing.TYPE_CHECKING:
	from typing import *
	import logging, tempfile, subprocess

bl_info = {
	"name": "Kawashirov's Scripts",
	"author": "Sergey V. Kawashirov",
	"description": "Kawashirov's Scripts for Unity and VRChat content creation",
	"location": "There is no UI. Use it from scripts or console by `import kawa_scripts` (or whatever)",
	"wiki_url": "",
	"version": (0, 2),
	"blender": (2, 83, 0),
	"category": "Object",
}

log = None


def reimport():
	import importlib
	from . import atlas_baker, combiner, commons, instantiator, shader_nodes, uv, tex_size_finder
	for m in (atlas_baker, combiner, commons, instantiator, shader_nodes, uv, tex_size_finder):
		importlib.reload(m)


def register():
	print("Hello from Kawashirov's Scripts!")
	import logging
	global log
	log = logging.getLogger('kawa')
	log.setLevel(logging.DEBUG)
	if len(log.handlers) < 1:
		import tempfile
		print("Updating kawa_scripts log handler!")
		log_file = tempfile.gettempdir() + '/kawa.log'
		log_formatter = logging.Formatter(fmt='[%(asctime)s][%(levelname)s] %(message)s')
		log_handler = logging.FileHandler(log_file, mode='w', encoding='utf-8', delay=False)
		log_handler.setFormatter(log_formatter)
		log.addHandler(log_handler)
		log.info("Log handler updated!")
	reimport()
	log.info("Hello from Kawashirov's Scripts again!")


def unregister():
	print("Goodbye from Kawashirov's Scripts!")
