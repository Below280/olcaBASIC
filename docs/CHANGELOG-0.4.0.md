# olcaBASIC 0.4.0

olcaBASIC no longer needs `b280-olca-mcp`. The engine that talks to openLCA now lives in olcaBASIC, and the MCP server (from 2.0.0) depends on olcaBASIC instead of the other way round. Installing olcaBASIC brings in `olca-ipc` and nothing else.

Requires Python 3.11 or later (`olca-ipc` 2.4 does).

0.4.0 does three things. The engine moved into olcaBASIC. The language now reaches every method of openLCA's IPC server (68 of 68), 17 of openLCA's 18 entity types and every field a process, flow or product system can hold. And the places where a model could be built or calculated wrongly without an error are errors.

## Behaviour changes

Programs written for 0.3.0 keep working, except in the cases below. Each one used to pass quietly and now stops with an error that says what to type.

| Change | 0.3.0 | 0.4.0 | What to do |
|---|---|---|---|
| A `USE PROCESS` name that matches several processes | Warning; the first match was used | Error listing the location and UUID of each candidate | Add `LOCATION "code"` to the line, or `PROVIDER "uuid"` |
| A `USE FLOW` name that several flows share | Warning; the first match was used | Error listing the folder and UUID of each candidate. A flow in your `SET FLOW FOLDER` is still found first | Add `FOLDER "path"` to the line, or give the flow's UUID in place of its name |
| `EPD CHECK SKIP` under `PROGRAMME` | (new in 0.4.0) | Refused: a programme's EPD is always checked | Run `EPD CHECK` and fix what it finds. Without a programme `SKIP` still works |
| Unknown database family | Building went ahead with ecoinvent flow property names | `MAKE FLOW`, `BRIDGE` and anything else that creates a flow is refused | `DATABASE FAMILY "ecoinvent"` or `DATABASE FAMILY "flcac"` |
| Calculating a system that failed `VALIDATE` | Allowed | Refused for the rest of the session, until `VALIDATE` passes | Fix the links, or `DELETE SYSTEM` and `SYSTEM` again, then `VALIDATE` |
| Impact method names | Part of a name was enough if only one method matched (`USING "IPCC"`) | The full name is required; a near miss lists the close matches | Use the full name, for example `USING "IPCC 2021"`. `FIND METHOD "IPCC"` lists them |
| `SENSITIVITY` without `BY` | Varied by 20% | Parse error | Say the range: `BY 10%` |
| `SENSITIVITY` with nothing to vary | Ran and reported no matching parameters | Parse error | Add a `VARY` line or `FROM "file.csv"` |
| `ALLOCATE` with an unknown word | Reached openLCA and failed there | Parse error listing the valid words | `AS_DEFINED`, `PHYSICAL`, `ECONOMIC`, `CAUSAL` or `NONE` |
| A background process named straight in `MAKE PROCESS`, `EDIT PROCESS` or `LINK` (one outside the folders the program builds in) | A note, and nothing at all when no process folder was set; an error only inside an EPD `MODULE` | Error in every program, naming the process and giving the `BRIDGE` block to write. No setting turns it off | Write a bridge and use it: `BRIDGE "Cement", kg` / `PROVIDER "name" LOCATION "code"` / `END BRIDGE`, then `INPUT USE PROCESS "BRIDGE \| Cement \| kg", 300, kg`. `EDIT PROCESS` on a bridge may still name background processes |
| A `MAKE PROCESS` block run again after it was changed | Warning; the old process stayed, so results came from a model the program no longer described | Error listing every difference between the block and the stored process (amounts, formulas, providers, parameters, uncertainty, costs, allocation, documentation, `DATA` and `RATING` lines). An identical block is still a quiet no-op, so a program can be run twice. The same holds for `TOTAL` in an EPD module, and for a `BRIDGE` block that now names another provider than the bridge has | Change the process with `EDIT PROCESS "name" ... END EDIT`, or `CONFIRM DELETE ON`, `DELETE PROCESS "name"` and run the block again |
| Calculating a product system after `EDIT PROCESS`, `LINK`, `MOVE` or `PARAMETERISE` on one of its processes | Allowed, with a note about old links | Refused: the system is out of date. Every calculating command checks it. An edit that only sets the description, `DOCUMENT` fields or `DATA`, `CONTROL` and `RATING` lines leaves the systems as they are | `CONFIRM DELETE ON`, `DELETE SYSTEM "name"`, `SYSTEM "name"` (or `EPD SYSTEMS`), then `VALIDATE "name"` |
| A product system changed outside the session (after `RESET`, in a new session, or edited in the openLCA app) | The session's marks were all there was, so a new session could calculate an out-of-date system | Every calculation compares the system's links with what its foreground processes ask for now. An input added or removed, or a new default provider, is an error listing what changed. A changed amount alone is not (openLCA reads amounts when it calculates). Systems olcaBASIC builds carry a tag saying how they were linked, so a system built with `IGNORE_DEFAULTS` is not taken for out of date | Build the system again: `DELETE SYSTEM`, `SYSTEM`, `VALIDATE` |
| Calculating in a session that has not run `VALIDATE` on the system | Allowed; a failure from another session or before `RESET` was forgotten | `VALIDATE` runs first, with a note saying so, and a failure refuses the calculation | Fix the system, or build it again |
| A process of one EPD module used inside another module | Warning; its impacts were counted in both modules | Error | Give the second module its own input: a bridge, or a process of its own |
| `OUTPUT "name", ...` where no flow has that name | The flow was created, with a note | Error, as for `INPUT` | `OUTPUT MAKE FLOW "name", amount, unit` |
| A new elementary flow (`MAKE FLOW ... TO AIR`) calculated with a method that has no factor for it | It added zero without a word | Every calculating command is refused, naming the flow. The flow is tagged `olcaBASIC`, so later sessions check it too | Use a flow the method knows, give the flow a factor in a method of your own (`EDIT METHOD`), or accept it: `CALCULATE ... IGNORE FACTORS "flow"` (the output then says so) |
| `MONTECARLO` on a model with no uncertainty | Ran, and said every run was the same | Error before the runs start, when nothing in the foreground has an `UNCERTAINTY` and two trial runs agree | Put `UNCERTAINTY ...` on the `INPUT`, `OUTPUT` or `LET` lines that are uncertain |
| `ALLOCATE PHYSICAL` or `ECONOMIC` when a foreground process with several products has no factors for that method (or its own default method, when `ALLOCATE` is left out) | openLCA calculated without sharing anything out | Error naming the process and its products | `ALLOCATION PHYSICAL` / `"product", share` / `END ALLOCATION` in the process, or `ALLOCATE NONE` |
| `BRIDGE "Cement", kg` | Bridge named `Cement` | Bridge named `BRIDGE \| Cement \| kg` | Nothing. A bridge that already exists under the plain name is reused |
| `DELETE FLOW` | Refused by the parser | Allowed, after checking that nothing uses the flow | Nothing |
| `SAVE "file.baslca"` | Wrote the latest results as CSV into that file | Writes the program in memory | For results use a name that does not end in `.baslca` or `.bas`, or `SAVE RESULTS` |
| `LOAD` and `LIST` | Refused as unsupported | As on a BBC Micro: `LOAD "file"` puts a program in memory without running it, `LIST` shows it, `RUN` on its own runs it | Nothing |
| `MOVE` a flow or product system | "not yet supported" | Works | Nothing |
| Errors inside `PROCESS`, `EDIT`, `SCENARIO` and `SENSITIVITY` blocks | Reported the first line of the block | Report their own line | Nothing |
| A `PROCESS` block with a wrong name on one line | Flows on earlier lines had already been created | Nothing is created: every line is looked up before anything is written | Nothing |
| Dependency | Installed `b280-olca-mcp` and `mcp` | Installs `olca-ipc` only | Nothing |

