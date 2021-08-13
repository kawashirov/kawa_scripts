
import typing as _typing
if _typing.TYPE_CHECKING:
	from typing import *
	from bpy.types import *


def process_blender_classes(__pdoc__: 'Dict[str, Any]', classes: 'Iterable[type]'):
	for class_ in classes:
		process_blender_class(__pdoc__, class_)


def process_blender_class(__pdoc__: 'Dict[str, Any]', class_: 'type'):
	for item in dir(class_):
		if hasattr(class_, item):
			# Скрыть всё по-умолчанию
			__pdoc__[class_.__name__ + '.' + item] = False
	
	_doc = getattr(class_, '__doc__', None)
	if _doc is None or len(_doc) < 1:
		class_.__doc__ = ''
	
	if 'bl_idname' in class_.__dict__:
		class_.__doc__ += '\n\nID name: `{0}`.'.format(class_.bl_idname)
		
	if 'bl_label' in class_.__dict__:
		class_.__doc__ += '\n\nLabel: `{0}`.'.format(class_.bl_label)
		
	if 'bl_description' in class_.__dict__:
		class_.__doc__ += '\n\nDescription: `{0}`.'.format(class_.bl_description)
	
	for key, value in _typing.get_type_hints(class_).items():
		# print("type hint: {0} - {1} - {2}".format(repr(class_), repr(key), repr(value)))
		if not isinstance(value, tuple) or len(value) != 2:
			continue
		prop_func, options = value
		if prop_func is None or 'Property' not in prop_func.__name__:
			continue
		if not isinstance(options, dict) or 'name' not in options:
			continue
		__pdoc__[class_.__name__ + '.' + key] = "**{0}.*** {1}".format(options['name'], options.get('description', ''))


if __name__ == '__main__':
	import pdoc
	from pdoc import cli
	import kawa_scripts
	print(dir(pdoc))
	# print(cli)
	# context = pdoc.Context()
	# mod = pdoc.Module('kawa_scripts', context=context)
	# pdoc.link_inheritance(context)
	#
	# def recursive_htmls(mod):
	# 	yield mod.name, mod.html()
	# 	for submod in mod.submodules():
	# 		yield from recursive_htmls(submod)
	cli.main(_args=cli.parser.parse_args(['--html', '-f', '-o', 'doc', 'kawa_scripts']))
	