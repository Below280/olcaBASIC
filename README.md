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
olcaBASIC v0.3.0
Connected to openLCA on port 8080
Database: 2586 processes, 8 methods
Family:   flcac (auto-detected)
Ready.

> FIND PROCESS "Portland cement"
  1 results (of 1 total)
  Name                       Category                                                              UUID
  -------------------------  --------------------------------------------------------------------  ------------------------------------
  Portland cement; at plant  31-33: Manufacturing/3273: Cement and Concrete Product Manufacturing  62993671-574c-3fc5-b66a-6be3bb21ad3d
```

If openLCA isn't running, olcaBASIC starts in offline mode and tells
you how to start the IPC server. Press Tab to complete commands and
names (on Windows, install `pip install olcabasic[completion]` first).

## Write programs

Save as `mymodel.baslca` and run with `python -m olcabasic run mymodel.baslca`:

```basic
REM Concrete block model

LET cement_mass = 300
LET aggregate_ratio = 2.667
LET sand_mass = cement_mass * aggregate_ratio

SET PROCESS FOLDER "00: My Project"
SET FLOW FOLDER "00: My Project/Flows"

MAKE PROCESS "Concrete block; at plant"
  OUTPUT MAKE FLOW "Concrete block", 1, m3, PRODUCT
  INPUT USE PROCESS "Portland cement; at plant", cement_mass, kg
  INPUT USE PROCESS "Construction sand and gravel; at mine", sand_mass, kg
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

## Building processes

Every exchange line says what it works with:

```basic
MAKE PROCESS "My product; at plant"
  OUTPUT MAKE FLOW "My product", 1, kg, PRODUCT        ' creates your product
  INPUT USE PROCESS "Portland cement; at plant", 300, kg  ' links a provider
  INPUT USE FLOW "Water, deionised", 50, kg             ' links a flow only
  INPUT MAKE FLOW "Custom blend", 5, kg                 ' creates a new flow
END PROCESS
```

`USE PROCESS` must match a process, because that's how the supply chain
gets linked. `USE FLOW` links a flow and leaves the provider to
openLCA's linking when the system is built. `MAKE FLOW` creates a flow,
or reuses one with the same name in the same folder, so running a
program twice doesn't create duplicates. A plain `INPUT "name"` still
works as shorthand, trying a process first and then a flow.

A name that matches nothing stops the program with an error, so a typo
can't quietly drop an input from your model.

`INPUT NEW` and `OUTPUT NEW` from earlier versions still work but are
deprecated, and will be removed in a future version.

### Choosing between processes with the same name

Some databases have several processes with the same name, one per
location. olcaBASIC warns when a name matches more than one, and
`LOCATION` picks the one you want:

```basic
INPUT USE PROCESS "market for cement, Portland", 300, kg LOCATION "RoW"
```

If the code doesn't match, the error lists the locations that exist.
`PROVIDER` takes a process UUID for when a name isn't enough;
`FIND PROCESS` shows the UUIDs.

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

### Pedigree scores and comments

Any exchange line can carry pedigree scores and a comment. Both are
optional:

```basic
MAKE PROCESS "Concrete block; at plant"
  FLOW SCHEMA "US EPA - Flow Pedigree Matrix"
  OUTPUT MAKE FLOW "Concrete block", 1, m3, PRODUCT
  INPUT USE PROCESS "Portland cement; at plant", 300, kg _
    PEDIGREE (1,2,4,1,3) COMMENT "Supplier EPD, 2025"
END PROCESS
```

The scores are written as openLCA's own data quality entries, so they
also appear in the openLCA app. A process with scored lines needs a
`FLOW SCHEMA`, and each line needs one score from 1 to 5 per indicator,
in the order `PRINT DQ SYSTEMS` lists them:

```
  US EPA - Flow Pedigree Matrix
    1. Flow Reliability
    2. Temporal Correlation
    3. Geographical Correlation
    4. Technological Correlation
    5. Data Collection Methods
```

## Changing a model

`EDIT PROCESS` changes a process in place:

```basic
EDIT PROCESS "Concrete block; at plant"
  ADD INPUT USE PROCESS "Construction sand and gravel; at mine", 10, kg
  REMOVE INPUT "Water, deionised"
  UPDATE INPUT "Portland cement; at plant", cement_mass * 0.06, kg
  UPDATE INPUT "Portland cement; at plant" PEDIGREE (2,2,2,2,2)
  ADD PARAM curing_days = 28
  SET DESCRIPTION "Updated mix"
END EDIT
```

`ADD` takes the same lines as a process. `REMOVE` and `UPDATE` name an
exchange by its flow or by the process supplying it. `UPDATE ...
LOCATION "US"` relinks to the same product from another location. The
reference product can't be removed.

`LINK` adds a supplier to an existing process, and `MOVE` puts a
process in another folder:

```basic
LINK PROCESS "Construction sand and gravel; at mine" TO PROCESS "Concrete block; at plant" WITH 25, kg
MOVE PROCESS "Concrete block; at plant" TO "00: My Project/Archive"
```

Product systems keep the links they were built with, so after adding,
removing or relinking inputs, delete the system and build it again.

### Flow properties

