# M3B1R local OpenMPI build evidence

## Outcome

SIESTA 5.4.2 was built in WSL2 with OpenMPI and installed in a prefix separate
from the existing serial installation. No global `PATH` was changed. No source
file was modified by the build.

- Source: `/home/jmc/siesta-5.4.2`
- Build: `/home/jmc/build/siesta-5.4.2-openmpi`
- Install prefix: `/home/jmc/.local/siesta-5.4.2-openmpi`
- MPI executable: `/home/jmc/.local/siesta-5.4.2-openmpi/bin/siesta`
- MPI executable SHA-256: `aaa9a2e45a41b12f3aad52ca4fca7c25b1cc6afd3aff2a0c7fe145b1bd9f18ce`
- Serial executable: `/home/jmc/.local/siesta-5.4.2-serial/bin/siesta`
- Serial SHA-256 before and after: `e6e33807a931a6b63e89c39a796865fb963ba485fe4c311fcdc7f5d2abd1cc53`

The source root was confirmed by inspecting `CMakeLists.txt`; it was not assumed
from the directory name.

## Environment and dependencies

Observed on 2026-07-22 UTC:

- WSL2 kernel: `6.6.114.1-microsoft-standard-WSL2`
- Logical CPUs: 12
- WSL memory/swap: 7.4 GiB / 2.0 GiB
- CMake: 3.28.3
- GCC/GFortran: 13.3.0
- OpenMPI: 4.1.6
- `mpicc`: `/usr/bin/mpicc`
- `mpifort`: `/usr/bin/mpifort`

Installed packages and versions relevant to this build:

| Package | Version |
|---|---|
| `openmpi-bin` | `4.1.6-7ubuntu2` |
| `libopenmpi-dev` | `4.1.6-7ubuntu2` |
| `libscalapack-openmpi-dev` | `2.2.1-3.1ubuntu1` |
| `libblas-dev` / `liblapack-dev` | `3.12.0-3build1.1` |
| `libreadline-dev` | `8.2-4build1` |
| `gcc`, `g++`, `gfortran` | Ubuntu metapackage `4:13.2.0-7ubuntu1`; compiler 13.3.0 |
| `cmake` | `3.28.3-1build7` |
| `make` / `ninja-build` | `4.3-4.1build2` / `1.11.1-2` |
| `pkg-config` | `1.8.1-2build1` |
| `python3-ruamel.yaml` | `0.17.21-1` (upstream test verifier) |

ScaLAPACK and Readline were added only after CMake reported those real missing
dependencies. Failed configuration attempts remain recorded; no undocumented
compiler option was introduced.

## Configuration, build and installation

Final CMake configuration:

```bash
cmake -S /home/jmc/siesta-5.4.2 \
  -B /home/jmc/build/siesta-5.4.2-openmpi \
  -DCMAKE_INSTALL_PREFIX=/home/jmc/.local/siesta-5.4.2-openmpi \
  -DCMAKE_Fortran_COMPILER=/usr/bin/mpifort \
  -DCMAKE_C_COMPILER=/usr/bin/mpicc \
  -DCMAKE_CXX_COMPILER=/usr/bin/mpicxx \
  -DSIESTA_WITH_MPI=ON \
  -DCMAKE_BUILD_TYPE=Release
cmake --build /home/jmc/build/siesta-5.4.2-openmpi --parallel 12
cmake --install /home/jmc/build/siesta-5.4.2-openmpi
```

Configuration completed, the build reached 100% in 128.8 s, and installation
returned 0. The cache records `SIESTA_WITH_MPI=ON`, the expected three compiler
wrappers, and the intended install prefix.

## Binary validation

`siesta --version` reports:

```text
Version         : 5.4.2
Compiler version: GNU-13.3.0
Parallelisations: MPI
Lua support
ELSI support. Solvers: ELPA (internal), NTPoly, OMM
DFT-D3 support
```

`file` identifies a dynamically linked x86-64 ELF executable. `ldd` resolves,
among others:

- `libmpi_usempif08.so.40`
- `libmpi_mpifh.so.40`
- `libmpi.so.40`
- `libopen-rte.so.40`
- `libopen-pal.so.40`
- `libscalapack-openmpi.so.2.2`

This is direct evidence that the installed executable is the MPI variant.

## Native project tests and logs

The complete native CTest inventory was executed: 715/730 passed. Fifteen
upstream cases remained non-passing; they are itemized in
`M3B1R_LOCAL_MPI_LIMITATIONS.md` and were not hidden by changing SIESTA source,
reference data, or tolerances. The real target smoke and all SIESTAFLOW
regressions pass independently.

Complete logs remain in the WSL build tree:

| Log | SHA-256 |
|---|---|
| `configure.log` | `18402e44e77d7cf029b53fd1b7c57c8296621381b47441ae34588ebcd9cb8092` |
| `build.log` | `10e8e80ba4db7bc6477725ea9a5fdccfe6a1c71e75a6c2c4f4a838124037806` |
| `ctest.log` | `82d15bdc674deb2b36b7c6779c898cb21534a41782f1b44636f139d7258c9c69` |
| `install.log` | `79d7f15b12643217c6193b48dc0c5be01db03d0f6d56b6780b98bd5bea9ad822` |
| `binary_validation.log` | `6fd9f3f2c22be6678e47eb062bf674d5b7739418f921e1976aea2538858b052f` |

Additional partial logs preserve the sequential attempt, the intentionally
stopped parallel-3 attempt that reached WSL OOM, and the pre-dependency run.