## New in 0.4.0

**Session.** Run olcaBASIC from Python and get structured results back:

```python
from olcabasic import Session

s = Session(port=8080)          # or Session(offline=True)
r = s.run('CALCULATE "Concrete block" USING "EF v3.1"')
r.ok          # True or False
r.text        # what the terminal would have shown
r.data        # the results as dictionaries
r.errors      # [{"line": ..., "message": ..., "hint": ...}]
r.warnings    # [{"line": ..., "message": ..., "level": "warning" or "note"}]
```

Variables, folders, scenarios and the latest results persist between `run` calls. `run` holds a lock from start to finish, so two programs can never write to openLCA at once. `s.run(code, dry_run=True)` parses a program and checks what can be checked without openLCA.

**Every error has a line and a hint.** The hint says what to type instead.

**Rules that used to be advice are now enforced.** See the table above: ambiguous names, the database family, validation before calculation, full method names. `CHECK ... TIER 1` always ends by saying that it checked structure only. Every default the interpreter applies (allocation, linking, `TOP`, `RUNS` and so on) is stated in the output the first time it is used in a session.

**One command reference.** `HELP`, `HELP <topic>` and `HELP <command>` (for example `HELP MAKE PROCESS`) are generated from one registry, as is the reference section of the README. The old help text, which still described `INPUT NEW`, is gone.

