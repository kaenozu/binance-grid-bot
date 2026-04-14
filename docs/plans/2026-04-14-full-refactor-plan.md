# Full Source Refactor Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Full source code review, refactoring, dead code removal, duplication elimination, bug fixes, and infrastructure cleanup.

**Architecture:** Incremental refactoring maintaining flat `src/` structure. Each task is independently testable. No module restructuring (no subpackages). All 127 tests must pass after each task.

**Tech Stack:** Python 3.11, pytest, ruff, pyright

---

### Task 1: Dead code removal — grid_strategy.py

**Files:**
- Modify: `src/grid_strategy.py:148-186`
- Modify: `tests/test_grid_strategy.py`

**Step 1: Delete dead methods from grid_strategy.py**

Remove `find_nearest_grid()` (lines 148-152) and `calculate_realized_profit()` (lines 182-186) from `GridStrategy`.

**Step 2: Search and remove any tests for deleted methods**

```bash
rg "find_nearest_grid|calculate_realized_profit" tests/
```

Remove any test functions that test these deleted methods. If no dedicated tests exist, skip.

**Step 3: Run tests**

```bash
python -m pytest tests/test_grid_strategy.py tests/test_bot.py tests/test_order_sync.py -v
```

Expected: ALL PASS

**Step 4: Commit**

```bash
git add src/grid_strategy.py tests/
git commit -m "refactor: remove dead code from grid_strategy"
```

---

### Task 2: Dead code removal — risk_manager.py

**Files:**
- Modify: `src/risk_manager.py:21-58, 110-168`
- Modify: `tests/test_risk_manager.py`
- Modify: `src/bot.py:63` (constructor call)

**Step 1: Remove dead fields and methods from RiskManager**

Remove from `__init__`:
- `entry_price` parameter and field (line 25, 37)
- `total_trades` field (line 50)
- `total_profit` field (line 51)
- `max_drawdown` field (line 52)
- `peak_value` field (line 53)

Remove methods:
- `update_peak()` (lines 110-123)
- `get_emergency_actions()` (lines 158-168)

Update `record_position_close()` (line 94-108): remove `self.total_trades += 1` and `self.total_profit += profit` lines. Keep only `self.current_positions -= 1` and the log.

Update `risk_status` property (lines 126-136): remove `total_trades`, `total_profit`, `max_drawdown_percent` entries.

Update constructor signature: remove `entry_price` parameter.

**Step 2: Update bot.py constructor call**

In `src/bot.py:63`, change:
```python
self.risk_manager = RiskManager(self.client, self.strategy, self.current_price)
```
to:
```python
self.risk_manager = RiskManager(self.client, self.strategy)
```

**Step 3: Update tests**

In `tests/test_risk_manager.py`:
- Remove tests for `update_peak()`, `get_emergency_actions()`, `entry_price`
- Update fixture that creates `RiskManager` to not pass `entry_price`
- Update `risk_status` assertions to not include removed keys

**Step 4: Run tests**

```bash
python -m pytest tests/test_risk_manager.py tests/test_bot.py -v
```

Expected: ALL PASS

**Step 5: Commit**

```bash
git add src/risk_manager.py src/bot.py tests/test_risk_manager.py
git commit -m "refactor: remove dead code from risk_manager"
```

---

### Task 3: Dead code removal — binance_client.py

**Files:**
- Modify: `src/binance_client.py:23`

**Step 1: Remove unused MAX_RETRIES constant**

Delete line 23: `MAX_RETRIES = 3`

**Step 2: Search for any references**

```bash
rg "MAX_RETRIES" src/ tests/
```

Remove any remaining references if found (tests that reference it).

**Step 3: Run tests**

```bash
python -m pytest tests/test_binance_client.py -v
```

**Step 4: Commit**

```bash
git add src/binance_client.py tests/
git commit -m "refactor: remove unused MAX_RETRIES constant"
```

---

