from pydantic import BaseModel
import subprocess

class Device(BaseModel):
    name: str
    pci_path: str

class GpuManager:
    def __init__(self):
        pass

    def find_gpu_on_system(self) -> list[Device]:
        pass