**Three dialects, side by side.** Navigation has an Acorn form and a Linux form for every command, and `HELP` shows both:

| Acorn | Linux | |
|---|---|---|
| `CAT` | `LS` | List the current folder |
| `DIR "folder"` | `CD "folder"` | Go to a folder |
| `UP` | `CD ..` | Up one folder |
| `BACK` | `CD -` | Back to the previous folder (new) |
| `DIR "/"` | `CD /` | To the top level (new) |
| `CDIR "name"` | | Create a folder and go into it |
| | `MKDIR "name"` | Create a folder and stay where you are (new) |
| | `PWD` | Show where you are |

**New commands.**

- `FIND SYSTEM "text"`, alongside `FIND PROCESS`, `FIND FLOW`, `FIND METHOD` and `FIND UNIT`. `FIND PROCESS` now shows each process's location, and `AT "GB"` filters by it.
- `SHOW SYSTEM "name"`, `SHOW SYSTEM "name" PARAMS`, `SHOW SYSTEM "name" LINKS "text"`, `SHOW GLOBAL PARAMS "text"`, `SHOW PROCESS "name" QUALITY`.
- `SHOW FLOW "name" USAGE [LIMIT n]`: where a flow is used.
- `DELETE FLOW "name"`: deletes a flow once every process has been read and none uses it. A flow used by a process, an impact category, a stored EPD or a stored result is refused, and the error names what uses it.
- `MOVE FLOW` and `MOVE SYSTEM`.
- `EDIT PROCESS`: when a flow appears more than once in a process, `REMOVE INPUT "name" INDEX 2` (or `PROVIDER`, `LOCATION`, `AMOUNT`) removes one of them, and `UPDATE INPUT "name" INDEX 2, ...` updates one.
- `SAVE PROGRAM "file.baslca"`: writes out every program that has run without error in the session, as the record of the work.
- `MAX(a, b)` works (it was a reserved word and could not be called).
- `PARAMETERISE PROCESS "name" [LOCATION "code"] CONFIRM`: replaces the fixed amounts of the product and waste exchanges of a process with parameters, so a background process (the shares of a market mix, say) can be varied by scenarios and sensitivity. It changes the process for good, so it is refused without `CONFIRM`, says how many amounts it would change, and tells you to back up the database first. `ALL` takes the elementary flows too; it asks twice before writing (type `YES`, then `PARAMETERISE`), and only runs in the olcaBASIC terminal, never through a Session or the MCP.

**EPDs to EN 15804+A2.** New commands that enforce the rules as the model is built:

- `EPD "name" ... END EPD` defines the EPD: declared unit, method, folder, modules, biogenic carbon, and optionally the programme, PCR, database and declared cut-offs. It is checked as it is read. A1 to A3 are always declared; C1 to C4 and D together, or not at all with an `EXEMPT C AND D` block (EN 15804+A2, clause 5.2). The method must be an EN 15804+A2 method with the full indicator set.
- `MODULE A1 ... TOTAL "name" ... END MODULE` builds the processes of one module and the process that adds them up. Names get their prefixes. An input must come from a bridge or from a process of the EPD.
- `EPD SYSTEMS`, `EPD CHECK`, `EPD CALCULATE`, `EPD REPORT "file.csv"`, in that order: each refuses to run until the one before has passed. Without a `PROGRAMME`, `EPD CHECK SKIP "reason"` goes on without the check and writes the reason into the report; under a programme there is no `SKIP`. `EPD STATUS` shows how far the work has got; `EPD CLOSE` ends EPD mode.
- The report has the indicators in the method's order, a column per module, A1-A3 as the only total and module D on its own, under a header with the product, EPD type, unit, method, database family, olcaBASIC version and date.
- `PROGRAMME "IES"` adds the International EPD System's rules (General Programme Instructions 5.1.0, Annex A) as errors with no override, and `EPD DATA QUALITY`, which works out the share of primary data, the proxy share of each indicator, data age and the list the data quality assessment has to cover. The profile is `olcabasic/workflows/programmes/ies.py`; every threshold in it is a named value.
- New lines inside `MAKE PROCESS`, `EDIT PROCESS` and `BRIDGE`: `DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n`, `CONTROL DIRECT|NONE`, and for bridges `ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION`, `COUNTRY`, `REGION`, `ENERGY SOURCE`, `LOCATION BASED PROVIDER`. They are stored on the process as tags (`epd:data=PRIMARY` and so on), the year also as the validity dates of the process documentation. They work outside an EPD too.
- `NEW FROM TEMPLATE "name" AS "file"` copies one of three templates: `epd_skeleton`, `bridges_common`, `sensitivity_epd`.

`EPD` and `MODULE` are not reserved words: programs that use them as variable names still run.

Clause numbers are given throughout; none of the text of EN 15804, the programme instructions or a PCR is in the package.

**Results stay open.** `CALCULATE` keeps its result open in openLCA as the current result, and `RESULT` reads from it without calculating again:

- `CALCULATE "system" USING "method" [ALLOCATE ...] [AMOUNT n unit [PROPERTY "x"]] [WITH COSTS] [WITH REGIONALISATION] [NW SET "name"] [PARAMETER SET "name"] [IGNORE FACTORS "flow"] [AS name]`. `AS name` keeps a named result open alongside the current one; a session holds 5 at most. `CLOSE RESULT [name | ALL]` disposes them, as do the next `CALCULATE`, `RESET`, the end of a program run from a file and the end of the session, an error included.
- `RESULT IMPACTS`, `RESULT CATEGORIES`, `RESULT PROCESSES`, `RESULT DEMAND`, `RESULT FLOWS`, `RESULT FLOW "x" BY PROCESS`, `RESULT CONTRIBUTION BY PROCESS | BY FLOW | OF PROCESS "x"`, `RESULT FACTORS`, `RESULT INTENSITY`, `RESULT SCALING`, `RESULT TOTALITY`, `RESULT REQUIREMENTS`, `RESULT TREE`, `RESULT COSTS`, `RESULT NORMALISED`, `RESULT WEIGHTED`, `RESULT SANKEY`, and `RESULT IMPACTS | FLOWS | COSTS BY GROUP` for the analysis groups of the system. Each takes `IN name`, `TOP n` and `SAVE "file.csv"`. A query the result cannot answer says what to calculate instead (`RESULT COSTS` needs `WITH COSTS`, `RESULT NORMALISED` an `NW SET`).
- `CONTRIBUTION`, `INVENTORY` and `TREE` read the current result when it is the same system, method and allocation.
- `SAVE RESULT AS "name"` stores the open result in the database as an openLCA result.
- `MONTECARLO` is a real simulation now. It used to ask an ordinary result for another run, which openLCA refuses and the client hides, so every run was the same.

