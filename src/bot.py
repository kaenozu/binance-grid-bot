"""
ファイルパス: src/bot.py
概要: グリッド取引ボット メインループ
説明: 価格監視、注文管理、リスク管理、ステータス表示を統合
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/order_manager.py, src/risk_manager.py, src/portfolio.py
"""

import time
import traceback
import sys
from datetime import datetime
from typing import Optional

from config.settings import Settings
from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy
from src.order_manager import OrderManager
from src.risk_manager import RiskManager
from src.portfolio import Portfolio
from utils.logger import setup_logger

logger = setup_logger("bot")


class GridBot:
    """グリッド取引ボット"""

    def __init__(self):
        errors = Settings.validate()
        if errors:
            for error in errors:
                logger.error(f"設定エラー: {error}")
            raise ValueError(f"設定エラーがあります: {errors}")

        self.client = BinanceClient()

        self.current_price = self.client.get_symbol_price(Settings.TRADING_SYMBOL)
        logger.info(f"現在価格: {self.current_price:.2f}")

        self.strategy = GridStrategy(
            symbol=Settings.TRADING_SYMBOL,
            current_price=self.current_price,
            lower_price=Settings.LOWER_PRICE,
            upper_price=Settings.UPPER_PRICE,
            grid_count=Settings.GRID_COUNT,
            investment_amount=Settings.INVESTMENT_AMOUNT,
        )

        self.order_manager = OrderManager(self.client, self.strategy)
        self.risk_manager = RiskManager(self.client, self.strategy, self.current_price)
        self.portfolio = Portfolio(self.client, Settings.TRADING_SYMBOL)

        self.is_running = False
        self.consecutive_errors = 0
        self._last_status_time: float = 0

        logger.info("グリッドボット初期化完了")

    def start(self):
        """ボット開始"""
        logger.info("=" * 60)
        logger.info("グリッドボット 開始")
        logger.info("=" * 60)

        self.is_running = True
        self._last_status_time = time.time()

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

    def _place_initial_orders(self):
        """初期注文を配置"""
        logger.info("初期注文配置開始...")
        result = self.order_manager.place_grid_orders()
        logger.info(f"初期注文配置完了: {result.placed} 件")

    def _place_grid_orders_for_level(self, grid_level: int):
        """特定グリッドレベルの買い注文を配置（決済後）"""
        if not self.risk_manager.can_open_position():
            logger.warning(
                f"グリッド {grid_level}: ポジション上限のため買い再注文スキップ"
            )
            return

        self.order_manager.place_buy_order_for_grid(grid_level)

    def _place_sell_for_grid(self, grid_level: int, quantity: float):
        """特定グリッドレベルの売り注文を配置（買い約定後）"""
        self.order_manager.place_sell_order_for_grid(grid_level, quantity)

    def _tick(self) -> None:
        """1 ティック処理"""
        try:
            self.current_price = self.client.get_symbol_price(Settings.TRADING_SYMBOL)
            self.strategy.update_current_price(self.current_price)

            if self.risk_manager.should_halt_trading(self.current_price):
                logger.warning("リスク管理により取引を停止します")
                self._emergency_stop()
                return

            new_fills = self.order_manager.check_order_fills()

            for fill in new_fills:
                self.portfolio.record_trade(
                    side=fill.side,
                    price=fill.price,
                    quantity=fill.quantity,
                    order_id=fill.order_id,
                    grid_level=fill.grid,
                )

                if fill.side == "BUY":
                    self.risk_manager.record_position_open()
                    logger.info(f"グリッド {fill.grid}: 買い約定、売り注文配置")
                    self._place_sell_for_grid(fill.grid, fill.quantity)
                elif fill.side == "SELL":
                    buy_trade = self.portfolio.find_matching_buy_trade(fill.grid)
                    profit = 0.0
                    if buy_trade:
                        profit = (fill.price - buy_trade.price) * fill.quantity
                    self.risk_manager.record_position_close(profit)
                    self.strategy.mark_position_closed(fill.grid, fill.order_id)
                    logger.info(f"グリッド {fill.grid}: 決済完了、再注文配置")
                    self._place_grid_orders_for_level(fill.grid)

            self.portfolio.calculate_unrealized_pnl(self.current_price)
            self.consecutive_errors = 0

            now = time.time()
            if now - self._last_status_time >= Settings.STATUS_DISPLAY_INTERVAL:
                self._display_status()
                self._last_status_time = now

        except Exception as e:
            self.consecutive_errors += 1
            logger.error(
                f"ティック処理エラー ({self.consecutive_errors}/{Settings.MAX_CONSECUTIVE_ERRORS}): {e}"
            )
            logger.error(f"スタックトレース:\n{traceback.format_exc()}")

            if self.consecutive_errors >= Settings.MAX_CONSECUTIVE_ERRORS:
                logger.critical(
                    f"連続エラーが{Settings.MAX_CONSECUTIVE_ERRORS}回に到達。ボットを停止します。"
                )
                self.stop()

    def _display_status(self):
        """ステータスをCUIに表示"""
        stats = self.portfolio.get_stats()
        grid_status = self.strategy.grid_status
        risk_status = self.risk_manager.risk_status

        print("\n" + "=" * 70)
        print(
            f"グリッドボット ステータス - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
        )
        print("=" * 70)
        print(f"取引ペア: {Settings.TRADING_SYMBOL}")
        print(f"現在価格: {self.current_price:.2f}")
        print(f"価格範囲: {grid_status['price_range']}")
        print(
            f"グリッド数: {grid_status['total_grids']} (間隔: {grid_status['grid_spacing']:.2f})"
        )
        print(
            f"ポジション: {grid_status['filled_positions']}/{grid_status['total_grids']}"
        )
        print("-" * 70)
        print(f"初期残高: {stats.initial_balance:.2f} USDT")
        print(f"現在残高: {stats.current_balance:.2f} USDT")
        print(f"実現利益: {stats.realized_profit:+.2f} USDT")
        print(f"未実現利益: {stats.unrealized_profit:+.2f} USDT")
        print(f"総利益: {stats.total_profit:+.2f} USDT")
        print("-" * 70)
        print(f"取引回数: {stats.total_trades}")
        print(f"勝率: {stats.win_rate:.1f}%")
        print(f"損切りライン: {risk_status['stop_loss_price']:.2f}")
        print(
            f"ポジション: {risk_status['current_positions']}/{risk_status['max_positions']}"
        )
        print("=" * 70)
        print("Ctrl+C で停止")

    def _emergency_stop(self):
        """緊急停止"""
        logger.warning("緊急停止処理開始...")
        self.is_running = False
        self.order_manager.cancel_all_orders()
        print(self.portfolio.generate_report())
        logger.info("緊急停止完了")

    def stop(self):
        """ボット停止"""
        logger.info("ボット停止中...")
        self.is_running = False
        canceled = self.order_manager.cancel_all_orders()
        logger.info(f"キャンセル完了: {canceled} 件")
        report = self.portfolio.generate_report()
        logger.info("\n" + report)
        logger.info("ボット停止完了")
