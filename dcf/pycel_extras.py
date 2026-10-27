"""Excel functions pycel does not ship (MEDIAN, RSQ), registered as a pycel plugin for the
workbook check in dcf/verify.py."""
import statistics

from pycel.excelutil import flatten


def _nums(args):
    return [x for x in flatten(args) if isinstance(x, (int, float)) and not isinstance(x, bool)]


def median(*args):
    return statistics.median(_nums(args))


def rsq(known_y, known_x):
    ys, xs = _nums(known_y), _nums(known_x)
    return statistics.correlation(xs, ys) ** 2
