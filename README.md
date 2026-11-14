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

### Give openLCA enough memory

The openLCA installer sets openLCA's maximum memory to about 3.5 GB.
That is not enough for a product system on a large background database
such as ecoinvent: during a contribution analysis or a full read of a
system, openLCA runs out of memory, drops the IPC connection and may
restart itself. Set the maximum memory in openLCA (File > Preferences >
Configuration) to 10 GB or more if the computer has it, then restart
openLCA. olcaBASIC cannot read this setting through IPC, so it can only
tell you afterwards: when openLCA drops the connection, the error says
so and points here.

## What 0.4 changed

olcaBASIC now holds the engine that talks to openLCA, and no longer
needs `b280-olca-mcp` (the MCP server depends on olcaBASIC instead).
Rules that used to be advice are enforced by the language: a name that
could mean several processes is an error, impact methods are named in
full, nothing is built until the database family is known, and a system
that failed `VALIDATE` cannot be calculated. Every error gives its line
and what to type instead.

It also reaches all of openLCA's IPC server: results that stay open
and can be queried ([Reading more from a result](#reading-more-from-a-result)),
uncertainty, costs, allocation factors and documentation on a process,
and every other entity type, from actors to impact methods
([Everything else in the database](#everything-else-in-the-database)).

See [docs/CHANGELOG-0.4.0.md](docs/CHANGELOG-0.4.0.md) for the list and
the fix for each change in behaviour.

### What the language refuses

A model that is built or calculated wrongly without an error is worse
than one that does not build. Each of these stops the program with the
line and what to type instead, and none has an override:

- a background process used without a [bridge](#bridges), directly or
  through `USE FLOW`, and a bridge in a unit its provider cannot be
  measured in (kg onto a provider in m3, say);
- changing, moving or deleting background data: anything in a folder
  named with an ISIC or NAICS code, as ecoinvent and the US databases
  file theirs, is read-only; and a process that a product system still
  uses, or a flow that anything still uses, is not deleted;
- a name that could mean several processes or flows, and a method name
  that is not the full name;
- a `MAKE PROCESS` block that is run again after it was changed (an
  identical block is a quiet no-op, so a program can be run twice);
- calculating a product system after one of its processes was edited,
  linked, moved or parameterised, until it is built again and passes
  `VALIDATE`; and calculating one that failed `VALIDATE`;
- an `OUTPUT` or `INPUT` whose name matches nothing (write `MAKE FLOW`);
- a new emission that the method has no characterisation factor for
  (`CALCULATE ... IGNORE FACTORS "flow"` accepts it knowingly);
- `MONTECARLO` when nothing is uncertain;
- an amount that would mean something different as an openLCA formula
  (see [Programming](#programming));
- `ALLOCATE PHYSICAL` or `ECONOMIC` when a process with several
  products has no factors for it;
- in an EPD, a module that uses another module's process, and anything
  that breaks a rule of the programme.

## Write programs

Save as `mymodel.baslca` and run with `python -m olcabasic run mymodel.baslca`:

```basic
REM Concrete block model

LET cement_mass = 300
LET aggregate_ratio = 2.667
LET sand_mass = cement_mass * aggregate_ratio

SET PROCESS FOLDER "00: My Project"
SET FLOW FOLDER "00: My Project/Flows"

REM One bridge per background dataset: the choice sits in one place
BRIDGE "Cement", kg
  PROVIDER "Portland cement; at plant"
END BRIDGE
BRIDGE "Sand", kg
  PROVIDER "Construction sand and gravel; at mine"
END BRIDGE

MAKE PROCESS "Concrete block; at plant"
  OUTPUT MAKE FLOW "Concrete block", 1, m3, PRODUCT
  INPUT USE PROCESS "BRIDGE | Cement | kg", cement_mass, kg
  INPUT USE PROCESS "BRIDGE | Sand | kg", sand_mass, kg
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

### Bridges

A background process is one the program did not build: anything outside
the folders it builds in, such as a dataset of the database you bought.
A process of your own never uses one directly. It uses a bridge, a
one-line process of yours that passes the background dataset through:

```basic
BRIDGE "Cement", kg
  PROVIDER "market for cement, Portland" LOCATION "RoW"
END BRIDGE
```

The bridge is called `BRIDGE | Cement | kg`, and that is the name your
processes use. Swapping the dataset later is one change in one place,
and every process that uses the bridge follows. Naming a background
process straight in `MAKE PROCESS`, `EDIT PROCESS` or `LINK` is an
error, and the error gives the bridge to write. There is no setting
that turns this off.

## Building processes

Every exchange line says what it works with:

```basic
MAKE PROCESS "My product; at plant"
  OUTPUT MAKE FLOW "My product", 1, kg, PRODUCT        ' creates your product
  INPUT USE PROCESS "BRIDGE | Cement | kg", 300, kg     ' links a provider
  INPUT USE FLOW "Water, deionised", 50, kg             ' links a flow only
  INPUT MAKE FLOW "Custom blend", 5, kg                 ' creates a new flow
END PROCESS
```

`USE PROCESS` must match a process, because that's how the supply chain
gets linked. `USE FLOW` links a flow and leaves the provider to
openLCA's linking when the system is built. It is refused for a flow
that only background processes make, because the system would then
take one of them in with no bridge. `MAKE FLOW` creates a flow,
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
BRIDGE "Cement", kg
  PROVIDER "market for cement, Portland" LOCATION "RoW"
END BRIDGE
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
  INPUT USE PROCESS "BRIDGE | Cement | kg", 300, kg _
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

### Uncertainty, costs and allocation

```basic
LET kiln_kwh = 55 UNCERTAINTY TRIANGLE 45, 55, 70

MAKE PROCESS "Kilning"
  OUTPUT MAKE FLOW "Kiln-dried timber", 1, m3, PRODUCT COST 320 CURRENCY "EUR"
  OUTPUT MAKE FLOW "Sawdust", 40, kg
  INPUT USE PROCESS "BRIDGE | Electricity | kWh", kiln_kwh, kWh _
    COST 0.25 CURRENCY "EUR"
  INPUT USE PROCESS "BRIDGE | Sawn timber | m3", 1.1, m3 _
    UNCERTAINTY LOGNORMAL 1.1, 1.05
  ALLOCATION ECONOMIC
    "Kiln-dried timber", 0.97
    "Sawdust", 0.03
  END ALLOCATION
  DEFAULT ALLOCATION ECONOMIC
END PROCESS
```

`UNCERTAINTY` takes `LOGNORMAL gm, gsd`, `NORMAL mean, sd`, `TRIANGLE
min, mode, max` or `UNIFORM min, max`, on an exchange or a `LET`, and
is what `MONTECARLO` samples. `AVOIDED` marks a co-product as an avoided
product. `COST` needs a currency that exists (`FIND CURRENCY`, `MAKE
CURRENCY`); `CALCULATE ... WITH COSTS` then gives `RESULT COSTS`. The
shares of an `ALLOCATION` block add up to 1. `DOCUMENT ... END
DOCUMENT` holds openLCA's process documentation, `SOCIAL` lines the
social aspects. `SHOW PROCESS "name" FIELDS` reads it all back, and
`HELP MAKE PROCESS` lists every line.

## Changing a model

`EDIT PROCESS` changes a process in place:

```basic
EDIT PROCESS "Concrete block; at plant"
  ADD INPUT USE PROCESS "BRIDGE | Sand | kg", 10, kg
  REMOVE INPUT "Water, deionised"
  UPDATE INPUT "BRIDGE | Cement | kg", cement_mass * 0.06, kg
  UPDATE INPUT "BRIDGE | Cement | kg" PEDIGREE (2,2,2,2,2)
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
LINK PROCESS "BRIDGE | Sand | kg" TO PROCESS "Concrete block; at plant" WITH 25, kg
MOVE PROCESS "Concrete block; at plant" TO "00: My Project/Archive"
```

A product system keeps the links it was built with. After `EDIT
PROCESS`, `LINK`, `MOVE` or `PARAMETERISE` on a process, every product
system that holds it is out of date, and nothing can be calculated on
it until it is built again and checked. This does not end with the
session: every calculation also compares the system's links with what
its processes ask for now, so an input added, removed or given another
provider is caught after `RESET`, in a new session, and when the change
was made in the openLCA app. (A changed amount on its own is only held
against the session that made it: openLCA reads amounts from the
processes when it calculates, so the result is right.) A system that
has not passed `VALIDATE` in the session is checked with `VALIDATE`
before its first calculation, so a failure is never forgotten either.

```basic
CONFIRM DELETE ON
DELETE SYSTEM "Concrete block; at plant"
SYSTEM "Concrete block; at plant"
VALIDATE "Concrete block; at plant"
```

(An edit that only sets the description, documentation or data
declarations changes no result and leaves the systems as they are.)
Running a `MAKE PROCESS` block again does not change a process that
exists: if the block now differs from the process, that is an error
which lists the differences.

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

## Reading more from a result

`CALCULATE` leaves its result open in openLCA, and `RESULT` reads from
it without calculating again:

```basic
CALCULATE "Concrete block; at plant" USING "IPCC" WITH COSTS

RESULT CONTRIBUTION BY PROCESS CATEGORY "AR6-100" TOP 10
RESULT CONTRIBUTION BY FLOW CATEGORY "AR6-100"     ' which emissions drive it
RESULT FLOW "Carbon dioxide" BY PROCESS            ' where one emission comes from
RESULT FACTORS CATEGORY "AR6-100"                  ' the characterisation factors
RESULT REQUIREMENTS TOP 20                         ' how much of each product
RESULT TREE CATEGORY "AR6-100" LEVELS 3
RESULT COSTS BY PROCESS
RESULT SANKEY CATEGORY "AR6-100" SAVE "sankey.json"
SAVE RESULT AS "Concrete block, baseline"          ' into the database
CLOSE RESULT
```

`CALCULATE ... AS base` keeps a result open under a name, next to the
current one, and `RESULT ... IN base` reads from it; a session holds
five. Every query takes `TOP n` and `SAVE "file.csv"`. A query the
result cannot answer says what to calculate instead: `RESULT COSTS`
needs `WITH COSTS`, `RESULT NORMALISED` an `NW SET "name"`, `RESULT
IMPACTS BY GROUP` analysis groups on the system. `HELP RESULT` lists
them all.

## Inspecting

```basic
SHOW PROCESS "Concrete block; at plant"          ' exchanges and parameters
SHOW PROCESS "Concrete block; at plant" INPUTS
SHOW FLOW "Concrete block" UNITS
SHOW PARAMETER "cement_mass"
PRINT DQ SYSTEMS
```

## Everything else in the database

`FIND`, `SHOW`, `DELETE` and `MOVE` work on every type openLCA has:
processes, systems, flows, flow properties (`PROPERTY`), unit groups
(`UNITS`), parameters, impact methods and categories, locations, data
quality systems, actors, sources, currencies, social indicators,
projects, stored results and EPDs.

```basic
FIND ACTOR "Below"
SHOW SOURCE "EN 15804" USAGE          ' what points at it
SHOW METHOD "IPCC" JSON               ' openLCA's own JSON-LD, read-only

MAKE ACTOR "Below280"
  EMAIL "info@example.com"
END ACTOR

MAKE METHOD "Site water use"
  CATEGORY "Water drawn" UNIT "m3"
    FACTOR "Water, well, in ground", 1
  END CATEGORY
END METHOD
```

There are `MAKE` and `EDIT` blocks for actors, sources, currencies,
locations, unit groups, flow properties, social indicators, data
quality systems, impact methods and projects (`CALCULATE PROJECT`
compares the variants). A method that olcaBASIC did not make is licensed
and shared by every model in the database: changing one is refused
without `CONFIRM`, and then asks a person at the terminal. Nothing
writes raw JSON into the database.

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
try them. A loop stops after 1,000,000 passes, and a SUB that calls
itself without end is an error, not a hang.

An amount that uses a variable is written into openLCA as a formula, so
that a scenario or a sensitivity run can change it. openLCA's formula
functions are not BASIC's: there `sqr(x)` is x squared, `log` is base
10 and `int` cuts towards zero. olcaBASIC writes `SQR`, `LOG` and `INT`
as `sqrt`, `ln` and `floor`, so the amount means in openLCA what it
means in your program, and refuses what openLCA would read differently
(a comparison, `AND`/`OR`, `SGN`, the text functions, `ROUND(x, n)`).
`ROUND` takes halves up, as openLCA does. `a ^ b ^ c` needs brackets,
because BASIC and maths read it differently; `-2 ^ 2` is -4.

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

`DELETE PROCESS` refuses a process that a product system still uses:
delete the system first. `DELETE FLOW` refuses a flow that a process,
an impact category, an EPD or a stored result still uses. openLCA's IPC
interface has no usage query, so olcaBASIC reads the processes itself:
for a flow of your own folders, every process outside the background
folders (seconds); for any other flow, every process in the database,
which takes about an hour on ecoinvent. We've asked GreenDelta to add a
usage query to IPC
([olca-modules issue #76](https://github.com/GreenDelta/olca-modules/issues/76)).
Background data is never deleted. Empty folders cannot be removed over
IPC: delete them in openLCA.

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
| `SHOW PROCESS` | olcaBASIC | Show a process: exchanges, parameters, data quality, and its other fields |
| `SHOW FLOW` | olcaBASIC | Show a flow: type, folder, units, or where it is used |
| `SHOW SYSTEM` | olcaBASIC | Show a product system, its parameters, links, parameter sets or groups |
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
SHOW PROCESS "name" [INPUTS|OUTPUTS|PARAMS|QUALITY|LOCATION|DESCRIPTION|
                     FIELDS|DOCUMENT|ALLOCATION|SOCIAL]
SHOW FLOW "name" [UNITS|DESCRIPTION|FIELDS|USAGE [LIMIT n]]
SHOW SYSTEM "name" [PARAMS ["text"] | LINKS ["text"] | SETS | GROUPS]
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
| `MOVE` | olcaBASIC | Move an entity of any type to another folder |
| `DELETE` | olcaBASIC | Delete an entity of any type that nothing else uses |
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
  [... UNCERTAINTY LOGNORMAL gm, gsd | NORMAL mean, sd |
       TRIANGLE min, mode, max | UNIFORM min, max] [BASE UNCERTAINTY n]
  [... AVOIDED] [COST value [FORMULA "x"] CURRENCY "code"]
  [... SITE "location code"] [PROPERTY "flow property"]
  [LET name = value UNCERTAINTY ...]
  [TYPE UNIT | TYPE LCI RESULT] [INFRASTRUCTURE]
  [PROCESS PEDIGREE (1,2,1,1)]
  [DEFAULT ALLOCATION PHYSICAL|ECONOMIC|CAUSAL|NONE]
  [ALLOCATION PHYSICAL|ECONOMIC
     "product", share
   END ALLOCATION]
  [ALLOCATION CAUSAL
     "product", share FOR INPUT|OUTPUT "flow"
   END ALLOCATION]
  [DOCUMENT
     TIME "text" | GEOGRAPHY "text" | TECHNOLOGY "text" | ...
   END DOCUMENT]
  [SOCIAL "indicator", "raw value", risk level [ACTIVITY n]
          [COMMENT "text"] [SOURCE "name"] [QUALITY (scores)]]
  [SOCIAL SCHEMA "data quality system"]
  [DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n]
  [CONTROL DIRECT|NONE]
END PROCESS
MAKE FLOW "name", unit, PRODUCT|WASTE|ELEMENTARY [FOLDER "path"]
  [CAS "number"] [FORMULA "chemical formula"] [SYNONYMS "a; b"]
  [DESCRIPTION "text"] [LOCATION "code"] [INFRASTRUCTURE]
MAKE FLOW "name", unit TO AIR|WATER|SOIL
MAKE FLOW "name", unit FROM NATURE
BRIDGE "BRIDGE | name | unit", unit [WASTE]
  FOLDER "path"
  PROVIDER "process name or uuid" [LOCATION "code"]
  [DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n]
  [ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION]
  [COUNTRY "code"] [REGION "grid region"] [ENERGY SOURCE "text"]
  [LOCATION BASED PROVIDER "process name or uuid"]
END BRIDGE
SYSTEM "process name"
  [LINKING PREFER_DEFAULTS|ONLY_DEFAULTS|IGNORE_DEFAULTS]
  [PREFER UNIT PROCESSES | PREFER SYSTEM PROCESSES]
  [CUTOFF fraction]
  [TARGET amount, unit [PROPERTY "flow property"]]
  [FOLDER "path"]
  [PARAMETER SET "name" [BASELINE]
     name = value [IN PROCESS "process"]
   END PARAMETER SET]
  [ANALYSIS GROUP "name"
     "process" [LOCATION "code"]
   END ANALYSIS GROUP]
END SYSTEM
LINK PROCESS "source" TO PROCESS "target" WITH amount, unit
MOVE <type> "name" TO "folder"
DELETE <type> "name or uuid" [CONFIRM]
CONFIRM DELETE ON|OFF
```

### Edit: changing what already exists

| Command | Dialect | What it does |
|---|---|---|
| `EDIT PROCESS` | olcaBASIC | Add, remove or update exchanges and parameters of a process |
| `EDIT FLOW` | olcaBASIC | Change a flow: its properties, CAS number, formula, synonyms, location |
| `EDIT SYSTEM` | olcaBASIC | Change the parameter sets and analysis groups of a product system |
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
  UPDATE INPUT|OUTPUT "name" [UNCERTAINTY ... | UNCERTAINTY NONE]
                             [AVOIDED | NOT AVOIDED] [SITE "code" | NO SITE]
                             [COST value CURRENCY "code" | NO COST]
  UPDATE PARAM name = value [UNCERTAINTY ...]
  UPDATE PARAM name UNCERTAINTY ... | UNCERTAINTY NONE
  SET DESCRIPTION|FOLDER|LOCATION "value"
  ALLOCATION ... END ALLOCATION        (replaces that method's factors)
  REMOVE ALLOCATION [PHYSICAL|ECONOMIC|CAUSAL]
  DEFAULT ALLOCATION PHYSICAL|ECONOMIC|CAUSAL|NONE
  DOCUMENT ... END DOCUMENT            (sets the fields it names)
  SOCIAL "indicator", "raw value", risk level ...
  REMOVE SOCIAL "indicator"
  TYPE UNIT | TYPE LCI RESULT
  INFRASTRUCTURE [YES|NO]
END EDIT
EDIT FLOW "name"
  ADD PROPERTY "Mass" AS 2400 kg PER m3
  UPDATE PROPERTY "Mass" AS 2350 kg PER m3
  SET REFERENCE "Mass"
  SET CAS|FORMULA|SYNONYMS|DESCRIPTION|LOCATION "value" | NONE
  SET INFRASTRUCTURE YES|NO
END EDIT
EDIT SYSTEM "name"
  PARAMETER SET "name" [BASELINE] [DESCRIPTION "text"]
    name = value [IN PROCESS "process"]
  END PARAMETER SET
  ANALYSIS GROUP "name" [COLOUR "#rrggbb"]
    "process" [LOCATION "code"]
  END ANALYSIS GROUP
  REMOVE PARAMETER SET "name"
  REMOVE ANALYSIS GROUP "name"
  SET DESCRIPTION "text"
END EDIT
PARAMETERISE PROCESS "name" [LOCATION "code"] [ALL] CONFIRM
```

### Entities: actors, sources, units, locations, methods and every other type

| Command | Dialect | What it does |
|---|---|---|
| `FIND <TYPE>` | olcaBASIC | List entities of any type, by part of a name |
| `SHOW <TYPE>` | olcaBASIC | Show an entity of any type, as fields, as JSON-LD, or where it is used |
| `MAKE ACTOR` | olcaBASIC | Make an actor: a person or an organisation |
| `MAKE SOURCE` | olcaBASIC | Make a source: a report, standard or dataset reference |
| `MAKE CURRENCY` | olcaBASIC | Make a currency, for costs on exchanges |
| `MAKE LOCATION` | olcaBASIC | Make a location, with coordinates or a GeoJSON shape |
| `MAKE UNITS` / `MAKE UNIT GROUP` | olcaBASIC | Make a unit group: units and their conversion factors |
| `MAKE PROPERTY` / `MAKE FLOW PROPERTY` | olcaBASIC | Make a flow property: a quantity measured in a unit group |
| `MAKE SOCIAL INDICATOR` | olcaBASIC | Make a social indicator, for SOCIAL lines on a process |
| `MAKE DQ SYSTEM` | olcaBASIC | Make a data quality system: indicators and their scores |
| `EDIT <TYPE>` | olcaBASIC | Change an actor, source, currency, location, unit group, flow property, social indicator or data quality system |
| `MAKE METHOD` | olcaBASIC | Make an impact method: categories, factors, normalisation and weighting |
| `EDIT METHOD` | olcaBASIC | Change the categories, factors and NW sets of an impact method |

```basic
FIND <type> ["text"] [IN "folder"]
SHOW <type> "name or uuid" [JSON | USAGE]
MAKE ACTOR "name" [FOLDER "path"]
    ADDRESS "text"
    CITY "text"
    POSTCODE "text"
    COUNTRY "text"
    EMAIL "text"
    PHONE "text"
    FAX "text"
    WEBSITE "text"
    DESCRIPTION "text"
END ACTOR
MAKE SOURCE "name" [FOLDER "path"]
    REFERENCE "full citation"
    URL "address"
    YEAR n
    ATTACH "file"
    DESCRIPTION "text"
END SOURCE
MAKE CURRENCY "name" [FOLDER "path"]
    CODE "ISO code"
    FACTOR n
    REFERENCE "reference currency"
    DESCRIPTION "text"
END CURRENCY
MAKE LOCATION "name" [FOLDER "path"]
    CODE "code"
    LATITUDE n
    LONGITUDE n
    GEOMETRY "file.geojson"
    DESCRIPTION "text"
END LOCATION
MAKE UNITS "name" [FOLDER "path"]
    UNIT "name", factor [REFERENCE] [SYNONYMS "a; b"]
    ...
    DESCRIPTION "text"
END UNITS
MAKE PROPERTY "name" [FOLDER "path"]
    UNITS "unit group"
    TYPE PHYSICAL|ECONOMIC
    DESCRIPTION "text"
END PROPERTY
MAKE SOCIAL INDICATOR "name" [FOLDER "path"]
    ACTIVITY VARIABLE "text"
    ACTIVITY QUANTITY "flow property"
    ACTIVITY UNIT "unit"
    MEASURED IN "unit of measurement"
    EVALUATION "evaluation scheme"
    DESCRIPTION "text"
END SOCIAL INDICATOR
MAKE DQ SYSTEM "name" [FOLDER "path"]
    SOURCE "source"
    UNCERTAINTIES YES|NO
    INDICATOR "name"
    SCORE n "label" [DESCRIPTION "text"] [UNCERTAINTY n]
    ...
    DESCRIPTION "text"
END DQ SYSTEM
EDIT ACTOR|SOURCE|CURRENCY|LOCATION|UNITS|PROPERTY|SOCIAL INDICATOR|DQ SYSTEM "name" ... END EDIT
MAKE METHOD "name" [FOLDER "path"]
    DESCRIPTION "text"
    SOURCE "source"
    CODE "code"
    CATEGORY "name" UNIT "reference unit" [INPUT|OUTPUT] [CODE "code"]
        DESCRIPTION "text"
        PARAM name = value | FORMULA "formula"
        FACTOR "flow" [IN "compartment"], value [PER unit]
               [FORMULA "formula"] [LOCATION "code"] [UNCERTAINTY ...]
        ...
    END CATEGORY
    NW SET "name" [UNIT "weighted unit"]
        "category", normalisation [, weighting]
        ...
    END NW SET
END METHOD
EDIT METHOD "name" [CONFIRM]
    DESCRIPTION "text"
    CATEGORY "name" [UNIT "reference unit"]
        FACTOR "flow" [IN "compartment"], value ...
        REMOVE FACTOR "flow" [IN "compartment"]
        PARAM name = value
    END CATEGORY
    REMOVE CATEGORY "name"
    NW SET "name" [UNIT "weighted unit"]
        "category", normalisation [, weighting]
    END NW SET
    REMOVE NW SET "name"
END EDIT
```

### Parameters: variables that become openlca parameters

| Command | Dialect | What it does |
|---|---|---|
| `LET` | BASIC | Set a variable (LET may be left out: name = expression) |
| `UPDATE PARAMETER` | olcaBASIC | Set a variable and write the global parameter to openLCA now |

```basic
LET name = expression
  [UNCERTAINTY LOGNORMAL gm, gsd | NORMAL mean, sd |
               TRIANGLE min, mode, max | UNIFORM min, max | NONE]
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
| `SAVE RESULT AS` | olcaBASIC | Store the open result in the database as an openLCA result |
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
SAVE RESULT AS "name" [FOLDER "path"] [REPLACE] [IN name]
CLOSE RESULT [name | ALL]
```

### Scenarios: scenarios and sensitivity analysis

| Command | Dialect | What it does |
|---|---|---|
| `SCENARIO` | olcaBASIC | Define a scenario as a set of parameter values |
| `RUN SCENARIOS` | olcaBASIC | Calculate every scenario defined so far |
| `MAKE PROJECT` | olcaBASIC | Make a project: variants of product systems to compare |
| `CALCULATE PROJECT` | olcaBASIC | Calculate every enabled variant of a project and compare them |
| `SENSITIVITY` | olcaBASIC | Vary parameters up and down by a percentage, one at a time |

```basic
SCENARIO "name"
  LET parameter = value
END SCENARIO
RUN SCENARIOS ON "system" USING "method" [ALLOCATE method]
  [FROM CSV "scenarios.csv"]
  [SAVE "results.csv"]
END RUN
RUN SCENARIOS ON "system" USING "method" FROM SYSTEM
MAKE PROJECT "name" [FOLDER "path"]
    METHOD "method"
    NW SET "name"
    WITH COSTS
    WITH REGIONALISATION
    DESCRIPTION "text"
    VARIANT "name" SYSTEM "system" [AMOUNT n unit] [ALLOCATE method] [DISABLED]
        name = value [IN PROCESS "process"]
        DESCRIPTION "text"
    END VARIANT
    ...
END PROJECT
CALCULATE PROJECT "name"
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
| `EPD SAVE` | olcaBASIC | Write the EPD into openLCA as its own EPD entity, with a stored result per module |
| `RATING` | olcaBASIC | Rate how well a dataset represents what it stands for |
| `EPD DQ SHEET` | olcaBASIC | Write the register of the datasets the data quality assessment has to cover |
| `EPD DQ TABLE` | olcaBASIC | Write the data quality assessment table for the accompanying report |
| `EPD SENSITIVITY` | olcaBASIC | Vary groups of parameters together and sum the modules |
| `EPD DOCUMENT` | olcaBASIC | Write the EPD itself, in the sections of the International EPD System |
| `EPD EXPORT MODEL` | olcaBASIC | Write the whole model of the EPD folder as JSON, for a verifier |
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
  [BIOGENIC CONTENT PRODUCT n kg C [PACKAGING n kg C]]
  [BIOGENIC CONTENT PRODUCT FROM MASS n kg DRY [PACKAGING n kg C]]
  [BIOGENIC EXPORT A1|A2|A3 "co-product", n kg C]
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
EPD DATA QUALITY [PARAMETER SET "name" | FROM "scenarios.csv"]
EPD REPORT "file.csv" [LOCATION BASED]
EPD SAVE [REPLACE]
    [MANUFACTURER "actor"] [VERIFIER "actor"] [OPERATOR "actor"]
    [GENERATOR "actor"] [PCR "source"] [REGISTRATION "number"] [URN "urn"]
    [VALID FROM "DD/MM/YYYY"] [VALID UNTIL "DD/MM/YYYY"]
    [DESCRIPTION "text"]
RATING GEOGRAPHY "level" REASON "why"
RATING TECHNOLOGY "level" REASON "why"
RATING TIME "level" REASON "why"
EPD DQ SHEET "file.csv"
EPD DQ TABLE "file.md"
EPD SENSITIVITY BY n% [SAVE "file.csv"]
  GROUP "name" VARY parameter, parameter, ...
  ...
END EPD SENSITIVITY
EPD DOCUMENT "file.docx" | "file.md"
  STATEMENTS "statements.txt"
  OWNER "name"
  OWNER ADDRESS "address"
  OWNER CONTACT "e-mail or phone"
  OWNER DESCRIPTION "the organisation"
  [PRACTITIONER "who did the LCA, with contact details"]
  PRODUCT DESCRIPTION "what it is, its performance and use"
  PRODUCT IDENTIFICATION "standard, concession or other means"
  [PRODUCT CODE "UN CPC", "code", "name"]
  MANUFACTURING "the main processes"
  SITE "city, country"                       (one per site)
  [LIFESPAN "text"] [WEBSITE "address"] [RSL "text"]
  CONTENT "material", n kg [RECYCLED n%] [PRECONSUMER n%] [BIOGENIC n%]
  [PACKAGING "material", n kg]
  SVHC NONE | SVHC "name", "EC No.", "CAS No.", n%
  GEOGRAPHY module, module ... "scope"       (every declared module)
  SCENARIO module, module ... "description"  (every declared module after A3)
  OMITTED module, module ... "why"           (every module not declared)
  [MASS PER UNIT n] [AREA DENSITY n] [THICKNESS n] [DENSITY n] [LINEAR DENSITY n]
  [SOFTWARE "name and version"] [METHOD VERSION "EF 3.1"]
  [INFRASTRUCTURE "how capital goods are modelled"]
  [VERIFICATION "how"] [VERIFIER "who"] [APPROVED BY "who"] [TOOL "name"]
  [FOLLOW UP YES|NO]
  [REGISTRATION "number"] [VERSION DATE "YYYY-MM-DD"] [VALID UNTIL "YYYY-MM-DD"]
  [LICENSEE "name"] [DIAGRAM "file"] [IMAGE "file"] [LOGO "file"]
  [HISTORY "YYYY-MM-DD", "what changed"] [REFERENCE "text"]
  [ABBREVIATION "short", "meaning"] [ADDITIONAL "text"]
END EPD DOCUMENT
EPD EXPORT MODEL "file.json"
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
| `EXPORT <TYPE>` | olcaBASIC | Have openLCA write an entity and what it depends on as JSON-LD |
| `SAVE PROGRAM` / `SAVE "file.baslca"` | olcaBASIC | Write the program in memory to a file |

```basic
PRINT RESULTS
SAVE RESULTS "file.csv"
EXPORT <type> "name or uuid" TO "file.zip"
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
| `SHUTDOWN SERVER` | olcaBASIC | Stop openLCA's IPC server (terminal only) |
| `EXIT` / `QUIT` | olcaBASIC | Leave olcaBASIC |

```basic
HELP [topic or command]
REFRESH
CLEAR
SHUTDOWN SERVER CONFIRM
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
EPD SAVE                     ' the EPD and a result per module, into openLCA
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

- **Data quality.** `EPD DATA QUALITY` works over the impact
  indicators only, checks that the parts add up to each module's total,
  and refuses while a dataset that matters has no ratings. The ratings
  are yours to give, on the bridge or the process:

  ```basic
  BRIDGE "Sawn timber", m3
    PROVIDER "uuid of the background process"
    DATA SECONDARY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2024
    RATING GEOGRAPHY "Fair" REASON "Rest-of-World forestry applied to UK supply"
    RATING TECHNOLOGY "Good" REASON "Mechanised harvesting, as in UK practice"
    RATING TIME "Good" REASON "Valid 2010 to 2023"
  END BRIDGE
  ```

  `EPD DQ SHEET "register.csv"` lists every dataset that needs them,
  and `EPD DQ TABLE "assessment.md"` writes the table for the report.
- **Biogenic carbon.** With `BIOGENIC CARBON YES` the block declares
  the carbon in the product (`BIOGENIC CONTENT PRODUCT n kg C`, or
  `FROM MASS n kg DRY`), and `EPD CALCULATE` checks that the uptake in
  A1 to A3 matches it, that GWP-biogenic sums to zero over A to C, and
  that it is zero in D. A balance that does not close is an error.

`EPD SENSITIVITY BY 20% ... GROUP "Electricity" VARY a, b ... END EPD
SENSITIVITY` varies groups of parameters together and sums the modules.
`EPD EXPORT MODEL "model.json"` writes the whole model out for a
verifier.

`NEW FROM TEMPLATE "epd_skeleton" AS "my_epd.baslca"` writes a starting
point with a comment at every decision. `bridges_common` and
`sensitivity_epd` are the other two templates. `HELP EPD` has the full
syntax.

Still for the practitioner: which inventory item belongs in which
module, the ratings and their reasons, pedigree scores on every
exchange, and process documentation.
`EPD CHECK` lists what is missing; it does not invent it. The standards
and programme instructions are referred to by clause number only: you
need your own copies.

## Help us improve it

This is version 0.4. It has been tested offline (about 1,800 tests)
and against openLCA 2.7.0 with two ecoinvent-based databases, one with
the `EN15804+A2 (EF 3.1)` method, where a small EPD runs end to end and
its document is written. The known rough edges:

- Some of what openLCA's IPC server cannot answer is worked out by
  reading many processes: `DELETE FLOW` of a background flow, and
  `SHOW FLOW ... USAGE`. On ecoinvent that takes a long time.
- `EPD DOCUMENT` writes a draft in the order the International EPD
  System asks for. It is not the programme's own template, and it has
  tables, not charts. It is a draft until the statements, registration,
  dates and verification are given, and a verifier still reads it.
- `DELETE SYSTEM` does not check whether a project or a stored result
  refers to the system.

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

- openLCA 2 with its IPC server running (port 8080). Tested on 2.6 and
  2.7.0; attaching a file to a source needs 2.6.2 or later
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
