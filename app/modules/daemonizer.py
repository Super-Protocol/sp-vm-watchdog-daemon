import subprocess
import logging
import signal
import time
import os
from dataclasses import dataclass
from pathlib import Path

import psutil

from .qemu import Qemu

__logger__ = logging.getLogger(__name__)


@dataclass(slots=True)
class Daemonizer:
    vm: Qemu
    pid_file: Path
    log_file: Path | None = None

    def get_pid_from_file(self) -> int | None:
        if self.pid_file.is_file() == False:
            __logger__.info(f"failed to get process pid from file `{self.pid_file}`, not found")
            return None
        try:
            pid_str = self.pid_file.read_text()
            return int(pid_str)
        except Exception as e:
            __logger__.info(f"failed to get process pid from file `{self.pid_file}`, reason {e}")
            return None

    def get_process_from_pid(self, pid: int) -> psutil.Process | None:
        try:
            return psutil.Process(pid=pid)
        except psutil.NoSuchProcess:
            __logger__.info(f"failed to get process from pid: `{pid}`, not found")
            return None

    def is_process_running(self, process: psutil.Process | None) -> (bool, str):
        allowed_statuses = (
            psutil.STATUS_RUNNING,
            psutil.STATUS_SLEEPING,
            psutil.STATUS_DISK_SLEEP,
            psutil.STATUS_WAKING,
            psutil.STATUS_PARKED,
            psutil.STATUS_IDLE,
        )

        if process is not None:
            state = process.status()
            return (state in allowed_statuses, state)

        return (False, None)

    def remove_pid_file(self) -> None:
        try:
            assert self.pid_file.is_file() == True
            self.pid_file.unlink()
        except Exception as e:
            __logger__.warning(f"failed to remove pid file `{self.pid_file}`, reason {e}")

    def write_pid_file(self, pid: int) -> None:
        try:
            self.pid_file.write_text(str(pid))
            __logger__.info(f"pid: `{pid}` written to pid file `{self.pid_file}`")
        except Exception as e:
            __logger__.warning(f"failed to write pid: `{pid}` to pid file `{self.pid_file}`, reason {e}")

    def get_process_cmdline(self) -> list[str]:
        pid = self.get_pid_from_file()
        if pid is not None:
            process = self.get_process_from_pid(pid)
            if process is not None:
                return process.cmdline()
        return []

    def remove_stopped_process(self, process: psutil.Process) -> None:
        try:
            process.kill()
        except Exception as e:
            __logger__.warning(f"failed to remove process, pid: `{p.pid}`, reason {e}")

    def start(self) -> None:
        pid = self.get_pid_from_file()
        if pid is not None:
            process = self.get_process_from_pid(pid)
            if process is not None:
                running_state, state = self.is_process_running(process)
                if running_state:
                    __logger__.info(f"attempting to start process wich already started, pid: `{pid}`, state: `{state}`")
                    return
                __logger__.warning(f"found procrss: `{pid}` in a wrong state: `{state}`, removing")
                self.remove_stopped_process(process)
            self.remove_pid_file()

        kwargs: dict = dict(
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            close_fds=True,
            start_new_session=True,
        )
        log_f = None

        if self.log_file:
            self.log_file.touch()
            log_f = open(self.log_file, "ab", buffering=0)
            kwargs["stdout"] = log_f
            kwargs["stderr"] = log_f

        p = subprocess.Popen(self.get_process_cmdline(), **kwargs)
        # self.assert_process_started(p)
        self.write_pid_file(p.pid)

        if log_f:
            log_f.close()  # the decriptors will alive in a child process

    def graceful_shutdown(self, pid: int, timeout: int = 120) -> bool:
        __logger__.info(f"sending sigterm to process with pid: `{pid}`")

        process = self.get_process_from_pid(pid)
        if process is None:
            __logger__.error(f"attempting to shutdown process with pid `{pid}` but it isn't found")
            return False

        try:
            os.killpg(pid, signal.SIGTERM)
        except Exception as e:
            __logger__.error(f"graceful shutdown of process with pid: `{pid}` failed with exception: {e}")
            return False

        __logger__.info(f"awaiting graceful shutdown of process with pid: `{pid}`, timeout: `{timeout}`")
        gone, alive = psutil.wait_procs([process], timeout=timeout)
        if alive:
            __logger__.warning(
                f"timeout: `{timeout}` is exeeded while awaiting graceful shutdown of process with pid: `{pid}`"
            )
        else:
            __logger__.info(f"graceful shutdown success for process with pid: `{pid}`")
        return not alive

    def kill(self, pid: int) -> bool:
        __logger__.info(f"sending sigkill to process with pid: `{pid}`")

        process = self.get_process_from_pid(pid)
        if process is None:
            __logger__.error(f"attempting to kill process with pid `{pid}` but it isn't found")
            return False

        try:
            os.killpg(pid, signal.SIGKILL)
        except Exception as e:
            __logger__.error(f"kill of process with pid: `{pid}` failed with exception: {e}")
            return False

        __logger__.info(f"kill success for process with pid: `{pid}`")
        return True

    def stop(self) -> None:
        pid = self.get_pid_from_file()
        if pid is None:
            __logger__.error(f"attempting to stop process but can't get pid from file: `{self.pid_file}`")
            return

        graceful_terminated = self.graceful_shutdown(pid)
        if not graceful_terminated:
            self.kill(pid)

        self.remove_pid_file()

    def is_running(self) -> bool:
        pid = self.get_pid_from_file()
        if pid is None:
            return False

        process = self.get_process_from_pid(pid)
        if process is None:
            return False

        running_state, _ = self.is_process_running(process)
        return running_state

    def is_healthy(self) -> bool:
        return False


if __name__ == "__main__":
    __logger__.getLogger().setLevel(__logger__.INFO)
    d = Daemonizer(["/tmp/test"], Path("/tmp/test.pid"), Path("/tmp/test.log"))
    d2 = Daemonizer(["/tmp/test"], Path("/tmp/test2.pid"), Path("/tmp/test.log"))
    # d.start()
    # d2.start()
    print(d.get_process_cmdline())
    time.sleep(1)
    d.stop()
    d2.stop()
