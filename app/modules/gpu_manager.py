import subprocess
import re

from pydantic import BaseModel


class Device(BaseModel):
    name: str
    pci_path: str


class GpuManager:
    def __init__(self):
        self.vendor_id = "10de:"
        self.lspci_regex = re.compile(r'^(?P<pci_address>[a-f\d]+:[a-f\d]+:[a-f\d]+\.[0-7])\W(?P<device_type>.+)\W\[(?P<device_type_id>[a-f\d]+)\]:\W(?P<device_name>.+)\W\[(?P<vendor_id>[a-f\d]+):(?P<device_id>[a-f\d]+)\]')

    def find_gpu_on_system(self) -> list[Device]:
        ret = subprocess.run(
            ["lspci", "-nnk", "-d", self.vendor_id],
            capture_output=True
        )
        stdout = ret.stdout.decode('utf-8')

        if ret.returncode != 0:
            stderr = ret.stderr.decode('utf-8')
            msg = f'{stdout} {stderr}'
            raise Exception(f'failed to get devices from `lscpi`: `target_file`, reason: `{msg}`')

        devices = []

        lines = stdout.splitlines()
        for line in lines:
            match = self.lspci_regex.match(line)
            if not match:
                continue
            devices.append(Device(name=match.group('device_name'), pci_path=match.group('pci_address')))

        return devices
        

gpu_manager = GpuManager()
