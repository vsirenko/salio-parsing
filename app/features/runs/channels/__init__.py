"""Channel implementations, one per source slug.

Imported for their side effect: each module registers itself, and a channel that is not
imported is a channel the worker cannot find. Adding a shop is adding a module and a line
here; nothing about the scheduler or the run lifecycle changes.
"""

from app.features.runs.channels import bigbox, ksenukai, onea, rdveikals

__all__ = ("bigbox", "ksenukai", "onea", "rdveikals")
