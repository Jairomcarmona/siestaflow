# QRAFT CLI reference

<!-- Generated from `src/qraft/cli.py`; do not edit manually. -->

The core workflow is `init`, `check`, `run`, `status`, `results`, and `examples`. Use `qraft --help` for task-oriented discovery.

## Core commands

### `qraft init`

Create an editable campaign file

**Usage:**

`qraft init [PATH] [--force] [--json]`

**Example:**

`qraft init --help`

### `qraft check`

Check whether a target is ready to run

**Usage:**

`qraft check TARGET [execution options] [--json]`

**Example:**

`qraft check --help`

### `qraft run`

Run a checked campaign or calculation

**Usage:**

`qraft run TARGET [execution options] [--json]`

**Example:**

`qraft run --help`

### `qraft status`

Show progress and the next available action

**Usage:**

`qraft status [TARGET] [--runs-root PATH] [--json]`

**Example:**

`qraft status --help`

### `qraft resume`

Continue using saved recovery state

**Usage:**

`qraft resume [FDF] [execution options] [--json]`

**Example:**

`qraft resume --help`

### `qraft results`

Inventory recorded outputs and route supported exports

**Usage:**

`qraft results [TARGET] | qraft results export TYPE ...`

**Example:**

`qraft results --help`

### `qraft examples`

Show fixture-backed learning topics

**Usage:**

`qraft examples [TOPIC] [--json]`

**Example:**

`qraft examples --help`

## Setup and inspection

### `qraft setup`

configure execution environments and profiles

**Example:**

`qraft setup --help`

### `qraft setup env`

inspect installed execution capabilities

**Usage:**

`qraft setup env [execution options] [--json]`

**Example:**

`qraft setup env --help`

**Compatibility aliases:** `qraft env`

### `qraft setup config`

show effective execution configuration

**Usage:**

`qraft setup config [execution options] [--json]`

**Example:**

`qraft setup config --help`

**Compatibility aliases:** `qraft config`

### `qraft setup profile`

list, show or validate execution profiles

**Usage:**

`qraft setup profile {list,show,validate} ...`

**Example:**

`qraft setup profile --help`

**Compatibility aliases:** `qraft profile`

### `qraft inspect`

inspect inputs, rules, pseudopotentials, and plans

**Example:**

`qraft inspect --help`

**Compatibility aliases:** `qraft input`

### `qraft inspect fdf`

inspect a parsed SIESTA FDF

**Usage:**

`qraft inspect fdf PATH [--json]`

**Example:**

`qraft inspect fdf --help`

**Compatibility aliases:** `qraft fdf`, `qraft fdf inspect`

### `qraft inspect input`

validate a SIESTA input

**Usage:**

`qraft inspect input PATH [--json]`

**Example:**

`qraft inspect input --help`

**Compatibility aliases:** `qraft input validate`

### `qraft inspect rules`

list versioned SIESTA validation rules

**Usage:**

`qraft inspect rules [--json]`

**Example:**

`qraft inspect rules --help`

**Compatibility aliases:** `qraft input rules`

### `qraft inspect pseudo`

verify a pseudopotential manifest

**Usage:**

`qraft inspect pseudo MANIFEST [--json]`

**Example:**

`qraft inspect pseudo --help`

**Compatibility aliases:** `qraft pseudo`, `qraft pseudo verify`

### `qraft inspect plan`

resolve a non-submitting execution plan

**Usage:**

`qraft inspect plan TARGET [execution options] [--json]`

**Example:**

`qraft inspect plan --help`

**Compatibility aliases:** `qraft plan`

## Advanced commands

### `qraft advanced`

discover architecture-facing workflows

**Example:**

`qraft advanced --help`

### `qraft advanced project`

prepare and inspect reproducible project packages

**Example:**

`qraft advanced project --help`

**Compatibility aliases:** `qraft project`

### `qraft advanced campaign`

manage allocation-controller campaigns

**Example:**

`qraft advanced campaign --help`

**Compatibility aliases:** `qraft campaign`

### `qraft advanced campaign render`

materialize CampaignSpec FDF variants without execution

**Example:**

`qraft advanced campaign render --help`

**Compatibility aliases:** `qraft render`

### `qraft advanced workflow`

author, validate and compile workflow definitions

**Example:**

`qraft advanced workflow --help`

**Compatibility aliases:** `qraft workflow`

### `qraft advanced scientific`

record reviewed scientific decisions and profiles

**Example:**

`qraft advanced scientific --help`

**Compatibility aliases:** `qraft scientific`

### `qraft advanced execution`

manage hash-bound execution packages

**Example:**

`qraft advanced execution --help`

### `qraft advanced execution prepare`

prepare a self-contained Slurm package

**Example:**

`qraft advanced execution prepare --help`

**Compatibility aliases:** `qraft run prepare`

### `qraft advanced execution candidates`

rank saved scheduler candidates

**Example:**

`qraft advanced execution candidates --help`

**Compatibility aliases:** `qraft run candidates`

### `qraft advanced execution discover`

capture live scheduler capabilities

**Example:**

`qraft advanced execution discover --help`

**Compatibility aliases:** `qraft run discover`

### `qraft advanced execution resources`

show live scheduler resources

**Example:**

`qraft advanced execution resources --help`

**Compatibility aliases:** `qraft run resources`

### `qraft advanced execution placement`

derive explicit live scheduler placement

**Example:**

`qraft advanced execution placement --help`

**Compatibility aliases:** `qraft run placement`

### `qraft advanced execution snapshot-import`

import saved scheduler command output

**Example:**

`qraft advanced execution snapshot-import --help`

**Compatibility aliases:** `qraft run snapshot-import`

### `qraft advanced execution inspect`

inspect a prepared package

**Example:**

`qraft advanced execution inspect --help`

**Compatibility aliases:** `qraft run inspect`

### `qraft advanced execution status`

show prepared-package status

**Example:**

`qraft advanced execution status --help`

**Compatibility aliases:** `qraft run status`

### `qraft advanced execution resume`

produce a prepared-package resume plan

**Example:**

`qraft advanced execution resume --help`

**Compatibility aliases:** `qraft run resume`

### `qraft advanced example`

manage curated example assets

**Example:**

`qraft advanced example --help`

### `qraft advanced example inspect`

inspect an installed example

**Example:**

`qraft advanced example inspect --help`

**Compatibility aliases:** `qraft examples inspect`

### `qraft advanced example validate`

validate an installed example

**Example:**

`qraft advanced example validate --help`

**Compatibility aliases:** `qraft examples validate`

### `qraft advanced example stage`

stage example pseudopotentials

**Example:**

`qraft advanced example stage --help`

**Compatibility aliases:** `qraft examples stage`

### `qraft advanced example package`

package an installed example

**Example:**

`qraft advanced example package --help`

**Compatibility aliases:** `qraft examples package`

### `qraft advanced example simulate`

simulate an installed example

**Example:**

`qraft advanced example simulate --help`

**Compatibility aliases:** `qraft examples run`

### `qraft advanced example import-results`

import an example results bundle

**Example:**

`qraft advanced example import-results --help`

**Compatibility aliases:** `qraft examples results import`

### `qraft advanced remote`

create or inspect non-submitting remote artifacts

**Example:**

`qraft advanced remote --help`

**Compatibility aliases:** `qraft remote`

## Compatibility

- `qraft validate` remains available; canonical replacement: `qraft check`.
- `qraft environment` remains available; canonical replacement: `qraft setup env`.
