from collections import Counter
from operator import attrgetter
from typing import Callable, Any


def assert_unique(objs, path: str, name_path: str, match_function: Callable[[Any], bool] = lambda x: True):
    path_getter = attrgetter(path)
    name_getter = attrgetter(name_path)
    counts = Counter([path_getter(o) for o in objs if match_function(o)])
    dupes = [o for o in objs if counts[path_getter(o)] > 1]
    if dupes:
        dupes_str = ', '.join([name_getter(o) for o in dupes])
        raise Exception(f"duplicate {path} found for: {dupes_str}")