**Every field of a process, a flow and a product system.** New lines in `MAKE PROCESS`, `EDIT PROCESS` and on `LET`, each read back by `SHOW PROCESS "x" FIELDS | DOCUMENT | ALLOCATION | SOCIAL`:

- `UNCERTAINTY LOGNORMAL gm, gsd | NORMAL mean, sd | TRIANGLE min, mode, max | UNIFORM min, max` and `BASE UNCERTAINTY n` on an exchange or a parameter. The numbers are checked.
- `AVOIDED` on an output (never the reference product); `COST value [FORMULA "x"] CURRENCY "code"`; `SITE "location"` for regionalised calculation; `PROPERTY "flow property"`.
- `ALLOCATION PHYSICAL|ECONOMIC|CAUSAL ... END ALLOCATION` (shares that add up to 1) and `DEFAULT ALLOCATION`.
- `DOCUMENT ... END DOCUMENT`: all 26 fields of openLCA's process documentation, sources and reviewers by name.
- `SOCIAL "indicator", "raw value", risk level ...`; `TYPE UNIT | LCI RESULT`; `INFRASTRUCTURE`; `PROCESS PEDIGREE`.
- `SYSTEM "x" ... END SYSTEM` and `EDIT SYSTEM` take `PARAMETER SET "name" ... END PARAMETER SET` (openLCA's stored scenarios; `RUN SCENARIOS ... FROM SYSTEM` runs them) and `ANALYSIS GROUP "name" ... END ANALYSIS GROUP`. `SYSTEM` linking gains `IGNORE_DEFAULTS`, `PREFER UNIT|SYSTEM PROCESSES` and `CUTOFF`.
- `MAKE FLOW` and `EDIT FLOW` take `CAS`, `FORMULA`, `SYNONYMS`, `DESCRIPTION`, `LOCATION` and `INFRASTRUCTURE`.

**Every entity type.** `FIND`, `SHOW [JSON | USAGE]`, `DELETE`, `MOVE` and `EXPORT ... TO "file.zip"` work on every type: `PROCESS`, `SYSTEM`, `FLOW`, `PROPERTY`, `UNITS`, `PARAMETER`, `METHOD`, `CATEGORY`, `LOCATION`, `DQ SYSTEM`, `ACTOR`, `SOURCE`, `CURRENCY`, `SOCIAL INDICATOR`, `PROJECT`, `RESULT` and `EPD`. `SHOW ... JSON` prints openLCA's own JSON-LD; nothing writes raw JSON.

- `MAKE` and `EDIT` blocks for `ACTOR`, `SOURCE` (with `ATTACH "file"`), `CURRENCY`, `LOCATION` (with `GEOMETRY "file.geojson"`), `UNITS`, `PROPERTY`, `SOCIAL INDICATOR` and `DQ SYSTEM`.
- `MAKE METHOD ... END METHOD` and `EDIT METHOD`: categories, characterisation factors and normalisation and weighting sets. A method or category olcaBASIC did not make is refused without `CONFIRM`, and with it a person at the terminal has to answer: such methods are licensed and shared by every model.
- `MAKE PROJECT ... END PROJECT` and `CALCULATE PROJECT "name"`: variants compared, one calculation each.
- Deleting is refused while anything still points at the entity.
- `FLOW MAP` is in openLCA's data format but not in its IPC server, so the commands for it parse and say so.

**EPD toolkit.** Below280's EPD scripts as commands:

- `EPD SAVE` writes the finished EPD into openLCA as its own EPD entity, with a stored result per module. `EPD SYSTEMS` sets an analysis group per module.
- `EPD DATA QUALITY` counts the impact indicators only (the 13 core and 6 additional indicators of EN 15804+A2, Tables 3 and 4, and GWP-GHG, found by the code in brackets at the end of each category name), not all 38 categories. A residual check makes sure the parts add up to each module's total. `PARAMETER SET "name"` and `FROM "scenarios.csv"` run it per scenario.
- `RATING GEOGRAPHY|TECHNOLOGY|TIME "level" REASON "why"` on a bridge or a process records how well a dataset represents what it stands for (the five levels of EN 15804+A2, Annex E). The ratings are kept in the process description, where openLCA shows them. `EPD DATA QUALITY` refuses while a dataset in the 80% coverage of any impact indicator is unrated. `EPD DQ SHEET "file.csv"` writes the register; `EPD DQ TABLE "file.md"` the assessment table.
- Under `BIOGENIC CARBON YES`: `BIOGENIC CONTENT PRODUCT n kg C [PACKAGING n kg C]` (or `FROM MASS n kg DRY`) is required, and `EPD CALCULATE` checks that the uptake in A1 to A3 matches the content, that GWP-biogenic sums to zero over A to C and that it is zero in D. `BIOGENIC EXPORT A3 "co-product", n kg C` declares carbon that leaves with a co-product. The renewable primary energy used as material (PERM) is not checked: PCR 2019:14 allows three ways of declaring it.
- `EPD SENSITIVITY BY n% ... GROUP "name" VARY a, b ... END EPD SENSITIVITY` moves groups of parameters together, recalculates only the modules that hold them, and reports A to C and D separately. A parameter no module holds is an error.
- `EPD EXPORT MODEL "file.json"` writes the whole model for a verifier.
- Several products in one program: one `SUB` per product, shared bridges built once, `EPD CLOSE` between them.

**Engine.** `olcabasic.engine.Engine` is the class that was `b280_olca_mcp.functions.LCAFunctions`, with the same methods and return shapes (`LCAFunctions` is kept as an alias). Additions: `find_process`, `find_system`, `find_method`, `get_descriptors`, `clear_caches`, `move_entity`, `process_candidates`, `describe_process`, `find_method_strict`, `processes_in_folder`, `get_process_tags`, `set_process_tags`, `get_method_categories`, `process_structure`, `process_contributions`, `set_switched_provider`, `parameterise_process`. The class is now put together from six modules (`core`, `explore`, `build`, `audit`, `calculate`, `analysis`); `olcabasic.engine.Engine` is the one name to import.

## Fixed

- A save that openLCA refuses is an error. `olca-ipc` logs a refused save and carries on, so a program could believe it had written what it had not. openLCA keeps 255 characters of tags per process and refuses a save that overruns them: three `RATING` reasons used to lose the whole data declaration that way.
- `SENSITIVITY` and scenarios no longer take a parameter of another process for a global parameter. openLCA lists process parameters among the parameter descriptors, and one that was not in the system was "varied" without changing anything.
- `RESULT ... BY GROUP` says why it is empty when openLCA returns nothing. In a large system openLCA only follows a group through processes that are in a group themselves, so a group has to hold the process the reference process uses directly (the bridge, not the background process behind it).
- A SUB's local variable used as an amount is written as its value, not as a formula naming a parameter openLCA does not have.
- EPD module systems are found by their reference process, so a second product in the same program no longer reuses the first product's systems.

- A failed product system creation that left a system behind now says so and names the commands to inspect or remove it.
- The `DATA` example in `HELP` quoted the name but not the unit, which parsed and then failed when run. Units in `DATA` go in quotes: `DATA "BRIDGE | Cement | kg", 300, "kg"`.
- Usage look-ups (`data/get/usage`) and results by tag (`result/tag-results-of-*`) no longer say they need openLCA 2.7. Checked live on 13/11/2026: openLCA 2.7.0 does not have them. olcaBASIC still asks the server, so they will work once a release has them. Attaching a file to a source works on 2.7.0.
- A connection that openLCA drops in the middle of a request, or refuses, is reported in plain words with what to check, not as the HTTP library's error. Found live: openLCA 2.7.0 on its default memory (3.5 GB) dropped the connection during a contribution analysis of an ecoinvent system and restarted itself.
