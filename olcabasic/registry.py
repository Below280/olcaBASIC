"""
The olcaBASIC command reference: one entry per command.

This is the only place commands are documented. HELP, HELP <topic>,
HELP <command>, the command reference in the README and the overview
the MCP server gives to an assistant are all generated from the entries
below, so they cannot drift apart. A test checks that every statement
the parser can produce has an entry here, and that every example parses.

To document a new command, add a Command to COMMANDS. To refresh the
README after a change:

    python -m olcabasic.registry --readme README.md
"""

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

# Dialects. olcaBASIC speaks three, plus its own LCA commands.
BASIC = "BASIC"            # Dartmouth BASIC, 1964 onwards
ACORN = "Acorn"            # Acorn Electron / BBC Micro filing commands
LINUX = "Linux"            # shell equivalents of the Acorn commands
OLCA = "olcaBASIC"         # the LCA commands

# Topics, in the order HELP lists them.
TOPICS: Dict[str, str] = {
    "NAVIGATION": "Moving round the database's folders",
    "EXPLORE": "Finding and inspecting what is in the database",
    "BUILD": "Creating flows, processes, bridges and product systems",
    "EDIT": "Changing what already exists",
    "ENTITIES": "Actors, sources, units, locations, methods and every "
                "other type",
    "PARAMETERS": "Variables that become openLCA parameters",
    "CALCULATE": "Impact results and where they come from",
    "RESULT": "Reading more from a result that is open",
    "SCENARIOS": "Scenarios and sensitivity analysis",
    "CHECK": "Checking a model before trusting its results",
    "EPD": "Environmental product declarations (EN 15804+A2)",
    "OUTPUT": "Showing and saving results",
    "PROGRAMMING": "BASIC: variables, loops, conditions, subroutines",
    "SESSION": "Help and housekeeping",
}

# Old HELP topic names that still work.
TOPIC_ALIASES = {"RESULTS": "RESULT", "FOLDER": "NAVIGATION", "FOLDERS": "NAVIGATION",
                 "BASIC": "PROGRAMMING", "AUDIT": "CHECK",
                 "SENSITIVITY ANALYSIS": "SCENARIOS"}


@dataclass(frozen=True)
class Command:
    name: str                       # primary form, e.g. "CAT"
    usage: str                      # one line
    summary: str                    # one line, no full stop
    example: str                    # a program that parses
    topic: str
    dialect: str = OLCA
    aliases: Tuple[str, ...] = ()   # other words for the same command
    alias_dialect: str = ""         # dialect of the aliases, if different
    syntax: str = ""                # full form, several lines; default usage
    notes: str = ""                 # detail shown by HELP <command>
    statements: Tuple[str, ...] = ()  # AST classes this entry documents

    @property
    def heading(self) -> str:
        """'CAT / LS': the primary form and its aliases side by side."""
        return " / ".join((self.name,) + self.aliases)

    @property
    def full_syntax(self) -> str:
        return self.syntax or self.usage

    @property
    def ipc(self) -> Tuple[str, ...]:
        """The openLCA IPC methods this command uses (see IPC_USE)."""
        return IPC_USE.get(self.name, ())


