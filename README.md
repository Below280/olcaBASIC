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
olcaBASIC v0.4.0
Connected to openLCA on port 8080
Database: 2586 processes, 8 methods
Family:   flcac (auto-detected)
Ready.

> FIND PROCESS "Portland cement"
```

`FIND PROCESS` lists the name, location, folder and UUID of each match.
`HELP` lists every command; `HELP <topic>` and `HELP <command>` give
the syntax and an example.

If openLCA isn't running, olcaBASIC starts in offline mode and tells
you how to start the IPC server. Press Tab to complete commands and
names (on Windows, install `pip install olcabasic[completion]` first).

## What 0.4 changed

olcaBASIC now holds the engine that talks to openLCA, and no longer
needs `b280-olca-mcp` (the MCP server depends on olcaBASIC instead).
Rules that used to be advice are enforced by the language: a name that
could mean several processes is an error, impact methods are named in
full, nothing is built until the database family is known, and a system
that failed `VALIDATE` cannot be calculated. Every error gives its line
and what to type instead. See
[docs/CHANGELOG-0.4.0.md](docs/CHANGELOG-0.4.0.md) for the list and the
fix for each.

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

### Choosing between processes or flows with the same name

Some databases have several processes with the same name, one per
location. A name that matches more than one stops the program with an
error listing each one's location and UUID, and `LOCATION` picks the
one you want:

```basic
INPUT USE PROCESS "market for cement, Portland", 300, kg LOCATION "RoW"
```

If the code doesn't match, the error lists the locations that exist.
`PROVIDER` takes a process UUID for when a name isn't enough;
`FIND PROCESS` shows the UUIDs.

Flows work the same way. A `USE FLOW` name that several flows share is
an error listing each one's folder and UUID. `FOLDER` says which folder
to look in, or give the flow's UUID in place of its name:

```basic
INPUT USE FLOW "Custom blend", 5, kg FOLDER "00: Supplier B"
```

A flow in your own flow folder (`SET FLOW FOLDER`) is found before one
elsewhere with the same name.

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

The program in memory works as it did on a BBC Micro. `LOAD "file"`
puts a program there without running it, `LIST` shows it, `RUN` on its
own runs it, and `SAVE "file.baslca"` writes it out. Everything you run
without an error is added to it, so `SAVE` at the end of a session keeps
a program that repeats the work.

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

<!-- BEGIN COMMAND REFERENCE (generated by olcabasic.registry; do not edit by hand) -->

Every command, by topic. `HELP`, `HELP <topic>` and `HELP <command>` show the same reference inside olcaBASIC.

### Navigation: moving round the database's folders

| Command | Dialect | What it does |
|---|---|---|
| `CAT` / `LS` | Acorn / Linux | List the folders and entries in the current folder |
| `DIR` / `CD` | Acorn / Linux | Go to a folder (DIR on its own shows where you are) |
| `UP` / `CD ..` | Acorn / Linux | Go up one folder |
| `BACK` / `CD -` | Acorn / Linux | Go back to the folder you were in before |
| `CDIR` | Acorn | Create a folder, go into it, and build there from now on |
| `MKDIR` | Linux | Create a folder without going into it |
| `PWD` | Linux | Show where you are browsing and where new things are built |
| `NAVIGATE` | olcaBASIC | Choose which tree CAT, DIR and UP move through |
| `SET PROCESS FOLDER` / `SET FOLDER` | olcaBASIC | Say where new processes are built |
| `SET FLOW FOLDER` | olcaBASIC | Say where new flows are built |

```basic
CAT ["folder"] [FLOWS|PROCESSES|SYSTEMS] [*pattern*]
DIR "folder"
UP
BACK
CDIR "name"
MKDIR "name"
PWD
NAVIGATE PROCESSES|FLOWS|METHODS|SYSTEMS
SET PROCESS FOLDER "path"
SET FLOW FOLDER "path"
```

### Explore: finding and inspecting what is in the database

| Command | Dialect | What it does |
|---|---|---|
| `FIND PROCESS` | olcaBASIC | Search processes by name |
| `FIND FLOW` | olcaBASIC | Search flows by name |
| `FIND SYSTEM` | olcaBASIC | Search product systems by name |
| `FIND METHOD` | olcaBASIC | Search impact methods by name |
| `FIND UNIT` | olcaBASIC | Look up a unit and the flow property it belongs to |
| `FIND CHEMICAL` | olcaBASIC | Look up a chemical's synonyms on PubChem |
| `SHOW PROCESS` | olcaBASIC | Show a process: exchanges, parameters, data quality, location |
| `SHOW FLOW` | olcaBASIC | Show a flow: type, folder, units, or where it is used |
| `SHOW SYSTEM` | olcaBASIC | Show a product system, its parameters or its provider links |
| `SHOW GLOBAL PARAMS` | olcaBASIC | List global parameters, optionally those whose name contains a text |
| `SHOW PARAMETER` | olcaBASIC | Show a global parameter |
| `DATABASE INFO` / `PRINT DATABASE` / `DATABASE` | olcaBASIC | Count what is in the database and name its family |
| `DATABASE FAMILY` | olcaBASIC | Say which flow property names the database uses |
| `PRINT PROCESSES` | olcaBASIC | Search processes (same as FIND PROCESS) |
| `PRINT METHODS` | olcaBASIC | List impact methods |
| `PRINT SYSTEMS` | olcaBASIC | List product systems |
| `PRINT DETAILS` | olcaBASIC | Show a process (same as SHOW PROCESS) |
| `PRINT PARAMS` | olcaBASIC | List the parameters a product system can redefine |
| `PRINT GLOBAL PARAMS` | olcaBASIC | List global parameters |
| `PRINT LINKS` | olcaBASIC | Show which provider supplies each input in a product system |
| `PRINT QUALITY` | olcaBASIC | Show the data quality (pedigree) entries of a process |
| `PRINT UNITS` | olcaBASIC | Look up a unit (same as FIND UNIT) |
| `PRINT DQ SYSTEMS` | olcaBASIC | List the data quality systems that can be used as schemas |

```basic
FIND PROCESS "text" [AT "location"] [IN "folder"]
FIND FLOW "text" [IN "folder"]
FIND SYSTEM "text"
FIND METHOD "text"
FIND UNIT "unit"
FIND CHEMICAL "name or CAS number"
SHOW PROCESS "name" [INPUTS|OUTPUTS|PARAMS|QUALITY|LOCATION|DESCRIPTION]
SHOW FLOW "name" [UNITS|DESCRIPTION|USAGE [LIMIT n]]
SHOW SYSTEM "name" [PARAMS ["text"] | LINKS ["text"]]
SHOW GLOBAL PARAMS ["text"]
SHOW PARAMETER "name" [VALUE|DESCRIPTION]
DATABASE INFO
DATABASE FAMILY "ecoinvent"|"flcac"
PRINT PROCESSES("text" [, "folder"])
PRINT METHODS(["text"])
PRINT SYSTEMS(["text"])
PRINT DETAILS("process")
PRINT PARAMS("system")
PRINT GLOBAL PARAMS(["text"])
PRINT LINKS("system" [, "text"])
PRINT QUALITY("process")
PRINT UNITS("unit")
PRINT DQ SYSTEMS
```

### Build: creating flows, processes, bridges and product systems

| Command | Dialect | What it does |
|---|---|---|
| `MAKE PROCESS` / `PROCESS` | olcaBASIC | Create a process from INPUT and OUTPUT lines |
| `MAKE FLOW` / `FLOW` | olcaBASIC | Create a flow (or reuse the one that already has that name) |
| `BRIDGE` / `MAKE BRIDGE` | olcaBASIC | Create a bridge process between your model and a background process |
| `SYSTEM` / `MAKE SYSTEM` | olcaBASIC | Create the product system for a process |
| `LINK` | olcaBASIC | Add the source's product as an input of the target |
| `MOVE` | olcaBASIC | Move a process, flow or product system to another folder |
| `DELETE` | olcaBASIC | Delete a process, a product system or an unused flow |
| `CONFIRM DELETE` | olcaBASIC | Let a program delete without being asked each time |

```basic
MAKE PROCESS "name" [LOCATION "code"]
  [FOLDER "path"]
  [DESCRIPTION "text"]
  [FLOW SCHEMA "data quality system"]
  [PROCESS SCHEMA "data quality system"]
  [LET name = value]
  OUTPUT MAKE FLOW "product", amount, unit, PRODUCT
  INPUT USE PROCESS "process name", amount, unit [LOCATION "code"] [PROVIDER "uuid"]
  INPUT USE FLOW "flow name or uuid", amount, unit [FOLDER "path"]
  INPUT MAKE FLOW "new flow", amount, unit
  OUTPUT "elementary flow", amount, unit TO AIR|WATER|SOIL
  INPUT "resource", amount, unit FROM NATURE
  OUTPUT MAKE FLOW "waste", amount, unit, WASTE
  [... PEDIGREE (1,2,1,1,3)] [COMMENT "text"] [FORMULA "expression"]
  [DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n]
  [CONTROL DIRECT|NONE]