### Task 4: Bug fix — api_weight.py deadlock

**Files:**
- Modify: `src/api_weight.py:32, 55-75`
- Modify: `tests/test_api_weight.py`

**Step 1: Replace Lock with Condition in api_weight.py**

Change `__init__`:
```python
self._lock = threading.Lock()
```
to:
```python
self._condition = threading.Condition()
```

Update `update_weight()`:
```python
def update_weight(self, used_weight: int):
    with self._condition:
        now = time.time()
        if now - self._last_reset >= self.window_seconds:
            self._current_weight = 0
            self._last_reset = now
        self._current_weight = used_weight
        self._condition.notify()
```

Update `available_weight` property:
```python
@property
def available_weight(self) -> int:
    with self._condition:
        available = self.max_weight - self._current_weight - self.weight_buffer
        return max(0, available)
```

Update `wait_if_needed()`:
```python
def wait_if_needed(self):
    if not self.should_wait():
        return
    with self._condition:
        elapsed = time.time() - self._last_reset
        reset_in = max(0, self.window_seconds - elapsed)
        if reset_in > 0:
            logger.warning(
                f"APIウェイト不足 (残り {self._current_weight}/{self.max_weight})。"
                f"{reset_in}秒後にリセットされます。待機中..."
            )
            self._condition.wait(timeout=reset_in + 1)
        self._current_weight = 0
        self._last_reset = time.time()
        logger.info("APIウェイトリセット完了")
```

Update `info` property:
```python
@property
def info(self) -> dict:
    with self._condition:
        return {
            "current_weight": self._current_weight,
            "max_weight": self.max_weight,
            "available_weight": self.max_weight - self._current_weight - self.weight_buffer,
            "buffer": self.weight_buffer,
        }
```

**Step 2: Run tests**

```bash
python -m pytest tests/test_api_weight.py -v
```

Expected: ALL PASS (Condition is API-compatible with Lock for these use cases)

**Step 3: Commit**

```bash
git add src/api_weight.py
git commit -m "fix: replace Lock with Condition in api_weight to prevent deadlock"
```

---

### Task 5: Encapsulation — order_sync.py + order_manager.py

**Files:**
- Modify: `src/order_manager.py:49-62`
- Modify: `src/order_sync.py:29-34`
- Modify: `tests/test_order_sync.py`

**Step 1: Add public methods to OrderManager**

Add to `OrderManager` class after `active_orders` property (after line 62):

```python
def get_active_order_ids(self) -> set[int]:
    return set(self._active_orders.keys())

def remove_order(self, order_id: int):
    self._active_orders.pop(order_id, None)
```

**Step 2: Update order_sync.py to use public API**

In `sync_with_exchange()`, change line 30:
```python
internal_ids = set(order_manager._active_orders.keys())
```
to:
```python
internal_ids = order_manager.get_active_order_ids()
```

Change line 34:
```python
del order_manager._active_orders[oid]
```
to:
```python
order_manager.remove_order(oid)
```

**Step 3: Run tests**

```bash
python -m pytest tests/test_order_sync.py tests/test_order_manager.py -v
```

**Step 4: Commit**

```bash
git add src/order_manager.py src/order_sync.py tests/
git commit -m "refactor: fix encapsulation — order_sync uses public OrderManager API"
```

---

### Task 6: Encapsulation — multi_bot.py get_status()

**Files:**
- Modify: `src/bot.py` (add `get_summary()` method)
- Modify: `src/multi_bot.py:97-118`
- Modify: `tests/test_multi_bot.py`

**Step 1: Add get_summary() to GridBot**

Add to `src/bot.py` GridBot class (after `_handle_grid_shift`):

```python
def get_summary(self) -> dict:
    stats = self.portfolio.refresh_stats()
    filled = sum(1 for g in self.strategy.grids if g.position_filled)
    return {
        "running": self.is_running,
        "price": self.current_price,
        "grids": len(self.strategy.grids),
        "filled": filled,
        "total_profit": stats.total_profit,
        "realized_profit": stats.realized_profit,
        "unrealized_profit": stats.unrealized_profit,
    }
```

