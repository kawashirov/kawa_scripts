# Kawashirov's Scripts (c) 2022 by Sergey V. Kawashirov
#
# Kawashirov's Scripts is licensed under a
# Creative Commons Attribution-NonCommercial-ShareAlike 3.0 Unported License.
#
# You should have received a copy of the license along with this
# work.  If not, see <http://creativecommons.org/licenses/by-nc-sa/3.0/>.
#
#
from pathlib import Path
import subprocess as sp

from .._internals import log

_embedded_magick = Path(__file__).parent / 'magick.exe'


def _run_imagemagick(args: 'list[str]'):
	log.info(f'Running ImageMagick: {args!r}')
	with sp.Popen(args, stdout=sp.PIPE, stderr=sp.STDOUT) as process:
		while process.poll() is None:
			if line := process.stdout.readline():
				log.warning(f'ImageMagick message: {line}')
		log.info(f'ImageMagick done: {args!r} {process.returncode}')
		return process.returncode


def _sanitize_input(input_path: 'str|Path', arg_name: 'str'):
	path = Path(input_path).resolve()
	if not path.exists():
		raise RuntimeError(f"{arg_name}={input_path!r} does not exist!")
	if not path.is_file():
		raise RuntimeError(f"{arg_name}={input_path!r} is not a file!")
	return str(path)


def _sanitize_output(output_path: 'str|Path', arg_name: 'str'):
	path = Path(output_path).resolve()
	if path.exists():
		raise RuntimeError(f"{arg_name}={output_path!r} already exists!")
	path.parent.mkdir(parents=True, exist_ok=True)


def test():
	""" Test if ImageMagick is working by running `magick.exe -version` """
	return _run_imagemagick([_embedded_magick, '-version'])


def join_rgb_and_alpha(diffuse_path: 'str|Path', alpha_path: 'str|Path', output_path: 'str|Path'):
	"""
	Joins RGB texture and alpha texture into single RGBA texture.
	Useful for exporting into Unity.
	"""
	diffuse_path = _sanitize_input(diffuse_path, 'diffuse_path')
	alpha_path = _sanitize_input(alpha_path, 'alpha_path')
	output_path = _sanitize_output(output_path, 'output_path')
	args = [_embedded_magick, 'convert', diffuse_path, alpha_path, '-alpha', 'Off',
		'-compose', 'CopyOpacity', '-composite', output_path]
	return _run_imagemagick(args)


__all__ = [
	'test', 'join_rgb_and_alpha'
]
