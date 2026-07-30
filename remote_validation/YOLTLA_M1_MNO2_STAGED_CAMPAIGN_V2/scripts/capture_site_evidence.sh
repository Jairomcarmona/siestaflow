#!/usr/bin/env bash
# Read-only evidence capture. It performs sbatch --test-only, never sbatch submission.
set -u
ROOT=$(cd "$(dirname "$0")/.." && pwd -P)
STAMP=$(date -u +%Y%m%dT%H%M%SZ)
DEST="$ROOT/site/evidence/$STAMP"
mkdir -p "$DEST"

capture() {
  name=$1
  shift
  {
    "$@"
    code=$?
    echo
    echo "capture_exit_code=$code"
  } >"$DEST/$name" 2>&1
}

date -u +%Y-%m-%dT%H:%M:%SZ >"$DEST/observed_at.txt"
capture hostname.txt hostname -f
capture user.txt id
capture sinfo.txt sinfo -N -l
capture scontrol_partition_qz2d-128p.txt scontrol show partition qz2d-128p
capture scontrol_nodes.txt scontrol show nodes
capture sacctmgr_assoc.txt sacctmgr -n -P show assoc user="$USER" format=Cluster,Account,User,Partition,QOS,DefaultQOS
capture sacctmgr_qos.txt sacctmgr -n -P show qos format=Name,Priority,MaxWall,MaxTRES,Flags
capture reservations.txt scontrol show reservation
capture unhealthy_nodes.txt sinfo -R
capture command_siesta.txt command -v siesta
capture siesta_version.txt siesta --version
capture command_srun.txt command -v srun
capture srun_version.txt srun --version
capture srun_help.txt srun --help
capture command_hydra.txt command -v mpiexec.hydra
capture hydra_version.txt mpiexec.hydra -version
capture hydra_help.txt mpiexec.hydra -help
capture command_sbatch.txt command -v sbatch

{
  echo '#!/usr/bin/env bash'
  echo '#SBATCH --partition=qz2d-128p'
  echo '#SBATCH --account=vini'
  echo '#SBATCH --qos=normal'
  echo '#SBATCH --nodes=2'
  echo '#SBATCH --ntasks=80'
  echo '#SBATCH --ntasks-per-node=40'
  echo '#SBATCH --cpus-per-task=1'
  echo '#SBATCH --time=2-00:00:00'
  echo '# --mem intentionally omitted: partition_default policy pending current evidence'
  echo '/bin/true'
} >"$DEST/exact_request.slurm"

capture sbatch_test_only.txt sbatch --test-only "$DEST/exact_request.slurm"

{
  echo "purge=true"
  echo "load=siesta/5.4.2"
  type module
  module purge
  module load siesta/5.4.2
  module list
} >"$DEST/module_list.txt" 2>&1
{
  type module
  module avail siesta
} >"$DEST/module_avail_siesta.txt" 2>&1

echo "$DEST"
echo SITE_EVIDENCE_CAPTURED_NO_JOB_SUBMITTED
