# olcaBASIC

```
            ___  _     ____    _    ____    _    ____  _  ____
           / _ \| |   / ___|  / \  | __ )  / \  / ___|| |/ ___|
          | | | | |  | |     / _ \ |  _ \ / _ \ \___ \| | |
          | |_| | |__| |___ / ___ \| |_) / ___ \ ___) | | |___
           \___/|_____\____/_/   \_\____/_/   \_\____/|_|\____|
```

**A simplified language to control openLCA, borrowing heavily
from the BASIC programming language (1964)**

olcaBASIC lets LCA practitioners build models, run calculations, and
analyse results without writing Python. It connects to openLCA via the
IPC server and translates simple, readable commands into the full power
of the openLCA calculation engine.

## Quick start

```
pip install olcabasic
```

Start the IPC server in openLCA (Tools > Developer Tools > IPC Server),
then:

```
python -m olcabasic
```

```
olcaBASIC v0.1.5
Connected to openLCA on port 8080
Ready.

> PRINT DATABASE
  Processes:       2608
  Flows:           177294
  Impact methods:  8
  Family:          flcac

> FIND PROCESS "cement"
  Portland cement; at plant    31-33: Manufacturing/3273: Cement and Co

> CALCULATE "Ready-mix concrete" USING "IPCC"
  AR6-100    1.769261 kg CO2 eq
```

## Write programs

Save as `mymodel.baslca` and run with `python -m olcabasic run mymodel.baslca`:

```basic
REM Concrete block model

LET cement_mass = 300
LET sand_mass = 800

SET PROCESS FOLDER "00: My Project"
SET FLOW FOLDER "00: My Project/Flows"

PROCESS "Concrete block; at plant"
  OUTPUT NEW "Concrete block", 1, m3, PRODUCT
  INPUT "Portland cement; at plant", cement_mass, kg
  INPUT "Construction sand and gravel; at mine", sand_mass, kg
END PROCESS

SYSTEM "Concrete block; at plant"
CALCULATE "Concrete block; at plant" USING "IPCC"
PRINT RESULTS
SAVE RESULTS "concrete_results.csv"

SCENARIO "Baseline"
END SCENARIO

SCENARIO "Low cement"
  LET cement_mass = 240
END SCENARIO

RUN SCENARIOS ON "Concrete block; at plant" USING "IPCC"
```

## How INPUT and OUTPUT work

By default, `INPUT` finds existing flows and processes in the database
and wires them up as providers automatically. This is what connects your
foreground model to the background supply chain.

`OUTPUT NEW` creates a new foreground product flow. `INPUT NEW` creates
a fresh flow without linking to a provider.

```basic
OUTPUT NEW "My product", 1, kg, PRODUCT    ' creates your product
INPUT "Portland cement; at plant", 300, kg  ' finds and links to database
INPUT NEW "Custom blend", 50, kg            ' creates a new flow
```

## Navigation

olcaBASIC includes folder navigation inspired by the Acorn Electron:

```
CAT                         List current folder contents
CAT *concrete*              Filter by wildcard
DIR "31-33: Manufacturing"  Navigate to folder
UP                          Go up one level
BACK                        Toggle to previous folder
CDIR "My Model"             Create and enter a folder
PWD                         Show current folders
```

`LS` works as an alias for `CAT`. `CD` works as an alias for `DIR`.

## Parameters

Variables defined with `LET` become openLCA parameters. Use them in
exchange amounts and they flow through to scenarios and sensitivity
analysis:

```basic
LET cement_mass = 300
LET water_ratio = 0.45
LET water_mass = cement_mass * water_ratio

PROCESS "Mixing"
  INPUT "Portland cement; at plant", cement_mass, kg
  INPUT "Water", water_mass, kg
  OUTPUT NEW "Concrete", 1, m3, PRODUCT
END PROCESS
```

## Scenarios

```basic
SCENARIO "Baseline"
END SCENARIO

SCENARIO "Low cement"
  LET cement_mass = 240
END SCENARIO

SCENARIO "High cement"
  LET cement_mass = 380
END SCENARIO

RUN SCENARIOS ON "My System" USING "IPCC"
```

## Sensitivity

```basic
SENSITIVITY ON "My System" USING "IPCC" BY 20%
  VARY cement_mass
  VARY sand_mass
END SENSITIVITY
```

## Full command reference

Type `HELP` in the REPL for the command list, or `HELP PROCESS`,
`HELP FOLDER`, `HELP NEW`, `HELP SCENARIO`, `HELP SENSITIVITY` for
detailed guidance on each topic.

## Why?

Whilst openLCA has a wonderful set of scripting options, you need to have a good idea about programming to avoid making mistakes
This is a quick way to control by command line, with the complex bits hidden.

There was probably no good reason for this, but we wanted to make it. 

## Requirements

- openLCA 2.x with IPC server running (port 8080)
- Python 3.10+
- `b280-olca-mcp` (installed automatically)

## Licence

MPL-2.0

## Links

- [B280 openLCA MCP](https://github.com/Below280/B280-olca-MCP)
- [B280 Python IPC tools](https://github.com/Below280/openLCA-IPC-tools-python)
- [Below280](https://below280.com)

*Built by Below280. openLCA is developed by GreenDelta.*
*BASIC was created by Kemeny and Kurtz at Dartmouth College, 1964.*
*Navigation commands inspired by the Acorn Electron (1983).*