`EDIT FLOW` adds or updates a flow's properties and changes its
reference property:

```basic
EDIT FLOW "Concrete block"
  ADD PROPERTY "Mass" AS 2400 kg PER m3
  SET REFERENCE "Mass"
END EDIT
```

A property is written as a relation between units, so there's no
conversion factor to get the wrong way round: `AS 2400 kg PER m3` and
`AS 1 m3 PER 2400 kg` mean the same. Changing the reference rescales
every factor, so exchanges keep their meaning and results don't change.
`SHOW FLOW "Concrete block" UNITS` lists the properties. Properties
can't be removed from olcaBASIC; see [Deleting](#deleting).

## Navigation

olcaBASIC includes folder navigation inspired by the Acorn Electron:

```
CAT                         List current folder contents
CAT *concrete*              Filter by wildcard
DIR "31-33: Manufacturing"  Navigate to folder
UP                          Go up one level
BACK                        Toggle to previous folder
NAVIGATE FLOWS              Browse flows (or PROCESSES, SYSTEMS, METHODS)
CDIR "My Model"             Create a folder, enter it, and build there
PWD                         Show where you are browsing and building
```

`LS` works as an alias for `CAT`, and `CD` for `DIR`.

Browsing never changes where things are built. New processes and flows
go where `SET PROCESS FOLDER`, `SET FLOW FOLDER` or `CDIR` put them, so
you can look round the database without your model ending up in its
folders.

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

`UPDATE PARAMETER cement_mass = 280` writes the new value to the
database straight away. `SHOW PARAMETER "sand_mass"` shows a parameter,
and for a formula parameter shows the formula and its current value.

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
process and by flow. `ALLOCATE PHYSICAL`, `ECONOMIC`, `CAUSAL`, `NONE`
or `AS_DEFINED` sets the allocation method.

## Contribution trees and data quality

`TREE` follows the supply chain down from your product for one impact
category, and shows the pedigree scores on every branch, background
data included:

```basic
TREE "Concrete block; at plant" USING "IPCC" CATEGORY "AR6-100" LEVELS 3 TOP 5
```

```
  AR6-100: 13.2698 kg CO2 eq  (Test pedigree check, IPCC)

  Test pedigree check                                            100.0%
  `-- Portland cement; at plant [US]                             100.0%  (1;2;4;1;3)  ! geographical correlation 4
      +-- Bituminous coal; combusted in industrial boiler [US]    23.6%  n.a.  ! no pedigree
      +-- Electricity; at user; consumption mix - US - US [US]     5.1%  n.a.  ! no pedigree
      +-- Natural gas; combusted in industrial boiler [US]         1.0%  n.a.  ! no pedigree
      `-- Other (6)                                                0.3%

  Weak data (score 4 or 5) on the path to the result, in the branches shown:
    Flow Reliability             0.0%
    Temporal Correlation         0.0%
    Geographical Correlation   100.0%
    Technological Correlation    0.0%
    Data Collection Methods      0.0%
  No pedigree scores:   29.7%
```

Scores of 4 or 5 are flagged by indicator, and so are links with no
scores. The summary gives the share of the result that passes through at
least one weak link, counting each branch once. That's how a large
contribution from weak background data shows up. `NOQUALITY` hides the
scores, and where a background dataset is aggregated, its branch ends
there.

## Inspecting

```basic
SHOW PROCESS "Concrete block; at plant"          ' exchanges and parameters
SHOW PROCESS "Concrete block; at plant" INPUTS
SHOW FLOW "Concrete block" UNITS
SHOW PARAMETER "cement_mass"
PRINT DQ SYSTEMS
```

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

## Deleting

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

olcaBASIC doesn't delete flows or flow properties. openLCA's IPC
interface can't tell it whether a flow is used elsewhere in a model, and
deleting one that is leaves those processes broken. Delete flows in
openLCA, which checks first. We've asked GreenDelta to add a usage query
to IPC ([olca-modules issue #76](https://github.com/GreenDelta/olca-modules/issues/76)).

## Full command reference

Type `HELP` in the REPL for the command list, or `HELP PROCESS`,
`HELP FOLDER`, `HELP NEW`, `HELP SCENARIO`, `HELP SENSITIVITY` for
detailed guidance on each topic.

## Help us improve it

This is version 0.3. The known rough edges:

- `DELETE PROCESS` and `DELETE SYSTEM` don't check whether other
  processes or systems refer to what you're deleting, because IPC can't
  tell olcaBASIC that either. Use them on your own models.
- `MOVE` handles processes only.
- `EDIT PROCESS` can't remove one exchange of a flow that appears more
  than once in the same process.
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
- `b280-olca-mcp` 1.16.0 or later (installed automatically)
- For tab completion on Windows: `pip install olcabasic[completion]`

## Licence

MPL-2.0

## Links

- [B280 openLCA MCP](https://github.com/Below280/B280-olca-MCP)
- [B280 Python IPC tools](https://github.com/Below280/openLCA-IPC-tools-python)
- [Below280](https://below280.com)

*Built by Below280. openLCA is developed by GreenDelta.*
*BASIC was created by Kemeny and Kurtz at Dartmouth College, 1964.*
*Navigation commands inspired by the Acorn Electron (1983).*
