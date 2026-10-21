"""The four tool functions the agent calls, bundled so tests can swap in fakes (Phase 2, R2.2, R2.3)."""
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True)
class Toolset:
    generate: Callable  # exact signatures: see molcurator.tools.generate / predict / validate / curate
    predict: Callable
    validate: Callable
    curate: Callable

    @classmethod
    def default(cls) -> "Toolset":
        """The real tools. Imported here, so code that only uses fakes never loads their dependencies."""
        from molcurator.tools import curate, generate, predict, validate
        return cls(generate.generate, predict.predict, validate.validate, curate.curate)

    @classmethod
    def from_object(cls, tools) -> "Toolset":
        """Any object with the four methods, e.g. FakeTools in tests."""
        return cls(tools.generate, tools.predict, tools.validate, tools.curate)