END PROCESS
MAKE FLOW "name", unit, PRODUCT|WASTE|ELEMENTARY [FOLDER "path"]
BRIDGE "BRIDGE | name | unit", unit [WASTE]
  FOLDER "path"
  PROVIDER "process name or uuid"
  [DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n]
  [ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION]
  [COUNTRY "code"] [REGION "grid region"] [ENERGY SOURCE "text"]
  [LOCATION BASED PROVIDER "process name or uuid"]
END BRIDGE
SYSTEM "process name"
  [LINKING PREFER_DEFAULTS|ONLY_DEFAULTS]
  [TARGET amount, unit [PROPERTY "flow property"]]
  [FOLDER "path"]
END SYSTEM
LINK PROCESS "source" TO PROCESS "target" WITH amount, unit
MOVE PROCESS|FLOW|SYSTEM "name" TO "folder"
DELETE PROCESS|SYSTEM|FLOW "name or uuid"
CONFIRM DELETE ON|OFF
```

### Edit: changing what already exists

| Command | Dialect | What it does |
|---|---|---|
| `EDIT PROCESS` | olcaBASIC | Add, remove or update exchanges and parameters of a process |
| `EDIT FLOW` | olcaBASIC | Add or update a flow property, or set the reference property |
| `PARAMETERISE PROCESS` / `PARAMETERIZE PROCESS` | olcaBASIC | Replace the fixed amounts of a process with parameters |

```basic
EDIT PROCESS "name or uuid"
  ADD INPUT|OUTPUT ...                 (same forms as in MAKE PROCESS)
  ADD PARAM name = value
  REMOVE INPUT|OUTPUT "flow or provider name"
         [PROVIDER "name or uuid"] [LOCATION "code"] [AMOUNT n] [INDEX n]
  UPDATE INPUT|OUTPUT "name" [INDEX n], amount [, unit]
  UPDATE INPUT|OUTPUT "name" [LOCATION "code"] [PROVIDER "uuid"]
                             [PEDIGREE (1,2,1,1,3)] [COMMENT "text"]
  UPDATE PARAM name = value
  SET DESCRIPTION|FOLDER|LOCATION "value"
