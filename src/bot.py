"""
ファイルパス: src/bot.py
概要: グリッド取引ボット メインループ
説明: 価格監視、注文管理、リスク管理、ステータス表示を統合
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/order_manager.py, src/risk_manager.py, src/portfolio.py
"""

import time
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
        # バリデーション
        errors = Settings.validate()
        if errors:
            for error in errors:
                logger.error(f"設定エラー: {error}")
            raise ValueError(f"設定エラーがあります: {errors}")
        
        # クライアント初期化
        self.client = BinanceClient()
        
        # 現在価格取得
        self.current_price = self.client.get_symbol_price(Settings.TRADING_SYMBOL)
        logger.info(f"現在価格: {self.current_price:.2f}")
        
        # 戦略初期化
        self.strategy = GridStrategy(
            symbol=Settings.TRADING_SYMBOL,
            current_price=self.current_price,
            lower_price=Settings.LOWER_PRICE,
            upper_price=Settings.UPPER_PRICE,
            grid_count=Settings.GRID_COUNT,
            investment_amount=Settings.INVESTMENT_AMOUNT
        )
        
        # 注文管理
        self.order_manager = OrderManager(self.client, self.strategy)
        
        # リスク管理
        self.risk_manager = RiskManager(self.client, self.strategy, self.current_price)
        
        # ポートフォリオ
        self.portfolio = Portfolio(self.client, Settings.TRADING_SYMBOL)
        
        # 状態管理
        self.is_running = False
        self.check_interval = 10  # チェック間隔（秒）
        self.consecutive_errors = 0
        self.max_consecutive_errors = 5
        
        logger.info("グリッドボット初期化完了")
    
    def start(self):
        """ボット開始"""
        logger.info("=" * 60)
        logger.info("グリッドボット 開始")
        logger.info("=" * 60)
        
        self.is_running = True
        
        # 初期注文配置
        self._place_initial_orders()
        
        # メインループ
        try:
            while self.is_running:
                self._tick()
                time.sleep(self.check_interval)
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
        logger.info(f"初期注文配置完了: {result['placed']} 件")
    
    def _place_grid_orders_for_level(self, grid_level: int):
        """特定グリッドレベルの買い注文を配置（決済後）"""
        try:
            symbol_info = self.client.get_symbol_info(self.strategy.symbol)
            if not symbol_info:
                return
            
            grid = self.strategy.grids[grid_level]
            grid.position_filled = False  # リセット
            
            quantity = self.strategy.get_order_quantity(
                grid.buy_price,
                symbol_info["min_qty"],
                symbol_info["step_size"]
            )
            
            tick_size = symbol_info["tick_size"]
            adjusted_price = round(grid.buy_price / tick_size) * tick_size
            
            order = self.client.place_order(
                symbol=self.strategy.symbol,
                side="BUY",
                quantity=quantity,
                price=adjusted_price
            )
            
            self.order_manager.active_orders[order["orderId"]] = {
                "grid_level": grid_level,
                "side": "BUY",
                "price": float(order["price"]),
                "quantity": float(order["origQty"]),
                "status": order["status"]
            }
            
            logger.info(f"グリッド {grid_level}: 買い再注文配置 @ {adjusted_price}")
            
        except Exception as e:
            logger.error(f"グリッド {grid_level} 再注文失敗: {e}")
    
    def _place_sell_for_grid(self, grid_level: int, quantity: float):
        """特定グリッドレベルの売り注文を配置（買い約定後）"""
        try:
            symbol_info = self.client.get_symbol_info(self.strategy.symbol)
            if not symbol_info:
                return
            
            grid = self.strategy.grids[grid_level]
            if not grid.sell_price:
                return
            
            tick_size = symbol_info["tick_size"]
            adjusted_price = round(grid.sell_price / tick_size) * tick_size
            
            order = self.client.place_order(
                symbol=self.strategy.symbol,
                side="SELL",
                quantity=quantity,
                price=adjusted_price
            )
            
            self.order_manager.active_orders[order["orderId"]] = {
                "grid_level": grid_level,
                "side": "SELL",
                "price": float(order["price"]),
                "quantity": float(order["origQty"]),
                "status": order["status"]
            }
            
            logger.info(f"グリッド {grid_level}: 売り注文配置 @ {adjusted_price}")
            
        except Exception as e:
            logger.error(f"グリッド {grid_level} 売り注文失敗: {e}")
    
    def _tick(self):
        """1 ティック処理"""
        try:
            # 価格更新
            self.current_price = self.client.get_symbol_price(Settings.TRADING_SYMBOL)
            self.strategy.update_current_price(self.current_price)
            
            # リスクチェック
            if self.risk_manager.should_halt_trading(self.current_price):
                logger.warning("リスク管理により取引を停止します")
                self._emergency_stop()
                return
            
            # 約定チェック
            new_fills = self.order_manager.check_order_fills()
            
            for fill in new_fills:
                # ポートフォリオに記録
                self.portfolio.record_trade(
                    side=fill["side"],
                    price=fill["price"],
                    quantity=fill["quantity"],
                    order_id=fill["order_id"],
                    grid_level=fill["grid"]
                )
                
                # リスク管理のポジション記録
                if fill["side"] == "BUY":
                    self.risk_manager.record_position_open()
                elif fill["side"] == "SELL":
                    # 利益計算
                    buy_trade = self.portfolio._find_matching_buy_trade(fill["grid"])
                    profit = 0.0
                    if buy_trade:
                        profit = (fill["price"] - buy_trade.price) * fill["quantity"]
                    self.risk_manager.record_position_close(profit)
                
                # 約定に応じて該当グリッドの注文のみを再配置
                if fill["side"] == "SELL":
                    # 売り約定 → グリッドリセット、再度買い注文を配置
                    self.strategy.mark_position_closed(fill["grid"], fill["order_id"])
                    logger.info(f"グリッド {fill['grid']}: 決済完了、再注文配置")
                    self._place_grid_orders_for_level(fill["grid"])
                elif fill["side"] == "BUY":
                    # 買い約定 → 売り注文を配置
                    logger.info(f"グリッド {fill['grid']}: 買い約定、売り注文配置")
                    self._place_sell_for_grid(fill["grid"], fill["quantity"])
            
            # 未実現損益計算
            self.portfolio.calculate_unrealized_pnl(self.current_price)
            
            # 成功したらエラーカウンターリセット
            self.consecutive_errors = 0
            
            # ステータス表示（60秒ごと）
            if int(time.time()) % 60 < self.check_interval:
                self._display_status()
            
        except Exception as e:
            self.consecutive_errors += 1
            import traceback
            error_trace = traceback.format_exc()
            logger.error(f"ティック処理エラー ({self.consecutive_errors}/{self.max_consecutive_errors}): {e}")
            logger.error(f"スタックトレース:\n{error_trace}")
            
            if self.consecutive_errors >= self.max_consecutive_errors:
                logger.critical(f"連続エラーが{self.max_consecutive_errors}回に到達。ボットを停止します。")
                self.stop()
    
    def _display_status(self):
        """ステータスをCUIに表示"""
        stats = self.portfolio.get_stats()
        grid_status = self.strategy.get_grid_status()
        risk_status = self.risk_manager.get_risk_status()
        
        # クリア（Windows 対応）
        print("\n" + "=" * 70)
        print(f"グリッドボット ステータス - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 70)
        print(f"取引ペア: {Settings.TRADING_SYMBOL}")
        print(f"現在価格: {self.current_price:.2f}")
        print(f"価格範囲: {grid_status['price_range']}")
        print(f"グリッド数: {grid_status['total_grids']} (間隔: {grid_status['grid_spacing']:.2f})")
        print(f"ポジション: {grid_status['filled_positions']}/{grid_status['total_grids']}")
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
        print(f"ポジション: {risk_status['current_positions']}/{risk_status['max_positions']}")
        print("=" * 70)
        print("Ctrl+C で停止")
    
    def _emergency_stop(self):
        """緊急停止"""
        logger.warning("緊急停止処理開始...")
        self.is_running = False
        
        # 全注文キャンセル
        self.order_manager.cancel_all_orders()
        
        # 最終レポート
        print(self.portfolio.generate_report())
        
        logger.info("緊急停止完了")
    
    def stop(self):
        """ボット停止"""
        logger.info("ボット停止中...")
        self.is_running = False
        
        # 全注文キャンセル
        canceled = self.order_manager.cancel_all_orders()
        logger.info(f"キャンセル完了: {canceled} 件")
        
        # 最終レポート
        report = self.portfolio.generate_report()
        logger.info("\n" + report)
        
        logger.info("ボット停止完了")
