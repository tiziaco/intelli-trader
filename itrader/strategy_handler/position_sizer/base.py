from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class AbstractPositionSizer(Protocol):
    """
    Structural interface (D-07) for position sizers, which modify
    the quantity (or not) of any share transacted.
    """

    def size_order(self, portfolio: Any, initial_order: Any) -> Any:
        """
        Modify the order quantity according to the sizer policy.
        """
        ...
