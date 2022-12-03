from time import perf_counter as _perf_counter

import typing as _typing

if _typing.TYPE_CHECKING:
	from typing import Callable


class AbstractReporter:
	def __init__(self, **kwargs):
		self.report_time = kwargs.get('report_time')
		self.time_begin = _perf_counter()
		self.time_progress = _perf_counter()
	
	def get_eta(self, progress) -> 'float':
		time_passed = self.time_progress - self.time_begin
		time_total = time_passed / progress
		return time_total - time_passed
	
	def do_report(self, time_passed):
		raise NotImplementedError('do_report')
	
	def ask_report(self, force=False):
		now = _perf_counter()
		if force is False and now - self.time_progress < self.report_time:
			return
		self.time_progress = now
		self.do_report(now - self.time_begin)


class LambdaReporter(AbstractReporter):
	def __init__(self, **kwargs):
		super().__init__(**kwargs)
		self.func = kwargs.get('func')  # type: Callable[[LambdaReporter, float], None]
	
	def do_report(self, time_passed):
		self.func(self, time_passed)
