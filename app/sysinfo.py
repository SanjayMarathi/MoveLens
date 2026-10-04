"""Facts about the machine we run on."""
from __future__ import annotations

import os
from pathlib import Path
from typing import Optional


def _read(path: str) -> Optional[str]:
    try:
        return Path(path).read_text().strip()
    except OSError:
        return None


def cgroup_cpu_limit(v2_file: str = "/sys/fs/cgroup/cpu.max",
                     v1_quota_file: str = "/sys/fs/cgroup/cpu/cpu.cfs_quota_us",
                     v1_period_file: str = "/sys/fs/cgroup/cpu/cpu.cfs_period_us") -> Optional[float]:
    """CPU limit imposed on this container (e.g. 2.0 for "2 vCPU"), or None if there is none.

    Containers see every core of the host, so os.cpu_count() would say 64 on a free host that only gives you 2."""
    text = _read(v2_file)                                    # cgroup v2: "200000 100000" or "max 100000"
    if text:
        parts = text.split()
        if len(parts) >= 2 and parts[0] != "max":
            try:
                return int(parts[0]) / int(parts[1])
            except (ValueError, ZeroDivisionError):
                pass
        return None
    quota, period = _read(v1_quota_file), _read(v1_period_file)   # cgroup v1
    if quota and period:
        try:
            if int(quota) > 0:
                return int(quota) / int(period)
        except (ValueError, ZeroDivisionError):
            pass
    return None


def effective_cpus(**cgroup_files) -> int:
    """How many CPUs we can really use: the host's cores, narrowed by CPU pinning and by container limits."""
    cpus = os.cpu_count() or 1
    try:
        cpus = min(cpus, len(os.sched_getaffinity(0)))
    except AttributeError:                                   # not available on Windows / macOS
        pass
    limit = cgroup_cpu_limit(**cgroup_files)
    if limit is not None:
        cpus = min(cpus, max(1, round(limit)))
    return max(1, cpus)


def default_limits(cpus: int) -> tuple:
    """(highest analysis depth, longest waiting queue) that suit this host when nothing is configured.

    A small free host (2 CPUs) should not accept 10-minute "Maximum" reviews or a queue of twenty of them."""
    return ("deep", 6) if cpus <= 2 else ("max", 20)
