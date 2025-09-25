import os
from collections import Counter
from operator import attrgetter
from pathlib import Path
from typing import Callable, Any


def assert_unique(objs, path: str, name_path: str, match_function: Callable[[Any], bool] = lambda x: True):
    path_getter = attrgetter(path)
    name_getter = attrgetter(name_path)
    counts = Counter([path_getter(o) for o in objs if match_function(o)])
    dupes = [o for o in objs if counts[path_getter(o)] > 1 and match_function(o)]
    if dupes:
        dupes_str = ', '.join([name_getter(o) for o in dupes])
        raise Exception(f"duplicate {path} found for: {dupes_str}")


def find_qemu_on_system() -> Path | None:
    qemu_locations = (
        "/usr/local/bin/qemu-system-x86_64",
        "/usr/bin/qemu-system-x86_64",
        "/bin/qemu-system-x86_64",
        "/usr/local/sbin/qemu-system-x86_64",
        "/usr/sbin/qemu-system-x86_64",
    )
    found_qemu = next(
        iter([Path(x) for x in qemu_locations if Path(x).is_file() and os.access(Path(x), os.X_OK)]), None
    )
    if found_qemu is None:
        raise Exception(f'failed to find working qemu on paths: `{qemu_locations}`')
    return found_qemu


found_system_qemu = find_qemu_on_system()
