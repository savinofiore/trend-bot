"""Private-client tests that need no network: serialization + surface area."""

from __future__ import annotations

from decimal import Decimal

from trendbot.marketdata.bybit_private import BybitPrivateClient, _fmt


def test_fmt_never_uses_scientific_notation():
    # The classic prod bug: str(float(qty)) → "1e-07" → "qty invalid" on Bybit.
    assert _fmt(Decimal("0.0000001")) == "0.0000001"
    assert "e" not in _fmt(Decimal("0.00000001")).lower()
    assert _fmt(Decimal("12345.6")) == "12345.6"


def test_signature_is_deterministic():
    client = BybitPrivateClient("key", "secret", testnet=True)
    a = client._sign("1700000000000", "symbol=BTCUSDT")
    b = client._sign("1700000000000", "symbol=BTCUSDT")
    assert a == b and len(a) == 64  # hex sha256


def test_no_withdrawal_or_transfer_methods_exist():
    # BP-6: the capability must be absent, not merely unused.
    forbidden = ("withdraw", "transfer", "subaccount", "create_sub", "internal_transfer")
    names = [n.lower() for n in dir(BybitPrivateClient)]
    for name in names:
        assert not any(bad in name for bad in forbidden), f"forbidden surface: {name}"


def test_secret_not_stored_in_plaintext_attr():
    # BP-7: the raw secret string must not be trivially retrievable/loggable.
    client = BybitPrivateClient("key", "supersecret", testnet=True)
    assert "supersecret" not in repr(client)
