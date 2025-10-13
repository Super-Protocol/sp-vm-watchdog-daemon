import logging
import time
from pathlib import Path

from .daemonizer import Daemonizer
from .config import AppConfig
from .qemu import Qemu


class VmManager:
    def __init__(self, config: AppConfig):
        self.logger = logging.getLogger(__name__)
        self.config = config
        self.run_dir = Path('/var/run/sp/watchdog/vms')
        self.run_dir.mkdir(exist_ok=True, parents=True)

        self.vms_from_config = [Qemu.load_from_config(vm) for vm in self.config.vm_configs]
        self.vms = self.constuct_vms_from_qemu()

    def constuct_vms_from_qemu(self) -> list[Daemonizer]:
        vms = []
        for vm in self.vms_from_config:
            vm_name = vm.config.name
            self.logger.info(f'processing vm: `{vm_name}`')
            pidfile = self.run_dir / Path(f"{vm_name}.pid")
            logfile = self.run_dir / Path(f"{vm_name}.log")
            vms.append(Daemonizer(vm, pidfile, logfile))
        return sorted(vms, key=lambda d: d.vm.config.name)

    def start_vm(self, d: Daemonizer) -> None:
        self.logger.info(f'starting vm: `{d.vm.config.name}`')
        # ensure state disk
        # ensure provider config
        # ensure GPU
        pass

    def stop_vm(self, d: Daemonizer) -> None:
        self.logger.info(f'stopping vm: `{d.vm.config.name}`')
        # graceful until timeout
        # kill if timeout
        # remove state disk
        # remove provider config
        pass

    def restart_vm(self, d: Daemonizer) -> None:
        self.stop_vm(d)
        self.start_vm(d)

    def run(self):
        self.logger.info(f'started, found: `{len(self.vms)}` VMs')
        while True:
            for d in self.vms:
                self.logger.info(f'checking vm: `{d.vm.config.name}`')
                if not d.is_running():
                    self.logger.info(f"vm: `{d.vm.config.name}` isn't running, starting")
                    self.start_vm(d)
                # elif cmdline != vm.cmdline():
                #    self.logger.info(f"vm: `{d.vm_name}` parameters changed, restarting")
                #    self.restart_vm(d)
                elif not d.is_healthy():
                    self.logger.info(f"vm: `{d.vm.config.name}` isn't healthy, restarting")
                    self.restart_vm(d)
            time.sleep(1)
