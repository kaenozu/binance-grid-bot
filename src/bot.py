"""グリッド取引ボット メインループ"""

import time
import traceback
from pathlib import Path

from config.settings import Settings
from src import exporter, order_sync, persistence
from src.api_weight import APIWeightTracker
from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from src.order_manager import OrderManager, OrderPlacementResult
from src.portfolio import Portfolio
from src.position_closer import close_open_positions
from src.risk_manager import RiskManager
from src.status_display import display_status, get_summary
from src.ws_client import BinanceWebSocketClient
from utils.logger import setup_logger

logger = setup_logger("bot")

# JPYペアは為替レートを考慮（1 USD ≈ 150 JPY）
# 最低1往復利益: 手数料の2倍以上 + 少しのマージン
_MIN_PROFIT_USDT = 0.3  # USDT基準 (0.3 USDT ≈ 45 JPY)


def _estimate_cycle_profit(
    current_price: float,
    lower_price: float,
    upper_price: float,
    grid_count: int,
    investment_amount: float,
    fee_rate: float,
) -> float:
    """グリッド設定から1往復あたりの概算純利益を見積もる。"""
    if current_price <= 0 or lower_price <= 0 or upper_price <= lower_price or grid_count <= 0:
        return 0.0

    amount_per_grid = investment_amount / grid_count
    raw_qty = amount_per_grid / current_price
    grid_spacing = (upper_price - lower_price) / grid_count
    gross = raw_qty * grid_spacing
    fees = amount_per_grid * (fee_rate * 2)
    return gross - fees