COMMANDS: List[Command] = [

    # ── NAVIGATION ───────────────────────────────────────────
    Command(
        name="CAT", aliases=("LS",), dialect=ACORN, alias_dialect=LINUX,
        topic="NAVIGATION",
        usage='CAT ["folder"] [FLOWS|PROCESSES|SYSTEMS] [*pattern*]',
        summary="List the folders and entries in the current folder",
        example='CAT\nCAT "00: My model"\nLS *concrete*',
        notes="CAT lists a folder, as *CAT did on the Acorn Electron. It "
              "does not print a file as the Linux cat does.",
        statements=("CatStmt",)),
    Command(
        name="DIR", aliases=("CD",), dialect=ACORN, alias_dialect=LINUX,
        topic="NAVIGATION",
        usage='DIR "folder"',
        summary="Go to a folder (DIR on its own shows where you are)",
        example='DIR "C:Manufacturing"\nCD "00: My model"\nDIR\nCD /',
        notes="The folder can be relative to the current one or a full "
              "path. DIR \"/\" and CD / go to the top level. A folder "
              "that does not exist is an error: use CDIR or MKDIR to "
              "create one.",
        statements=("DirStmt", "CdStmt")),
    Command(
        name="UP", aliases=("CD ..",), dialect=ACORN, alias_dialect=LINUX,
        topic="NAVIGATION",
        usage="UP",
        summary="Go up one folder",
        example="UP\nCD ..",
        statements=("UpStmt",)),
    Command(
        name="BACK", aliases=("CD -",), dialect=ACORN, alias_dialect=LINUX,
        topic="NAVIGATION",
        usage="BACK",
        summary="Go back to the folder you were in before",
        example="BACK\nCD -",
        statements=("BackStmt",)),
    Command(
        name="CDIR", dialect=ACORN, topic="NAVIGATION",
        usage='CDIR "name"',
        summary="Create a folder, go into it, and build there from now on",
        example='CDIR "00: My model"',
        notes="The folder appears in openLCA when the first process or "
              "flow is built in it. CDIR goes into the new folder, as "
              "*CDIR followed by *DIR would on an Acorn; the Linux MKDIR "
              "creates it and stays where you are.",
        statements=("CdirStmt",)),
    Command(
        name="MKDIR", dialect=LINUX, topic="NAVIGATION",
        usage='MKDIR "name"',
        summary="Create a folder without going into it",
        example='MKDIR "00: My model"',
        notes="Unlike CDIR, MKDIR does not move you and does not change "
              "where new processes are built. Follow it with DIR, or with "
              "SET PROCESS FOLDER, to use the folder.",
        statements=("MkdirStmt",)),
    Command(
        name="PWD", dialect=LINUX, topic="NAVIGATION",
        usage="PWD",
        summary="Show where you are browsing and where new things are built",
        example="PWD",
        statements=("PwdStmt",)),
    Command(
        name="NAVIGATE", topic="NAVIGATION",
        usage="NAVIGATE PROCESSES|FLOWS|METHODS|SYSTEMS",
        summary="Choose which tree CAT, DIR and UP move through",
        example="NAVIGATE FLOWS",
        notes="NAVIGATE on its own shows a menu in the terminal.",
        statements=("NavigateStmt",)),
    Command(
        name="SET PROCESS FOLDER", aliases=("SET FOLDER",), topic="NAVIGATION",
        usage='SET PROCESS FOLDER "path"',
        summary="Say where new processes are built",
        example='SET PROCESS FOLDER "00: My model"',
        notes="Browsing never changes where things are built. Only SET "
              "PROCESS FOLDER, SET FLOW FOLDER and CDIR do.",
        statements=("SetFolderStmt",)),
    Command(
        name="SET FLOW FOLDER", topic="NAVIGATION",
        usage='SET FLOW FOLDER "path"',
        summary="Say where new flows are built",
        example='SET FLOW FOLDER "00: My model/Flows"',
        statements=("SetFolderStmt",)),

    # ── EXPLORE ──────────────────────────────────────────────
    Command(
        name="FIND PROCESS", topic="EXPLORE",
        usage='FIND PROCESS "text" [AT "location"] [IN "folder"]',
        summary="Search processes by name",
        example='FIND PROCESS "cement"\nFIND PROCESS "electricity" IN "D:Electricity"',
        notes="Shows name, folder and UUID. Use it to get the exact name "
              "or the UUID for USE PROCESS and PROVIDER.",
        statements=("FindStmt",)),
    Command(
        name="FIND FLOW", topic="EXPLORE",
        usage='FIND FLOW "text" [IN "folder"]',
        summary="Search flows by name",
        example='FIND FLOW "Carbon dioxide"',
        statements=("FindStmt",)),
    Command(
        name="FIND SYSTEM", topic="EXPLORE",
        usage='FIND SYSTEM "text"',
        summary="Search product systems by name",
        example='FIND SYSTEM "concrete"',
        statements=("FindStmt",)),
    Command(
        name="FIND METHOD", topic="EXPLORE",
        usage='FIND METHOD "text"',
        summary="Search impact methods by name",
        example='FIND METHOD "EF"',
        statements=("FindStmt",)),
    Command(
        name="FIND UNIT", topic="EXPLORE",
        usage='FIND UNIT "unit"',
        summary="Look up a unit and the flow property it belongs to",
        example='FIND UNIT "kWh"',
        statements=("FindStmt",)),
    Command(
        name="FIND CHEMICAL", topic="EXPLORE",
        usage='FIND CHEMICAL "name or CAS number"',
        summary="Look up a chemical's synonyms on PubChem",
        example='FIND CHEMICAL "caustic soda"',
        notes="This sends the name to PubChem over the internet.",
        statements=("FindStmt",)),
    Command(
        name="SHOW PROCESS", topic="EXPLORE",
        usage='SHOW PROCESS "name" [INPUTS|OUTPUTS|PARAMS|QUALITY|FIELDS|DOCUMENT|ALLOCATION|SOCIAL]',
        summary="Show a process: exchanges, parameters, data quality, and its other fields",
        syntax='SHOW PROCESS "name" [INPUTS|OUTPUTS|PARAMS|QUALITY|LOCATION|'
               'DESCRIPTION|\n                     FIELDS|DOCUMENT|ALLOCATION|SOCIAL]',
        example='SHOW PROCESS "Concrete block"\nSHOW PROCESS "Concrete block" INPUTS',
        notes="FIELDS shows what MAKE PROCESS can set besides the "
              "exchanges: type, uncertainty, avoided products, costs, "
              "sites, allocation factors, documentation and social "
              "aspects, in the form they are typed. DOCUMENT, ALLOCATION "
              "and SOCIAL show one of those.",
        statements=("ShowStmt",)),
    Command(
        name="SHOW FLOW", topic="EXPLORE",
        usage='SHOW FLOW "name" [UNITS|DESCRIPTION|FIELDS|USAGE [LIMIT n]]',
        summary="Show a flow: type, folder, units, or where it is used",
        example='SHOW FLOW "Concrete block" UNITS\nSHOW FLOW "Concrete block" USAGE LIMIT 5',
        notes="USAGE lists the processes and impact categories that use "
              "the flow. openLCA cannot answer that directly, so every "
              "process is read until LIMIT uses are found (10 by default): "
              "slow on a large database.",
        statements=("ShowStmt",)),
    Command(
        name="SHOW SYSTEM", topic="EXPLORE",
        usage='SHOW SYSTEM "name" [PARAMS ["text"] | LINKS ["text"] | SETS | GROUPS]',
        summary="Show a product system, its parameters, links, parameter sets or groups",
        example='SHOW SYSTEM "Concrete block"\nSHOW SYSTEM "Concrete block" LINKS "electricity"',
        notes="Without a sub-command it shows the folder, the UUID and "
              "whether the system passed VALIDATE in this session.",
        statements=("ShowStmt",)),
    Command(
        name="SHOW GLOBAL PARAMS", topic="EXPLORE",
        usage='SHOW GLOBAL PARAMS ["text"]',
        summary="List global parameters, optionally those whose name contains a text",
        example='SHOW GLOBAL PARAMS "cement"',
        statements=("ShowStmt",)),
    Command(
        name="SHOW PARAMETER", topic="EXPLORE",
        usage='SHOW PARAMETER "name" [VALUE|DESCRIPTION]',
        summary="Show a global parameter",
        example='SHOW PARAMETER "cement_mass"',
        statements=("ShowStmt",)),
    Command(
        name="DATABASE INFO", aliases=("PRINT DATABASE", "DATABASE"),
        topic="EXPLORE",
        usage="DATABASE INFO",
        summary="Count what is in the database and name its family",
        example="DATABASE INFO",
        statements=("PrintStmt",)),
    Command(
        name="DATABASE FAMILY", topic="EXPLORE",
        usage='DATABASE FAMILY "ecoinvent"|"flcac"',
        summary="Say which flow property names the database uses",
        example='DATABASE FAMILY "ecoinvent"',
        notes="The family is detected when olcaBASIC connects. ecoinvent "
              "covers ecoinvent, EN15804GD, HiQLCD and BAFU; flcac covers "
              "the US LCA Commons, US LCI and USEEIO.",
        statements=("PrintStmt",)),
    Command(
        name="PRINT PROCESSES", topic="EXPLORE",
        usage='PRINT PROCESSES("text" [, "folder"])',
        summary="Search processes (same as FIND PROCESS)",
        example='PRINT PROCESSES("cement")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT METHODS", topic="EXPLORE",
        usage='PRINT METHODS(["text"])',
        summary="List impact methods",
        example='PRINT METHODS("EF")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT SYSTEMS", topic="EXPLORE",
        usage='PRINT SYSTEMS(["text"])',
        summary="List product systems",
        example="PRINT SYSTEMS",
        statements=("PrintStmt",)),
    Command(
        name="PRINT DETAILS", topic="EXPLORE",
        usage='PRINT DETAILS("process")',
        summary="Show a process (same as SHOW PROCESS)",
        example='PRINT DETAILS("Concrete block")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT PARAMS", topic="EXPLORE",
        usage='PRINT PARAMS("system")',
        summary="List the parameters a product system can redefine",
        example='PRINT PARAMS("Concrete block")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT GLOBAL PARAMS", topic="EXPLORE",
        usage='PRINT GLOBAL PARAMS(["text"])',
        summary="List global parameters",
        example='PRINT GLOBAL PARAMS("cement")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT LINKS", topic="EXPLORE",
        usage='PRINT LINKS("system" [, "text"])',
        summary="Show which provider supplies each input in a product system",
        example='PRINT LINKS("Concrete block", "electricity")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT QUALITY", topic="EXPLORE",
        usage='PRINT QUALITY("process")',
        summary="Show the data quality (pedigree) entries of a process",
        example='PRINT QUALITY("Concrete block")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT UNITS", topic="EXPLORE",
        usage='PRINT UNITS("unit")',
        summary="Look up a unit (same as FIND UNIT)",
        example='PRINT UNITS("kWh")',
        statements=("PrintStmt",)),
    Command(
        name="PRINT DQ SYSTEMS", topic="EXPLORE",
        usage="PRINT DQ SYSTEMS",
        summary="List the data quality systems that can be used as schemas",
        example="PRINT DQ SYSTEMS",
        statements=("PrintStmt",)),

    # ── BUILD ────────────────────────────────────────────────
    Command(
        name="MAKE PROCESS", aliases=("PROCESS",), topic="BUILD",
        usage='MAKE PROCESS "name" ... END PROCESS',
        summary="Create a process from INPUT and OUTPUT lines",
        syntax='''MAKE PROCESS "name" [LOCATION "code"]
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
END PROCESS''',
        example='''MAKE PROCESS "Concrete block"
  FOLDER "00: My model"
  OUTPUT MAKE FLOW "Concrete block", 1, m3, PRODUCT
  INPUT USE PROCESS "BRIDGE | Cement | kg", 300, kg
  OUTPUT "Carbon dioxide, fossil", 5, kg TO AIR
END PROCESS''',
        notes="Exactly one line is marked PRODUCT: the reference product.\n"
              "Run again for a process that exists, the block changes "
              "nothing, as long as it still says what the database holds. "
              "If it does not (an amount, a formula, a provider, a "
              "parameter or any other line differs), it is an error that "
              "lists the differences: change the process with EDIT "
              "PROCESS, or DELETE PROCESS and run the block again.\n"
              "An OUTPUT whose name matches no flow is an error: OUTPUT "
              "MAKE FLOW creates one. A new elementary flow (MAKE FLOW ... "
              "TO AIR) has no characterisation factor in any method, and "
              "calculating is refused until it has one or is accepted "
              "with IGNORE FACTORS (HELP CALCULATE).\n"
              "USE PROCESS finds an existing process and links it as the "
              "provider; USE FLOW links a flow with no provider; MAKE FLOW "
              "creates the flow, or reuses one with the same name.\n"
              "A name that matches several processes or flows is an error "
              "that lists them: pick a process with LOCATION or PROVIDER, "
              "and a flow with FOLDER or its UUID.\n"
              "An amount written as a number becomes a process parameter. "
              "An amount written with a variable stays a formula, and the "
              "variable becomes a global parameter.\n"
              "UNCERTAINTY puts a distribution on an amount, for MONTECARLO. "
              "The numbers are checked: a geometric standard deviation "
              "above 1, a standard deviation above 0, minimum <= mode <= "
              "maximum.\n"
              "AVOIDED marks a co-product as an avoided product (never the "
              "reference product). COST needs a currency that exists "
              "(FIND CURRENCY). SITE gives the exchange its own location, "
              "for regionalised calculation; LOCATION on the same line "
              "still picks the provider.\n"
              "ALLOCATION blocks hold the factors of one method: one line "
              "per product, shares between 0 and 1 that add up to 1. "
              "Causal factors are given per exchange (FOR INPUT \"flow\").\n"
              "DOCUMENT holds openLCA's process documentation, one field "
              "per line: COMPLETENESS, COMPLIANCE, COPYRIGHT YES|NO, "
              "CREATED, DATA COLLECTION, DATA SELECTION, DATA TREATMENT, "
              "DOCUMENTOR, FLOW COMPLETENESS, GENERATOR, GEOGRAPHY, "
              "INTENDED APPLICATION, INVENTORY METHOD, MODELLING "
              "CONSTANTS, OWNER, PROJECT, PUBLICATION, RESTRICTIONS, "
              "REVIEW, SAMPLING, SOURCE, TECHNOLOGY, TIME, USE ADVICE, "
              "VALID FROM, VALID UNTIL. Dates are DD/MM/YYYY or "
              "YYYY-MM-DD. Actors and sources are named, and must exist "
              "(MAKE ACTOR, MAKE SOURCE).\n"
              "Every line of the block is checked before anything is "
              "written. SHOW PROCESS \"name\" FIELDS reads these back.\n"
              "Running the block twice does not create a second process: "
              "it warns and leaves the first one alone.\n"
              "DATA and CONTROL declare where the data comes from and "
              "whether the manufacturer controls the process (HELP DATA PRIMARY).",
        statements=("ProcessStmt",)),
    Command(
        name="MAKE FLOW", aliases=("FLOW",), topic="BUILD",
        usage='MAKE FLOW "name", unit, PRODUCT|WASTE|ELEMENTARY [FOLDER "path"]',
        summary="Create a flow (or reuse the one that already has that name)",
        syntax='''MAKE FLOW "name", unit, PRODUCT|WASTE|ELEMENTARY [FOLDER "path"]
  [CAS "number"] [FORMULA "chemical formula"] [SYNONYMS "a; b"]
  [DESCRIPTION "text"] [LOCATION "code"] [INFRASTRUCTURE]
MAKE FLOW "name", unit TO AIR|WATER|SOIL
MAKE FLOW "name", unit FROM NATURE''',
        example='MAKE FLOW "Concrete block", m3, PRODUCT',
        notes="FLOW without MAKE looks for an existing flow first. The "
              "extra fields are written when the flow is created; on a "
              "flow that exists already they are left alone (EDIT FLOW "
              "changes them).",
        statements=("FlowStmt",)),
    Command(
        name="BRIDGE", aliases=("MAKE BRIDGE",), topic="BUILD",
        usage='BRIDGE "name", unit [WASTE] ... END BRIDGE',
        summary="Create a bridge process between your model and a background process",
        syntax='''BRIDGE "BRIDGE | name | unit", unit [WASTE]
  FOLDER "path"
  PROVIDER "process name or uuid" [LOCATION "code"]
  [DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n]
  [ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION]
  [COUNTRY "code"] [REGION "grid region"] [ENERGY SOURCE "text"]
  [LOCATION BASED PROVIDER "process name or uuid"]
END BRIDGE''',
        example='''BRIDGE "BRIDGE | Cement | kg", kg
  FOLDER "00: My model/Bridges"
  PROVIDER "0f0f0f0f-0000-0000-0000-000000000000"
END BRIDGE''',
        notes="A bridge has the bridge flow as its product and one input "
              "from the background process. Your own processes use the "
              "bridge, so the background process can be swapped in one "
              "place.\n"
              "Bridges are always named BRIDGE | what | unit. A plain name "
              "(BRIDGE \"Cement\", kg) is given that form. PROVIDER takes "
              "a UUID, a name that only one process has, or a name with "
              "LOCATION \"code\" when several locations share it.\n"
              "Every background input goes through a bridge: a process "
              "outside the folders the program builds in cannot be named "
              "in MAKE PROCESS, EDIT PROCESS or LINK. EDIT PROCESS on a "
              "bridge may name background processes, which is how a "
              "bridge with several providers (a mix) is made.\n"
              "While an EPD is active a bridge with no FOLDER line goes "
              "into the EPD's Bridges folder. DATA and ELECTRICITY are "
              "described under HELP DATA PRIMARY and HELP ELECTRICITY.",
        statements=("BridgeStmt",)),
    Command(
        name="SYSTEM", aliases=("MAKE SYSTEM",), topic="BUILD",
        usage='SYSTEM "process" ... END SYSTEM',
        summary="Create the product system for a process",
        syntax='''SYSTEM "process name"
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
END SYSTEM''',
        example='SYSTEM "Concrete block"',
        notes="LINKING says what openLCA does with default providers: "
              "PREFER_DEFAULTS uses them where they are set, ONLY_DEFAULTS "
              "links nothing else (ONLY_LINK_PROVIDERS is the same, in "
              "the words of openLCA's own dialogue), IGNORE_DEFAULTS lets "
              "openLCA choose every provider itself. PREFER decides "
              "between unit and system processes where no default "
              "settles it; CUTOFF leaves out supply chains below that "
              "fraction.\n"
              "PARAMETER SET stores a scenario on the system; the one "
              "marked BASELINE is what a plain CALCULATE uses. ANALYSIS "
              "GROUP names processes whose results RESULT ... BY GROUP "
              "adds up. EDIT SYSTEM changes both later.\n"
              "Linking defaults to PREFER_DEFAULTS. One system is built "
              "at a time. If the system already exists it is reused: "
              "DELETE SYSTEM first to rebuild it after changing a process.",
        statements=("SystemStmt",)),
    Command(
        name="LINK", topic="BUILD",
        usage='LINK PROCESS "source" TO PROCESS "target" WITH amount, unit',
        summary="Add the source's product as an input of the target",
        example='LINK PROCESS "Cement supply" TO PROCESS "Concrete block" WITH 300, kg',
        notes="The source has to be a bridge or a process of the program's "
              "own folders. Product systems that hold the target are out "
              "of date afterwards: DELETE SYSTEM, SYSTEM, VALIDATE.",
        statements=("LinkStmt",)),
    Command(
        name="MOVE", topic="BUILD",
        usage='MOVE <type> "name" TO "folder"',
        summary="Move an entity of any type to another folder",
        example='MOVE PROCESS "Concrete block" TO "00: My model/A3"\n'
                'MOVE FLOW "Concrete block" TO "00: My model/Flows"',
        notes="MOVE ... TO FOLDER moves it to the current build folder. "
              "Only the folder changes: links are by UUID and are not "
              "affected. A name shared by several entries is refused: use "
              "the UUID. Moving a process marks the product systems that "
              "hold it as out of date (which folder a process is in "
              "decides whether it is the program's own): build them again "
              "and VALIDATE before calculating.\n"
              "The type is any of: PROCESS, SYSTEM, FLOW, PROPERTY (flow property), UNITS (unit group), PARAMETER (global parameter), METHOD, CATEGORY (impact category), LOCATION, DQ SYSTEM, ACTOR, SOURCE, CURRENCY, SOCIAL INDICATOR, PROJECT, RESULT (stored result), EPD and FLOW MAP. Flow maps cannot be "
              "reached through openLCA's IPC server, so MOVE FLOW MAP is "
              "refused.",
        statements=("MoveStmt", "EntityMoveStmt")),
    Command(
        name="DELETE", topic="BUILD",
        usage='DELETE <type> "name or uuid" [CONFIRM]',
        summary="Delete an entity of any type that nothing else uses",
        example='CONFIRM DELETE ON\nDELETE SYSTEM "Concrete block"\nDELETE PROCESS "Concrete block"\nDELETE FLOW "Concrete block"',
        notes="Deleting cannot be undone. In the terminal olcaBASIC asks "
              "first; a program must say CONFIRM DELETE ON. A name that "
              "matches several entries is refused: use the UUID.\n"
              "DELETE FLOW first reads every process to check that nothing "
              "uses the flow (slow on a large database) and refuses if "
              "anything does, naming it. Delete the system, then the "
              "process, then its flows.\n"
              "The type is any of: PROCESS, SYSTEM, FLOW, PROPERTY (flow property), UNITS (unit group), PARAMETER (global parameter), METHOD, CATEGORY (impact category), LOCATION, DQ SYSTEM, ACTOR, SOURCE, CURRENCY, SOCIAL INDICATOR, PROJECT, RESULT (stored result), EPD and FLOW MAP. Every type is "
              "checked the same way: an actor, source, currency, location, "
              "data quality system, social indicator or global parameter "
              "that a process still points at is not deleted (from openLCA "
              "2.7 the server answers this; before that every process is "
              "read). A unit group used by a flow property, or a flow "
              "property used by a flow, is not deleted.\n"
              "DELETE METHOD and DELETE CATEGORY on a method olcaBASIC did "
              "not make are refused without CONFIRM, and with it need a "
              "person at the terminal to answer YES: they cannot be done "
              "through a Session or the MCP. Deleting a method olcaBASIC "
              "made also deletes its categories. Flow maps cannot be "
              "reached through IPC, so DELETE FLOW MAP is refused.",
        statements=("DeleteStmt", "EntityDeleteStmt")),
    Command(
        name="CONFIRM DELETE", topic="BUILD",
        usage="CONFIRM DELETE ON|OFF",
        summary="Let a program delete without being asked each time",
        example="CONFIRM DELETE ON",
        statements=("ConfirmDeleteStmt",)),

    # ── EDIT ─────────────────────────────────────────────────
    Command(
        name="EDIT PROCESS", topic="EDIT",
        usage='EDIT PROCESS "name" ... END EDIT',
        summary="Add, remove or update exchanges and parameters of a process",
        syntax='''EDIT PROCESS "name or uuid"
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
END EDIT''',
        example='''EDIT PROCESS "Concrete block"
  UPDATE INPUT "BRIDGE | Cement | kg", 320, kg
  SET DESCRIPTION "Mix revised"
END EDIT''',
        notes="Every product system that holds the process is out of "
              "date after the edit, and nothing can be calculated on it "
              "until it is built again and passes VALIDATE: DELETE SYSTEM, "
              "SYSTEM, VALIDATE. (An edit that only sets the description, "
              "DOCUMENT fields, DATA, CONTROL or RATING lines changes no "
              "result and leaves the systems as they are.)\n"
              "If a flow appears more than once in the process, say which "
              "exchange you mean: INDEX n (the error lists them with their "
              "index), or for REMOVE also PROVIDER, LOCATION or AMOUNT.",
        statements=("EditProcessStmt",)),
    Command(
        name="EDIT FLOW", topic="EDIT",
        usage='EDIT FLOW "name" ... END EDIT',
        summary="Change a flow: its properties, CAS number, formula, synonyms, location",
        syntax='''EDIT FLOW "name"
  ADD PROPERTY "Mass" AS 2400 kg PER m3
  UPDATE PROPERTY "Mass" AS 2350 kg PER m3
  SET REFERENCE "Mass"
  SET CAS|FORMULA|SYNONYMS|DESCRIPTION|LOCATION "value" | NONE
  SET INFRASTRUCTURE YES|NO
END EDIT''',
        example='''EDIT FLOW "Concrete block"
  ADD PROPERTY "Mass" AS 2400 kg PER m3
END EDIT''',
        statements=("EditFlowStmt",)),
    Command(
        name="EDIT SYSTEM", topic="EDIT",
        usage='EDIT SYSTEM "name" ... END EDIT',
        summary="Change the parameter sets and analysis groups of a product system",
        syntax='''EDIT SYSTEM "name"
  PARAMETER SET "name" [BASELINE] [DESCRIPTION "text"]
    name = value [IN PROCESS "process"]
  END PARAMETER SET
  ANALYSIS GROUP "name" [COLOUR "#rrggbb"]
    "process" [LOCATION "code"]
  END ANALYSIS GROUP
  REMOVE PARAMETER SET "name"
  REMOVE ANALYSIS GROUP "name"
  SET DESCRIPTION "text"
END EDIT''',
        example='''EDIT SYSTEM "Concrete block"
  PARAMETER SET "Low cement"
    cement_mass = 250
  END PARAMETER SET
  ANALYSIS GROUP "Binder"
    "BRIDGE | Cement | kg"
  END ANALYSIS GROUP
END EDIT''',
        notes="A parameter set is one of openLCA's stored scenarios: "
              "values for parameters of the system. A value without IN "
              "PROCESS sets every input parameter of that name (the "
              "global one and each process's own). The set marked "
              "BASELINE is what a plain CALCULATE uses; CALCULATE ... "
              "PARAMETER SET \"name\" uses another, and RUN SCENARIOS "
              "... FROM SYSTEM runs them all.\n"
              "An analysis group names processes of the system. RESULT "
              "IMPACTS BY GROUP then adds up the results per group; a "
              "process in no group counts with what it supplies. A "
              "process can be in one group only.\n"
              "A block with the name of a stored set or group replaces "
              "it. SHOW SYSTEM \"name\" SETS and ... GROUPS read them "
              "back.",
        statements=("EditSystemStmt",)),

    # ── ENTITIES ─────────────────────────────────────────────
    Command(
        name="FIND <TYPE>", topic="ENTITIES",
        usage='FIND <type> ["text"] [IN "folder"]',
        summary="List entities of any type, by part of a name",
        example='FIND ACTOR "Example"\nFIND CURRENCY\nFIND LOCATION "United" '
                'IN "Countries"\nFIND DQ SYSTEM',
        notes="The type is any of: PROPERTY (flow property), UNITS (unit "
              "group), PARAMETER (global parameter), CATEGORY (impact "
              "category), LOCATION, DQ SYSTEM, ACTOR, SOURCE, CURRENCY, "
              "SOCIAL INDICATOR, PROJECT, RESULT (stored result) and EPD. "
              "FIND PROCESS, FIND FLOW, FIND SYSTEM, FIND METHOD and FIND "
              "UNIT have their own entries. Without text every entity of "
              "the type is listed. FLOW PROPERTY, UNIT GROUP, IMPACT "
              "CATEGORY and STORED RESULT are accepted as longer forms.\n"
              "Flow maps are the one type openLCA's IPC server cannot "
              "reach: FIND FLOW MAP says so.",
        statements=("EntityFindStmt",)),
    Command(
        name="SHOW <TYPE>", topic="ENTITIES",
        usage='SHOW <type> "name or uuid" [JSON | USAGE]',
        summary="Show an entity of any type, as fields, as JSON-LD, or where it is used",
        example='SHOW ACTOR "Example Consulting"\nSHOW METHOD "My method"\n'
                'SHOW LOCATION "United Kingdom" JSON\n'
                'SHOW SOURCE "Synthetic report 2024" USAGE\nSHOW PROCESS "Concrete block" JSON',
        notes="Works for every type: PROCESS, SYSTEM, FLOW, PROPERTY (flow property), UNITS (unit group), PARAMETER (global parameter), METHOD, CATEGORY (impact category), LOCATION, DQ SYSTEM, ACTOR, SOURCE, CURRENCY, SOCIAL INDICATOR, PROJECT, RESULT (stored result), EPD and FLOW MAP.\n"
              "JSON prints the entity as openLCA stores it (JSON-LD). It "
              "is read only: no command writes JSON into the database, "
              "because that would let a program put anything in, past "
              "every rule.\n"
              "USAGE lists what points at the entity. From openLCA 2.7 "
              "the server answers (data/get/usage). Before that, olcaBASIC "
              "reads every entity that could point at it, which for "
              "actors, sources, currencies, locations, data quality "
              "systems, social indicators and global parameters means "
              "every process: slow on a large database, but complete. "
              "SHOW PROCESS ... USAGE and SHOW SYSTEM ... USAGE need "
              "openLCA 2.7; SHOW FLOW ... USAGE has its own entry.",
        statements=("EntityShowStmt", "ShowStmt")),
    Command(
        name="MAKE ACTOR", topic="ENTITIES",
        usage='MAKE ACTOR "name" [FOLDER "path"] ... END ACTOR',
        summary="Make an actor: a person or an organisation",
        syntax='''MAKE ACTOR "name" [FOLDER "path"]
    ADDRESS "text"
    CITY "text"
    POSTCODE "text"
    COUNTRY "text"
    EMAIL "text"
    PHONE "text"
    FAX "text"
    WEBSITE "text"
    DESCRIPTION "text"
END ACTOR''',
        example='MAKE ACTOR "Example Consulting"\n    CITY "Leeds"\n'
                '    COUNTRY "United Kingdom"\n    EMAIL "lca@example.org"\n'
                'END ACTOR',
        notes="Every line is optional. Actors are what a process's DOCUMENT "
              "block (GENERATOR, DOCUMENTOR, OWNER, REVIEW ... BY) and an "
              "EPD (manufacturer, verifier, programme operator) point at. "
              "Without FOLDER the actor goes into the process folder, and "
              "the output says so once. Making an actor that exists changes "
              "nothing: EDIT ACTOR \"name\" ... END EDIT changes one.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE SOURCE", topic="ENTITIES",
        usage='MAKE SOURCE "name" [FOLDER "path"] ... END SOURCE',
        summary="Make a source: a report, standard or dataset reference",
        syntax='''MAKE SOURCE "name" [FOLDER "path"]
    REFERENCE "full citation"
    URL "address"
    YEAR n
    ATTACH "file"
    DESCRIPTION "text"
END SOURCE''',
        example='MAKE SOURCE "Synthetic report 2024"\n'
                '    REFERENCE "Author, A. (2024). A report."\n'
                '    YEAR 2024\nEND SOURCE',
        notes="ATTACH uploads a file (a PDF, say) into the database next "
              "to the source; it needs openLCA 2.6.2 or later, and on an "
              "older server the source is saved and the error says the "
              "file was not attached. Sources are what DOCUMENT blocks "
              "(SOURCE, PUBLICATION, REVIEW ... REPORT), data quality "
              "systems and methods point at.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE CURRENCY", topic="ENTITIES",
        usage='MAKE CURRENCY "name" [FOLDER "path"] ... END CURRENCY',
        summary="Make a currency, for costs on exchanges",
        syntax='''MAKE CURRENCY "name" [FOLDER "path"]
    CODE "ISO code"
    FACTOR n
    REFERENCE "reference currency"
    DESCRIPTION "text"
END CURRENCY''',
        example='MAKE CURRENCY "Test pound"\n    CODE "TGB"\n    FACTOR 1.17\n'
                'END CURRENCY',
        notes="FACTOR is how many units of the reference currency one "
              "unit of this currency is worth. The first currency in a "
              "database is its own reference, with factor 1. After that "
              "FACTOR is required, and REFERENCE only when the database "
              "has more than one reference currency.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE LOCATION", topic="ENTITIES",
        usage='MAKE LOCATION "name" [FOLDER "path"] ... END LOCATION',
        summary="Make a location, with coordinates or a GeoJSON shape",
        syntax='''MAKE LOCATION "name" [FOLDER "path"]
    CODE "code"
    LATITUDE n
    LONGITUDE n
    GEOMETRY "file.geojson"
    DESCRIPTION "text"
END LOCATION''',
        example='MAKE LOCATION "Example site"\n    CODE "EX-1"\n'
                '    LATITUDE 53.8\n    LONGITUDE -1.55\nEND LOCATION',
        notes="CODE is required: it is what LOCATION \"code\" on a process "
              "or exchange refers to. GEOMETRY reads one geometry from a "
              "GeoJSON file (a geometry, a feature, or a collection of "
              "exactly one feature), used by regionalised calculation.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE UNITS", aliases=("MAKE UNIT GROUP",), topic="ENTITIES",
        usage='MAKE UNITS "name" [FOLDER "path"] ... END UNITS',
        summary="Make a unit group: units and their conversion factors",
        syntax='''MAKE UNITS "name" [FOLDER "path"]
    UNIT "name", factor [REFERENCE] [SYNONYMS "a; b"]
    ...
    DESCRIPTION "text"
END UNITS''',
        example='MAKE UNITS "Units of test"\n    UNIT "tu", 1 REFERENCE\n'
                '    UNIT "ktu", 1000 SYNONYMS "kilotest"\nEND UNITS',
        notes="Exactly one unit is the REFERENCE, with factor 1; every "
              "other factor says how many reference units one of that "
              "unit is. A unit group is used through a flow property: "
              "MAKE PROPERTY. EDIT UNITS replaces the list of units and "
              "keeps the identity of units whose names stay.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE PROPERTY", aliases=("MAKE FLOW PROPERTY",),
        topic="ENTITIES",
        usage='MAKE PROPERTY "name" [FOLDER "path"] ... END PROPERTY',
        summary="Make a flow property: a quantity measured in a unit group",
        syntax='''MAKE PROPERTY "name" [FOLDER "path"]
    UNITS "unit group"
    TYPE PHYSICAL|ECONOMIC
    DESCRIPTION "text"
END PROPERTY''',
        example='MAKE PROPERTY "Test quantity"\n    UNITS "Units of mass"\n'
                'END PROPERTY',
        notes="UNITS is required. TYPE is PHYSICAL unless ECONOMIC is "
              "given. A unit made with MAKE UNITS can be used in MAKE FLOW "
              "once exactly one flow property uses its unit group.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE SOCIAL INDICATOR", topic="ENTITIES",
        usage='MAKE SOCIAL INDICATOR "name" [FOLDER "path"] ... END SOCIAL INDICATOR',
        summary="Make a social indicator, for SOCIAL lines on a process",
        syntax='''MAKE SOCIAL INDICATOR "name" [FOLDER "path"]
    ACTIVITY VARIABLE "text"
    ACTIVITY QUANTITY "flow property"
    ACTIVITY UNIT "unit"
    MEASURED IN "unit of measurement"
    EVALUATION "evaluation scheme"
    DESCRIPTION "text"
END SOCIAL INDICATOR''',
        example='MAKE SOCIAL INDICATOR "Test working hours"\n'
                '    ACTIVITY VARIABLE "Working hours"\n'
                '    ACTIVITY UNIT "h"\n    MEASURED IN "h per week"\n'
                'END SOCIAL INDICATOR',
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE DQ SYSTEM", topic="ENTITIES",
        usage='MAKE DQ SYSTEM "name" [FOLDER "path"] ... END DQ SYSTEM',
        summary="Make a data quality system: indicators and their scores",
        syntax='''MAKE DQ SYSTEM "name" [FOLDER "path"]
    SOURCE "source"
    UNCERTAINTIES YES|NO
    INDICATOR "name"
    SCORE n "label" [DESCRIPTION "text"] [UNCERTAINTY n]
    ...
    DESCRIPTION "text"
END DQ SYSTEM''',
        example='MAKE DQ SYSTEM "Test quality"\n    INDICATOR "Reliability"\n'
                '    SCORE 1 "Verified data"\n    SCORE 2 "Estimate"\n'
                '    INDICATOR "Completeness"\n    SCORE 1 "All sites"\n'
                '    SCORE 2 "Some sites"\nEND DQ SYSTEM',
        notes="Each INDICATOR line is followed by its SCORE lines, "
              "numbered from 1. Every indicator has the same number of "
              "scores. UNCERTAINTY on a score is the factor openLCA uses "
              "when the system has UNCERTAINTIES YES.",
        statements=("MakeEntityStmt",)),
    Command(
        name="EDIT <TYPE>", topic="ENTITIES",
        usage='EDIT ACTOR|SOURCE|CURRENCY|LOCATION|UNITS|PROPERTY|SOCIAL INDICATOR|DQ SYSTEM "name" ... END EDIT',
        summary="Change an actor, source, currency, location, unit group, flow property, social indicator or data quality system",
        example='EDIT ACTOR "Example Consulting"\n    CITY "York"\nEND EDIT',
        notes="The block takes the same lines as the MAKE block of the "
              "type. Only the lines given change; the rest stays. UNIT "
              "lines (unit groups) and INDICATOR and SCORE lines (data "
              "quality systems) replace the whole list. To move an "
              "entity use MOVE; to rename one, make a new one.",
        statements=("MakeEntityStmt",)),
    Command(
        name="MAKE METHOD", topic="ENTITIES",
        usage='MAKE METHOD "name" [FOLDER "path"] ... END METHOD',
        summary="Make an impact method: categories, factors, normalisation and weighting",
        syntax='''MAKE METHOD "name" [FOLDER "path"]
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
END METHOD''',
        example='MAKE METHOD "Test method"\n'
                '    CATEGORY "Test climate" UNIT "kg CO2 eq"\n'
                '        FACTOR "Methane, fossil", 29.8\n'
                '        FACTOR "Carbon dioxide, fossil" IN "unspecified", 1\n'
                '    END CATEGORY\n'
                '    NW SET "Test set" UNIT "pt"\n'
                '        "Test climate", 8000, 0.2\n'
                '    END NW SET\nEND METHOD',
        notes="A FACTOR is for an elementary flow that exists. A name "
              "shared by several flows needs IN \"compartment\" (part of "
              "the flow's folder path) or the UUID. The value is per "
              "reference unit of the flow unless PER unit says otherwise. "
              "LOCATION makes a regionalised factor.\n"
              "In an NW SET each line gives a category of this method, "
              "its normalisation factor and, optionally, its weighting "
              "factor; NONE leaves one out. A normalised result is the "
              "total divided by the normalisation factor; a weighted "
              "result is that times the weighting factor (CALCULATE ... "
              "NW SET \"name\", then RESULT NORMALISED and RESULT "
              "WEIGHTED).\n"
              "Everything is checked before anything is written. Methods "
              "and categories olcaBASIC makes are tagged olcaBASIC, which "
              "is how EDIT METHOD and DELETE METHOD tell them from a "
              "licensed method pack. Making a method that exists changes "
              "nothing.",
        statements=("MethodStmt",)),
    Command(
        name="EDIT METHOD", topic="ENTITIES",
        usage='EDIT METHOD "name" [CONFIRM] ... END EDIT',
        summary="Change the categories, factors and NW sets of an impact method",
        syntax='''EDIT METHOD "name" [CONFIRM]
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
END EDIT''',
        example='EDIT METHOD "Test method"\n'
                '    CATEGORY "Test climate"\n'
                '        FACTOR "Methane, fossil", 27.0\n'
                '    END CATEGORY\nEND EDIT',
        notes="In a category that exists, a FACTOR line adds a factor, or "
              "replaces the one the flow (and location) already has; "
              "REMOVE FACTOR takes one out. A category that does not exist "
              "is added (it needs UNIT). An NW SET block replaces the set "
              "of that name or adds it. Everything is checked before "
              "anything is written.\n"
              "A method olcaBASIC did not make (anything without the "
              "olcaBASIC tag: the methods of ecoinvent, of openLCA Nexus "
              "method packs, of the EN 15804 add-on) follows the "
              "PARAMETERISE rule. Without CONFIRM the edit is refused, and "
              "the error says how many factors would change and to back "
              "the database up first. With CONFIRM a person at the "
              "terminal has to answer YES; through a Session or the MCP "
              "it is refused. Such methods are licensed and shared by "
              "every model in the database: copy the method in openLCA, "
              "or make your own with MAKE METHOD.",
        statements=("MethodStmt",)),
    Command(
        name="PARAMETERISE PROCESS", aliases=("PARAMETERIZE PROCESS",),
        topic="EDIT",
        usage='PARAMETERISE PROCESS "name" [LOCATION "code"] [ALL] CONFIRM',
        summary="Replace the fixed amounts of a process with parameters",
        example='PARAMETERISE PROCESS "Grid mix, test" CONFIRM',
        notes="For a process of the background database whose amounts you "
              "want to vary: the shares of a market mix, say. Every product "
              "and waste exchange with a fixed amount gets a process "
              "parameter holding that amount, and the exchange takes the "
              "parameter as its formula. Results do not change until a "
              "scenario or a sensitivity analysis varies a parameter. "
              "Elementary flows and exchanges that already have a formula "
              "are left alone.\n"
              "ALL takes the elementary flows (emissions and resources) "
              "too. Because it rewrites every amount, it asks twice before "
              "it writes anything: type YES, then PARAMETERISE. Any other "
              "answer cancels it with nothing changed. Only a person at "
              "the olcaBASIC terminal can answer, so ALL cannot run through "
              "a Session or the MCP.\n"
              "This changes the process for good. It cannot be undone "
              "without restoring a backup of the database, so back the "
              "database up in openLCA first. Without CONFIRM the command is "
              "refused and says how many amounts it would change.\n"
              "A name that several processes share needs LOCATION \"code\" "
              "or the UUID.\n"
              "Product systems that hold the process are out of date "
              "afterwards: DELETE SYSTEM, SYSTEM, VALIDATE before "
              "calculating.",
        statements=("ParameteriseStmt",)),

    # ── PARAMETERS ───────────────────────────────────────────
    Command(
        name="LET", dialect=BASIC, topic="PARAMETERS",
        usage="LET name = expression [UNCERTAINTY ...]",
        syntax="LET name = expression\n"
               "  [UNCERTAINTY LOGNORMAL gm, gsd | NORMAL mean, sd |\n"
               "               TRIANGLE min, mode, max | UNIFORM min, max | NONE]",
        summary="Set a variable (LET may be left out: name = expression)",
        example="LET cement_mass = 300\nLET water_mass = cement_mass * 0.5",
        notes="A top-level variable used as an exchange amount becomes a "
              "global parameter in openLCA. A variable defined from other "
              "variables becomes a formula parameter, so it follows them "
              "in scenarios. Text variables end in $: LET folder$ = \"00: X\".\n"
              "UNCERTAINTY gives the parameter a distribution for "
              "MONTECARLO (HELP MAKE PROCESS has the rules for the "
              "numbers); UNCERTAINTY NONE takes it away again.",
        statements=("LetStmt",)),
    Command(
        name="UPDATE PARAMETER", topic="PARAMETERS",
        usage="UPDATE PARAMETER name = expression",
        summary="Set a variable and write the global parameter to openLCA now",
        example="UPDATE PARAMETER cement_mass = 320",
        statements=("UpdateParamStmt",)),

    # ── CALCULATE ────────────────────────────────────────────
    Command(
        name="CALCULATE", topic="CALCULATE",
        usage='CALCULATE "system" USING "method" [ALLOCATE method] [AS name]',
        summary="Calculate the impacts of a product system and keep the result open",
        syntax='''CALCULATE "system" USING "method"
  [ALLOCATE AS_DEFINED|PHYSICAL|ECONOMIC|CAUSAL|NONE]
  [AMOUNT n unit [PROPERTY "flow property"]]
  [WITH COSTS] [WITH REGIONALISATION]
  [NW SET "name"] [PARAMETER SET "name"]
  [IGNORE FACTORS "flow"]
  [AS name]''',
        example='CALCULATE "Concrete block" USING "EF v3.1"\n'
                'CALCULATE "Concrete block" USING "EF v3.1" AMOUNT 2 m3 '
                'WITH COSTS AS doubled',
        notes="USING is required: there is no default method. ALLOCATE "
              "takes AS_DEFINED (the default), PHYSICAL, ECONOMIC, CAUSAL "
              "or NONE.\n"
              "The result stays open in openLCA as the current result, so "
              "RESULT commands can read more from it without calculating "
              "again. It is closed by the next CALCULATE, by CLOSE RESULT, "
              "at the end of a program run from a file and when the "
              "session ends. AS name keeps a result open under a name "
              "alongside the current one (RESULT ... IN name). A session "
              "holds at most 5 open results.\n"
              "AMOUNT calculates for another amount of the product than "
              "the system's own target. WITH COSTS adds the costs on the "
              "exchanges (RESULT COSTS). WITH REGIONALISATION uses the "
              "locations on exchanges and regional factors. NW SET names "
              "a normalisation and weighting set of the method (RESULT "
              "NORMALISED, RESULT WEIGHTED). PARAMETER SET uses a "
              "parameter set stored on the system. WITH REGIONALIZATION is "
              "accepted as a spelling. The words can come in any order "
              "after the method.\n"
              "Refused, like every command that calculates: a system that "
              "failed VALIDATE; a system that is out of date because one "
              "of its processes was edited, linked, moved or parameterised "
              "(build it again, then VALIDATE); ALLOCATE PHYSICAL or "
              "ECONOMIC when a process with several products has no "
              "factors for that method; and a method with no "
              "characterisation factor for an elementary flow the program "
              "created. IGNORE FACTORS \"flow\" accepts the last one "
              "knowingly, for that flow and method, for the rest of the "
              "session, and the output says so.",
        statements=("CalculateStmt",)),
    Command(
        name="CONTRIBUTION", topic="CALCULATE",
        usage='CONTRIBUTION "system" USING "method" [TOP n]',
        summary="Show which processes contribute most to each impact category",
        syntax='''CONTRIBUTION "system" USING "method" [TOP n] [ALLOCATE method]
  [CATEGORIES "category", "category"]
END CONTRIBUTION''',
        example='CONTRIBUTION "Concrete block" USING "EF v3.1" TOP 5',
        notes="TOP defaults to 10. Without CATEGORIES every category is "
              "analysed. The block form ends with END CONTRIBUTION.",
        statements=("ContributionStmt",)),
    Command(
        name="TREE", topic="CALCULATE",
        usage='TREE "system" USING "method" CATEGORY "category" [LEVELS n] [TOP n] [NOQUALITY]',
        summary="Show the contribution tree for one category, with pedigree scores",
        example='TREE "Concrete block" USING "EF v3.1" CATEGORY "Climate change" LEVELS 3 TOP 5',
        notes="LEVELS defaults to 3 and TOP to 5.",
        statements=("TreeStmt",)),
    Command(
        name="INVENTORY", topic="CALCULATE",
        usage='INVENTORY "system" USING "method" [MAX n]',
        summary="List the largest elementary flows of a product system",
        example='INVENTORY "Concrete block" USING "EF v3.1" MAX 20',
        notes="MAX defaults to 50.",
        statements=("InventoryStmt",)),
    Command(
        name="MONTECARLO", topic="CALCULATE",
        usage='MONTECARLO "system" USING "method" [RUNS n]',
        summary="Run a Monte Carlo simulation and report the spread per category",
        example='MONTECARLO "Concrete block" USING "EF v3.1" RUNS 500',
        notes="RUNS defaults to 1000. Reports mean, standard deviation, "
              "coefficient of variation, minimum, maximum, median and the "
              "5th and 95th percentiles.\n"
              "Refused before the runs start when nothing is uncertain: "
              "no exchange or parameter of the foreground has an "
              "UNCERTAINTY and two trial runs give the same results. Put "
              "UNCERTAINTY on the INPUT, OUTPUT or LET lines that are "
              "uncertain.",
        statements=("MonteCarloStmt",)),

    # ── RESULT ───────────────────────────────────────────────
    Command(
        name="RESULT IMPACTS", topic="RESULT",
        usage='RESULT IMPACTS [CATEGORY "x"] [BY GROUP | BY TAG]',
        summary="Impact totals of the open result, whole or by analysis group or tag",
        syntax='''RESULT IMPACTS [CATEGORY "category"]
RESULT IMPACTS BY GROUP [CATEGORY "category"]
RESULT IMPACTS BY TAG CATEGORY "category"''',
        example='RESULT IMPACTS\nRESULT IMPACTS CATEGORY "Climate change"\n'
                'RESULT IMPACTS BY GROUP',
        notes="Every RESULT command reads the current result (the last "
              "CALCULATE), or a named one with IN name. Each can end with "
              "TOP n (the n largest rows) and SAVE \"file.csv\".\n"
              "BY GROUP needs analysis groups on the product system (EDIT "
              "SYSTEM ... ANALYSIS GROUP). A process that is in no group "
              "counts towards the group of what it supplies. BY TAG sums "
              "the direct results of the processes carrying each tag, and "
              "needs openLCA 2.7.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT CATEGORIES", topic="RESULT",
        usage="RESULT CATEGORIES",
        summary="List the impact categories of the open result",
        example="RESULT CATEGORIES",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT PROCESSES", topic="RESULT",
        usage="RESULT PROCESSES",
        summary="List the processes of the calculated system",
        example="RESULT PROCESSES TOP 20",
        notes="These are the names OF PROCESS accepts in the other RESULT "
              "commands.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT DEMAND", topic="RESULT",
        usage="RESULT DEMAND",
        summary="Show the product and amount the result was calculated for",
        example="RESULT DEMAND",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT FLOWS", topic="RESULT",
        usage='RESULT FLOWS [OF PROCESS "x" [DIRECT]] [FLOW "y"] [LIST]',
        summary="Inventory: elementary flows of the system or of one process",
        syntax='''RESULT FLOWS [FLOW "flow" [IN "compartment"]]
RESULT FLOWS LIST
RESULT FLOWS OF PROCESS "process" [DIRECT] [FLOW "flow"]
RESULT FLOWS BY GROUP FLOW "flow"
RESULT FLOWS BY TAG FLOW "flow"''',
        example='RESULT FLOWS TOP 20\n'
                'RESULT FLOWS OF PROCESS "Kiln" DIRECT\n'
                'RESULT FLOWS FLOW "Carbon dioxide, fossil" IN "air"',
        notes="Without a process: the totals of the whole system. OF "
              "PROCESS gives one process with everything that supplies "
              "it, or with DIRECT only what its own exchanges emit and "
              "take. LIST names the flows without amounts.\n"
              "A flow name that exists in several compartments needs IN "
              "\"compartment\" straight after it (part of the path is "
              "enough). A process name shared by several processes needs "
              "LOCATION \"code\" after it.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT FLOW", topic="RESULT",
        usage='RESULT FLOW "y" BY PROCESS',
        summary="Show which processes one elementary flow comes from",
        example='RESULT FLOW "Carbon dioxide, fossil" IN "air" BY PROCESS TOP 10',
        notes="Direct amounts: what each process itself emits or takes.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT CONTRIBUTION", topic="RESULT",
        usage='RESULT CONTRIBUTION BY PROCESS|BY FLOW|OF PROCESS "x" [DIRECT] [CATEGORY "y"]',
        summary="Contributions to the impacts, by process or by elementary flow",
        syntax='''RESULT CONTRIBUTION BY PROCESS [DIRECT] [CATEGORY "category"]
RESULT CONTRIBUTION OF PROCESS "process" [DIRECT] [CATEGORY "category"]
RESULT CONTRIBUTION BY FLOW [CATEGORY "category" [FLOW "flow"]]''',
        example='RESULT CONTRIBUTION BY PROCESS DIRECT CATEGORY "Climate change" TOP 10\n'
                'RESULT CONTRIBUTION BY FLOW CATEGORY "Climate change" TOP 5\n'
                'RESULT CONTRIBUTION OF PROCESS "Kiln"',
        notes="BY PROCESS without DIRECT gives each process with its "
              "whole supply chain, so the shares add up to more than "
              "100%; with DIRECT each process counts only its own "
              "exchanges and the shares add up to 100%. Without DIRECT "
              "and on a large database it asks openLCA about every "
              "process, which takes minutes: DIRECT with a CATEGORY is "
              "one question.\n"
              "BY FLOW shows which emissions and resources drive a "
              "category.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT FACTORS", topic="RESULT",
        usage='RESULT FACTORS CATEGORY "x" [FLOW "y"]',
        summary="Characterisation factors of a category for the flows of the inventory",
        example='RESULT FACTORS CATEGORY "Climate change" TOP 10',
        notes="A flow with factor 0 is not characterised by that category.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT INTENSITY", topic="RESULT",
        usage='RESULT INTENSITY OF PROCESS "x" [CATEGORY "y" | FLOWS | FLOW "y"]',
        summary="Impacts or flows of one unit of a process's product, with its supply chain",
        example='RESULT INTENSITY OF PROCESS "Kiln"\n'
                'RESULT INTENSITY OF PROCESS "Kiln" FLOWS TOP 10',
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT SCALING", topic="RESULT",
        usage='RESULT SCALING [OF PROCESS "x" [UNSCALED]]',
        summary="Scaling factors, or the product and waste flows of one process",
        example='RESULT SCALING TOP 20\nRESULT SCALING OF PROCESS "Kiln"',
        notes="A scaling factor says how many times a process runs to "
              "meet the demand. OF PROCESS lists the process's product "
              "(positive) and its inputs (negative) at that scaling; "
              "UNSCALED lists them as written in the process.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT TOTALITY", topic="RESULT",
        usage='RESULT TOTALITY [OF PROCESS "x"]',
        summary="Totality factors: total requirements corrected for loops",
        example="RESULT TOTALITY TOP 20",
        notes="The same as RESULT REQUIREMENTS unless the supply chain "
              "has loops, in which case the factor stops a loop being "
              "counted twice.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT REQUIREMENTS", topic="RESULT",
        usage='RESULT REQUIREMENTS [OF PROCESS "x"]',
        summary="How much of each product the system needs in total",
        example='RESULT REQUIREMENTS TOP 20\n'
                'RESULT REQUIREMENTS OF PROCESS "Kiln"',
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT TREE", topic="RESULT",
        usage='RESULT TREE CATEGORY "x" | FLOW "y" | COSTS [LEVELS n] [TOP n]',
        summary="Upstream tree of a category, an elementary flow or the costs",
        example='RESULT TREE CATEGORY "Climate change" LEVELS 3 TOP 5\n'
                'RESULT TREE FLOW "Carbon dioxide, fossil" IN "air"',
        notes="LEVELS defaults to 3 and TOP to 5; TOP is the number of "
              "branches kept at each level, the rest are summed. TREE "
              "\"system\" USING \"method\" does the same for a "
              "category and adds the pedigree scores.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT COSTS", topic="RESULT",
        usage='RESULT COSTS [BY PROCESS | BY GROUP | OF PROCESS "x" [DIRECT] | TREE]',
        summary="Life cycle costs of a result calculated WITH COSTS",
        syntax='''RESULT COSTS
RESULT COSTS BY PROCESS | BY GROUP | BY TAG
RESULT COSTS OF PROCESS "process" [DIRECT]
RESULT COSTS INTENSITY OF PROCESS "process"
RESULT COSTS TREE [LEVELS n] [TOP n]''',
        example='RESULT COSTS\nRESULT COSTS BY PROCESS TOP 10',
        notes="Needs CALCULATE ... WITH COSTS, and costs on the exchanges "
              "(COST in MAKE PROCESS). Costs are net: what a process pays "
              "for its inputs less what it earns from its products.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT NORMALISED", aliases=("RESULT NORMALIZED",),
        topic="RESULT",
        usage="RESULT NORMALISED",
        summary="Normalised results of a result calculated with an NW SET",
        example="RESULT NORMALISED",
        notes="Each total divided by the set's normalisation factor.",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT WEIGHTED", topic="RESULT",
        usage="RESULT WEIGHTED",
        summary="Normalised and weighted results of a result calculated with an NW SET",
        example="RESULT WEIGHTED",
        statements=("ResultQueryStmt",)),
    Command(
        name="RESULT SANKEY", topic="RESULT",
        usage='RESULT SANKEY CATEGORY "x" | FLOW "y" [MIN SHARE n%] [MAX NODES n] [SAVE "file.json"]',
        summary="Nodes and links for a Sankey diagram of a category or a flow",
        example='RESULT SANKEY CATEGORY "Climate change" MIN SHARE 1% '
                'MAX NODES 30 SAVE "sankey.json"',
        notes="MIN SHARE leaves out processes below that share of the "
              "total; MAX NODES limits their number. The data is nodes "
              "and links, so it saves as JSON, not CSV. openLCA cannot "
              "make one for costs.",
        statements=("ResultQueryStmt",)),
    Command(
        name="SAVE RESULT AS", topic="RESULT",
        usage='SAVE RESULT AS "name" [FOLDER "path"] [REPLACE] [IN name]',
        summary="Store the open result in the database as an openLCA result",
        example='CALCULATE "Concrete block" USING "EF v3.1"\n'
                'SAVE RESULT AS "Concrete block, A1-A3"',
        notes="Writes openLCA's own Result entity: the product system, the "
              "method, the impact totals and the inventory with its "
              "reference flow. Stored results are what an EPD's modules "
              "point at (EPD SAVE makes them itself). A stored result of "
              "that name is not written over unless REPLACE is given. "
              "DESCRIPTION \"text\" adds a description. FIND RESULT, SHOW "
              "RESULT, MOVE RESULT and DELETE RESULT work on stored "
              "results. The open result stays open.",
        statements=("SaveResultAsStmt",)),
    Command(
        name="CLOSE RESULT", topic="RESULT",
        usage="CLOSE RESULT [name | ALL]",
        summary="Close the current result, a named one, or all of them",
        example="CLOSE RESULT\nCLOSE RESULT base\nCLOSE RESULT ALL",
        notes="A result uses memory in openLCA until it is closed. "
              "olcaBASIC closes results itself at the next CALCULATE (the "
              "current one), at the end of a program run from a file, on "
              "reset and when the session ends.",
        statements=("CloseResultStmt",)),

    # ── SCENARIOS ────────────────────────────────────────────
    Command(
        name="SCENARIO", topic="SCENARIOS",
        usage='SCENARIO "name" ... END SCENARIO',
        summary="Define a scenario as a set of parameter values",
        syntax='''SCENARIO "name"
  LET parameter = value
END SCENARIO''',
        example='''SCENARIO "Low cement"
  LET cement_mass = 250
END SCENARIO''',
        notes="A variable calculated from others cannot be set in a "
              "scenario: set the variables it is calculated from.",
        statements=("ScenarioStmt",)),
    Command(
        name="RUN SCENARIOS", topic="SCENARIOS",
        usage='RUN SCENARIOS ON "system" USING "method"',
        summary="Calculate every scenario defined so far",
        syntax='''RUN SCENARIOS ON "system" USING "method" [ALLOCATE method]
  [FROM CSV "scenarios.csv"]
  [SAVE "results.csv"]
END RUN
RUN SCENARIOS ON "system" USING "method" FROM SYSTEM''',
        example='RUN SCENARIOS ON "Concrete block" USING "EF v3.1"',
        notes="FROM SYSTEM runs the parameter sets stored on the product "
              "system (SYSTEM ... PARAMETER SET, EDIT SYSTEM).\n"
              "With FROM CSV the scenarios come from a file whose first "
              "column is Parameter and whose other columns are scenarios. "
              "The scenarios are cleared after the run.",
        statements=("RunScenariosStmt",)),
    Command(
        name="MAKE PROJECT", topic="SCENARIOS",
        usage='MAKE PROJECT "name" [FOLDER "path"] ... END PROJECT',
        summary="Make a project: variants of product systems to compare",
        syntax='''MAKE PROJECT "name" [FOLDER "path"]
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
END PROJECT''',
        example='MAKE PROJECT "Block options"\n'
                '    METHOD "EF v3.1"\n'
                '    VARIANT "Base" SYSTEM "Concrete block"\n'
                '    END VARIANT\n'
                '    VARIANT "Less cement" SYSTEM "Concrete block" AMOUNT 1 kg\n'
                '        cement_mass = 0.10\n'
                '    END VARIANT\nEND PROJECT',
        notes="METHOD is required. A variant is a product system with an "
              "amount (the system's own target when AMOUNT is left out), "
              "an allocation method and parameter values. A parameter "
              "value without IN PROCESS sets every copy of that parameter "
              "in the system. The project is stored in openLCA, where its "
              "own project report can be opened; CALCULATE PROJECT "
              "compares the variants from olcaBASIC. Making a project "
              "that exists changes nothing: delete it and make it again "
              "to change it.",
        statements=("ProjectStmt",)),
    Command(
        name="CALCULATE PROJECT", topic="SCENARIOS",
        usage='CALCULATE PROJECT "name"',
        summary="Calculate every enabled variant of a project and compare them",
        example='CALCULATE PROJECT "Block options"',
        notes="openLCA's IPC server has no project calculation, so each "
              "enabled variant is one ordinary calculation with the "
              "variant's system, amount, allocation and parameter values "
              "and the project's method. With an NW SET the normalised "
              "and weighted results are shown too. SAVE RESULTS writes "
              "the comparison. Every result is disposed.",
        statements=("CalculateProjectStmt",)),
    Command(
        name="SENSITIVITY", topic="SCENARIOS",
        usage='SENSITIVITY ON "system" USING "method" BY n% ... END SENSITIVITY',
        summary="Vary parameters up and down by a percentage, one at a time",
        syntax='''SENSITIVITY ON "system" USING "method" BY n% [ALLOCATE method]
  VARY parameter [, parameter]
  [FROM "parameters.csv"]
  [SAVE "results.csv"]
END SENSITIVITY''',
        example='''SENSITIVITY ON "Concrete block" USING "EF v3.1" BY 10%
  VARY cement_mass
END SENSITIVITY''',
        notes="BY is required: there is no default range. So is at least "
              "one VARY line or a FROM file.",
        statements=("SensitivityStmt",)),

    # ── CHECK ────────────────────────────────────────────────
    Command(
        name="VALIDATE", topic="CHECK",
        usage='VALIDATE "system" [WITH CALCULATION]',
        summary="Check the structure of a product system",
        example='VALIDATE "Concrete block"',
        notes="Checks the reference process, its reference product, the "
              "links and the parameters. It does not check whether the "
              "amounts are right. If a system fails, calculations on it "
              "are refused for the rest of the session until VALIDATE "
              "passes.",
        statements=("ValidateStmt",)),
    Command(
        name="CHECK", topic="CHECK",
        usage='CHECK "system" [TIER 1|2|3] [AGAINST "file"]',
        summary="Run a tier of model checks",
        example='CHECK "Concrete block" TIER 1',
        notes="Tier 1 is structural (the same checks as VALIDATE) and "
              "always ends by saying so. Tier 2 lists the model for "
              "comparison with its source data. Tier 3 is the plausibility "
              "check of the results, which only a person can make.",
        statements=("CheckStmt",)),
    Command(
        name="AUDIT", topic="CHECK",
        usage='AUDIT [FOLDER] "folder"',
        summary="Look for structural problems in the processes of a folder",
        example='AUDIT FOLDER "00: My model"',
        statements=("AuditStmt",)),
    Command(
        name="EXTRACT", topic="CHECK",
        usage='EXTRACT [FOLDER] "folder"',
        summary="List every process and exchange in a folder, to compare with source data",
        example='EXTRACT FOLDER "00: My model"',
        statements=("ExtractStmt",)),

    # ── EPD ──────────────────────────────────────────────────
    Command(
        name="EPD", topic="EPD",
        usage='EPD "product name" ... END EPD',
        summary="Define an EPD: unit, method, folder, modules and programme",
        syntax='''EPD "product name"
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
END EPD''',
        example='''EPD "Concrete block"
  DECLARED UNIT 1, m3
  METHOD "EN15804+A2 (EF 3.1)"
  FOLDER "00: Concrete block EPD"
  MODULES A1, A2, A3, C1, C2, C3, C4, D
  BIOGENIC CARBON NO
END EPD''',
        notes="The block is checked as it is read, and nothing is built "
              "if it is wrong.\n"
              "Modules: A1, A2 and A3 are always declared. C1 to C4 and D "
              "are declared together, or left out together with an EXEMPT "
              "C AND D block that justifies it. The exemption is refused "
              "for a product with biogenic carbon (EN 15804+A2, clause "
              "5.2). A4, A5 and B1 to B7 are options. The EPD type follows "
              "from the modules and is written into the report.\n"
              "Unit: FUNCTIONAL UNIT is only for types with options or "
              "cradle to grave.\n"
              "Method: it has to be an EN 15804+A2 method with the full "
              "indicator set (38 categories for \"EN15804+A2 (EF 3.1)\"). "
              "CATEGORIES n states another size.\n"
              "PROGRAMME adds a programme operator's rules. They are "
              "errors, with no override. PROGRAMME \"IES\" is the "
              "International EPD System; with it, DATA is required on "
              "every process and bridge, and EPD DATA QUALITY has to pass "
              "before EPD REPORT.\n"
              "CUTOFF declares what was left out of a module, as a share "
              "of mass or energy.\n"
              "BIOGENIC CARBON YES needs BIOGENIC CONTENT: the kg of "
              "biogenic carbon in the product (and the packaging) per "
              "declared unit (EN 15804+A2, 6.4.4 and 7.2.5), or FROM MASS "
              "n kg DRY, which takes the oven-dry mass of wood at 0.5 kg "
              "of carbon per kg (EN 16485, 6.3.4.2). EPD CALCULATE then "
              "checks the biogenic CO2 in the GWP-biogenic indicator: in "
              "A1 to A3 it equals the content times 44/12, taken up; over "
              "A to C it sums to zero; in D it is zero. A balance that "
              "does not close is an error and the results are not kept. "
              "Methane and other biogenic gases are left out of the "
              "balance. BIOGENIC EXPORT declares a co-product that leaves "
              "A1 to A3 with its carbon (sawdust, chips); the report lists "
              "it, and the error says so when exactly that carbon is "
              "missing. Packaging carbon is expected in A1 to A3 only "
              "when A5 is declared; otherwise its release is reported in "
              "A1 to A3 (PCR 2019:14, Annex 2). The renewable primary "
              "energy used as material (PERM) is not checked: the PCR "
              "allows three ways of declaring it (Annex 3, options A to "
              "C).\n"
              "The steps: EPD block, bridges, MODULE blocks, EPD SYSTEMS, "
              "EPD CHECK, EPD CALCULATE, EPD DATA QUALITY, EPD REPORT. NEW "
              "FROM TEMPLATE \"epd_skeleton\" AS \"my_epd.baslca\" "
              "writes a starting point.",
        statements=("EpdStmt",)),
    Command(
        name="MODULE", topic="EPD",
        usage='MODULE code ... TOTAL "name" ... END MODULE',
        summary="Build the processes of one EPD module and the process that adds them up",
        syntax='''MODULE A1
  MAKE PROCESS "name"
    ...
  END PROCESS
  [NET FLOW "flow", amount, unit [QUALITY n%]]     (module D)
  TOTAL "name" [AS "flow", amount, unit]
END MODULE''',
        example='''MODULE A1
  MAKE PROCESS "Cement supply"
    OUTPUT MAKE FLOW "Cement, supplied", 300, kg, PRODUCT
    INPUT USE PROCESS "BRIDGE | Cement | kg", 300, kg
  END PROCESS
  TOTAL "Raw material supply"
END MODULE''',
        notes="Names are given without the prefix: the process above "
              "becomes \"A1 | Cement supply\" and the total \"A1: Raw "
              "material supply\", both in the module's folder.\n"
              "Amounts are per declared unit. TOTAL takes the whole output "
              "of each process of the module, with the declared unit as "
              "its own product (or the product given after AS). A process "
              "whose output goes into another process of the same module "
              "is counted through that one.\n"
              "An input has to come from a bridge or from a process in "
              "the EPD folder. A background process used directly is an "
              "error, and so is a process that belongs to another module: "
              "its impacts would be counted in both.\n"
              "A module with nothing in it still needs its TOTAL line; "
              "its results are zero.\n"
              "NET FLOW, in MODULE D, declares what leaves the product "
              "system and its quality factor.",
        statements=("ModuleStmt",)),
    Command(
        name="EPD SYSTEMS", topic="EPD",
        usage="EPD SYSTEMS",
        summary="Create one product system per module total, one at a time",
        example="EPD SYSTEMS",
        notes="Uses LINKING PREFER_DEFAULTS. A system that already exists "
              "is reused, with a warning.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD CHECK", topic="EPD",
        usage='EPD CHECK [SKIP "reason"]',
        summary="Validate every module system and list what is missing",
        example='EPD CHECK\nEPD CHECK SKIP "Checked this morning, nothing has changed"',
        notes="Validates each product system, lists processes with no "
              "pedigree scores or no description, and applies the "
              "programme's rules to the model as built. It checks "
              "structure and declarations only.\n"
              "EPD CALCULATE is refused until this has passed. Without a "
              "PROGRAMME, EPD CHECK SKIP \"reason\" goes on without it, "
              "and the reason is written into the report. Under a "
              "PROGRAMME there is no SKIP: the EPD is checked.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD CALCULATE", topic="EPD",
        usage="EPD CALCULATE",
        summary="Calculate every module with the EPD method",
        example="EPD CALCULATE",
        notes="Shows indicator by module, with A1-A3 as the one total. "
              "Module D is never part of a total.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD DATA QUALITY", topic="EPD",
        usage='EPD DATA QUALITY [PARAMETER SET "name" | FROM "scenarios.csv"]',
        summary="Do the programme's data quality arithmetic and apply its limits",
        example="EPD DATA QUALITY",
        notes="Needs PROGRAMME in the EPD block. From the DATA lines and "
              "the results it works out: the processes above 10% of "
              "GWP-GHG in A1-A3, with their source and data category; the "
              "share of primary data; the share of each indicator that "
              "comes from proxy data; the age of the data; and the "
              "processes that give 80% of each indicator. A limit that is "
              "passed is an error (GPI 5.1.0, A.5).\n"
              "The coverage and the proxy limit run over the environmental "
              "impact indicators only: the core and additional indicators "
              "of EN 15804+A2 (Tables 3 and 4) and GWP-GHG. They are picked "
              "by the code at the end of each category name (GWP-total, "
              "ODP, AP and so on). Resource use, waste and output flow "
              "indicators are reported, not counted.\n"
              "Residual check: in every module, for every indicator, the "
              "module's own processes and its bridges have to add up to "
              "the module total (within 0.1%). A gap is an error naming "
              "the module, the indicator and the size; the usual cause is "
              "an input that does not go through a bridge.\n"
              "Ratings: every dataset in the 80% coverage has to carry "
              "RATING GEOGRAPHY, RATING TECHNOLOGY and RATING TIME (HELP "
              "RATING). EPD DATA QUALITY refuses while one is missing; EPD "
              "DQ SHEET lists what is needed.\n"
              "PARAMETER SET \"name\" runs the analysis with the values of "
              "that stored parameter set (EDIT SYSTEM ... PARAMETER SET) "
              "on the module systems that have it. FROM \"scenarios.csv\" "
              "runs it once per scenario of the file (a Parameter column, "
              "then one column per scenario). Each scenario gets the same "
              "checks. A parameter that no module holds is an error. The "
              "gate before EPD REPORT is the run without scenarios.\n"
              "The thresholds are named values in the programme profile.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD REPORT", topic="EPD",
        usage='EPD REPORT "file.csv" [LOCATION BASED]',
        summary="Write the results table and the declarations to a CSV file",
        example='EPD REPORT "results.csv"',
        notes="The header gives the product, EPD type, unit, method, "
              "database family, olcaBASIC version, date, programme, PCR and "
              "database. Then the cut-offs, the electricity used by "
              "processes under direct control (approach, energy source and "
              "climate impact per kWh), the net flows of module D, the "
              "data sources, and the indicators by module with A1-A3 "
              "added up and D on its own.\n"
              "Under a programme it is refused until EPD DATA QUALITY has "
              "passed.\n"
              "LOCATION BASED adds a second table with every electricity "
              "bridge on its LOCATION BASED PROVIDER.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD SAVE", topic="EPD",
        usage='EPD SAVE [REPLACE] [MANUFACTURER "actor"] [VERIFIER "actor"] ...',
        summary="Write the EPD into openLCA as its own EPD entity, with a stored result per module",
        syntax='''EPD SAVE [REPLACE]
    [MANUFACTURER "actor"] [VERIFIER "actor"] [OPERATOR "actor"]
    [GENERATOR "actor"] [PCR "source"] [REGISTRATION "number"] [URN "urn"]
    [VALID FROM "DD/MM/YYYY"] [VALID UNTIL "DD/MM/YYYY"]
    [DESCRIPTION "text"]''',
        example='EPD SAVE\nEPD SAVE REPLACE VERIFIER "Example Verifier" '
                'VALID FROM "12/11/2026" VALID UNTIL "11/11/2031"',
        notes="Refused until EPD REPORT has passed: what is stored is "
              "what the report declares. Each declared module is "
              "calculated once more and stored as an openLCA result "
              "called \"EPD name | module\" in the Results folder of the "
              "EPD; if a number differs from the report, the model has "
              "changed and EPD SAVE stops. Then the EPD entity is "
              "written in the EPD's folder: the product flow (the output "
              "of A3), the declared unit, and one module entry per "
              "declared module pointing at its stored result. The EPD "
              "can then be opened, exported and sent on from openLCA. "
              "The CSV report stays as it is.\n"
              "The actors and the PCR source must exist (MAKE ACTOR, MAKE "
              "SOURCE). An EPD of the same name is not written over "
              "without REPLACE. SHOW EPD, FIND EPD, MOVE EPD and DELETE "
              "EPD work on stored EPDs.\n"
              "EPD SYSTEMS also sets one analysis group per module on "
              "each module's product system, named after the module, so "
              "openLCA and RESULT ... BY GROUP show results by module.",
        statements=("EpdCommandStmt",)),
    Command(
        name="RATING", topic="EPD",
        usage='RATING GEOGRAPHY|TECHNOLOGY|TIME "level" REASON "why"',
        summary="Rate how well a dataset represents what it stands for",
        syntax='''RATING GEOGRAPHY "level" REASON "why"
RATING TECHNOLOGY "level" REASON "why"
RATING TIME "level" REASON "why"''',
        example='''EDIT PROCESS "BRIDGE | Steel | kg"
  RATING GEOGRAPHY "Fair" REASON "Global average used for a national supply"
  RATING TECHNOLOGY "Good" REASON "Same route, average plant"
  RATING TIME "Good" REASON "Valid 2018 to 2024"
END EDIT''',
        notes="A line inside BRIDGE, MAKE PROCESS or EDIT PROCESS. The "
              "levels are Very good, Good, Fair, Poor and Very poor: the "
              "scale of the two data quality schemes in EN 15804+A2, Annex "
              "E, which the International EPD System allows (GPI 5.1.0, "
              "A.5.4). A level that is not on the scale is an error. "
              "REASON is required.\n"
              "The ratings are stored on the process as tags, so they "
              "stay with the model. A rating on a bridge that several "
              "products share counts for each of them. EPD DATA QUALITY "
              "needs all three on every dataset in the 80% coverage; EPD "
              "DQ SHEET and EPD DQ TABLE write them out.",
        statements=("EditProcessStmt",)),
    Command(
        name="EPD DQ SHEET", topic="EPD",
        usage='EPD DQ SHEET "file.csv"',
        summary="Write the register of the datasets the data quality assessment has to cover",
        example='EPD DQ SHEET "dq_register.csv"',
        notes="One row per dataset that is above 10% of GWP-GHG in A1-A3 "
              "or in the 80% coverage of any impact indicator: its "
              "modules and shares, its data declaration, the background "
              "process behind a bridge (name, location, validity, "
              "technology, geography and time descriptions, data quality "
              "system), and the ratings and reasons recorded so far. It "
              "runs before EPD DATA QUALITY passes, so it shows what still "
              "needs a RATING.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD DQ TABLE", topic="EPD",
        usage='EPD DQ TABLE "file.md"',
        summary="Write the data quality assessment table for the accompanying report",
        example='EPD DQ TABLE "data_quality_assessment.md"',
        notes="A Markdown table: dataset, products, and the geographical, "
              "technical and temporal representativeness ratings with "
              "their reasons. It covers every product assessed in the "
              "session so far, so with several products in one program, "
              "run it after the last one (or after each: the file is "
              "written again with one more product).",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD SENSITIVITY", topic="EPD",
        usage='EPD SENSITIVITY BY n% ... END EPD SENSITIVITY',
        summary="Vary groups of parameters together and sum the modules",
        syntax='''EPD SENSITIVITY BY n% [SAVE "file.csv"]
  GROUP "name" VARY parameter, parameter, ...
  ...
END EPD SENSITIVITY''',
        example='''EPD SENSITIVITY BY 20% SAVE "sensitivity.csv"
  GROUP "Electricity" VARY kiln_kwh, saw_kwh
  GROUP "Transport" VARY road_tkm
END EPD SENSITIVITY''',
        notes="Needs EPD CALCULATE first: its results are the baseline. "
              "The parameters of a group move together, down and then up "
              "by the percentage, each from its own value. Only the "
              "module systems that hold a parameter of the group are "
              "calculated again; the others keep their baseline. Results "
              "are summed per indicator over A to C; module D is shown on "
              "its own and never added.\n"
              "A parameter that no module holds is an error naming it "
              "(a typing mistake does not pass as 'no effect'). A module "
              "holds the input parameters of its own processes and "
              "bridges, and the global parameters their formulas use. "
              "SAVE writes the table: indicator, unit, modules, baseline, "
              "then down and up for each group.",
        statements=("EpdSensitivityStmt",)),
    Command(
        name="EPD EXPORT MODEL", topic="EPD",
        usage='EPD EXPORT MODEL "file.json"',
        summary="Write the whole model of the EPD folder as JSON, for a verifier",
        example='EPD EXPORT MODEL "model.json"',
        notes="Every process in the EPD folder with every exchange field "
              "(amount, formula, unit, provider, uncertainty, cost, data "
              "quality entry), its parameters, allocation factors, "
              "documentation and tags; the flows those processes use; the "
              "global parameters the model uses; and the module systems "
              "with their parameter sets and analysis groups. It only "
              "reads. Names of background datasets the model buys from "
              "appear as providers: check the database licence before "
              "passing the file on.",
        statements=("EpdCommandStmt",)),
    Command(
        name="EPD STATUS", aliases=("EPD CLOSE",), topic="EPD",
        usage="EPD STATUS | EPD CLOSE",
        summary="Show how far the active EPD has got, or end EPD mode",
        example="EPD STATUS",
        notes="EPD CLOSE ends EPD mode. What was built stays in the "
              "database.",
        statements=("EpdCommandStmt",)),
    Command(
        name="DATA PRIMARY", topic="EPD",
        aliases=("DATA SECONDARY", "DATA PROXY", "CONTROL"),
        usage='DATA PRIMARY|SECONDARY|PROXY SOURCE "type" PROVIDER "who" YEAR n',
        summary="Declare where the data of a process or bridge comes from",
        syntax='''DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025
DATA SECONDARY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2024
DATA PROXY SOURCE "Database" PROVIDER "ecoinvent 3.11" YEAR 2019 REASON "why"
  [SHARE n%]
CONTROL DIRECT|NONE''',
        example='''EDIT PROCESS "A3 | Manufacturing"
  DATA PRIMARY SOURCE "Collected" PROVIDER "EPD owner" YEAR 2025
  CONTROL DIRECT
END EDIT''',
        notes="A line inside MAKE PROCESS, BRIDGE or EDIT PROCESS. "
              "SOURCE is the type of source (collected data, a database, "
              "an EPD), PROVIDER is who or what it came from, YEAR is the "
              "reference year. PROXY needs REASON. SHARE n% states the "
              "share of primary data when it is neither all nor nothing, "
              "for example for data taken from another EPD.\n"
              "CONTROL says whether the manufacturer controls the process "
              "directly. A3 is taken to be under direct control unless a "
              "process says CONTROL NONE.\n"
              "It is stored on the process as tags (epd:data=PRIMARY and "
              "so on), and the year also as the validity dates of the "
              "process documentation.\n"
              "DATA followed by values, on a line outside these blocks, is "
              "still the statement that queues values for READ INPUTS FROM "
              "DATA (HELP DATA).",
        statements=("EditProcessStmt",)),
    Command(
        name="ELECTRICITY", topic="EPD",
        usage='ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION',
        summary="Declare how the electricity of a bridge is modelled",
        syntax='''ELECTRICITY CONTRACT|RESIDUAL|CONSUMPTION
COUNTRY "code"
[REGION "grid region"]
[ENERGY SOURCE "text"]
[LOCATION BASED PROVIDER "process name or uuid"]''',
        example='''BRIDGE "Electricity", kWh
  PROVIDER "0f0f0f0f-0000-0000-0000-000000000000"
  ELECTRICITY RESIDUAL
  COUNTRY "GB"
  ENERGY SOURCE "Residual mix, United Kingdom"
END BRIDGE''',
        notes="Lines inside a BRIDGE block. CONTRACT is electricity "
              "backed by a contractual instrument, RESIDUAL the residual "
              "mix of the market, CONSUMPTION the consumption mix.\n"
              "Under PROGRAMME \"IES\": a consumption-mix bridge is "
              "refused in an A1 to A3 process under the manufacturer's "
              "direct control (GPI 5.1.0, A.7.1); for Australia, Brazil, "
              "Canada, China, India and the USA a residual or consumption "
              "mix needs REGION, the grid region (A.6.2).\n"
              "LOCATION BASED PROVIDER gives the bridge a second provider, "
              "the consumption mix, used only for the location-based "
              "results of EPD REPORT ... LOCATION BASED.",
        statements=("BridgeStmt",)),
    Command(
        name="NEW FROM TEMPLATE", topic="EPD",
        usage='NEW FROM TEMPLATE "name" AS "file.baslca"',
        summary="Copy a template program into the working folder",
        example='NEW FROM TEMPLATE "epd_skeleton" AS "my_epd.baslca"',
        notes="Templates: epd_skeleton (the EPD block and empty modules, "
              "with a comment at every decision), bridges_common (bridge "
              "patterns for electricity, road transport, water, landfill "
              "and incineration), sensitivity_epd (sensitivity on the "
              "main A1 and A3 parameters). It does not write over a file "
              "that exists.",
        statements=("NewFromTemplateStmt",)),

    # ── OUTPUT ───────────────────────────────────────────────
    Command(
        name="PRINT RESULTS", topic="OUTPUT",
        usage="PRINT RESULTS",
        summary="Show the most recent results again",
        example="PRINT RESULTS",
        statements=("PrintResultsStmt",)),
    Command(
        name="SAVE RESULTS", aliases=("EXPORT RESULTS TO",), topic="OUTPUT",
        usage='SAVE RESULTS "file.csv"',
        summary="Write the most recent results to a CSV file",
        example='SAVE RESULTS "results.csv"',
        statements=("SaveResultsStmt", "ExportResultsStmt")),
    Command(
        name="EXPORT <TYPE>", topic="OUTPUT",
        usage='EXPORT <type> "name or uuid" TO "file.zip"',
        summary="Have openLCA write an entity and what it depends on as JSON-LD",
        example='EXPORT PROCESS "Concrete block" TO "concrete_block.zip"\n'
                'EXPORT SYSTEM "Concrete block" TO "system.zip"',
        notes="openLCA writes the zip file itself, on the machine openLCA "
              "runs on, with everything the entity refers to (a system "
              "brings its processes and flows). The file can be imported "
              "into another openLCA database. Works for every type but "
              "flow maps. Licensed background data is exported with the "
              "model if the model uses it: check the licence before "
              "passing a file on.",
        statements=("EntityExportStmt",)),
    Command(
        name="SAVE PROGRAM", aliases=('SAVE "file.baslca"',), topic="OUTPUT",
        usage='SAVE PROGRAM "file.baslca"',
        summary="Write the program in memory to a file",
        example='SAVE PROGRAM "my_model.baslca"',
        notes="The program in memory is what LOAD put there, plus every "
              "program that has run without an error since. The file is "
              "the reproducible record of the work: RUN "
              "\"my_model.baslca\" repeats it. SAVE with a name ending in "
              ".baslca does the same.",
        statements=("SaveProgramStmt",)),

    # ── PROGRAMMING ──────────────────────────────────────────
    Command(
        name="PRINT", dialect=BASIC, topic="PROGRAMMING",
        usage="PRINT expression [, expression]",
        summary="Print text or values",
        example='PRINT "Cement:", cement_mass',
        statements=("PrintExprStmt", "PrintStmt")),
    Command(
        name="REM", aliases=("'",), dialect=BASIC, topic="PROGRAMMING",
        usage="REM text",
        summary="A comment (an apostrophe starts one too)",
        example="REM The mix design\nLET cement_mass = 300 ' kg per m3",
        statements=("CommentStmt",)),
    Command(
        name="IF", dialect=BASIC, topic="PROGRAMMING",
        usage="IF condition THEN ... [ELSE ...] END IF",
        summary="Do something only if a condition holds",
        syntax='''IF condition THEN
  statements
[ELSE
  statements]
END IF

IF condition THEN statement [ELSE statement]''',
        example='IF cement_mass > 350 THEN\n  PRINT "High cement mix"\nEND IF',
        notes="Conditions use =, <>, <, >, <=, >=, AND, OR and NOT.",
        statements=("IfStmt",)),
    Command(
        name="FOR", dialect=BASIC, topic="PROGRAMMING",
        usage="FOR name = start TO end [STEP n] ... NEXT",
        summary="Repeat with a counter",
        example='FOR i = 1 TO 3\n  PRINT i\nNEXT i',
        statements=("ForStmt",)),
    Command(
        name="FOR EACH", dialect=BASIC, topic="PROGRAMMING",
        usage="FOR EACH name IN value, value ... NEXT",
        summary="Repeat once for each value in a list",
        example='FOR EACH method$ IN "EF v3.1", "IPCC 2021"\n  PRINT method$\nNEXT',
        statements=("ForEachStmt",)),
    Command(
        name="WHILE", dialect=BASIC, topic="PROGRAMMING",
        usage="WHILE condition ... WEND",
        summary="Repeat while a condition holds",
        example="LET n = 0\nWHILE n < 3\n  LET n = n + 1\nWEND",
        statements=("WhileStmt",)),
    Command(
        name="SUB", dialect=BASIC, topic="PROGRAMMING",
        usage="SUB name(parameters) ... END SUB",
        summary="Define a subroutine; call it by name",
        example='SUB report(title$)\n  PRINT title$\nEND SUB\nreport "Results"',
        statements=("SubDef", "SubCall")),
    Command(
        name="FUNCTION", dialect=BASIC, topic="PROGRAMMING",
        usage="FUNCTION name(parameters) ... END FUNCTION",
        summary="Define a function; it returns the variable with its own name",
        example="FUNCTION double(x)\n  LET double = x * 2\nEND FUNCTION\nPRINT double(4)",
        notes="Built-in functions: ABS, INT, SQR, LOG, EXP, SIN, COS, TAN, "
              "MIN, MAX, ROUND, LEN, VAL, STR$, TRIM$, UCASE$, LCASE$.",
        statements=("FunctionDef",)),
    Command(
        name="DATA", dialect=BASIC, topic="PROGRAMMING",
        usage='DATA "name", amount, "unit"',
        summary="Queue values for READ INPUTS FROM DATA inside a PROCESS block",
        example='DATA "BRIDGE | Cement | kg", 300, "kg"\n'
                'PROCESS "Concrete block"\n'
                '  OUTPUT MAKE FLOW "Concrete block", 1, m3, PRODUCT\n'
                '  READ INPUTS FROM DATA\nEND PROCESS',
        statements=("DataStmt",)),
    Command(
        name="INPUT", dialect=BASIC, topic="PROGRAMMING",
        usage='INPUT "prompt", name',
        summary="Ask for a value at the terminal",
        example='INPUT "Cement mass in kg?", cement_mass',
        notes="Only works in the terminal. A program run through a "
              "Session has nobody to ask.",
        statements=("InputStmt",)),
    Command(
        name="INCLUDE", dialect=BASIC, topic="PROGRAMMING",
        usage='INCLUDE "file.baslca"',
        summary="Insert another program file at this point",
        example='INCLUDE "bridges.baslca"',
        statements=("IncludeStmt",)),
    Command(
        name="RUN", dialect=BASIC, topic="PROGRAMMING",
        usage='RUN ["file.baslca"]',
        summary="Run a program file, or on its own the program in memory",
        example='RUN "model.baslca"\nLOAD "model.baslca"\nRUN',
        notes="There is no GOTO and there are no line numbers.",
        statements=("RunFileStmt", "RunMemoryStmt")),
    Command(
        name="LOAD", dialect=BASIC, topic="PROGRAMMING",
        usage='LOAD "file.baslca"',
        summary="Put a program in memory without running it",
        example='LOAD "model.baslca"\nLIST\nRUN',
        notes="As on a BBC Micro: LOAD replaces the program in memory, "
              "LIST shows it, RUN runs it and SAVE writes it out. A file "
              "that does not parse is refused and memory is left as it "
              "was.",
        statements=("LoadStmt",)),
    Command(
        name="LIST", dialect=BASIC, topic="PROGRAMMING",
        usage="LIST",
        summary="Show the program in memory",
        example="LIST",
        notes="Lines are numbered for reference only; olcaBASIC programs "
              "have no line numbers.",
        statements=("ListStmt",)),

    # ── SESSION ──────────────────────────────────────────────
    Command(
        name="HELP", topic="SESSION",
        usage="HELP [topic or command]",
        summary="Show the command list, a topic, or one command",
        example="HELP\nHELP NAVIGATION\nHELP MAKE PROCESS",
        statements=("HelpStmt",)),
    Command(
        name="REFRESH", topic="SESSION",
        usage="REFRESH",
        summary="Read the lists of processes and flows from openLCA again",
        example="REFRESH",
        notes="Use it after changing the database in openLCA itself.",
        statements=("RefreshStmt",)),
    Command(
        name="CLEAR", topic="SESSION",
        usage="CLEAR",
        summary="Clear the terminal screen",
        example="CLEAR",
        statements=("ClearStmt",)),
    Command(
        name="SHUTDOWN SERVER", topic="SESSION",
        usage="SHUTDOWN SERVER CONFIRM",
        summary="Stop openLCA's IPC server (terminal only)",
        example="SHUTDOWN SERVER CONFIRM",
        notes="Closes every open result, then stops the IPC server and "
              "closes its database. Nothing can reach openLCA afterwards "
              "until the server is started again by hand. Refused without "
              "CONFIRM, and with it a person at the terminal has to "
              "answer YES: it cannot be done through a Session or the "
              "MCP.",
        statements=("ShutdownStmt",)),
    Command(
        name="EXIT", aliases=("QUIT",), topic="SESSION",
        usage="EXIT",
        summary="Leave olcaBASIC",
        example="EXIT",
        statements=("ExitStmt",)),
]