**Step 2: Update multi_bot.py get_status()**

Replace lines 103-108 with:
```python
summary = bot.get_summary()
statuses[symbol] = {
    "running": summary["running"],
    "price": summary["price"],
    "grids": summary["grids"],
    "filled": summary["filled"],
    "total_profit": summary["total_profit"],
    "errors": self._errors.get(symbol, []),
}
```

**Step 3: Update tests for new summary format**

In `tests/test_multi_bot.py`, update any assertions that check `get_status()` return values to include `total_profit` key.

**Step 4: Run tests**

```bash
python -m pytest tests/test_multi_bot.py tests/test_bot.py -v
```

**Step 5: Commit**

```bash
git add src/bot.py src/multi_bot.py tests/test_multi_bot.py
git commit -m "refactor: add GridBot.get_summary() for encapsulated status access"
```

---

### Task 7: Extract src/fee.py

**Files:**
- Create: `src/fee.py`
- Modify: `src/portfolio.py:143-152`
- Modify: `src/backtest.py:231-234`

**Step 1: Create src/fee.py**

```python
"""
ファイルパス: src/fee.py
概要: 手数料計算ユーティリティ
説明: 買い/売りの手数料を差し引いた純利益を計算
関連ファイル: src/portfolio.py, src/backtest.py
"""


def calculate_net_profit(
    buy_price: float, sell_price: float, quantity: float, fee_rate: float
) -> tuple[float, float, float]:
    """純利益と各手数料を計算

    Args:
        buy_price: 買い価格
        sell_price: 売り価格
        quantity: 数量
        fee_rate: 手数料率 (例: 0.001 = 0.1%)

    Returns:
        (net_profit, buy_fee, sell_fee)
    """
    gross_profit = (sell_price - buy_price) * quantity
    buy_fee = buy_price * quantity * fee_rate
    sell_fee = sell_price * quantity * fee_rate
    return gross_profit - buy_fee - sell_fee, buy_fee, sell_fee
```

**Step 2: Update portfolio.py**

In `record_trade()`, replace lines 146-152:
```python
profit = (price - buy_trade.price) * quantity
fee_rate = self._fee_rate
if fee_rate > 0 and buy_trade:
    buy_fee = buy_trade.price * quantity * fee_rate
    sell_fee = price * quantity * fee_rate
    profit = profit - buy_fee - sell_fee
    self.stats.total_fees += buy_fee + sell_fee
```
with:
```python
from src.fee import calculate_net_profit
# ... inside the if block:
if self._fee_rate > 0 and buy_trade:
    profit, buy_fee, sell_fee = calculate_net_profit(
        buy_trade.price, price, quantity, self._fee_rate
    )
    self.stats.total_fees += buy_fee + sell_fee
else:
    profit = (price - buy_trade.price) * quantity
```

**Step 3: Update backtest.py**

In `_check_fills()`, replace lines 231-234:
```python
gross_profit = (grid.sell_price - buy_price) * quantity
buy_fee = buy_price * quantity * self.fee_rate
sell_fee = grid.sell_price * quantity * self.fee_rate
profit = gross_profit - buy_fee - sell_fee
```
with:
```python
from src.fee import calculate_net_profit
profit, _, _ = calculate_net_profit(buy_price, grid.sell_price, quantity, self.fee_rate)
```

**Step 4: Run tests**

```bash
python -m pytest tests/test_portfolio.py tests/test_backtest.py -v
```

**Step 5: Commit**

```bash
git add src/fee.py src/portfolio.py src/backtest.py
git commit -m "refactor: extract shared fee calculation to src/fee.py"
```

---

### Task 8: Extract src/bot_display.py

**Files:**
- Create: `src/bot_display.py`
- Modify: `src/bot.py:254-281`

