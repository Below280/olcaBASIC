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

olcaBASIC is a work in progress. It works, we use it, and we want to
know where it breaks. See [Help us improve it](#help-us-improve-it).

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
olcaBASIC v0.2.1
Connected to openLCA on port 8080
Database: 2586 processes, 8 methods
Family:   flcac (auto-detected)
Ready.

> FIND PROCESS "Portland cement"
  1 results (of 1 total)
  Name                       Category
  -------------------------  --------------------------------------------------------------------
  Portland cement; at plant  31-33: Manufacturing/3273: Cement and Concrete Product Manufacturing
```

If openLCA isn't running, olcaBASIC starts in offline mode and tells
you how to start the IPC server.

## Write programs

Save as `mymodel.baslca` and run with `python -m olcabasic run mymodel.baslca`:

```basic
REM Concrete block model

LET cement_mass = 300
LET aggregate_ratio = 2.667
LET sand_mass = cement_mass * aggregate_ratio

SET PROCESS FOLDER "00: My Project"
SET FLOW FOLDER "00: My Project/Flows"

PROCESS "Concrete block; at plant"
  OUTPUT NEW "Concrete block", 1, m3, PRODUCT
  INPUT "Portland cement; at plant", cement_mass, kg
  INPUT "Construction sand and gravel; at mine", sand_mass, kg
END PROCESS

SYSTEM "Concrete block; at plant"
CALCULATE "Concrete block; at plant" USING "IPCC"
SAVE RESULTS "concrete_results.csv"

SCENARIO "Baseline"
END SCENARIO

SCENARIO "Low cement"
  LET cement_mass = 240
END SCENARIO

RUN SCENARIOS ON "Concrete block; at plant" USING "IPCC"
```

In the 'Low cement' scenario the sand follows the cement, because
`sand_mass` is defined from `cement_mass`. See [Parameters](#parameters).

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

A name that matches nothing stops the program with an error, so a typo
can't quietly drop an input from your model. Use `INPUT NEW` when you
really do want a new flow.

### Choosing between processes with the same name

Some databases have several processes with the same name, one per
location. olcaBASIC warns when a name matches more than one, and
`LOCATION` picks the one you want:

```basic
INPUT "market for cement, Portland", 300, kg LOCATION "RoW"
```

If the code doesn't match, the error lists the locations that exist.
`PROVIDER` takes a process UUID when you need to name one exactly.

### Elementary flows

Emissions and resources use a compartment (flow names vary between
databases, so check yours):

```basic
OUTPUT "Carbon dioxide", 5, kg TO AIR
OUTPUT "Ammonia", 0.2, kg TO WATER
OUTPUT "Zinc", 0.01, kg TO SOIL
INPUT "Water, fresh", 1, m3 FROM NATURE
```

olcaBASIC searches only that compartment, and understands both
ecoinvent-style categories ('Emission to air') and FLCAC categories
('emission/air', with 'ground' for soil). When a flow exists in several
sub-compartments it uses 'unspecified', or the compartment itself where
there's no 'unspecified', and tells you which. `FIND FLOW "Carbon dioxide"`
shows the names and categories in your database.

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
analysis.

A `LET` at the top of a program becomes a global parameter, shared by
every process that uses it, so one scenario change applies to the whole
model. A `LET` defined from other variables becomes a formula parameter,
which openLCA recalculates whenever its inputs change:

```basic
LET cement_mass = 300
LET aggregate_ratio = 2.667
LET sand_mass = cement_mass * aggregate_ratio   ' follows cement_mass
```

A `LET` inside a `PROCESS` block is local to that process, and takes
priority over a global of the same name.

Global parameters belong to the whole database. If another model already
has a global with the same name, olcaBASIC updates it and prints a note
with the old value.

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

Scenarios set input parameters. Setting a derived one such as
`sand_mass` gives an error naming the inputs to change instead.

## Sensitivity

One parameter at a time, each moved up and down by the given
percentage while everything else stays at baseline:

```basic
SENSITIVITY ON "My System" USING "IPCC" BY 20%
  VARY cement_mass, aggregate_ratio
END SENSITIVITY
```

`MONTECARLO "My System" USING "IPCC" RUNS 1000` runs an uncertainty
analysis, and `CONTRIBUTION` and `INVENTORY` break results down by
process and by flow.

## Programming

The usual BASIC structures work:

```basic
FOR i = 1 TO 3
  PRINT "Run", i
NEXT i

FOR EACH mass IN 200, 300, 400
  IF mass > 250 THEN PRINT mass, "high" ELSE PRINT mass, "low"
NEXT mass
```

`WHILE`/`WEND`, `SUB`, `FUNCTION`, `DATA`/`READ` and `INCLUDE` are
there too. `GOTO` and line numbers aren't; olcaBASIC says so if you
try them.

## Rebuilding a model

Re-running a program leaves existing processes and systems as they are,
with a warning. To rebuild, delete them first, systems before the
processes they use:

```basic
CONFIRM DELETE ON
DELETE SYSTEM "Concrete block; at plant"
DELETE PROCESS "Concrete block; at plant"
```

`CONFIRM DELETE ON` skips the yes/no prompt, which is handy at the top
of a program.

## Full command reference

Type `HELP` in the REPL for the command list, or `HELP PROCESS`,
`HELP FOLDER`, `HELP NEW`, `HELP SCENARIO`, `HELP SENSITIVITY` for
detailed guidance on each topic.

## Help us improve it

This is version 0.2. The known rough edges:

- `DIR`, `UP` and `BACK` move the folder new processes are built in, so
  browsing the database and then writing a `PROCESS` builds it where you
  browsed to. `SET PROCESS FOLDER` before building puts it back.
- `EDIT PROCESS` isn't implemented yet. Delete and rebuild instead.
- `DELETE` removes processes, flows and systems, but global parameters
  stay in the database.
- Functions in exchange amounts (`SQR`, `MIN` and so on) are passed to
  openLCA as written, and openLCA's formula functions have their own
  names.
- Errors inside a `PROCESS` block report the line the block starts on.
- `LOCATION` has been tested against FLCAC, which has few duplicate
  names. We'd like to hear how it behaves on ecoinvent.

Try it on your own models and databases. When it breaks, or when you
want something it doesn't do, open an issue at
[github.com/Below280/olcaBASIC/issues](https://github.com/Below280/olcaBASIC/issues)
with the program you ran and what it printed.

## Why?

openLCA has a wonderful set of scripting options, but you need a good
grasp of programming to use them without making mistakes. olcaBASIC
lets you drive openLCA from the command line in plain, readable
commands, with the fiddly parts handled for you.

There was probably no good reason for this, but we wanted to make it.

## Requirements

- openLCA 2.x with IPC server running (port 8080)
- Python 3.10+
- `b280-olca-mcp` 1.15.0 or later (installed automatically)

## Licence

MPL-2.0

## Links

- [B280 openLCA MCP](https://github.com/Below280/B280-olca-MCP)
- [B280 Python IPC tools](https://github.com/Below280/openLCA-IPC-tools-python)
- [Below280](https://below280.com)

*Built by Below280. openLCA is developed by GreenDelta.*
*BASIC was created by Kemeny and Kurtz at Dartmouth College, 1964.*
*Navigation commands inspired by the Acorn Electron (1983).*