# ── lookups ──────────────────────────────────────────────────

# ── which IPC methods each command uses ──────────────────────
#
# Command name -> the methods of openLCA's IPC server it calls. The
# authoritative method list is olcabasic.engine.ipc_methods.IPC_METHODS;
# a test fails if any method there is used by no command here.
_READ = ("data/get", "data/get/descriptors")

IPC_USE: Dict[str, Tuple[str, ...]] = {
    "CAT": ("data/get/descriptors",),
    "DIR": ("data/get/descriptors",),
    "FIND PROCESS": ("data/get/descriptors",),
    "FIND FLOW": ("data/get/descriptors",),
    "FIND SYSTEM": ("data/get/descriptors",),
    "FIND METHOD": ("data/get/descriptors",),
    "FIND UNIT": ("data/get/all",),
    "SHOW PROCESS": _READ + ("data/get/descriptor",),
    "SHOW FLOW": _READ + ("data/get/providers",),
    "SHOW SYSTEM": _READ + ("data/get/parameters",),
    "SHOW GLOBAL PARAMS": ("data/get/all",),
    "SHOW PARAMETER": ("data/get/all",),
    "DATABASE INFO": ("data/get/descriptors",),
    "PRINT UNITS": ("data/get/all",),
    "PRINT DQ SYSTEMS": ("data/get/all",),
    "MAKE PROCESS": _READ + ("data/put", "data/get/providers"),
    "MAKE FLOW": _READ + ("data/put",),
    "BRIDGE": _READ + ("data/put",),
    "SYSTEM": _READ + ("data/create/system", "data/put"),
    "LINK": _READ + ("data/put",),
    "MOVE": _READ + ("data/put",),
    "DELETE": _READ + ("data/delete", "data/get/usage", "data/get/all"),
    "EPD DQ SHEET": _READ + ("result/calculate", "result/dispose"),
    "EPD DQ TABLE": _READ + ("result/calculate", "result/dispose"),
    "EPD SENSITIVITY": _READ + ("data/get/parameters", "result/calculate",
                                "result/state", "result/total-impacts",
                                "result/dispose"),
    "EPD EXPORT MODEL": _READ + ("data/get/all",),
    "EPD SAVE": _READ + ("data/put", "result/calculate", "result/state",
                         "result/total-impacts", "result/total-flows",
                         "result/demand", "result/dispose"),
    "FIND <TYPE>": ("data/get/descriptors",),
    "SHOW <TYPE>": _READ + ("data/get/usage", "data/get/all"),
    "MAKE ACTOR": _READ + ("data/put",),
    "MAKE SOURCE": _READ + ("data/put", "data/put/source-file"),
    "MAKE CURRENCY": _READ + ("data/put", "data/get/all"),
    "MAKE LOCATION": _READ + ("data/put",),
    "MAKE UNITS": _READ + ("data/put",),
    "MAKE PROPERTY": _READ + ("data/put",),
    "MAKE SOCIAL INDICATOR": _READ + ("data/put",),
    "MAKE DQ SYSTEM": _READ + ("data/put",),
    "EDIT <TYPE>": _READ + ("data/put",),
    "MAKE METHOD": _READ + ("data/put",),
    "EDIT METHOD": _READ + ("data/put", "data/delete", "data/get/all"),
    "MAKE PROJECT": _READ + ("data/put", "data/get/parameters"),
    "CALCULATE PROJECT": ("data/get", "result/calculate", "result/state",
                          "result/total-impacts", "result/dispose"),
    "SAVE RESULT AS": ("data/put", "result/total-impacts",
                       "result/total-flows", "result/demand"),
    "EXPORT <TYPE>": ("data/get/descriptors", "export/json-ld"),
    "SHUTDOWN SERVER": ("result/dispose", "runtime/shutdown"),
    "EDIT PROCESS": _READ + ("data/put",),
    "EDIT FLOW": _READ + ("data/put",),
    "EDIT SYSTEM": _READ + ("data/get/parameters", "data/put"),
    "PARAMETERISE PROCESS": _READ + ("data/put",),
    "LET": ("data/put",),
    "UPDATE PARAMETER": ("data/get/all", "data/put"),
    "CALCULATE": ("result/calculate", "result/state", "result/demand",
                  "result/total-impacts", "result/dispose"),
    "CLOSE RESULT": ("result/dispose",),
    "RESULT IMPACTS": ("result/total-impacts",
                       "result/total-impact-value-of",
                       "result/grouped-impact-results-of",
                       "result/tag-results-of-impact"),
    "RESULT CATEGORIES": ("result/impact-categories",),
    "RESULT PROCESSES": ("result/tech-flows",),
    "RESULT DEMAND": ("result/demand",),
    "RESULT FLOWS": ("result/total-flows", "result/envi-flows",
                     "result/total-flow-value-of",
                     "result/total-interventions-of",
                     "result/total-intervention-of",
                     "result/direct-interventions-of",
                     "result/direct-intervention-of",
                     "result/grouped-flow-results-of",
                     "result/tag-results-of-flow"),
    "RESULT FLOW": ("result/flow-contributions-of",),
    "RESULT CONTRIBUTION": ("result/impact-contributions-of",
                            "result/total-impacts-of",
                            "result/total-impact-of",
                            "result/direct-impacts-of",
                            "result/direct-impact-of",
                            "result/flow-impacts-of",
                            "result/flow-impact-of"),
    "RESULT FACTORS": ("result/impact-factors-of",
                       "result/impact-factor-of"),
    "RESULT INTENSITY": ("result/impact-intensities-of",
                         "result/impact-intensity-of",
                         "result/flow-intensities-of",
                         "result/flow-intensity-of"),
    "RESULT SCALING": ("result/scaling-factors",
                       "result/scaled-tech-flows-of",
                       "result/unscaled-tech-flows-of"),
    "RESULT TOTALITY": ("result/totality-factors",
                        "result/totality-factor-of"),
    "RESULT REQUIREMENTS": ("result/total-requirements",
                            "result/total-requirements-of"),
    "RESULT TREE": ("result/upstream-impacts-of",
                    "result/upstream-interventions-of",
                    "result/upstream-costs-of"),
    "RESULT COSTS": ("result/total-costs", "result/total-costs-of",
                     "result/direct-costs-of", "result/cost-intensities-of",
                     "result/cost-contributions",
                     "result/grouped-cost-results",
                     "result/tag-results-of-costs",
                     "result/upstream-costs-of"),
    "RESULT NORMALISED": ("result/total-impacts/normalized",),
    "RESULT WEIGHTED": ("result/total-impacts/weighted",),
    "RESULT SANKEY": ("result/sankey",),
    "CONTRIBUTION": ("result/calculate", "result/tech-flows",
                     "result/total-impacts-of", "result/dispose"),
    "TREE": ("result/calculate", "result/demand",
             "result/upstream-impacts-of", "result/dispose"),
    "INVENTORY": ("result/calculate", "result/total-flows",
                  "result/dispose"),
    "MONTECARLO": ("result/simulate", "result/simulate/next",
                   "result/total-impacts", "result/dispose"),
    "RUN SCENARIOS": ("data/get/parameters", "result/calculate",
                      "result/total-impacts", "result/dispose"),
    "SENSITIVITY": ("data/get/parameters", "result/calculate",
                    "result/total-impacts", "result/dispose"),
    "VALIDATE": _READ,
    "AUDIT": _READ,
    "EXTRACT": _READ,
}


