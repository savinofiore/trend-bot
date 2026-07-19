# trend-bot

Systematic trend-following trading bot for crypto spot (BTC/ETH, no leverage).
A single pure signal drives both the backtest and live execution. The design
bias is **safety over features**: on any ambiguity about state, the bot stops,
alerts, and does not trade.

```
marketdata → signal (pure) → order_sizer (pure) → execution engine → exchange
                                    │                     │
                                    └──────► storage (Supabase, observability) ◄─┘
```

## Layout

| Module | Purpose |
|---|---|
| `trendbot/config.py` | `StrategyConfig` (hashable) + `RuntimeSettings` (env toggles) |
| `trendbot/core/signal.py` | pure `(history) → weights`, no look-ahead |
| `trendbot/marketdata/bybit_client.py` | public Bybit v5 client (read-only) |
| `trendbot/marketdata/bybit_private.py` | authenticated client (HMAC, retry, **no withdrawal**) |
| `trendbot/marketdata/ingestor.py` | candle store (parquet) + gap detection |
| `trendbot/backtest/` | backtest engine + walk-forward gate |
| `trendbot/execution/order_sizer.py` | pure weight → executable qty (ROUND_DOWN) |
| `trendbot/execution/guards.py` | kill switch, staleness, cap, no-withdrawal |
| `trendbot/execution/reconciler.py` | idempotency keys + divergence detection |
| `trendbot/execution/engine.py` | the loop (state machine) |
| `trendbot/storage/repository.py` | the only Supabase access point |
| `trendbot/notify/telegram.py` | notifications |

## Execution engine

The engine is a small state machine:

```
STARTUP → RECONCILE → IDLE ⇄ (PREFLIGHT → EXECUTE) → IDLE
                                                        │
                                              HALTED (terminal)
```

- **STARTUP** — verifies the API key. A key that **can withdraw** or **cannot
  trade** halts immediately; the bot never reaches `IDLE`. A sticky halt
  sentinel from a previous run also blocks startup.
- **RECONCILE** — the exchange is the *sole source of truth* for positions. Any
  divergence from the local view is alerted (Telegram) and the exchange value
  wins. Runs at startup and every `RECONCILE_INTERVAL_SEC`.
- **PREFLIGHT** — runs every guard (kill switch, withdrawal permission, signal
  staleness, notional cap). Any failure raises `TradingHalted`.
- **EXECUTE** — per symbol: size the order (ROUND_DOWN, never over budget),
  skip if the deterministic `order_link_id` already exists, then either record a
  dry-run row (no API call) or submit a `PostOnly` order and record it. A single
  symbol failing is isolated and alerted — it never kills the loop.
- **HALTED** — terminal. Writes a critical alert and a **sticky sentinel file**
  on a persistent volume, then exits with code `42`. `restart: always` must not
  be used, so a logical halt cannot be auto-revived (compose uses `on-failure`).

Safety invariants:

- No leverage. `max_weight > 1.0` is a config error; per-symbol weight is
  clamped to `[0, 1]` and resulting notional never exceeds allocated equity.
- Quantities/prices are `Decimal`, serialized with `format(x, 'f')` (never
  scientific notation) for the exchange.
- Below-minimum and within-band rebalances are **no-trades**, not errors.
- A Supabase failure never blocks or alters a trading decision — the DB is
  observability, not authoritative state.
- Partial fills are normal: the next bar recomputes and orders only the residual.

## CLI

```bash
trendbot run [--dry-run/--no-dry-run] [--once]   # execution loop; --once = one cycle
trendbot reconcile                                # print exchange vs stored; never trades
trendbot report [--date YYYY-MM-DD]               # recompute + send the daily report
```

`--no-dry-run` prompts for interactive confirmation unless
`TRENDBOT_NON_INTERACTIVE=1`.

## Configuration (environment)

Copy `.env.example` to `.env`. Both safety switches default to the **safe**
value; only the literal string `false` flips them, and **mainnet live trading
requires BOTH** `DRY_RUN=false` and `BYBIT_TESTNET=false`.

| Variable | Default | Meaning |
|---|---|---|
| `DRY_RUN` | `true` | `false` → real orders. Any other value is safe. |
| `BYBIT_TESTNET` | `true` | `false` → mainnet. Any other value is safe. |
| `TRENDBOT_NON_INTERACTIVE` | `0` | `1` skips the `--no-dry-run` confirmation. |
| `BYBIT_API_KEY` / `BYBIT_API_SECRET` | — | Key **without** withdrawal permission. |
| `SUPABASE_URL` / `SUPABASE_SERVICE_ROLE_KEY` | — | Service role key only. |
| `TELEGRAM_BOT_TOKEN` / `TELEGRAM_CHAT_ID` | — | Notifications. |
| `RECONCILE_INTERVAL_SEC` | `300` | Reconciliation cadence. |
| `POST_ONLY_TIMEOUT_SEC` | `60` | PostOnly → Market fallback window. |
| `IDLE_POLL_SEC` | `15` | Idle poll interval. |
| `TRENDBOT_HALT_FILE` | `/data/trendbot.halt` | Sticky halt sentinel (persistent volume). |
| `TRENDBOT_DATA_DIR` | `data/candles` | Candle cache location. |

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"
pytest -q                 # full suite
ruff check .              # lint
```

## Docker

```bash
docker compose up --build      # starts in DRY_RUN=true + BYBIT_TESTNET=true
```

The `execution-engine` service runs dry-run on testnet by default. The halt
sentinel and candle cache live on the `trendbot-data` volume.

## Database

Apply `supabase/migrations/001_init.sql` (schema `trendbot`). The
`supabase/functions/daily-report` edge function reads the latest equity snapshot
and pushes a summary to Telegram (schedule via `pg_cron`).
