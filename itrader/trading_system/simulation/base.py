from abc import ABC, abstractmethod
from typing import Any, Iterator


class SimulationEngine(ABC):
    """
    Interface to a trading event simulation engine.

    Subclasses take starting and ending timestamps and generate events at a specific
    frequency by overriding ``__iter__`` and yielding Event entities — an exchange
    opening or closing, and the pre- and post-opening events that let the system
    handle cash-flows and corporate actions.
    """

    @abstractmethod
    def __iter__(self) -> Iterator[Any]:
        raise NotImplementedError(
            "Should implement __iter__()"
        )