_TYPE_WORDS = (
    "PROPERTY", "FLOW PROPERTY", "UNITS", "UNIT GROUP", "PARAMETER",
    "METHOD", "CATEGORY", "IMPACT CATEGORY", "LOCATION", "DQ SYSTEM",
    "ACTOR", "SOURCE", "CURRENCY", "SOCIAL INDICATOR", "PROJECT", "RESULT",
    "STORED RESULT", "EPD", "FLOW MAP", "PROCESS", "FLOW", "SYSTEM",
    "TYPE", "<TYPE>")


def _norm(text: str) -> str:
    return " ".join(text.upper().split())


def find(name: str) -> Optional[Command]:
    """The entry for a command word or one of its aliases."""
    key = _norm(name)
    for c in COMMANDS:
        if _norm(c.name) == key or key in (_norm(a) for a in c.aliases):
            return c
    # HELP FIND ACTOR, HELP SHOW DQ SYSTEM: the entry for any type
    first, _, rest = key.partition(" ")
    if rest in _TYPE_WORDS:
        generic = f"{first} <TYPE>"
        for c in COMMANDS:
            if c.name == generic:
                return c
        if first in ("DELETE", "MOVE"):
            return find(first)
    return None


def find_all(name: str) -> List[Command]:
    """Entries a word could mean: 'FIND' gives every FIND command."""
    exact = find(name)
    if exact:
        return [exact]
    key = _norm(name)
    return [c for c in COMMANDS
            if _norm(c.name).startswith(key + " ")
            or any(_norm(a).startswith(key + " ") for a in c.aliases)]