class GridBot:
    """グリッド取引ボット"""

    def __init__(
        self,
        symbol: str | None = None,
        ws_client: BinanceWebSocketClient | None = None,
        weight_tracker: APIWeightTracker | None = None,
    ):
        errors = Settings.validate()
        if errors:
            for error in errors:
                logger.error(f"設定エラー: {error}")
            raise ValueError(f"設定エラーがあります: {errors}")

        self.symbol = symbol or Settings.TRADING_SYMBOL
        self.ws_client = ws_client

        self.client = BinanceClient(weight_tracker=weight_tracker)

        if ws_client is None:
            self.ws_client = BinanceWebSocketClient(binance_client=self.client)

        self.current_price = self.client.get_symbol_price(self.symbol)
        logger.info(f"現在価格: {self.current_price:.2f}")

        symbol_info = self.client.get_symbol_info(self.symbol)
        self.quote_asset = symbol_info.get("quote_asset", "USDT") if symbol_info else "USDT"
        logger.debug(f"Quote asset: {self.quote_asset}")
        self._live_quote_balance: float | None = None

        investment_amount = self._resolve_investment_amount()
        lower_price, upper_price = self._resolve_grid_bounds(self.current_price)
        grid_count = self._resolve_grid_count(
            investment_amount=investment_amount,
            lower_price=lower_price,
            upper_price=upper_price,
        )
        estimated_cycle_profit = _estimate_cycle_profit(
            current_price=self.current_price,
            lower_price=lower_price,
            upper_price=upper_price,
            grid_count=grid_count,
            investment_amount=investment_amount,
            fee_rate=Settings.TRADING_FEE_RATE,
        )

        self.strategy = GridStrategy(
            symbol=self.symbol,
            current_price=self.current_price,
            lower_price=lower_price,
            upper_price=upper_price,
            grid_count=grid_count,
            investment_amount=investment_amount,
        )
        balance_label = (
            f"{self._live_quote_balance:.2f} {self.quote_asset}"
            if self._live_quote_balance is not None
            else "n/a"
        )
        logger.info(
            f"起動サマリ: 残高={balance_label}, "
            f"採用投資額={investment_amount:.2f} {self.quote_asset}, "
            f"採用グリッド数={grid_count}, "
            f"推定1往復利益={estimated_cycle_profit:.2f} {self.quote_asset}"
        )
        logger.info(
            f"推定1往復利益: {estimated_cycle_profit:.2f} {self.quote_asset} "
            f"(目安: {self._min_cycle_profit():.2f} {self.quote_asset} 以上が実用ライン)"
        )
        if estimated_cycle_profit < self._min_cycle_profit():
            logger.warning(
                f"現在設定の推定1往返利益が低いです: {estimated_cycle_profit:.2f} "
                f"{self.quote_asset}. GRID_COUNT を減らすか投資額を増やしてください。"
            )

        self.order_manager = OrderManager(self.client, self.strategy)
        self.risk_manager = RiskManager(self.client, self.strategy)
        self.portfolio = Portfolio(
            self.client,
            self.symbol,
            quote_asset=self.quote_asset,
            fee_rate=Settings.TRADING_FEE_RATE,
        )

        self.is_running = False
        self.consecutive_errors = 0
        self._last_status_time: float = 0
        self._last_detail_time: float = 0
        self._last_persist_time: float = 0

        self._restore_state()
        self._sync_orders()

        if self.ws_client:
            self.ws_client.set_on_order_update(self._on_ws_order_update)

        logger.info("グリッドボット初期化完了")

    # ── 価格検証 ───────────────────────────────────────────────────

    def _min_cycle_profit(self) -> float:
        """quote_assetに応じた1往復利益の最低ライン"""
        if self.quote_asset == "JPY":
            return _MIN_PROFIT_USDT * 150  # ~75 JPY
        return _MIN_PROFIT_USDT  # 0.5 USDT

    def _resolve_investment_amount(self) -> float:
        """投資額を決定

        INVESTMENT_AMOUNT=0 or 未設定 → 残高全額を自動使用（本番・testnet共通）
        INVESTMENT_AMOUNT>0 → min(設定値, 残高)
        """
        configured = Settings.INVESTMENT_AMOUNT
        try:
            balances = self._retry_api(
                lambda: self.client.get_account_balance(),
                "残高取得",
            )
            quote_balance = balances.get(self.quote_asset, {}).get("free", 0.0)
            self._live_quote_balance = quote_balance
            if quote_balance <= 0:
                raise ValueError(f"{self.quote_asset} 残高が不足しています: {quote_balance}")

            if configured > 0:
                resolved = min(configured, quote_balance)
                if resolved < configured:
                    logger.info(
                        f"投資額: {resolved:.2f} {self.quote_asset} "
                        f"（残高 {quote_balance:.2f} < 設定値 {configured:.2f}）"
                    )
                else:
                    logger.info(f"投資額: {resolved:.2f} {self.quote_asset}（設定値を採用）")
                return resolved

            logger.info(f"投資額: {quote_balance:.2f} {self.quote_asset}（残高全額を自動使用）")
            return quote_balance
        except Exception as e:
            logger.error(f"残高取得失敗: {e}")
            raise

    def _resolve_grid_bounds(self, current_price: float) -> tuple[float, float]:
        """グリッドの価格帯を決定する"""
        if Settings.LOWER_PRICE is not None and Settings.UPPER_PRICE is not None:
            return Settings.LOWER_PRICE, Settings.UPPER_PRICE

        factor = Settings.GRID_RANGE_FACTOR
        lower_price = current_price * (1 - factor)
        upper_price = current_price * (1 + factor)
        return lower_price, upper_price

    def _resolve_grid_count(
        self, investment_amount: float, lower_price: float, upper_price: float
    ) -> int:
        """資金額に基づいて最適なグリッド数を完全自動計算

        GRID_COUNT=0 → 資金から最大適正グリッド数を自動算出
        GRID_COUNT>0 → その値を上限として、資金に合わせて減らす

        最適化ルール:
        1. 1グリッドの投資額 >= min_notional（取引所最低注文額）
        2. 1往復利益 >= _min_cycle_profit（手数料を上回る実益）
        3. 利益/グリッド数の効率が最大化される点を採用
        """
        min_profit = self._min_cycle_profit()

        symbol_info = self.client.get_symbol_info(self.symbol)
        min_notional = float(symbol_info.get("min_notional", 0) or 0) if symbol_info else 0
        if min_notional <= 0:
            # SOLJPY等、NOTIONALフィルターの銘柄向けフォールバック
            min_notional = 100.0 if self.quote_asset == "JPY" else 10.0
            logger.debug(f"min_notional取得不可、フォールバック: {min_notional} {self.quote_asset}")

        # 上限の決定
        if Settings.GRID_COUNT <= 0:
            # 完全自動: min_notionalから理論上の最大を計算
            max_by_notional = int(investment_amount / (min_notional * 1.5))  # 1.5x余裕
            hard_cap = min(max_by_notional, 30)  # 30上限（API負荷対策）
            start = max(hard_cap, 2)
        else:
            start = max(2, Settings.GRID_COUNT)

        # 条件を満たす最大グリッド数を探す（上から順に）
        best = 2
        for candidate in range(start, 1, -1):
            per_grid = investment_amount / candidate

            if per_grid < min_notional:
                continue

            est = _estimate_cycle_profit(
                current_price=self.current_price,
                lower_price=lower_price,
                upper_price=upper_price,
                grid_count=candidate,
                investment_amount=investment_amount,
                fee_rate=Settings.TRADING_FEE_RATE,
            )
            if est < min_profit:
                continue

            best = candidate
            break

        label = "自動" if Settings.GRID_COUNT <= 0 else f"上限{Settings.GRID_COUNT}"
        logger.info(
            f"グリッド数決定: {best} ({label}) "
            f"資金={investment_amount:.2f} {self.quote_asset}, "
            f"perGrid={investment_amount / best:.2f}, "
            f"minNotional={min_notional}, minCycleProfit={min_profit:.2f}"
        )
        return best

    def _validate_price(self, price: float) -> bool:
        """異常価格（0, 負値, 極端な変動）を検知してスキップ

        Testnetでは時々0や極端なスパイク価格が返ることがある。
        前回価格との変動率が50%超、または0以下の場合は異常とみなす。
        """
        if not isinstance(price, (int, float)) or price <= 0:
            logger.warning(f"異常価格を検知: {price}。スキップします。")
            return False

        prev_price = self.strategy.current_price
        if (
            isinstance(prev_price, (int, float))
            and prev_price > 0
            and abs(price - prev_price) / prev_price > 0.5
        ):
            logger.warning(
                f"異常な価格変動を検知: {prev_price:.2f} -> {price:.2f} "
                f"({abs(price - prev_price) / prev_price * 100:.1f}%). スキップします。"
            )
            return False

        return True

    # ── 初期化ヘルパー ──────────────────────────────────────────────

    def _restore_state(self):
        """永続化された状態を復元"""
        grid_states = persistence.load_grid_states(self.symbol)
        if grid_states:
            for gs in grid_states:
                level = gs["level"]
                if level < len(self.strategy.grids):
                    grid = self.strategy.grids[level]
                    grid.position_filled = gs["position_filled"]
                    grid.buy_order_id = gs["buy_order_id"]
                    grid.sell_order_id = gs["sell_order_id"]
            logger.info(f"グリッド状態を復元: {len(grid_states)} レベル")

            filled_count = sum(1 for g in self.strategy.grids if g.position_filled)
            self.risk_manager.current_positions = filled_count

        portfolio_stats = persistence.load_portfolio_stats()
        if portfolio_stats:
            persistence.restore_stats_to(self.portfolio.stats, portfolio_stats)
            logger.info(
                f"ポートフォリオ統計を復元: "
                f"初期残高={self.portfolio.stats.initial_balance:.2f}, "
                f"実現利益={self.portfolio.stats.realized_profit:+.4f}, "
                f"取引={self.portfolio.stats.total_trades}件"
            )

        trade_records = persistence.load_trades()
        if trade_records:
            self.portfolio.restore_trades(trade_records)
            self._restore_open_position_quantities()

    def _restore_open_position_quantities(self) -> None:
        """復元済みの買い取引から未決済ポジションの数量を補完する"""
        restored = 0
        for grid in self.strategy.grids:
            if not grid.position_filled or grid.filled_quantity is not None:
                continue

            trade = self.portfolio.find_matching_buy_trade(grid.level)
            if trade is None or trade.quantity <= 0:
                continue

            grid.filled_quantity = trade.quantity
            if grid.buy_order_id is None:
                grid.buy_order_id = trade.order_id
            restored += 1

        if restored:
            logger.info(f"オープンポジション数量を復元: {restored} 件")

    def _sync_orders(self):
        """取引所のオープン注文と内部状態を同期"""
        registered, removed = order_sync.sync_with_exchange(
            self.order_manager, self.strategy, self.risk_manager
        )
        if registered or removed:
            logger.info(f"注文同期完了: 登録={registered}, 削除={removed}")

    # ── 状態永続化 ─────────────────────────────────────────────────

    def _persist_state(self):
        """現在の状態を永続化"""
        try:
            persistence.save_grid_states(self.symbol, self.strategy.grids)
            persistence.save_portfolio_stats(self.portfolio.stats)
        except Exception as e:
            logger.error(f"状態永続化失敗: {e}")

    # ── メインループ ───────────────────────────────────────────────

    def start(self):
        """ボット開始"""
        logger.info("=" * 60)
        logger.info("グリッドボット 開始")
        logger.info("=" * 60)

        self.is_running = True
        self._last_status_time = time.time()
        self._last_detail_time = time.time()

        if self.ws_client:
            self.ws_client.start_price_stream(self.symbol)
            self.ws_client.start_user_stream()

        self._place_initial_orders()

        try:
            while self.is_running:
                self._tick()
                time.sleep(Settings.CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt 検出。ボット停止中...")
        except Exception as e:
            logger.error(f"予期せぬエラー: {e}", exc_info=True)
        finally:
            if self.is_running:
                self.stop()

    def _update_price(self):
        """現在価格を更新（停滞検知付き）"""
        ws = self.ws_client
        if ws and ws.current_price is not None:
            if ws.is_price_stale:
                logger.warning(
                    f"価格更新停滞: {ws.seconds_since_last_price:.0f}秒。REST API で取得します"
                )
                self.current_price = self.client.get_symbol_price(self.symbol)
            else:
                self.current_price = ws.current_price
        else:
            self.current_price = self.client.get_symbol_price(self.symbol)
        self.strategy.update_current_price(self.current_price)

    def _tick(self) -> None:
        """1 ティック処理"""
        try:
            self._update_price()
        except Exception as e:
            self._handle_tick_error(e)
            return

        if not self._validate_price(self.current_price):
            return

        if self._check_halt_conditions():
            return

        self._execute_trading_logic()

        try:
            self._run_maintenance_tasks()
        except Exception as e:
            # メンテナンスタスクの失敗（ログ表示やDB保存など）は取引に影響させない
            logger.warning(f"メンテナンスタスク失敗（スキップ）: {e}")

    def _check_halt_conditions(self) -> bool:
        """取引停止条件のチェック"""
        if self.risk_manager.should_halt_trading(self.current_price):
            logger.warning("リスク管理により取引を停止します")
            self._emergency_stop()
            self.consecutive_errors = 0
            return True
        return False

    def _execute_trading_logic(self) -> None:
        """取引実行ロジックの管理（通信エラー時は自動リトライ）"""
        try:
            self._process_fills()
        except Exception as e:
            logger.warning(f"約定チェック失敗（次ティックでリトライ）: {e}")

        try:
            self.portfolio.calculate_unrealized_pnl(self.current_price)
        except Exception as e:
            logger.warning(f"未実現損益計算失敗（スキップ）: {e}")

        self.consecutive_errors = 0

        if self._check_portfolio_drawdown():
            return

        if not self.strategy.is_within_grid_range(self.current_price):
            self._handle_grid_shift()

    def _run_maintenance_tasks(self) -> None:
        """定期メンテナンスの実行"""
        now = time.time()
        if now - self._last_status_time >= Settings.STATUS_DISPLAY_INTERVAL:
            display_status(
                self.symbol, self.current_price, self.strategy, self.portfolio, self.risk_manager
            )
            self._last_status_time = now

        detail_interval = max(Settings.STATUS_DISPLAY_INTERVAL * 5, 300)
        if now - self._last_detail_time >= detail_interval:
            display_status(
                self.symbol,
                self.current_price,
                self.strategy,
                self.portfolio,
                self.risk_manager,
                detail=True,
            )
            self._last_detail_time = now

        if now - self._last_persist_time >= Settings.PERSIST_INTERVAL:
            self._persist_state()
            self._last_persist_time = now
            self._update_health_file()

    @staticmethod
    def _update_health_file():
        """ヘルスチェック用ファイルを更新（Docker HEALTHCHECK で参照）"""
        try:
            health_path = Path("data") / ".health"
            health_path.parent.mkdir(parents=True, exist_ok=True)
            health_path.write_text(str(time.time()))
        except Exception:
            pass

    def _retry_api(self, fn, label: str, max_wait: float = 300):
        """API呼び出しを無限リトライ（指数バックオフ、最大5分待機）"""
        delay = 1.0
        while True:
            try:
                return fn()
            except Exception as e:
                logger.warning(f"{label}失敗 ({delay:.0f}秒後にリトライ): {e}")
                time.sleep(delay)
                delay = min(delay * 2, max_wait)

    def _handle_tick_error(self, e: Exception) -> None:
        """ティック処理エラーのハンドリング（停止せず無限リトライ）"""
        self.consecutive_errors += 1
        logger.warning(f"ティック処理エラー ({self.consecutive_errors}回目、継続します): {e}")
        logger.debug(f"スタックトレース:\n{traceback.format_exc()}")

        # 通信エラーは停止せずリトライし続ける
        # 致命的エラー（設定ミス等）は上位の try/except でキャッチされる

    def _check_portfolio_drawdown(self) -> bool:
        """ポートフォリオのドローダウンが上限を超えたら停止する"""
        stats = self.portfolio.stats
        max_drawdown_pct_limit = getattr(Settings, "MAX_DRAWDOWN_PCT", 10.0)
        if stats.peak_balance <= 0:
            return False
        if stats.max_drawdown_pct < max_drawdown_pct_limit:
            return False

        logger.critical(
            f"最大ドローダウン到達: {stats.max_drawdown_pct:.2f}% >= "
            f"{max_drawdown_pct_limit:.2f}%。ボットを停止します。"
        )
        self._emergency_stop()
        return True

    # ── 注文管理 ───────────────────────────────────────────────────

    def _place_initial_orders(self) -> OrderPlacementResult | None:
        """初期注文を配置"""
        logger.info("初期注文配置開始...")
        result = self.order_manager.place_grid_orders()
        logger.info(f"初期注文配置完了: {result.placed} 件")
        return result

    def _place_grid_orders_for_level(self, grid_level: int):
        """特定グリッドレベルの買い注文を配置（決済後）"""
        if not self.risk_manager.can_open_position():
            logger.warning(f"グリッド {grid_level}: ポジション上限のため買い再注文スキップ")
            return

        success = self.order_manager.place_buy_order_for_grid(grid_level)
        if not success:
            logger.error(f"グリッド {grid_level}: 買い再注文に失敗しました")

    def _place_sell_for_grid(self, grid_level: int, quantity: float):
        """特定グリッドレベルの売り注文を配置（買い約定後）"""
        success = self.order_manager.place_sell_order_for_grid(grid_level, quantity)
        if not success:
            logger.error(
                f"グリッド {grid_level}: 売り注文配置に失敗しました。"
                "次回ティックでリトライされます。"
            )

    def _process_fills(self):
        """約定イベントを処理（下方向 + 上方向 双方対応）"""
        new_fills = self.order_manager.check_order_fills()

        for fill in new_fills:
            grid = self.strategy.grids[fill.grid]

            # ── 下方向: BUY約定 → SELL配置 ──
            if fill.side == "BUY" and not grid.short_position_filled:
                self.risk_manager.record_position_open()
                if grid.sell_price is None:
                    logger.warning(
                        f"グリッド {fill.grid}: 最上位グリッドのため売り注文なし。"
                        "手動での決済が必要です。"
                    )
                    continue
                logger.info(f"グリッド {fill.grid}: 買い約定、売り注文配置")
                grid.filled_quantity = fill.quantity
                profit = self.portfolio.record_trade(
                    side=fill.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    order_id=fill.order_id,
                    grid_level=fill.grid,
                )
                self._place_sell_for_grid(fill.grid, fill.quantity)

            # ── 下方向: SELL約定 → 再BUY配置 ──
            elif fill.side == "SELL" and grid.position_filled:
                profit = self.portfolio.record_trade(
                    side=fill.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    order_id=fill.order_id,
                    grid_level=fill.grid,
                )
                self.risk_manager.record_position_close(profit or 0.0)
                logger.info(f"グリッド {fill.grid}: 決済完了、再注文配置")
                self._place_grid_orders_for_level(fill.grid)

            # ── 上方向: SELL約定（ショート開始）→ BUYBACK配置 ──
            elif (
                fill.side == "SELL"
                and grid.short_sell_price
                and fill.price >= grid.short_sell_price
            ):
                grid.short_filled_quantity = fill.quantity
                self.strategy.mark_short_filled(fill.grid, fill.order_id)
                profit = self.portfolio.record_trade(
                    side=fill.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    order_id=fill.order_id,
                    grid_level=fill.grid,
                )
                # BUYBACK注文を配置
                if grid.short_buyback_price:
                    try:
                        self.order_manager.place_buy_order_for_grid(fill.grid)
                        logger.info(
                            f"グリッド {fill.grid}: ショートSELL約定 -> "
                            f"BUYBACK配置 @ {grid.short_buyback_price:.0f}"
                        )
                    except Exception as e:
                        logger.error(f"グリッド {fill.grid}: BUYBACK配置失敗: {e}")

            # ── 上方向: BUYBACK約定（ショート決済）→ 再SELL配置 ──
            elif fill.side == "BUY" and grid.short_position_filled:
                self.strategy.mark_short_closed(fill.grid, fill.order_id)
                profit = self.portfolio.record_trade(
                    side=fill.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    order_id=fill.order_id,
                    grid_level=fill.grid,
                )
                logger.info(f"グリッド {fill.grid}: ショートBUYBACK約定、再SELL配置")
                # 再度SELL指値を配置
                if grid.short_sell_price:
                    symbol_info = self.client.get_symbol_info(self.symbol)
                    if symbol_info:
                        qty = self._resolve_short_sell_qty(fill.grid, symbol_info)
                        if qty > 0:
                            self.order_manager.place_sell_order_for_grid(fill.grid, qty)

    def _resolve_short_sell_qty(self, grid_level: int, symbol_info: dict) -> float:
        """ショート再SELL用の数量を決定（手持ちSOLから）"""
        try:
            balances = self._retry_api(
                lambda: self.client.get_account_balance(),
                "残高取得(short)",
            )
            base_asset = symbol_info.get("base_asset", "")
            available = float(balances.get(base_asset, {}).get("free", 0))
        except Exception:
            return 0
        if available <= 0:
            return 0
        from utils.precision import quantize_down

        step_size = float(symbol_info.get("step_size", 0) or 0)
        if step_size > 0:
            return quantize_down(available, step_size)
        return available

    def _handle_grid_shift(self):
        """グリッド範囲外時に動的シフト

        ポジションを持つ売り注文はキャンセルせず保護する。
        ポジションなしの注文のみキャンセルして再配置する。
        """
        logger.warning(f"価格 {self.current_price:.2f} がグリッド範囲外。動的シフトを実行します。")

        protected_order_ids: set[int] = set()
        for grid in self.strategy.grids:
            if grid.position_filled and grid.sell_order_id is not None:
                protected_order_ids.add(grid.sell_order_id)

        unprotected_orders = [
            oid for oid in self.order_manager.active_orders.keys() if oid not in protected_order_ids
        ]
        canceled = 0
        for oid in unprotected_orders:
            try:
                self.client.cancel_order(self.strategy.symbol, oid)
                self.order_manager.remove_order(oid)
                canceled += 1
            except Exception as e:
                logger.error(f"キャンセル失敗 order_id={oid}: {e}")
        logger.info(f"非保護注文キャンセル: {canceled} 件（保護: {len(protected_order_ids)} 件）")

        self.strategy.shift_grids()
        self.risk_manager.update_stop_loss_price(self.strategy.lower_price)
        self._place_initial_orders()

    def _on_ws_order_update(self, fill_info: dict):
        """WebSocket 約定コールバック（別スレッドから呼ばれる）"""
        try:
            symbol = fill_info.get("symbol", "")
            if symbol != self.symbol:
                return
            handled = self.order_manager.handle_ws_fill(fill_info)
            if handled:
                logger.info(f"WS約定を先取り処理: order_id={fill_info.get('order_id')}")
        except Exception as e:
            logger.error(f"WS約定コールバック処理エラー: {e}")

    # ── ステータス表示 ─────────────────────────────────────────────

    def get_summary(self) -> dict:
        return get_summary(self.is_running, self.current_price, self.strategy, self.portfolio)

    # ── 停止処理 ───────────────────────────────────────────────────

    def _shutdown_core(self, close_positions=False):
        """停止時の共通処理"""
        self._persist_state()
        canceled = self.order_manager.cancel_all_orders()
        logger.info(f"キャンセル完了: {canceled} 件")

        if close_positions:
            close_open_positions(self.client, self.strategy, self.portfolio)

        report = self.portfolio.generate_report()
        logger.info("\n" + report)
        return report

    def _export_on_stop(self):
        """停止時にトレード履歴をエクスポート

        メモリ上のtradesが空の場合はDBから再読み込みする。
        """
        trades = self.portfolio.trades
        if not trades:
            records = persistence.load_trades()
            if records:
                self.portfolio.restore_trades(records)
                trades = self.portfolio.trades
        if not trades:
            logger.info("エクスポート対象のトレードなし")
            return
        try:
            export_dir = Path("data") / "exports"
            timestamp_str = time.strftime("%Y%m%d_%H%M%S")
            csv_path = export_dir / f"trades_{timestamp_str}.csv"
            json_path = export_dir / f"trades_{timestamp_str}.json"
            count = exporter.export_trades_csv(trades, csv_path)
            exporter.export_trades_json(trades, json_path)
            logger.info(f"トレード履歴をエクスポート: {count} 件 -> {export_dir}")
        except Exception as e:
            logger.error(f"エクスポート失敗: {e}")

    def _emergency_stop(self):
        """緊急停止（オープンポジションを成行決済）"""
        self.is_running = False
        logger.warning("緊急停止処理開始...")
        report = self._shutdown_core(close_positions=True)
        print(report)
        logger.info("緊急停止完了")

    def stop(self):
        """ボット停止"""
        self.is_running = False
        logger.info("ボット停止中...")
        if self.ws_client:
            self.ws_client.stop()
        self._shutdown_core(close_positions=Settings.CLOSE_ON_STOP)
        self._export_on_stop()
        logger.info("ボット停止完了")
