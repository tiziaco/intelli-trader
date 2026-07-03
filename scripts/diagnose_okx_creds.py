"""Read-only OKX credential diagnostic (RECON-06 support tooling).

Tries an authenticated ``fetch_balance`` against BOTH the demo (x-simulated-trading)
and live OKX endpoints to tell whether the ``OKX_API_*`` triple in the environment is
recognized, and by which environment. Places no orders and never prints secret values
(only the key's first 4 characters and value lengths).

Run via ``make diagnose-okx`` (loads ``.env``), or with OKX_API_* exported manually.

Interpreting results:
- ✅ on DEMO only  -> a demo-trading key; the live suite (sandbox=True) will work.
- ✅ on LIVE only  -> a production key; do NOT run the live suite with it (real-money
  routing risk) — create a Demo Trading key instead.
- ❌ 50119 on both -> OKX does not recognize the key at all: it is revoked/expired,
  from a different OKX regional entity, or simply wrong. Regenerate it in your OKX
  account (Demo Trading -> API for the demo suite).
- 50105 (passphrase) -> key is found but the passphrase does not match.
"""
from __future__ import annotations

import os

import ccxt


def _mask(v: str) -> str:
    return (v[:4] + "…") if v else "<empty>"


def _try_mode(sandbox: bool) -> None:
    label = "DEMO (x-simulated-trading:1)" if sandbox else "LIVE (production)"
    key = os.environ.get("OKX_API_KEY", "")
    sec = os.environ.get("OKX_API_SECRET", "")
    pw = os.environ.get("OKX_API_PASSPHRASE", "")
    print(f"\n=== {label} ===")
    print(
        f"    key={_mask(key)} (len {len(key)})  "
        f"secret={'set' if sec else 'MISSING'} (len {len(sec)})  "
        f"passphrase={'set' if pw else 'MISSING'} (len {len(pw)})"
    )
    client = ccxt.okx(
        {"apiKey": key, "secret": sec, "password": pw, "enableRateLimit": True}
    )
    if sandbox:
        client.set_sandbox_mode(True)
    try:
        bal = client.fetch_balance()
        nonzero = {k: v for k, v in bal.get("total", {}).items() if v}
        print(
            "    ✅ AUTH OK — fetch_balance succeeded. "
            f"non-zero balances: {nonzero or '(all zero)'}"
        )
    except ccxt.AuthenticationError as e:
        print(f"    ❌ AUTH FAILED: {type(e).__name__}: {e}")
    except Exception as e:  # noqa: BLE001 — diagnostic surfaces every failure verbatim
        print(f"    ⚠️  ERROR: {type(e).__name__}: {e}")
    finally:
        try:
            client.close()
        except Exception:  # noqa: BLE001
            pass


def main() -> None:
    print("OKX credential diagnostic (read-only fetch_balance — no orders placed)")
    _try_mode(sandbox=True)
    _try_mode(sandbox=False)


if __name__ == "__main__":
    main()