def topic_of(name: str) -> Optional[str]:
    key = _norm(name)
    key = TOPIC_ALIASES.get(key, key)
    return key if key in TOPICS else None


def by_topic(topic: str) -> List[Command]:
    return [c for c in COMMANDS if c.topic == topic]


def documented_statements() -> set:
    """Names of every AST statement class that has an entry."""
    return {s for c in COMMANDS for s in c.statements}


# ── renderers ────────────────────────────────────────────────

def _indent(text: str, by: str = "    ") -> str:
    return "\n".join(by + line if line else line for line in text.split("\n"))


def _summary_line(c: Command) -> List[str]:
    """'    CAT / LS      summary', wrapped if the words are long."""
    if len(c.heading) <= 28:
        return [f"    {c.heading:<28}  {c.summary}"]
    return [f"    {c.heading}", f"    {'':<28}  {c.summary}"]


def render_help() -> str:
    """HELP: every command with its one-line summary, by topic."""
    out = ["", "  olcaBASIC commands"]
    for topic, title in TOPICS.items():
        commands = by_topic(topic)
        if not commands:
            continue
        out.append("")
        out.append(f"  {topic}: {title}")
        for c in commands:
            out.extend(_summary_line(c))
    out.append("")
    out.append("  HELP <topic> shows syntax and examples: "
               + ", ".join(TOPICS))
    out.append("  HELP <command> shows one command, for example HELP MAKE PROCESS")
    out.append("  Navigation works in two dialects: Acorn (CAT, DIR, UP) "
               "and Linux (LS, CD, CD ..).")
    out.append("")
    return "\n".join(out)


