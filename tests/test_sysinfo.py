"""CPU detection inside containers (cgroup limits), tested with fake files."""
import os

from app.sysinfo import cgroup_cpu_limit, effective_cpus

MISSING = "/definitely/not/here"


def files(tmp_path, v2=None, quota=None, period=None):
    def write(name, text):
        if text is None:
            return str(tmp_path / ("missing-" + name))
        p = tmp_path / name
        p.write_text(text)
        return str(p)
    return dict(v2_file=write("cpu.max", v2), v1_quota_file=write("quota", quota), v1_period_file=write("period", period))


def test_cgroup_v2_quota(tmp_path):
    assert cgroup_cpu_limit(**files(tmp_path, v2="200000 100000\n")) == 2.0
    assert cgroup_cpu_limit(**files(tmp_path, v2="50000 100000")) == 0.5


def test_cgroup_v2_unlimited(tmp_path):
    assert cgroup_cpu_limit(**files(tmp_path, v2="max 100000")) is None


def test_cgroup_v1_quota(tmp_path):
    assert cgroup_cpu_limit(**files(tmp_path, quota="400000", period="100000")) == 4.0
    assert cgroup_cpu_limit(**files(tmp_path, quota="-1", period="100000")) is None


def test_no_cgroup_files(tmp_path):
    assert cgroup_cpu_limit(**files(tmp_path)) is None


def test_effective_cpus_respects_the_container_limit(tmp_path):
    host = os.cpu_count() or 1
    assert effective_cpus(**files(tmp_path, v2="100000 100000")) == 1                   # a 1-CPU container
    assert effective_cpus(**files(tmp_path, v2="max 100000")) <= host                   # unlimited: the host's cores
    assert effective_cpus(**files(tmp_path, v2="25000 100000")) == 1                    # never below 1
    assert effective_cpus(**files(tmp_path, v2="9900000 100000")) <= host               # never above what the host has


def test_small_hosts_get_safer_defaults():
    from app.sysinfo import default_limits
    assert default_limits(1) == ("deep", 6) and default_limits(2) == ("deep", 6)       # a free 2-CPU Space
    assert default_limits(8) == ("max", 20) and default_limits(4) == ("max", 20)
