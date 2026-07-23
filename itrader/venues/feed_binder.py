"""FeedConnectionBinder — bind the ONE live feed to a venue CONNECTION, not an account (11.2-07, D-36).

D-36 DELETES "primary account" as a concept. The former primary-lifecycle accessor had
zero production readers, and the data path provably does not care WHICH account supplies
its bars: ``okx_plugin.build_provider`` resolves an account-keyed connector but
configures everything from ``ctx.config.stream``, using only the connector's host
routing and its **public** ``fetch_ohlcv``. So the feed is bound to a *connection*,
never to a privileged account, and the binder owns that binding:

* it **borrows the first available connection** — the first online account whose
  execution bundle carries a live connector (paper carries ``connector=None`` and is
  not a streaming connection);
* it **re-borrows** when the account whose connection it holds is retired or disabled,
  logging the switch at a level an operator sees;
* it **warns and unbinds** when no connection is left, and warns when there was none to
  begin with (a zero-account boot comes up RUNNING with an unbound feed — D-09).

Bars are PUBLIC data, so a connection switch changes TRANSPORT, not content, and
``LiveBarFeed``'s monotonic-forward guard covers the reconnect — no bar is replayed out
of order. There is **no in-tree analog for a re-bindable provider** (11.2-PATTERNS
§"No Analog Found"); this is derived from those two facts, not copied from a shape.

**Why this is a collaborator the manager OWNS rather than inline manager methods.** The
re-borrow rule, the provider build and the feed wiring are one cohesive concern with a
single piece of state (the currently-bound pair), unit-testable with a fake feed and a
fake data registry and no ``LiveTradingSystem``. ``VenueAccountManager`` DRIVES it — it
calls ``rebind`` from ``bring_online`` and exposes ``feed_provider`` through — so the
account domain owns the binding, and this class is where the novel logic lives so it can
be tested in isolation.

**Why it does NOT loosen credentials.** It builds the data provider through the SAME
``DataProviderRegistry.get(spec.data_provider).build_provider`` path the composition root
used, over the SAME account-keyed connector — so a credential-free data connection stays
the deferred phase it is, and ``okx_plugin``'s ``CredentialResolutionError`` fail-closed
gate is untouched.

Import-inert (GATE-01): ``from __future__ import annotations`` + ``TYPE_CHECKING``-only
annotations keep this module ccxt/sqlalchemy/async-free. Every collaborator is a plain
injected object; the concretion lives inside the plugins' ``build_provider`` bodies.

Indentation: 4-SPACE (``venues/`` package convention). ``mypy --strict`` applies.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from itrader.logger import get_itrader_logger

if TYPE_CHECKING:
    from collections.abc import Sequence

    #: One candidate connection: ``(venue_name, account_id, venue_spec)``. The spec
    #: carries ``data_provider`` (the registry key) and the account identity the provider
    #: build borrows its connector under.
    Candidate = tuple[str, str, Any]


class FeedConnectionBinder:
    """Own the ONE live feed's borrowed data connection and its re-borrow rule (D-36).

    Parameters
    ----------
    feed :
        The ONE ``LiveBarFeed``. ``set_provider`` is its only public bind seam;
        ``set_provider(None)`` unbinds. Typed ``Any`` because naming ``LiveBarFeed`` here
        would drag it onto this module's import graph (the same reason the manager types
        its handler ``Any``).
    data_registry :
        The ``DataProviderRegistry``. ``get(spec.data_provider).build_provider(...)`` is
        the SAME one-provider build path the composition root used — one home for the
        default-provider map (D-11), one fail-loud ``KeyError`` on an unregistered
        provider.
    ctx :
        The shared ``EngineContext`` the provider build reads (``ctx.config.stream`` is
        the single wiring source for the OKX subscription — IN-01).
    connectors :
        The shared ``ConnectorProvider`` — the provider borrows the account-keyed
        connector from it, the same one the execution arm holds (D-03).
    global_queue :
        The live bus the provider publishes onto (``set_global_queue``).
    """

    def __init__(
        self,
        *,
        feed: Any,
        data_registry: Any,
        ctx: Any,
        connectors: Any,
        global_queue: Any,
    ) -> None:
        self._feed = feed
        self._data_registry = data_registry
        self._ctx = ctx
        self._connectors = connectors
        self._global_queue = global_queue
        # The ONE piece of state: which pair's connection the feed currently holds, and
        # the provider object built from it. Both None means the feed is unbound.
        self._bound_pair: tuple[str, str] | None = None
        self._provider: Any = None
        self.logger = get_itrader_logger().bind(component="FeedConnectionBinder")

    @property
    def feed_provider(self) -> Any:
        """The provider currently bound to the feed, or ``None`` when unbound.

        Read by the composition root's facade-dependent halt-signal wiring and by the
        live session's warmup/subscribe step — both None-guard it, because a zero-account
        boot leaves it None (D-09).
        """
        return self._provider

    def rebind(self, available: "Sequence[Candidate]") -> None:
        """Ensure the feed holds a VALID connection, re-borrowing or unbinding as needed.

        ``available`` is the ordered set of connections that could serve the feed RIGHT
        NOW — the online accounts with a live connector, still enabled. The manager
        computes it; this method acts on it:

        * bound pair still present  → no-op (the borrow is still valid);
        * bound pair gone, others   → re-borrow the FIRST available, log the SWITCH;
        * unbound, some available    → bind the FIRST, log the initial bind;
        * none available             → unbind (if bound) and WARN, naming the cause.

        Idempotent: calling it repeatedly with an unchanged, valid ``available`` set does
        nothing. Safe to call on every ``bring_online`` and once more after the boot loop.
        """
        present = {(venue, account) for venue, account, _ in available}
        if self._provider is not None and self._bound_pair in present:
            return

        if not available:
            if self._provider is not None:
                self._feed.set_provider(None)
                lost = self._bound_pair
                self._provider = None
                self._bound_pair = None
                self.logger.warning(
                    "Live feed UNBOUND — the connection it borrowed from %r is gone and "
                    "no other venue connection is left; the feed will receive no bars "
                    "until an account is provisioned (D-36/D-09)", lost)
            else:
                self.logger.warning(
                    "Live feed has no venue connection to borrow — it stays UNBOUND "
                    "(zero streaming accounts online). A provisioned account will bind it "
                    "with no restart (D-36/D-09)")
            return

        venue_name, account_id, spec = available[0]
        switching = self._provider is not None
        previous = self._bound_pair
        # SAME build path as the composition root: one provider, over the account-keyed
        # connector. The concretion import lives inside build_provider (GATE-01).
        provider = self._data_registry.get(
            spec.data_provider).build_provider(self._ctx, spec, self._connectors)
        self._feed.set_provider(provider)
        provider.set_bar_sink(self._feed.update)
        provider.set_global_queue(self._global_queue)
        self._provider = provider
        self._bound_pair = (venue_name, account_id)
        if switching:
            self.logger.info(
                "Live feed RE-BORROWED its data connection: %r -> (%s, %s). Bars are "
                "public data, so this changes transport not content; the monotonic guard "
                "covers the reconnect (D-36)", previous, venue_name, account_id)
        else:
            self.logger.info(
                "Live feed bound to the data connection of (%s, %s) (D-36)",
                venue_name, account_id)