def render_command(c: Command) -> str:
    """HELP <command>."""
    out = ["", f"  {c.heading}", f"    {c.summary}."]
    if c.aliases:
        if c.alias_dialect and c.alias_dialect != c.dialect:
            out.append(f"    {c.name} is the {c.dialect} form; "
                       f"{', '.join(c.aliases)} the {c.alias_dialect} form. "
                       f"They do the same thing.")
        else:
            out.append(f"    Also written: {', '.join(c.aliases)}")
    out.append("")
    out.append("  Syntax:")
    out.append(_indent(c.full_syntax))
    out.append("")
    out.append("  Example:")
    out.append(_indent(c.example))
    if c.notes:
        out.append("")
        for para in c.notes.split("\n"):
            out.append(f"  {para}")
    out.append("")
    return "\n".join(out)


def render_topic(topic: str) -> str:
    """HELP <topic>: syntax and an example for each command."""
    out = ["", f"  {topic}: {TOPICS[topic]}"]
    for c in by_topic(topic):
        out.append("")
        out.append(f"  {c.heading}")
        out.append(f"    {c.summary}.")
        out.append(_indent(c.full_syntax, "      "))
    out.append("")
    out.append("  HELP <command> shows an example and notes for one command.")
    out.append("")
    return "\n".join(out)