END EDIT
EDIT FLOW "name"
  ADD PROPERTY "Mass" AS 2400 kg PER m3
  UPDATE PROPERTY "Mass" AS 2350 kg PER m3
  SET REFERENCE "Mass"
END EDIT
PARAMETERISE PROCESS "name" [LOCATION "code"] [ALL] CONFIRM
```

### Parameters: variables that become openlca parameters

| Command | Dialect | What it does |
|---|---|---|
| `LET` | BASIC | Set a variable (LET may be left out: name = expression) |
| `UPDATE PARAMETER` | olcaBASIC | Set a variable and write the global parameter to openLCA now |

```basic
LET name = expression
UPDATE PARAMETER name = expression
```

### Calculate: impact results and where they come from

| Command | Dialect | What it does |
|---|---|---|
| `CALCULATE` | olcaBASIC | Calculate the impacts of a product system and keep the result open |
| `CONTRIBUTION` | olcaBASIC | Show which processes contribute most to each impact category |
| `TREE` | olcaBASIC | Show the contribution tree for one category, with pedigree scores |
| `INVENTORY` | olcaBASIC | List the largest elementary flows of a product system |
| `MONTECARLO` | olcaBASIC | Run a Monte Carlo simulation and report the spread per category |

```basic
CALCULATE "system" USING "method"
  [ALLOCATE AS_DEFINED|PHYSICAL|ECONOMIC|CAUSAL|NONE]
  [AMOUNT n unit [PROPERTY "flow property"]]
  [WITH COSTS] [WITH REGIONALISATION]
  [NW SET "name"] [PARAMETER SET "name"]
  [IGNORE FACTORS "flow"]
  [AS name]
CONTRIBUTION "system" USING "method" [TOP n] [ALLOCATE method]
  [CATEGORIES "category", "category"]
