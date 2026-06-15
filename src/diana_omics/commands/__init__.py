"""Runnable Python command families.

Public CLI names and implementation modules are registered in
``diana_omics.commands.registry``. This package keeps module-level exports for
tests and exploratory imports while the files live under family folders.
"""

from __future__ import annotations

from importlib import import_module

from .registry import COMMAND_SPECS, TASK_ONLY_MODULES

_MODULE_ALIASES = {
    command_spec.module.rsplit(".", 1)[-1]: command_spec.module
    for command_spec in COMMAND_SPECS.values()
}
_MODULE_ALIASES.update(
    {
        module.rsplit(".", 1)[-1]: module
        for module in TASK_ONLY_MODULES
    }
)

__all__ = sorted(_MODULE_ALIASES)


def __getattr__(name: str):
    if name not in _MODULE_ALIASES:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module = import_module(_MODULE_ALIASES[name])
    globals()[name] = module
    return module