def render(query: str = "") -> str:
    """What HELP prints for a query: nothing, a topic, or a command."""
    query = (query or "").strip().strip('"')
    if not query:
        return render_help()
    topic = topic_of(query)
    exact = find(query)
    if exact and not topic:
        return render_command(exact)
    if topic:
        text = render_topic(topic)
        if exact:
            text = render_command(exact).rstrip("\n") + "\n" + text
        return text
    if _norm(query) == "NEW":
        return ("\n  NEW is the old word for MAKE FLOW inside a PROCESS block "
                "(INPUT NEW, OUTPUT NEW).\n  It still works but is "
                "deprecated. See HELP MAKE PROCESS.\n  NEW FROM TEMPLATE "
                "copies a template program: HELP NEW FROM TEMPLATE.\n")
    matches = find_all(query)
    if len(matches) == 1:
        return render_command(matches[0])
    if matches:
        out = ["", f"  {_norm(query)} has several forms:"]
        for c in matches:
            out.extend(_summary_line(c))
        out.append("")
        out.append("  HELP <one of these> shows its syntax and an example.")
        out.append("")
        return "\n".join(out)
    return (f"\n  No help for: {query}\n  Type HELP for the command list. "
            f"Topics: {', '.join(TOPICS)}\n")


RULES = """\
olcaBASIC is a BASIC-style language that drives openLCA. One statement per
line. Names go in "double quotes". Blocks end with END <word>. No GOTO, no
line numbers. Comments start with REM or '.
- Every calculation needs USING "method" (the full method name).
- A name that could mean several processes is an error: add LOCATION "code"
  or PROVIDER "uuid". FIND PROCESS shows the candidates.
- A program stops at its first error. Each error gives the line and a hint.
- DELETE needs CONFIRM DELETE ON earlier in the program.
- Variables persist between runs in the same session. A top-level variable
  used as an amount becomes a global parameter in openLCA.
- Every background process goes through a bridge: BRIDGE "short name", unit
  with PROVIDER "process" LOCATION "code", then INPUT USE PROCESS
  "BRIDGE | short name | unit". Naming a background process straight in a
  process is an error.
- MAKE is idempotent: an identical block run again changes nothing. A MAKE
  PROCESS block that differs from the stored process is an error listing
  the differences: use EDIT PROCESS, or DELETE PROCESS and run it again.
- After EDIT PROCESS, LINK, MOVE or PARAMETERISE, the product systems that
  hold the process are out of date: DELETE SYSTEM, SYSTEM, VALIDATE.
- A product system that fails VALIDATE cannot be calculated until it passes.
- OUTPUT and INPUT never create a flow by themselves: write MAKE FLOW. A new
  emission needs a characterisation factor in the method, or IGNORE FACTORS.
- MONTECARLO needs UNCERTAINTY somewhere; ALLOCATE PHYSICAL|ECONOMIC needs
  ALLOCATION factors on every process with several products.
- RESULT reads more from the result CALCULATE left open (HELP RESULT).
- Defaults that were applied are stated in the output (NOTE: default used).
- SAVE PROGRAM "file.baslca" writes out what has run, as the record of the work.
"""


