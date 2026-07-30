[CmdletBinding()]
param(
    [string]$Distribution = "Ubuntu",
    [string]$SiestaExecutable = "",
    [string]$Account = ""
)

$ErrorActionPreference = "Stop"
$RepoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..\..")).Path
$EvidenceRoot = Join-Path $RepoRoot ".siestaflow-local-slurm"
$RunId = [DateTime]::UtcNow.ToString("yyyyMMddTHHmmssZ")
$BuildRoot = Join-Path $EvidenceRoot "controller-$RunId"

if (-not $Account) {
    $Account = (& wsl.exe -d $Distribution --exec id -un).Trim()
}
if (-not $SiestaExecutable) {
    $SiestaExecutable = (
        & wsl.exe -d $Distribution --exec bash -lc `
            'command -v siesta || find "$HOME/.local" -maxdepth 4 -type f -name siesta -executable 2>/dev/null | head -1'
    ).Trim()
}
if (-not $SiestaExecutable) {
    throw "SIESTA_EXECUTABLE_NOT_FOUND"
}

$previousPythonPath = $env:PYTHONPATH
try {
    $env:PYTHONPATH = Join-Path $RepoRoot "src"
    & python (Join-Path $RepoRoot "tools\build_local_slurm_controller_acceptance.py") `
        --output $BuildRoot `
        --siesta $SiestaExecutable `
        --account $Account
    if ($LASTEXITCODE -ne 0) {
        throw "LOCAL_CONTROLLER_BUILD_FAILED:$LASTEXITCODE"
    }
}
finally {
    $env:PYTHONPATH = $previousPythonPath
}

$PackageWindows = Join-Path $BuildRoot `
    "package\SIESTAFLOW_LOCAL_SLURM_CONTROLLER_ACCEPTANCE"
$PackageLinux = (
    & wsl.exe -d $Distribution --exec wslpath -a $PackageWindows
).Trim()

& wsl.exe -d $Distribution --cd $PackageLinux --exec env `
    PYTHONDONTWRITEBYTECODE=1 python3 verify_package.py
if ($LASTEXITCODE -ne 0) {
    throw "LOCAL_CONTROLLER_PACKAGE_VERIFICATION_FAILED:$LASTEXITCODE"
}

& wsl.exe -d $Distribution --cd $PackageLinux --exec `
    sbatch --test-only submit.slurm
if ($LASTEXITCODE -ne 0) {
    throw "LOCAL_CONTROLLER_SBATCH_TEST_FAILED:$LASTEXITCODE"
}

# Keeping this wsl.exe invocation open is intentional. WSL can otherwise stop
# the distribution while a service-owned Slurm job is still running.
& wsl.exe -d $Distribution --cd $PackageLinux --exec `
    sbatch --wait submit.slurm
$submissionExit = $LASTEXITCODE

& wsl.exe -d $Distribution --cd $PackageLinux --exec env `
    PYTHONDONTWRITEBYTECODE=1 ./progress.sh
if ($submissionExit -ne 0) {
    throw "LOCAL_CONTROLLER_ACCEPTANCE_FAILED:$submissionExit"
}

Write-Output "LOCAL_CONTROLLER_ACCEPTANCE_FINISHED"
Write-Output "PACKAGE=$PackageWindows"
