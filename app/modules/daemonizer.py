import subprocess
import logging
from dataclasses import dataclass
from pathlib import Path

import psutil


@dataclass(slots=True)
class Daemonizer:
    cmd: list[str]
    pid_file: Path
    log_file: Path | None = None

    def get_pid_from_file(self) -> int | None:
        if self.pid_file.is_file() == False:
            logging.info(f"failed to get process pid from file `{self.pid_file}`, not found")
            return None
        try:
            pid_str = self.pid_file.read_text()
            return int(pid_str)
        except Exception as e:
            logging.info(f"failed to get process pid from file `{self.pid_file}`, reason {e}")
            return None

    def get_process_from_pid(self, pid: int) -> psutil.Process | None:
        try:
            return psutil.Process(pid=pid)
        except psutil.NoSuchProcess:
            logging.info(f"failed to get process from pid: `{pid}`, not found")
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
            logging.warning(f"failed to remove pid file `{self.pid_file}`, reason {e}")

    def write_pid_file(self, pid: int) -> None:
        try:
            self.pid_file.write_text(str(pid))
        except Exception as e:
            logging.warning(f"failed to write pid: `{pid}` to pid file `{self.pid_file}`, reason {e}")

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
            logging.warning(f"failed to remove process, pid: `{p.pid}`, reason {e}")

    def start(self) -> None:
        pid = self.get_pid_from_file()
        if pid is not None:
            process = self.get_process_from_pid(pid)
            if process is not None:
                running_state, state = self.is_process_running(process)
                if running_state:
                    logging.info(f"attempting to start process wich already started, pid: `{pid}`, state: `{state}`")
                    return
                logging.warning(f"found procrss: `{pid}` in a wrong state: `{state}`, removing")
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

        p = subprocess.Popen(self.cmd, **kwargs)
        # self.assert_process_started(p)
        self.write_pid_file(p.pid)

        if log_f:
            log_f.close()

    def stop(self) -> None:
        pass


if __name__ == "__main__":
    logging.getLogger().setLevel(logging.INFO)
    d = Daemonizer.new(["sleep", "10000000"], "/tmp/test.pid")
    d.start()
    print(d.get_process_cmdline())
    # print(d.get_process_cmdline())
