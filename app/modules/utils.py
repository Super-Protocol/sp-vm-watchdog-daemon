import subprocess
import struct
import os
from collections import defaultdict, Counter
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
        raise Exception(f"duplicate path: `{path}` found for: `{dupes_str}`")


def assert_unique_pair(
    objs, path_one: str, path_two: str, name_path: str, match_function: Callable[[Any], bool] = lambda x: True
):
    path_one_getter = attrgetter(path_one)
    path_two_getter = attrgetter(path_two)
    name_getter = attrgetter(name_path)

    groups = defaultdict(list)
    [groups[path_two_getter(o)].append(o) for o in objs if match_function(o)]

    for group_key, items in groups.items():
        counts = Counter([path_one_getter(o) for o in items if match_function(o)])
        dupes = [o for o in objs if counts[path_one_getter(o)] > 1 and match_function(o)]
        if dupes:
            dupes_str = ', '.join([name_getter(o) for o in dupes])
            raise Exception(f"duplicate path: `{path_one}` in group: `{group_key}` found for: `{dupes_str}`")


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


def modprobe(name: str) -> None:
    cmd = ['modprobe', name]
    ret = subprocess.run(cmd, capture_output=True)
    if ret.returncode != 0:
        stdout = ret.stdout.decode('utf-8')
        stderr = ret.stderr.decode('utf-8')
        msg = f'{stdout} {stderr}'
        raise Exception(f'failed to modprobe {name}, reason: `{msg}`')


def get_cpu_cbitpos() -> int:
    modprobe('cpuid')
    cpuid_path = Path('/dev/cpu/0/cpuid')
    if not cpuid_path.is_char_device():
        raise Exception(f'failed to access cpuid file: {cpuid_path}, reason: not exists')
    # https://www.amd.com/content/dam/amd/en/documents/epyc-technical-docs/tuning-guides/58207-using-sev-with-amd-epyc-processors.pdf
    eax = 0x80000000 + 0x1F  # extended CPUID range + page number
    offset = 16 * eax
    with cpuid_path.open("rb") as f:
        f.seek(offset)
        data = f.read(16)
    ret_eax, ret_ebx, ret_ecx, ret_edx = struct.unpack("<4I", data)

    return ret_ebx & 0x3F


found_system_qemu = find_qemu_on_system()
detected_cpu_cbitpos = get_cpu_cbitpos()
