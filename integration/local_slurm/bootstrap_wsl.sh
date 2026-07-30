#!/usr/bin/env bash
set -euo pipefail

MARKER="# Managed by the SIESTAFlow local Slurm sandbox."
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd -P)"
TEMPLATE="$ROOT/slurm.conf.in"
CONFIG=/etc/slurm/slurm.conf

if [[ "$(id -u)" -ne 0 ]]; then
    echo "BOOTSTRAP_REQUIRES_ROOT" >&2
    exit 2
fi
if ! grep -qi microsoft /proc/sys/kernel/osrelease; then
    echo "LOCAL_SLURM_REQUIRES_WSL2" >&2
    exit 2
fi
if [[ "$(ps -p 1 -o comm=)" != systemd ]]; then
    echo "LOCAL_SLURM_REQUIRES_SYSTEMD" >&2
    exit 2
fi
if [[ -e "$CONFIG" ]] && ! grep -qxF "$MARKER" "$CONFIG"; then
    echo "REFUSING_TO_REPLACE_UNMANAGED_SLURM_CONFIG:$CONFIG" >&2
    exit 2
fi

export DEBIAN_FRONTEND=noninteractive
apt-get update
apt-get install -y slurm-wlm munge openmpi-bin jq

node_record="$(slurmd -C | sed -n '1p')"
value() {
    local name="$1"
    sed -n "s/.*${name}=\([^ ]*\).*/\1/p" <<<"$node_record"
}

hostname_value="$(value NodeName)"
cpus="$(value CPUs)"
boards="$(value Boards)"
sockets_per_board="$(value SocketsPerBoard)"
cores_per_socket="$(value CoresPerSocket)"
threads_per_core="$(value ThreadsPerCore)"
detected_memory="$(value RealMemory)"
real_memory_mb="$((detected_memory * 9 / 10))"

for item in \
    "$hostname_value" "$cpus" "$boards" "$sockets_per_board" \
    "$cores_per_socket" "$threads_per_core" "$real_memory_mb"
do
    [[ -n "$item" ]] || {
        echo "SLURMD_HARDWARE_DETECTION_FAILED:$node_record" >&2
        exit 2
    }
done

install -d -o slurm -g slurm /var/lib/slurm/slurmctld /var/log/slurm
install -d -o root -g root /var/lib/slurm/slurmd
touch /var/log/slurm/jobcomp.log
chown slurm:slurm /var/log/slurm/jobcomp.log

temporary="$(mktemp)"
trap 'rm -f "$temporary"' EXIT
sed \
    -e "s/@HOSTNAME@/$hostname_value/g" \
    -e "s/@CPUS@/$cpus/g" \
    -e "s/@BOARDS@/$boards/g" \
    -e "s/@SOCKETS_PER_BOARD@/$sockets_per_board/g" \
    -e "s/@CORES_PER_SOCKET@/$cores_per_socket/g" \
    -e "s/@THREADS_PER_CORE@/$threads_per_core/g" \
    -e "s/@REAL_MEMORY_MB@/$real_memory_mb/g" \
    "$TEMPLATE" >"$temporary"
install -o root -g root -m 0644 "$temporary" "$CONFIG"

systemctl enable munge slurmctld slurmd
systemctl restart munge
systemctl restart slurmctld
systemctl restart slurmd

for _ in {1..20}; do
    if sinfo -h -p local -o '%T' 2>/dev/null | grep -Eq '^(idle|mix|alloc)$'; then
        sinfo -p local -N -l
        echo "LOCAL_SLURM_BOOTSTRAP_PASS"
        exit 0
    fi
    sleep 1
done

systemctl status slurmctld slurmd --no-pager -l >&2 || true
echo "LOCAL_SLURM_BOOTSTRAP_FAILED" >&2
exit 2