**Step 1: Create src/bot_display.py**

```python
"""
ファイルパス: src/bot_display.py
概要: ボットステータス表示
説明: CUIでのステータス表示ロジック
関連ファイル: src/bot.py, src/portfolio.py, src/risk_manager.py
"""

from datetime import datetime


def display_status(symbol: str, current_price: float, grid_status: dict,
                   stats, risk_status: dict):
    """ステータスをCUIに表示"""
    print("\n" + "=" * 70)
    print(f"グリッドボット ステータス - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 70)
    print(f"取引ペア: {symbol}")
    print(f"現在価格: {current_price:.2f}")
    print(f"価格範囲: {grid_status['price_range']}")
    print(f"グリッド数: {grid_status['total_grids']} (間隔: {grid_status['grid_spacing']:.2f})")
    print(f"ポジション: {grid_status['filled_positions']}/{grid_status['total_grids']}")
    print("-" * 70)
    print(f"初期残高: {stats.initial_balance:.2f} USDT")
    print(f"現在残高: {stats.current_balance:.2f} USDT")
    print(f"実現利益: {stats.realized_profit:+.2f} USDT")
    print(f"未実現利益: {stats.unrealized_profit:+.2f} USDT")
    print(f"累計手数料: {stats.total_fees:.2f} USDT")
    print(f"総利益: {stats.total_profit:+.2f} USDT")
    print("-" * 70)
    print(f"取引回数: {stats.total_trades}")
    print(f"勝率: {stats.win_rate:.1f}%")
    print(f"損切りライン: {risk_status['stop_loss_price']:.2f}")
    print(f"ポジション: {risk_status['current_positions']}/{risk_status['max_positions']}")
    print("=" * 70)
    print("Ctrl+C で停止")
```

**Step 2: Update bot.py**

Replace `_display_status()` method (lines 254-281) with:
```python
def _display_status(self):
    from src.bot_display import display_status
    stats = self.portfolio.refresh_stats()
    display_status(
        self.symbol, self.current_price,
        self.strategy.grid_status, stats, self.risk_manager.risk_status,
    )
```

**Step 3: Run tests**

```bash
python -m pytest tests/test_bot.py -v
```

**Step 4: Commit**

```bash
git add src/bot_display.py src/bot.py
git commit -m "refactor: extract bot_display.py from bot.py"
```

---

### Task 9: Extract src/bot_shutdown.py

**Files:**
- Create: `src/bot_shutdown.py`
- Modify: `src/bot.py:283-389`

**Step 1: Create src/bot_shutdown.py**

Extract `_emergency_stop()`, `_close_open_positions()`, `stop()`, `_export_on_stop()` into functions that take required dependencies as parameters.

