"""
The olcaBASIC engine: everything that talks to openLCA.

Wraps olca_ipc calls using the same patterns as the tested
Below280 scenario and sensitivity scripts. All calculations
target ProductSystem objects (never bare Processes), and every
result is disposed after use.

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
"""

import logging

from .analysis import AnalysisMixin
from .audit import AuditMixin
from .build import BuildMixin
from .calculate import CalculateMixin
from .core import CoreMixin
from .explore import ExploreMixin
from .resolve import ResolveMixin

logger = logging.getLogger(__name__)


class Engine(CoreMixin, ExploreMixin, BuildMixin, AuditMixin, CalculateMixin,
             AnalysisMixin, ResolveMixin):
    """One connection's worth of openLCA operations.

    Methods return plain dictionaries. A failure is reported as
    {"error": "..."} and never raised, so callers can show the message.
    The public methods are listed in docs/ENGINE.md; names starting with
    an underscore are internal to the engine package.
    """


# The name this class had in b280_olca_mcp.functions up to v1.16.0.
LCAFunctions = Engine
