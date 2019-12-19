# Kawashirov's Scripts (c) 2019 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#

# from .commons import *
# from .mesh_combiner import *

bl_info = {
	"name": "Kawashirov's Scripts",
	"author": "Sergey V. Kawashirov",
	"description": "Kawashirov's Scripts for Unity and VRChat content creation",
	"location": "There is no UI. Use it from scripts or console by `import kawa_scripts` (or whatever)",
	"wiki_url": "",
	"version": (0, 1),
	"blender": (2, 79, 0),
	"category": "Object",
}


def register():
	print("Hello from Kawashirov's Scripts!")


def unregister():
	print("Goodbye from Kawashirov's Scripts!")