```python
"""
ファイルパス: src/bot_shutdown.py
概要: ボット停止・緊急停止処理
説明: 正常停止、緊急停止、オープンポジション決済、エクスポート
関連ファイル: src/bot.py, src/order_manager.py, src/portfolio.py, src/grid_strategy.py, src/binance_client.py
"""

from datetime import datetime
from pathlib import Path
from typing import Optional

from src import exporter
from src.grid_strategy import GridStrategy
from src.order_manager import OrderManager
from src.portfolio import Portfolio
from src.binance_client import BinanceClient
from utils.logger import setup_logger

logger = setup_logger("bot_shutdown")


def export_on_stop(portfolio: Portfolio) -> None:
    """停止時にトレード履歴をエクスポート"""
    if not portfolio.trades:
        return
    try:
        export_dir = Path("data") / "exports"
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        csv_path = export_dir / f"trades_{timestamp}.csv"
        json_path = export_dir / f"trades_{timestamp}.json"
        count = exporter.export_trades_csv(portfolio.trades, csv_path)
        exporter.export_trades_json(portfolio.trades, json_path)
        logger.info(f"トレード履歴をエクスポート: {count} 件 -> {export_dir}")
    except Exception as e:
        logger.error(f"エクスポート失敗: {e}")


def close_open_positions(
    client: BinanceClient,
    strategy: GridStrategy,
    portfolio: Portfolio,
) -> None:
    """オープンポジションを成行売却"""
    open_positions = [g for g in strategy.grids if g.position_filled]
    if not open_positions:
        return

    logger.warning(f"オープンポジション {len(open_positions)} 件を成行決済します")
    symbol_info = client.get_symbol_info(strategy.symbol)
    base_asset = (
        symbol_info["base_asset"] if symbol_info else strategy.symbol.replace("USDT", "")
    )
    step_size = symbol_info["step_size"] if symbol_info else 0
    min_qty = symbol_info["min_qty"] if symbol_info else 0
    try:
        balances = client.get_account_balance()
    except Exception as e:
        logger.error(f"残高取得失敗: {e}")
        return

    if base_asset not in balances:
        logger.error(f"残高がありません: {base_asset}")
        return

    available = balances[base_asset]["free"]
    if available <= 0:
        logger.warning(f"{base_asset} の残高がありません")
        return

    for grid in open_positions:
        if available <= 0:
            break
        try:
            qty_per_grid = strategy.get_order_quantity(
                grid.buy_price, min_qty=min_qty, step_size=step_size
            )
            sell_qty = min(available, qty_per_grid)
            if sell_qty <= 0:
                continue

            result = client.place_order(
                symbol=strategy.symbol,
                side="SELL",
                quantity=sell_qty,
                price=None,
            )
            filled_qty = float(result.get("executedQty", result.get("origQty", sell_qty)))
            filled_price = float(result.get("avgPrice") or result.get("price", 0))
            portfolio.record_trade(
                side="SELL",
                price=filled_price,
                quantity=filled_qty,
                order_id=result["orderId"],
                grid_level=grid.level,
            )
            available -= filled_qty
            grid.position_filled = False
            logger.info(f"グリッド {grid.level}: 緊急成行決済 {filled_qty} @ {filled_price}")
        except Exception as e:
            logger.error(f"グリッド {grid.level}: 緊急決済失敗: {e}")


def emergency_stop(
    client: BinanceClient,
    strategy: GridStrategy,
    order_manager: OrderManager,
    portfolio: Portfolio,
    persist_fn,
) -> None:
    """緊急停止処理"""
    logger.warning("緊急停止処理開始...")
    persist_fn()
    order_manager.cancel_all_orders()
    close_open_positions(client, strategy, portfolio)
    print(portfolio.generate_report())
    logger.info("緊急停止完了")


def stop_bot(
    client: BinanceClient,
    strategy: GridStrategy,
    order_manager: OrderManager,
    portfolio: Portfolio,
    persist_fn,
    close_positions: bool,
    ws_client=None,
) -> None:
    """ボット停止"""
    logger.info("ボット停止中...")

    if ws_client:
        ws_client.stop()

    persist_fn()

    canceled = order_manager.cancel_all_orders()
    logger.info(f"キャンセル完了: {canceled} 件")

    if close_positions:
        close_open_positions(client, strategy, portfolio)

    report = portfolio.generate_report()
    logger.info("\n" + report)

    export_on_stop(portfolio)
    logger.info("ボット停止完了")
```

**Step 2: Update bot.py**

Replace methods `_export_on_stop`, `_emergency_stop`, `_close_open_positions`, `stop` (lines 283-389) with thin wrappers:

```python
def _export_on_stop(self):
    from src.bot_shutdown import export_on_stop
    export_on_stop(self.portfolio)

def _emergency_stop(self):
    from src.bot_shutdown import emergency_stop
    self.is_running = False
    emergency_stop(self.client, self.strategy, self.order_manager, self.portfolio, self._persist_state)

def _close_open_positions(self):
    from src.bot_shutdown import close_open_positions
    close_open_positions(self.client, self.strategy, self.portfolio)

def stop(self):
    from config.settings import Settings
    from src.bot_shutdown import stop_bot
    self.is_running = False
    stop_bot(
        self.client, self.strategy, self.order_manager, self.portfolio,
        self._persist_state, Settings.CLOSE_ON_STOP, self.ws_client,
    )
```

