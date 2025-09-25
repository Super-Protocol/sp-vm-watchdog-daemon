from enum import Enum


class VmQemuConfigMode(str, Enum):
    AUTO = "auto"
    TDX = "tdx"
    SEV_SNP = "sev-snp"
    UNTRUSTED = "untrusted"

    @staticmethod
    def _get_cpu_flags() -> str:
        with open("/proc/cpuinfo") as f:
            for line in f:
                if line.startswith("flags"):
                    return line

    @staticmethod
    def _is_cpu_flag_set(cpu_flags_line: str, flag: str) -> bool:
        return flag.lower() in cpu_flags_line.lower().split()

    @classmethod
    def detect(cls) -> "VmQemuConfigMode":
        cpu_flags = cls._get_cpu_flags()

        if cls._is_cpu_flag_set(cpu_flags, "tdx"):
            return cls.TDX

        if cls._is_cpu_flag_set(cpu_flags, "sev_snp"):
            return cls.SEV_SNP

        return cls.UNTRUSTED


detected_cpu_type = VmQemuConfigMode.detect()