END CONTRIBUTION
TREE "system" USING "method" CATEGORY "category" [LEVELS n] [TOP n] [NOQUALITY]
INVENTORY "system" USING "method" [MAX n]
MONTECARLO "system" USING "method" [RUNS n]
```

### Result: reading more from a result that is open

| Command | Dialect | What it does |
|---|---|---|
| `RESULT IMPACTS` | olcaBASIC | Impact totals of the open result, whole or by analysis group or tag |
| `RESULT CATEGORIES` | olcaBASIC | List the impact categories of the open result |
| `RESULT PROCESSES` | olcaBASIC | List the processes of the calculated system |
| `RESULT DEMAND` | olcaBASIC | Show the product and amount the result was calculated for |
| `RESULT FLOWS` | olcaBASIC | Inventory: elementary flows of the system or of one process |
| `RESULT FLOW` | olcaBASIC | Show which processes one elementary flow comes from |
| `RESULT CONTRIBUTION` | olcaBASIC | Contributions to the impacts, by process or by elementary flow |
| `RESULT FACTORS` | olcaBASIC | Characterisation factors of a category for the flows of the inventory |
| `RESULT INTENSITY` | olcaBASIC | Impacts or flows of one unit of a process's product, with its supply chain |
| `RESULT SCALING` | olcaBASIC | Scaling factors, or the product and waste flows of one process |
| `RESULT TOTALITY` | olcaBASIC | Totality factors: total requirements corrected for loops |
| `RESULT REQUIREMENTS` | olcaBASIC | How much of each product the system needs in total |
| `RESULT TREE` | olcaBASIC | Upstream tree of a category, an elementary flow or the costs |
| `RESULT COSTS` | olcaBASIC | Life cycle costs of a result calculated WITH COSTS |
| `RESULT NORMALISED` / `RESULT NORMALIZED` | olcaBASIC | Normalised results of a result calculated with an NW SET |
| `RESULT WEIGHTED` | olcaBASIC | Normalised and weighted results of a result calculated with an NW SET |
| `RESULT SANKEY` | olcaBASIC | Nodes and links for a Sankey diagram of a category or a flow |
| `CLOSE RESULT` | olcaBASIC | Close the current result, a named one, or all of them |

```basic
RESULT IMPACTS [CATEGORY "category"]
RESULT IMPACTS BY GROUP [CATEGORY "category"]
RESULT IMPACTS BY TAG CATEGORY "category"
RESULT CATEGORIES
RESULT PROCESSES
RESULT DEMAND
RESULT FLOWS [FLOW "flow" [IN "compartment"]]
RESULT FLOWS LIST
RESULT FLOWS OF PROCESS "process" [DIRECT] [FLOW "flow"]
RESULT FLOWS BY GROUP FLOW "flow"
RESULT FLOWS BY TAG FLOW "flow"
RESULT FLOW "y" BY PROCESS
RESULT CONTRIBUTION BY PROCESS [DIRECT] [CATEGORY "category"]
RESULT CONTRIBUTION OF PROCESS "process" [DIRECT] [CATEGORY "category"]
RESULT CONTRIBUTION BY FLOW [CATEGORY "category" [FLOW "flow"]]
RESULT FACTORS CATEGORY "x" [FLOW "y"]
RESULT INTENSITY OF PROCESS "x" [CATEGORY "y" | FLOWS | FLOW "y"]
RESULT SCALING [OF PROCESS "x" [UNSCALED]]
RESULT TOTALITY [OF PROCESS "x"]
RESULT REQUIREMENTS [OF PROCESS "x"]
RESULT TREE CATEGORY "x" | FLOW "y" | COSTS [LEVELS n] [TOP n]
RESULT COSTS
RESULT COSTS BY PROCESS | BY GROUP | BY TAG
RESULT COSTS OF PROCESS "process" [DIRECT]
RESULT COSTS INTENSITY OF PROCESS "process"
RESULT COSTS TREE [LEVELS n] [TOP n]
RESULT NORMALISED
RESULT WEIGHTED
RESULT SANKEY CATEGORY "x" | FLOW "y" [MIN SHARE n%] [MAX NODES n] [SAVE "file.json"]
CLOSE RESULT [name | ALL]
```

### Scenarios: scenarios and sensitivity analysis

| Command | Dialect | What it does |
|---|---|---|
| `SCENARIO` | olcaBASIC | Define a scenario as a set of parameter values |
| `RUN SCENARIOS` | olcaBASIC | Calculate every scenario defined so far |
| `SENSITIVITY` | olcaBASIC | Vary parameters up and down by a percentage, one at a time |

```basic
SCENARIO "name"
  LET parameter = value