**Step 3: Run tests**

```bash
python -m pytest tests/test_bot.py -v
```

**Step 4: Commit**

```bash
git add src/bot_shutdown.py src/bot.py
git commit -m "refactor: extract bot_shutdown.py from bot.py"
```

---

### Task 10: Deduplicate order placement — order_manager.py

**Files:**
- Modify: `src/order_manager.py:85-304`

**Step 1: Create internal _place_order() helper**

Add after `_register_and_handle` (or before it):

```python
def _place_order(self, grid_level: int, side: str, price: float,
                 quantity: float | None = None) -> dict | None:
    """共通注文配置ロジック"""
    symbol_info = self.client.get_symbol_info(self.strategy.symbol)
    if not symbol_info:
        return None

    if quantity is None:
        grid = self.strategy.grids[grid_level]
        quantity = self.strategy.get_order_quantity(
            grid.buy_price, symbol_info["min_qty"], symbol_info["step_size"]
        )

    if quantity <= 0:
        return None

    adjusted_price = self._adjust_price(price, symbol_info["tick_size"], side=side)
    order = self.client.place_order(
        symbol=self.strategy.symbol,
        side=side,
        quantity=quantity,
        price=adjusted_price,
    )
    self._register_and_handle(order, grid_level, side, adjusted_price, quantity)
    return order
```

**Step 2: Refactor place_grid_orders() to use _place_order()**

Replace the buy loop body with calls to `_place_order()`. Keep the special sell loop logic (checking buy_order_id for actual quantity).

**Step 3: Refactor place_buy_order_for_grid() and place_sell_order_for_grid()**

Replace each with a thin wrapper around `_place_order()`.

**Step 4: Run tests**

```bash
python -m pytest tests/test_order_manager.py tests/test_bot.py -v
```

**Step 5: Commit**

```bash
git add src/order_manager.py
git commit -m "refactor: deduplicate order placement in order_manager"
```

---

### Task 11: Fix binance_client.py — retry limit + unified backoff

**Files:**
- Modify: `src/binance_client.py:23, 113-181`
- Modify: `tests/test_binance_client.py`

**Step 1: Add MAX_CONNECTION_RETRIES constant**

After line 24 (`RETRY_DELAY = 1`), add:
```python
MAX_CONNECTION_RETRIES = 10
```

**Step 2: Refactor _make_request() retry logic**

Replace lines 113-181 with a unified retry structure:

```python
attempt = 0
while True:
    attempt += 1
    try:
        response = self._send_request(method, url, params)
        if response.status_code == 429:
            retry_after = int(response.headers.get("Retry-After", RETRY_DELAY * (2 ** min(attempt, 5))))
            logger.warning(f"レートリミット到達、{retry_after}秒後にリトライ ({attempt}回目)")
            time.sleep(retry_after)
            continue
        if response.status_code >= 500:
            wait_time = RETRY_DELAY * (2 ** min(attempt, 5))
            logger.warning(f"サーバーエラー ({response.status_code})、{wait_time}秒後にリトライ")
            time.sleep(wait_time)
            continue
        response.raise_for_status()
        if self._weight_tracker:
            used = response.headers.get("X-MBX-USED-WEIGHT")
            if used:
                self._weight_tracker.update_weight(int(used))
        return response.json()
    except requests.exceptions.ConnectionError as e:
        if attempt >= MAX_CONNECTION_RETRIES:
            raise BinanceAPIError(f"接続エラー（{MAX_CONNECTION_RETRIES}回リトライ後）: {e}") from e
        cause = e.args[0] if e.args else ""
        is_dns_failure = "NameResolutionError" in cause or "getaddrinfo failed" in cause
        wait_time = 60 if is_dns_failure else min(RETRY_DELAY * (2 ** min(attempt, 5)), 60)
        logger.warning(f"{'DNS解決失敗' if is_dns_failure else '接続エラー'}、{wait_time}秒後にリトライ ({attempt}回目)")
        time.sleep(wait_time)
    except requests.exceptions.HTTPError as e:
        status_code = getattr(e.response, "status_code", 0) if e.response else 0
        if 400 <= status_code < 500:
            response_text = e.response.text if e.response else ""
            raise BinanceAPIError(f"クライアントエラー: {status_code} - {response_text}") from e
        wait_time = RETRY_DELAY * (2 ** min(attempt, 5))
        logger.warning(f"HTTP エラー、{wait_time}秒後にリトライ ({attempt}回目)")
        time.sleep(wait_time)
    except (requests.exceptions.Timeout, requests.exceptions.RequestException) as e:
        wait_time = min(RETRY_DELAY * (2 ** min(attempt, 5)), 60)
        logger.warning(f"リクエストエラー、{wait_time}秒後にリトライ ({attempt}回目)")
        time.sleep(wait_time)
```

