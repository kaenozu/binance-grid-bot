# Full Source Refactoring Design

Date: 2026-04-14
Status: Approved

## Approach

Incremental refactoring maintaining flat `src/` structure. Each change independently testable.

## Section 1: File Split + New Files

### Split `src/bot.py` (389 -> ~250 lines)
- Extract `src/bot_display.py` (~50 lines): `_display_status()`, status display logic
- Extract `src/bot_shutdown.py` (~80 lines): `_emergency_stop()`, `_close_open_positions()`, `_export_on_stop()`, `stop()`
- `bot.py` retains pure orchestration (init, start, _tick, _process_fills, _handle_grid_shift)

### Split `src/order_manager.py` (357 -> ~230 lines)
- Extract `src/price_utils.py` (~20 lines): `_adjust_price()` + order quantity helper
- `place_grid_orders()`, `place_buy_order_for_grid()`, `place_sell_order_for_grid()` all call internal `_place_order()`

### New utility files
- `src/fee.py` (~15 lines): `calculate_net_profit(buy_price, sell_price, quantity, fee_rate)` — used by portfolio.py and backtest.py

## Section 2: Code Cleanup (Dead Code + Duplication)

### Delete Dead Code
| Code | File | Reason |
|---|---|---|
| `find_nearest_grid()` | grid_strategy.py | Unused. Replaced by `order_sync._match_order_to_grid()` |
| `calculate_realized_profit()` | grid_strategy.py | Unused. Lives in `Portfolio.record_trade()` |
| `update_peak()` | risk_manager.py | Never called from bot.py |
| `get_emergency_actions()` | risk_manager.py | Never called from bot.py |
| `entry_price` field | risk_manager.py | Written but never read |
| `total_trades`, `total_profit` | risk_manager.py | Duplicate of Portfolio.stats |
| `MAX_RETRIES` | binance_client.py | Defined but unused |

### Consolidate Duplication

**D1: Order placement pattern (order_manager.py)**
- Merge 3 separate placement flows into single `_place_order(grid_level, side, price)` internal method

**D2: Fee calculation (portfolio.py + backtest.py)**
- Both use `fee.calculate_net_profit()`

**D3: main.py confirmation logic**
- Extract `_confirm_production_mode()` helper

**D4: persistence.py STATS_FIELDS**
- Replace manual 14-field list with `PortfolioStats.__dataclass_fields__.keys()`

## Section 3: Bug Fixes + Behavior Changes + Encapsulation

### Bug Fix
- **B1: api_weight.py deadlock risk** — Replace `lock.release() → sleep → lock.acquire()` with `threading.Condition`

### Behavior Changes
- **C1: binance_client.py infinite retry** — Add MAX_RETRIES=10 for ConnectionError
- **C2: binance_client.py retry logic** — Merge 4 duplicate backoff branches into single except block

### Encapsulation Fixes
- **E1: order_sync.py** — Add `get_active_order_ids()`, `remove_order()` to OrderManager instead of accessing `_active_orders` directly
- **E2: multi_bot.py** — Add `get_summary()` to GridBot instead of accessing internal attributes

## Section 4: Infrastructure + Test Refactoring

### Infrastructure
| Item | Fix |
|---|---|
| CI branch | `main` → `master` |
| Dockerfile HEALTHCHECK | Remove (no HTTP server) |
| pyright CI | Remove `\|\| true` — type errors fail CI |
| pytest in prod deps | Move to requirements-dev.txt |

### Test Refactoring
- **T1: Merge mock_env (test_bot.py) into conftest.py mock_settings**
- **T2: Create `make_grid_strategy()` helper in conftest.py** — replace 8 manual constructions
- **T3: Remove tests for deleted dead code** (risk_manager update_peak, get_emergency_actions, entry_price)

## File Change Summary

```
New files:
  src/bot_display.py    (~50 lines)
  src/bot_shutdown.py   (~80 lines)
  src/price_utils.py    (~20 lines)
  src/fee.py            (~15 lines)

Modified files:
  src/bot.py            (389→~250)
  src/order_manager.py  (357→~230)
  src/binance_client.py (301→~250)
  src/api_weight.py     (85→~80)
  src/grid_strategy.py  (228→~200)
  src/risk_manager.py   (168→~120)
  src/order_sync.py     (92→~90)
  src/persistence.py    (280→~250)
  src/backtest.py       (298→~280)
  src/portfolio.py      (257→~240)
  main.py               (137→~125)
  .github/workflows/ci.yml
  Dockerfile
  requirements.txt
  requirements-dev.txt
  tests/conftest.py
  tests/test_bot.py
  tests/test_risk_manager.py
  tests/test_grid_strategy.py
  tests/test_order_sync.py
```
