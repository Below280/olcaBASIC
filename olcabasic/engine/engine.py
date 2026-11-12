"""
The olcaBASIC engine: everything that talks to openLCA.

Wraps olca_ipc calls using the same patterns as the tested
Below280 scenario and sensitivity scripts. All calculations
target ProductSystem objects (never bare Processes), and every
result is disposed: straight away by the one-shot calculations, and by
close_result() or close_all_results() for results opened with
open_result().

This was b280_olca_mcp.functions.LCAFunctions up to B280-olca-MCP
v1.16.0. It moved here in olcaBASIC 0.4.0 so that olcaBASIC no longer
depends on the MCP server. Behaviour and return shapes are unchanged.

The class is put together from one module per kind of work:

    core.py       connection, cache, name resolution, family and units
    explore.py    searching, listing, inspecting
    build.py      flows, bridges, processes, systems, edits, deletions
    audit.py      extract, audit, validate
    calculate.py  impacts, contributions, inventory, Monte Carlo, tree
    analysis.py   scenarios and sensitivity
    resolve.py    name resolution for the language (strict look-ups)
    results.py    results that stay open, and every query on one
    fields.py     uncertainty, costs, allocation, documentation, social
                  aspects, parameter sets, analysis groups
    entities.py   every entity type: find, show, move, delete; actors,
                  sources, currencies, locations, unit groups, flow
                  properties, social indicators, data quality systems,
                  impact methods, projects, stored results
"""

import logging

from .analysis import AnalysisMixin
from .audit import AuditMixin
from .build import BuildMixin
from .calculate import CalculateMixin
from .core import CoreMixin
from .entities import EntitiesMixin
from .explore import ExploreMixin
from .fields import FieldsMixin
from .resolve import ResolveMixin
from .results import ResultsMixin

logger = logging.getLogger(__name__)


class Engine(CoreMixin, ExploreMixin, BuildMixin, AuditMixin, CalculateMixin,
             AnalysisMixin, ResolveMixin, ResultsMixin, FieldsMixin,
             EntitiesMixin):
    """One connection's worth of openLCA operations.

    Methods return plain dictionaries. A failure is reported as
    {"error": "..."} and never raised, so callers can show the message.
    The public methods are listed in docs/ENGINE.md; names starting with
    an underscore are internal to the engine package.
    """


# The name this class had in b280_olca_mcp.functions up to v1.16.0.
LCAFunctions = Engine