Key change: ConnectionError now has `MAX_CONNECTION_RETRIES` limit. Other errors remain infinite retry (server errors should retry indefinitely). Timeout and RequestException are merged into one except block.

**Step 3: Update tests**

In `tests/test_binance_client.py`, update any assertions about retry behavior if needed. Add a test that ConnectionError raises after MAX_CONNECTION_RETRIES.

**Step 4: Run tests**

```bash
python -m pytest tests/test_binance_client.py -v
```

**Step 5: Commit**

```bash
git add src/binance_client.py tests/test_binance_client.py
git commit -m "fix: add connection retry limit and unify backoff in binance_client"
```

---

### Task 12: Deduplicate main.py confirmation

**Files:**
- Modify: `main.py:74-82, 107-115`

**Step 1: Extract _confirm_production_mode() helper**

Add before `main()`:
```python
def _confirm_production_mode():
    """本番モードの確認"""
    if Settings.USE_TESTNET:
        return True
    print("警告: 本番モードで実行します")
    if not sys.stdin.isatty():
        print("非対話環境のため本番モードを中止します")
        sys.exit(1)
    confirm = input("続行しますか？ (yes/no): ").strip().lower()
    if confirm != "yes":
        print("中止しました")
        sys.exit(0)
    return True
```

**Step 2: Replace both confirmation blocks**

Replace lines 74-82 with: `if not _confirm_production_mode(): return`
Replace lines 107-115 with: `if not _confirm_production_mode(): return`

Wait — `_confirm_production_mode` calls `sys.exit()` so it never returns False. Simplify: just call `_confirm_production_mode()`.

**Step 3: Run tests**

```bash
python -m pytest tests/ -v
```

**Step 4: Commit**

```bash
git add main.py
git commit -m "refactor: deduplicate production confirmation in main.py"
```

---

### Task 13: Deduplicate persistence.py STATS_FIELDS

**Files:**
- Modify: `src/persistence.py:258-280`

**Step 1: Replace manual STATS_FIELDS with dataclass introspection**

Replace lines 258-273:
```python
STATS_FIELDS = [
    "initial_balance",
    ...
]
```
with:
```python
def _get_stats_fields() -> list[str]:
    from src.portfolio import PortfolioStats
    return [f for f in PortfolioStats.__dataclass_fields__.keys()]
```

Update `restore_stats_to` (lines 276-280) to use `_get_stats_fields()`:
```python
def restore_stats_to(stats_obj, data: dict):
    for field in _get_stats_fields():
        if field in data:
            setattr(stats_obj, field, data[field])
```

Note: keep backward compatibility — `_get_stats_fields()` is called at runtime so no circular import issue.

**Step 2: Run tests**

