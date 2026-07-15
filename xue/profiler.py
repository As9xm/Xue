import ctypes
import os
import platform
import sys

from xue.ansi import C

try:
    import psutil
    HAS_PSUTIL = True
except ImportError:
    HAS_PSUTIL = False


class SystemProfiler:
    def __init__(self):
        self.cpu_cores = os.cpu_count() or 2
        self.cpu_threads = self.cpu_cores
        self.total_ram_mb = 0
        self.available_ram_mb = 0
        self.cpu_usage_pct = 0.0
        self.os_name = platform.system()
        self.os_version = platform.version()
        self.python_version = platform.python_version()
        self._detect_specs()

    def _detect_specs(self):
        if HAS_PSUTIL:
            mem = psutil.virtual_memory()
            self.total_ram_mb = mem.total // (1024 * 1024)
            self.available_ram_mb = mem.available // (1024 * 1024)
            self.cpu_usage_pct = psutil.cpu_percent(interval=0.5)
            self.cpu_threads = psutil.cpu_count(logical=True) or self.cpu_cores
            self.cpu_cores = psutil.cpu_count(logical=False) or self.cpu_cores
        else:
            try:
                if sys.platform == "win32":
                    class MEMORYSTATUSEX(ctypes.Structure):
                        _fields_ = [
                            ("dwLength", ctypes.c_ulong),
                            ("dwMemoryLoad", ctypes.c_ulong),
                            ("ullTotalPhys", ctypes.c_ulonglong),
                            ("ullAvailPhys", ctypes.c_ulonglong),
                            ("ullTotalPageFile", ctypes.c_ulonglong),
                            ("ullAvailPageFile", ctypes.c_ulonglong),
                            ("ullTotalVirtual", ctypes.c_ulonglong),
                            ("ullAvailVirtual", ctypes.c_ulonglong),
                            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
                        ]
                    stat = MEMORYSTATUSEX()
                    stat.dwLength = ctypes.sizeof(stat)
                    ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat))
                    self.total_ram_mb = stat.ullTotalPhys // (1024 * 1024)
                    self.available_ram_mb = stat.ullAvailPhys // (1024 * 1024)
                elif sys.platform.startswith("linux"):
                    with open("/proc/meminfo") as f:
                        lines = f.readlines()
                    for line in lines:
                        if line.startswith("MemTotal:"):
                            self.total_ram_mb = int(line.split()[1]) // 1024
                        elif line.startswith("MemAvailable:"):
                            self.available_ram_mb = int(line.split()[1]) // 1024
            except Exception:
                self.total_ram_mb = 4096
                self.available_ram_mb = 2048

    def recommend_threads(self):
        base = self.cpu_threads * 2
        ram_available = self.available_ram_mb
        ram_budget = int(ram_available * 0.6)
        ram_threads = max(2, ram_budget // 15)
        if self.cpu_usage_pct > 80:
            cpu_factor = 0.3
        elif self.cpu_usage_pct > 50:
            cpu_factor = 0.6
        else:
            cpu_factor = 1.0
        recommended = int(min(base, ram_threads) * cpu_factor)
        recommended = max(2, min(recommended, 200))
        max_safe = min(ram_threads, self.cpu_threads * 8, 500)
        max_safe = max(recommended, max_safe)
        reasons = []
        if ram_threads < base:
            reasons.append(f"RAM-limited ({ram_available} MB available)")
        if cpu_factor < 1.0:
            reasons.append(f"CPU busy ({self.cpu_usage_pct:.0f}% usage)")
        if not reasons:
            reasons.append("balanced for your specs")
        return recommended, max_safe, ", ".join(reasons)

    def print_report(self):
        rec, max_safe, reason = self.recommend_threads()
        print(f"\n  {C.BOLD}System Profile{C.RST}")
        print(f"  ├─ OS:             {self.os_name} {self.os_version[:30]}")
        print(f"  ├─ Python:         {self.python_version}")
        print(f"  ├─ CPU cores:      {self.cpu_cores} physical / {self.cpu_threads} logical")
        if self.cpu_usage_pct > 0:
            cpu_color = C.GREEN if self.cpu_usage_pct < 50 else C.YELLOW if self.cpu_usage_pct < 80 else C.RED
            print(f"  ├─ CPU usage:      {cpu_color}{self.cpu_usage_pct:.0f}%{C.RST}")
        print(f"  ├─ RAM total:      {self.total_ram_mb:,} MB")
        avail_color = C.GREEN if self.available_ram_mb > 2048 else C.YELLOW if self.available_ram_mb > 512 else C.RED
        print(f"  ├─ RAM available:  {avail_color}{self.available_ram_mb:,} MB{C.RST}")
        if not HAS_PSUTIL:
            print(f"  ├─ {C.DIM}(install psutil for better detection){C.RST}")
        print(f"  ├─ Recommended:    {C.GREEN}{C.BOLD}{rec} threads{C.RST} ({reason})")
        print(f"  └─ Max safe:       {C.YELLOW}{max_safe} threads{C.RST}")
        return rec, max_safe
