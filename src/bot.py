"""
ファイルパス: src/bot.py
概要: グリッド取引ボット メインループ
説明: 価格監視、注文管理、リスク管理、ステータス表示、永続化、エクスポートを統合
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/order_manager.py,
  src/risk_manager.py, src/portfolio.py, src/persistence.py, src/order_sync.py, src/exporter.py
"""

import time
import traceback
from typing import Optional

from config.settings import Settings
from src import order_sync, persistence
from src.api_weight import APIWeightTracker
from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from src.order_manager import OrderManager
from src.portfolio import Portfolio
from src.risk_manager import RiskManager
from src.ws_client import BinanceWebSocketClient
from utils.logger import setup_logger

logger = setup_logger("bot")


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

        self.current_price = self.client.get_symbol_price(self.symbol)
        logger.info(f"現在価格: {self.current_price:.2f}")

        self.strategy = GridStrategy(
            symbol=self.symbol,
            current_price=self.current_price,
            lower_price=Settings.LOWER_PRICE,
            upper_price=Settings.UPPER_PRICE,
            grid_count=Settings.GRID_COUNT,
            investment_amount=Settings.INVESTMENT_AMOUNT,
        )

        self.order_manager = OrderManager(self.client, self.strategy)
        self.risk_manager = RiskManager(self.client, self.strategy)
        self.portfolio = Portfolio(self.client, self.symbol, fee_rate=Settings.TRADING_FEE_RATE)

        self.is_running = False
        self.consecutive_errors = 0
        self._last_status_time: float = 0
        self._last_persist_time: float = 0

        self._restore_state()
        self._sync_orders()

        logger.info("グリッドボット初期化完了")

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
            logger.info("ポートフォリオ統計を復元")

        trade_records = persistence.load_trades()
        if trade_records:
            self.portfolio.restore_trades(trade_records)

    def _sync_orders(self):
        """取引所のオープン注文と内部状態を同期"""
        registered, removed = order_sync.sync_with_exchange(self.order_manager, self.strategy)
        if registered or removed:
            logger.info(f"注文同期完了: 登録={registered}, 削除={removed}")

    def _persist_state(self):
        """現在の状態を永続化"""
        try:
            persistence.save_grid_states(self.symbol, self.strategy.grids)
            persistence.save_portfolio_stats(self.portfolio.stats)
        except Exception as e:
            logger.error(f"状態永続化失敗: {e}")

    def start(self):
        """ボット開始"""
        logger.info("=" * 60)
        logger.info("グリッドボット 開始")
        logger.info("=" * 60)

        self.is_running = True
        self._last_status_time = time.time()

        if self.ws_client:
            self.ws_client.start_price_stream(self.symbol)

        self._place_initial_orders()

        try:
            while self.is_running:
                self._tick()
                time.sleep(Settings.CHECK_INTERVAL)
        except KeyboardInterrupt:
            logger.info("KeyboardInterrupt 検出。ボット停止中...")
            self.stop()
        except Exception as e:
            logger.error(f"予期せぬエラー: {e}", exc_info=True)
            self.stop()

    def _place_initial_orders(self) -> Optional[dict]:
        """初期注文を配置

        Returns:
            使用したシンボル情報（失敗時はNone）
        """
        logger.info("初期注文配置開始...")
        result = self.order_manager.place_grid_orders()
        logger.info(f"初期注文配置完了: {result.placed} 件")
        return self.client.get_symbol_info(self.strategy.symbol)

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

    def _tick(self) -> None:
        """1 ティック処理"""
        try:
            ws_price = self.ws_client.current_price if self.ws_client else None
            if ws_price is not None:
                self.current_price = ws_price
            else:
                self.current_price = self.client.get_symbol_price(self.symbol)
            self.strategy.update_current_price(self.current_price)

            if self.risk_manager.should_halt_trading(self.current_price):
                logger.warning("リスク管理により取引を停止します")
                self._emergency_stop()
                self.consecutive_errors = 0
                return

            self._process_fills()
            self.portfolio.calculate_unrealized_pnl(self.current_price)
            self.consecutive_errors = 0

            now = time.time()
            if now - self._last_status_time >= Settings.STATUS_DISPLAY_INTERVAL:
                self._display_status()
                self._last_status_time = now

            if now - self._last_persist_time >= Settings.PERSIST_INTERVAL:
                self._persist_state()
                self._last_persist_time = now

            if not self.strategy.is_within_grid_range(self.current_price):
                self._handle_grid_shift()

        except Exception as e:
            self.consecutive_errors += 1
            logger.error(
                f"ティック処理エラー ({self.consecutive_errors}/"
                f"{Settings.MAX_CONSECUTIVE_ERRORS}): {e}"
            )
            logger.error(f"スタックトレース:\n{traceback.format_exc()}")

            if self.consecutive_errors >= Settings.MAX_CONSECUTIVE_ERRORS:
                logger.critical(
                    f"連続エラーが{Settings.MAX_CONSECUTIVE_ERRORS}回に到達。ボットを停止します。"
                )
                self.stop()

    def _process_fills(self):
        """約定イベントを処理"""
        new_fills = self.order_manager.check_order_fills()

        for fill in new_fills:
            profit = self.portfolio.record_trade(
                side=fill.side,
                price=fill.price,
                quantity=fill.quantity,
                order_id=fill.order_id,
                grid_level=fill.grid,
            )

            if fill.side == "BUY":
                self.risk_manager.record_position_open()
                grid = self.strategy.grids[fill.grid]
                if grid.sell_price is None:
                    logger.warning(
                        f"グリッド {fill.grid}: 最上位グリッドのため売り注文なし。"
                        "手動での決済が必要です。"
                    )
                    continue
                logger.info(f"グリッド {fill.grid}: 買い約定、売り注文配置")
                self.strategy.grids[fill.grid].filled_quantity = fill.quantity
                self._place_sell_for_grid(fill.grid, fill.quantity)
            elif fill.side == "SELL":
                self.risk_manager.record_position_close(profit or 0.0)
                logger.info(f"グリッド {fill.grid}: 決済完了、再注文配置")
                self._place_grid_orders_for_level(fill.grid)

    def _handle_grid_shift(self):
        logger.warning(f"価格 {self.current_price:.2f} がグリッド範囲外。動的シフトを実行します。")
        filled_positions = [
            (g.buy_price, g.buy_order_id, g.filled_quantity)
            for g in self.strategy.grids
            if g.position_filled
        ]

        self.order_manager.cancel_all_orders()
        self.strategy.shift_grids()
        self.risk_manager.stop_loss_price = self.strategy.lower_price * (
            1 - Settings.STOP_LOSS_PERCENTAGE / 100
        )

        claimed: set[int] = set()
        for buy_price, buy_order_id, qty in filled_positions:
            available = [g for g in self.strategy.grids if g.level not in claimed]
            if not available:
                logger.warning("グリッドシフト: 空きグリッド不足、一部ポジションの復元をスキップ")
                break
            best = min(available, key=lambda g: abs(g.buy_price - buy_price))
            best.position_filled = True
            best.buy_order_id = buy_order_id
            best.filled_quantity = qty
            claimed.add(best.level)

        self._place_initial_orders()

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

    def _display_status(self):
        from src.bot_display import display_status

        stats = self.portfolio.refresh_stats()
        display_status(
            self.symbol,
            self.current_price,
            self.strategy.grid_status,
            stats,
            self.risk_manager.risk_status,
        )

    def _export_on_stop(self):
        from src.bot_shutdown import export_on_stop

        export_on_stop(self.portfolio)

    def _emergency_stop(self):
        from src.bot_shutdown import emergency_stop

        self.is_running = False
        emergency_stop(
            self.client, self.strategy, self.order_manager, self.portfolio, self._persist_state
        )

    def _close_open_positions(self):
        from src.bot_shutdown import close_open_positions

        close_open_positions(self.client, self.strategy, self.portfolio)

    def stop(self):
        from config.settings import Settings
        from src.bot_shutdown import stop_bot

        self.is_running = False
        stop_bot(
            self.client,
            self.strategy,
            self.order_manager,
            self.portfolio,
            self._persist_state,
            Settings.CLOSE_ON_STOP,
            self.ws_client,
        )