```bash
python -m pytest tests/test_persistence.py tests/test_portfolio.py -v
```

**Step 3: Commit**

```bash
git add src/persistence.py
git commit -m "refactor: replace manual STATS_FIELDS with dataclass introspection"
```

---

### Task 14: Infrastructure fixes

**Files:**
- Modify: `.github/workflows/ci.yml`
- Modify: `Dockerfile`
- Modify: `requirements.txt`
- Modify: `requirements-dev.txt`

**Step 1: Fix CI branch**

In `.github/workflows/ci.yml`, change `main` to `master` on lines 5 and 7.

**Step 2: Remove pyright || true**

Line 28: change `pyright --level basic src/ || true` to `pyright --level basic src/`

**Step 3: Remove Dockerfile HEALTHCHECK**

Delete lines 18-19 from Dockerfile.

**Step 4: Move pytest to dev requirements**

From `requirements.txt`, remove lines 4-5 (pytest, pytest-mock).
To `requirements-dev.txt`, add:
```
pytest>=8.0.0
pytest-mock>=3.10.0
```

**Step 5: Commit**

```bash
git add .github/workflows/ci.yml Dockerfile requirements.txt requirements-dev.txt
git commit -m "fix: CI branch, pyright enforcement, remove HEALTHCHECK, move pytest to dev"
```

---

### Task 15: Test refactoring — conftest + shared helpers

**Files:**
- Modify: `tests/conftest.py`
- Modify: `tests/test_bot.py`
- Modify: `tests/test_risk_manager.py`
- Modify: `tests/test_order_manager.py`
- Modify: `tests/test_order_sync.py`
- Modify: `tests/test_dynamic_grid.py`

**Step 1: Expand conftest.py mock_settings fixture**

Add missing Settings attributes to the `mock_settings` fixture to cover all 17 attributes that `test_bot.py`'s `mock_env` has. Add:
```python
mock.CHECK_INTERVAL = 10
mock.MAX_CONSECUTIVE_ERRORS = 5
mock.GRID_RANGE_FACTOR = 0.15
mock.TRADING_FEE_RATE = 0.001
mock.CLOSE_ON_STOP = False
mock.PERSIST_INTERVAL = 60
mock.validate.return_value = []
```

**Step 2: Add make_grid_strategy() helper to conftest.py**

```python
@pytest.fixture
def make_grid_strategy():
    def _make(
        symbol="BTCUSDT",
        current_price=50000.0,
        lower_price=45000.0,
        upper_price=55000.0,
        grid_count=10,
        investment_amount=1000.0,
    ):
        return GridStrategy(
            symbol=symbol,
            current_price=current_price,
            lower_price=lower_price,
            upper_price=upper_price,
            grid_count=grid_count,
            investment_amount=investment_amount,
        )
    return _make
```

**Step 3: Update test files to use shared helpers**

In each test file that manually constructs `GridStrategy`:
- Replace with `make_grid_strategy()` fixture usage where applicable
- Remove `mock_env` from `test_bot.py` — use `mock_settings` from conftest instead

**Step 4: Run ALL tests**

```bash
python -m pytest tests/ -v
```

Expected: ALL 127 PASS

**Step 5: Commit**

```bash
git add tests/conftest.py tests/
git commit -m "refactor: unify test fixtures and grid strategy helper"
```

---

### Task 16: Final verification

**Step 1: Run full test suite**

```bash
python -m pytest tests/ -v --tb=short
```

Expected: ALL PASS (may be fewer if dead code tests were removed)

**Step 2: Run ruff**

```bash
ruff check src/ tests/
```

Expected: No errors

**Step 3: Run pyright**

```bash
pyright --level basic src/
```

Expected: No errors (or only pre-existing ones)

**Step 4: Verify line counts**

```bash
wc -l src/bot.py src/order_manager.py src/binance_client.py
```

Expected: all under 300 lines

**Step 5: Commit any remaining fixes if needed**
