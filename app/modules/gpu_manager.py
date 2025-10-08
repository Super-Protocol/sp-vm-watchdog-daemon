import subprocess

from pydantic import BaseModel


class Device(BaseModel):
    name: str
    pci_path: str


class GpuManager:
    def __init__(self):
        self.vendor_id = "10de:"

    def find_gpu_on_system(self) -> list[Device]:
        ret = subprocess.run(
            ["lspci", "-nnk", "-d", self.vendor_id],
            capture_output=True
        )
        if ret.returncode != 0:
            stdout = ret.stdout.decode('utf-8')
            stderr = ret.stderr.decode('utf-8')
            msg = f'{stdout} {stderr}'
            raise Exception(f'failed to get devices from `lscpi`: `target_file`, reason: `{msg}`')

gpu_manager = GpuManager()