# The commands whose one-line usage the overview spells out. Every
# other command is named, and olcabasic_help gives its syntax.
OVERVIEW_USAGE = (
    "FIND PROCESS", "SHOW PROCESS", "MAKE FLOW", "BRIDGE", "MAKE PROCESS",
    "SYSTEM", "VALIDATE", "CALCULATE", "RESULT CONTRIBUTION",
    "RUN SCENARIOS", "EPD", "SAVE RESULTS",
)


def overview_names(commands: List[Command]) -> str:
    """The names of some commands on one line. Commands that share a
    first word are folded: FIND PROCESS|FLOW|SYSTEM."""
    groups: Dict[str, List[str]] = {}
    for c in commands:
        first, _, rest = c.name.partition(" ")
        groups.setdefault(first, []).append(rest)
    parts = []
    for first, rests in groups.items():
        named = [r for r in rests if r]
        text = first
        if named:
            text += " " + "|".join(named)
            if len(named) < len(rests):       # the bare word is one too
                text = first + ", " + text
        parts.append(text)
    return "; ".join(parts)


def render_overview() -> str:
    """A compact reference for an assistant: the rules of the language,
    the usage of the commands most programs need, and the name of every
    command by topic. Kept under 2,000 tokens (tested)."""
    out = [RULES.rstrip(), "", "The commands most programs use:"]
    for name in OVERVIEW_USAGE:
        out.append(f"  {find(name).usage}")
    out.append("")
    out.append("Every command, by topic (A B|C means A B and A C; <TYPE> "
               "is any entity type):")
    for topic in TOPICS:
        commands = by_topic(topic)
        if commands:
            out.append(f"{topic}: {overview_names(commands)}")
    out.append("")
    out.append("Detail: olcabasic_help with a topic ("
               + ", ".join(t.lower() for t in TOPICS)
               + ") or a command name gives syntax, an example and notes.")
    return "\n".join(out)


def render_markdown() -> str:
    """The command reference section of the README."""
    out = ["Every command, by topic. `HELP`, `HELP <topic>` and "
           "`HELP <command>` show the same reference inside olcaBASIC.", ""]
    for topic, title in TOPICS.items():
        commands = by_topic(topic)
        if not commands:
            continue
        out.append(f"### {topic.capitalize()}: {title.lower()}")
        out.append("")
        out.append("| Command | Dialect | What it does |")
        out.append("|---|---|---|")
        for c in commands:
            words = " / ".join(f"`{w}`" for w in (c.name,) + c.aliases)
            dialect = c.dialect
            if c.aliases and c.alias_dialect and c.alias_dialect != c.dialect:
                dialect = f"{c.dialect} / {c.alias_dialect}"
            out.append(f"| {words} | {dialect} | {c.summary} |")
        out.append("")
        out.append("```basic")
        blocks = []
        for c in commands:
            blocks.append(c.full_syntax)
        out.append("\n".join(blocks))
        out.append("```")
        out.append("")
    return "\n".join(out).rstrip() + "\n"


README_BEGIN = "<!-- BEGIN COMMAND REFERENCE (generated by olcabasic.registry; do not edit by hand) -->"
README_END = "<!-- END COMMAND REFERENCE -->"


def update_readme(text: str) -> str:
    """README text with the generated reference between the markers."""
    start = text.index(README_BEGIN) + len(README_BEGIN)
    end = text.index(README_END)
    return text[:start] + "\n\n" + render_markdown() + "\n" + text[end:]


def _main(argv=None) -> int:
    import argparse
    parser = argparse.ArgumentParser(
        description="Print the olcaBASIC command reference, or write it "
                    "into a README between the reference markers.")
    parser.add_argument("--readme", help="README file to update in place")
    parser.add_argument("--overview", action="store_true",
                        help="print the compact overview")
    args = parser.parse_args(argv)
    if args.readme:
        with open(args.readme, "r", encoding="utf-8") as f:
            text = f.read()
        with open(args.readme, "w", encoding="utf-8", newline="\n") as f:
            f.write(update_readme(text))
        print(f"Updated the command reference in {args.readme}")
    elif args.overview:
        print(render_overview())
    else:
        print(render_help())
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