END SCENARIO
RUN SCENARIOS ON "system" USING "method" [ALLOCATE method]
  [FROM CSV "scenarios.csv"]
  [SAVE "results.csv"]
END RUN
SENSITIVITY ON "system" USING "method" BY n% [ALLOCATE method]
  VARY parameter [, parameter]
  [FROM "parameters.csv"]
  [SAVE "results.csv"]
END SENSITIVITY
```

### Check: checking a model before trusting its results

| Command | Dialect | What it does |
|---|---|---|
| `VALIDATE` | olcaBASIC | Check the structure of a product system |
| `CHECK` | olcaBASIC | Run a tier of model checks |
| `AUDIT` | olcaBASIC | Look for structural problems in the processes of a folder |
| `EXTRACT` | olcaBASIC | List every process and exchange in a folder, to compare with source data |

```basic
VALIDATE "system" [WITH CALCULATION]
CHECK "system" [TIER 1|2|3] [AGAINST "file"]
AUDIT [FOLDER] "folder"
EXTRACT [FOLDER] "folder"
```

### Epd: environmental product declarations (en 15804+a2)

| Command | Dialect | What it does |
|---|---|---|
| `EPD` | olcaBASIC | Define an EPD: unit, method, folder, modules and programme |
| `MODULE` | olcaBASIC | Build the processes of one EPD module and the process that adds them up |
| `EPD SYSTEMS` | olcaBASIC | Create one product system per module total, one at a time |
| `EPD CHECK` | olcaBASIC | Validate every module system and list what is missing |
| `EPD CALCULATE` | olcaBASIC | Calculate every module with the EPD method |
| `EPD DATA QUALITY` | olcaBASIC | Do the programme's data quality arithmetic and apply its limits |
| `EPD REPORT` | olcaBASIC | Write the results table and the declarations to a CSV file |
| `EPD STATUS` / `EPD CLOSE` | olcaBASIC | Show how far the active EPD has got, or end EPD mode |
| `DATA PRIMARY` / `DATA SECONDARY` / `DATA PROXY` / `CONTROL` | olcaBASIC | Declare where the data of a process or bridge comes from |
| `ELECTRICITY` | olcaBASIC | Declare how the electricity of a bridge is modelled |
| `NEW FROM TEMPLATE` | olcaBASIC | Copy a template program into the working folder |

```basic
EPD "product name"
  [PROGRAMME "IES" [GPI "5.1.0"]]
  [PCR "name" [VERSION "n"]]
  [DATABASE "name" [VERSION "n"]]
  DECLARED UNIT amount, unit | FUNCTIONAL UNIT amount, unit
  METHOD "EN15804+A2 (EF 3.1)" [CATEGORIES n]
  FOLDER "path"
  MODULES A1, A2, A3, C1, C2, C3, C4, D
  BIOGENIC CARBON YES|NO
  [CUTOFF module "item", n%]
  [GWP INDICATOR "category name"]
  [EXEMPT C AND D
     INTEGRATED "text"
     NOT IDENTIFIABLE "text"
     END OF LIFE SCENARIOS "text"
   END EXEMPT]
END EPD
MODULE A1
  MAKE PROCESS "name"
    ...
  END PROCESS
  [NET FLOW "flow", amount, unit [QUALITY n%]]     (module D)
  TOTAL "name" [AS "flow", amount, unit]
END MODULE
EPD SYSTEMS
EPD CHECK [SKIP "reason"]
EPD CALCULATE
EPD DATA QUALITY
EPD REPORT "file.csv" [LOCATION BASED]
EPD STATUS | EPD CLOSE
DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025
DATA SECONDARY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2024
DATA PROXY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2019 REASON "why"
  [SHARE n%]
CONTROL DIRECT|NONE
ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION
COUNTRY "code"
[REGION "grid region"]
[ENERGY SOURCE "text"]
[LOCATION BASED PROVIDER "process name or uuid"]
NEW FROM TEMPLATE "name" AS "file.baslca"
```

### Output: showing and saving results

| Command | Dialect | What it does |
|---|---|---|
| `PRINT RESULTS` | olcaBASIC | Show the most recent results again |
| `SAVE RESULTS` / `EXPORT RESULTS TO` | olcaBASIC | Write the most recent results to a CSV file |
| `SAVE PROGRAM` / `SAVE "file.baslca"` | olcaBASIC | Write the program in memory to a file |

```basic
PRINT RESULTS
SAVE RESULTS "file.csv"
SAVE PROGRAM "file.baslca"
```

### Programming: basic: variables, loops, conditions, subroutines

| Command | Dialect | What it does |
|---|---|---|
| `PRINT` | BASIC | Print text or values |
| `REM` / `'` | BASIC | A comment (an apostrophe starts one too) |
| `IF` | BASIC | Do something only if a condition holds |
| `FOR` | BASIC | Repeat with a counter |
| `FOR EACH` | BASIC | Repeat once for each value in a list |
| `WHILE` | BASIC | Repeat while a condition holds |
| `SUB` | BASIC | Define a subroutine; call it by name |
| `FUNCTION` | BASIC | Define a function; it returns the variable with its own name |
| `DATA` | BASIC | Queue values for READ INPUTS FROM DATA inside a PROCESS block |
| `INPUT` | BASIC | Ask for a value at the terminal |
| `INCLUDE` | BASIC | Insert another program file at this point |
| `RUN` | BASIC | Run a program file, or on its own the program in memory |
| `LOAD` | BASIC | Put a program in memory without running it |
| `LIST` | BASIC | Show the program in memory |

```basic
PRINT expression [, expression]
REM text
IF condition THEN
  statements
[ELSE
  statements]
END IF

IF condition THEN statement [ELSE statement]
FOR name = start TO end [STEP n] ... NEXT
FOR EACH name IN value, value ... NEXT
WHILE condition ... WEND
SUB name(parameters) ... END SUB
FUNCTION name(parameters) ... END FUNCTION
DATA "name", amount, "unit"
INPUT "prompt", name
INCLUDE "file.baslca"
RUN ["file.baslca"]
LOAD "file.baslca"
LIST
```

### Session: help and housekeeping

| Command | Dialect | What it does |
|---|---|---|
| `HELP` | olcaBASIC | Show the command list, a topic, or one command |
| `REFRESH` | olcaBASIC | Read the lists of processes and flows from openLCA again |
| `CLEAR` | olcaBASIC | Clear the terminal screen |
| `EXIT` / `QUIT` | olcaBASIC | Leave olcaBASIC |

```basic
HELP [topic or command]
REFRESH
CLEAR
EXIT
```

<!-- END COMMAND REFERENCE -->

## From Python: Session

`Session` runs olcaBASIC from Python and gives structured results back.
It is what the MCP server uses.

```python
from olcabasic import Session

s = Session(port=8080)            # Session(offline=True) needs no openLCA
r = s.run('''
    LET cement_mass = 300
    CALCULATE "Concrete block" USING "EF v3.1"
''')

r.ok          # True, or False if the program stopped at an error
r.text        # what the terminal would have shown
r.data        # results as dictionaries: [{"command", "line", "call", "result"}]
r.errors      # [{"line": 3, "message": "...", "hint": "what to type instead"}]
r.warnings    # [{"line": 2, "message": "...", "level": "warning" or "note"}]
```

- Variables, the current folder, scenarios, the latest results and the
  active EPD persist between `run` calls. `s.reset()` clears them.
- `run` holds a lock from start to finish, so two programs can never
  write to openLCA at once and product systems are never created in
  parallel.
- `s.run(code, dry_run=True)` parses the program and checks what can be
  checked without openLCA: undefined variables, missing files, the
  structure of `PROCESS` and `EPD` blocks, commands that would wait for
  the keyboard.
- `s.engine` is the engine itself (`olcabasic.engine.Engine`), for the
  calls a program cannot make.

## EPDs (EN 15804+A2)

An EPD is built with commands that enforce the rules as they go. The
steps are fixed, and each refuses to run until the one before it has
passed.

```basic
EPD "Concrete block"
  PROGRAMME "IES" GPI "5.1.0"
  PCR "PCR 2019:14 Construction products" VERSION "1.3.1"
  DATABASE "ecoinvent" VERSION "3.11"
  DECLARED UNIT 1, m3
  METHOD "EN15804+A2 (EF 3.1)"
  FOLDER "00: Concrete block EPD"
  MODULES A1, A2, A3, C1, C2, C3, C4, D
  BIOGENIC CARBON NO
  CUTOFF A3 "Lubricants", 0.2%
END EPD

BRIDGE "Cement", kg
  PROVIDER "uuid of the background process"
  DATA SECONDARY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2024
END BRIDGE

MODULE A1
  MAKE PROCESS "Cement supply"           ' becomes "A1 | Cement supply"
    DATA SECONDARY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2024
    OUTPUT MAKE FLOW "Cement, supplied", 300, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Cement | kg", 300, kg
  END PROCESS
  TOTAL "Raw material supply"            ' builds "A1: Raw material supply"
END MODULE

' ... one MODULE block per declared module ...

EPD SYSTEMS                  ' one product system per module, one at a time
EPD CHECK                    ' validate each; list missing pedigree and descriptions
EPD CALCULATE                ' every module with the EPD method
EPD DATA QUALITY             ' the programme's data quality arithmetic
EPD REPORT "results.csv"     ' indicators by module, with the header block
```

What is enforced:

- **Modules** (EN 15804+A2, clause 5.2). A1 to A3 are always declared.
  C1 to C4 and D are declared together, or left out together with an
  `EXEMPT C AND D` block that justifies it; the exemption is refused
  for a product with biogenic carbon. `FUNCTIONAL UNIT` is refused for
  the cradle to gate types. The EPD type follows from the modules and
  goes in the report, named as in clause 5.2.
- **Method.** It must be an EN 15804+A2 method with the full indicator
  set: 38 categories for `EN15804+A2 (EF 3.1)`. The 20-category method
  with the similar name is refused.
- **Inside a module**, an input comes from a bridge or from a process
  of the EPD. A background process used directly is an error. Names get
  their prefixes (`A1 | name`, `A1: name`) without your typing them.
- **Totals.** A1-A3 is the only total. Module D is its own column and
  is never added to anything.
- **Programme rules.** `PROGRAMME "IES"` applies the International EPD
  System's rules (General Programme Instructions 5.1.0, Annex A) as
  errors, with no override: `DATA` on every process and bridge, primary
  data for processes under direct control, no consumption-mix
  electricity in A1 to A3 processes under direct control, the grid
  region for countries with sub-national grids, cut-offs within the
  limit, proxy data within the limit, data within its age limit. Under
  a programme the model is always checked: there is no `EPD CHECK SKIP`.
  `EPD DATA QUALITY` works out the share of primary data and the rest
  of what the programme asks for. Every threshold is a named value in
  `olcabasic/workflows/programmes/ies.py`; another operator is another
  profile.

`NEW FROM TEMPLATE "epd_skeleton" AS "my_epd.baslca"` writes a starting
point with a comment at every decision. `bridges_common` and
`sensitivity_epd` are the other two templates. `HELP EPD` has the full
syntax.

Still for the practitioner: which inventory item belongs in which
module, pedigree scores on every exchange, and process documentation.
`EPD CHECK` lists what is missing; it does not invent it. The standards
and programme instructions are referred to by clause number only: you
need your own copies.

## Help us improve it

This is version 0.4. The known rough edges:

- `DELETE PROCESS` and `DELETE SYSTEM` don't check whether other
  processes or systems refer to what you're deleting, because IPC can't
  tell olcaBASIC that either. Use them on your own models.
- `DELETE FLOW` does check, by reading every process, which takes a
  long time on a large database.
- Functions in exchange amounts (`SQR`, `MIN` and so on) are passed to
  openLCA as written, and openLCA's formula functions have their own
  names.
- The EPD workflow has been tested against a synthetic method, and its
  storage and electricity switch against a live ecoinvent database. It
  has not yet run end to end against the real `EN15804+A2 (EF 3.1)`
  method pack.

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

The language is BASIC because BASIC was written so that people who were
not programmers could use a computer: John Kemeny and Thomas Kurtz,
Dartmouth College, 1964. The folder commands (`CAT`, `DIR`, `CDIR`)
come from the Acorn machines many of us learned on, and each has its
Linux form (`LS`, `CD`, `MKDIR`) beside it.

## Requirements

- openLCA 2.x with IPC server running (port 8080)
- Python 3.11 or later
- `olca-ipc` (installed automatically). Nothing else.
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
