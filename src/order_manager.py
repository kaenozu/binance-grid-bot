"""
ファイルパス: src/order_manager.py
概要: 注文管理
説明: グリッド注文の配置・監視・キャンセル・再配置を管理
関連ファイル: src/binance_client.py, src/grid_strategy.py, src/portfolio.py
"""

import time
from typing import Optional

from src.binance_client import BinanceClient
from src.grid_strategy import GridStrategy, GridLevel
from utils.logger import setup_logger

logger = setup_logger("order_manager")


class OrderManager:
    """注文管理クラス"""
    
    def __init__(self, client: BinanceClient, strategy: GridStrategy):
        self.client = client
        self.strategy = strategy
        self.active_orders: dict[int, dict] = {}  # order_id -> order_info
        
        logger.info("注文マネージャー初期化")
    
    def place_grid_orders(self) -> dict:
        """グリッド注文を一括配置
        
        Returns:
            配置結果 {"placed": 数, "errors": エラーリスト}
        """
        symbol_info = self.client.get_symbol_info(self.strategy.symbol)
        if not symbol_info:
            logger.error(f"シンボル情報取得失敗: {self.strategy.symbol}")
            return {"placed": 0, "errors": ["シンボル情報取得失敗"]}
        
        placed_count = 0
        errors = []
        
        # 買い注文を配置（現在価格より下のグリッド）
        for grid in self.strategy.get_active_buy_grids():
            if grid.position_filled:
                continue  # すでにポジションあり
            
            try:
                quantity = self.strategy.get_order_quantity(
                    grid.buy_price,
                    symbol_info["min_qty"],
                    symbol_info["step_size"]
                )
                
                if quantity <= 0:
                    logger.warning(f"グリッド {grid.level}: 無効な数量 {quantity}")
                    continue
                
                # 価格精度に合わせる
                tick_size = symbol_info["tick_size"]
                adjusted_price = round(grid.buy_price / tick_size) * tick_size
                
                order = self.client.place_order(
                    symbol=self.strategy.symbol,
                    side="BUY",
                    quantity=quantity,
                    price=adjusted_price
                )
                
                self.active_orders[order["orderId"]] = {
                    "grid_level": grid.level,
                    "side": "BUY",
                    "price": float(order["price"]),
                    "quantity": float(order["origQty"]),
                    "status": order["status"]
                }
                
                if order["status"] == "FILLED":
                    # すぐに約定した場合
                    self.strategy.mark_position_filled(grid.level, order["orderId"])
                    logger.info(f"グリッド {grid.level}: 即約定 @ {adjusted_price}")
                else:
                    self.strategy.grids[grid.level].buy_order_id = order["orderId"]
                    logger.info(f"グリッド {grid.level}: 買い注文配置 @ {adjusted_price}, qty={quantity}")
                
                placed_count += 1
                
            except Exception as e:
                error_msg = f"グリッド {grid.level} 買い注文失敗: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        # 売り注文を配置（ポジション持ちのグリッド）
        for grid in self.strategy.get_active_sell_grids():
            try:
                # 数量は買い注文と同じ
                buy_order_id = grid.buy_order_id
                if buy_order_id and buy_order_id in self.active_orders:
                    quantity = self.active_orders[buy_order_id]["quantity"]
                else:
                    # 数量を再計算
                    quantity = self.strategy.get_order_quantity(
                        grid.buy_price,
                        symbol_info["min_qty"],
                        symbol_info["step_size"]
                    )
                
                if quantity <= 0:
                    continue
                
                # 売り価格
                tick_size = symbol_info["tick_size"]
                adjusted_price = round(grid.sell_price / tick_size) * tick_size
                
                order = self.client.place_order(
                    symbol=self.strategy.symbol,
                    side="SELL",
                    quantity=quantity,
                    price=adjusted_price
                )
                
                self.active_orders[order["orderId"]] = {
                    "grid_level": grid.level,
                    "side": "SELL",
                    "price": float(order["price"]),
                    "quantity": float(order["origQty"]),
                    "status": order["status"]
                }
                
                if order["status"] == "FILLED":
                    self.strategy.mark_position_closed(grid.level, order["orderId"])
                    logger.info(f"グリッド {grid.level}: 売り即約定 @ {adjusted_price}")
                else:
                    self.strategy.grids[grid.level].sell_order_id = order["orderId"]
                    logger.info(f"グリッド {grid.level}: 売り注文配置 @ {adjusted_price}, qty={quantity}")
                
                placed_count += 1
                
            except Exception as e:
                error_msg = f"グリッド {grid.level} 売り注文失敗: {e}"
                logger.error(error_msg)
                errors.append(error_msg)
        
        logger.info(f"注文配置完了: {placed_count} 件, エラー: {len(errors)} 件")
        return {"placed": placed_count, "errors": errors}
    
    def check_order_fills(self) -> list[dict]:
        """約定済み注文をチェックし、新規約定があれば処理
        
        Returns:
            新規約定リスト
        """
        new_fills = []
        
        for order_id, order_info in list(self.active_orders.items()):
            if order_info["status"] == "FILLED":
                continue
            
            try:
                order = self.client.get_order(
                    self.strategy.symbol,
                    order_id
                )
                
                if order["status"] == "FILLED":
                    order_info["status"] = "FILLED"
                    grid_level = order_info["grid_level"]
                    executed_qty = float(order["executedQty"])
                    
                    if order_info["side"] == "BUY":
                        # 買い約定 → ポジション持ち
                        self.strategy.mark_position_filled(grid_level, order_id)
                        logger.info(f"グリッド {grid_level}: 買い約定完了 @ {float(order['price'])}")
                        new_fills.append({
                            "grid": grid_level,
                            "side": "BUY",
                            "price": float(order["price"]),
                            "quantity": executed_qty,
                            "order_id": order_id
                        })
                        
                    elif order_info["side"] == "SELL":
                        # 売り約定 → ポジション解消
                        self.strategy.mark_position_closed(grid_level, order_id)
                        logger.info(f"グリッド {grid_level}: 売り約定完了 @ {float(order['price'])}")
                        new_fills.append({
                            "grid": grid_level,
                            "side": "SELL",
                            "price": float(order["price"]),
                            "quantity": executed_qty,
                            "order_id": order_id
                        })
                
            except Exception as e:
                logger.error(f"注文状態確認失敗 order_id={order_id}: {e}")
        
        return new_fills
    
    def cancel_all_orders(self) -> int:
        """すべてのアクティブ注文をキャンセル
        
        Returns:
            キャンセル件数
        """
        open_orders = self.client.get_open_orders(self.strategy.symbol)
        canceled_count = 0
        
        for order in open_orders:
            try:
                self.client.cancel_order(self.strategy.symbol, order["orderId"])
                if order["orderId"] in self.active_orders:
                    del self.active_orders[order["orderId"]]
                canceled_count += 1
                logger.info(f"注文キャンセル: {order['orderId']}")
            except Exception as e:
                logger.error(f"注文キャンセル失敗: {e}")
        
        logger.info(f"注文キャンセル完了: {canceled_count} 件")
        return canceled_count
    
    def cleanup_filled_orders(self):
        """約定済み注文をクリーンアップ"""
        filled_ids = [oid for oid, info in self.active_orders.items() if info["status"] == "FILLED"]
        for oid in filled_ids:
            del self.active_orders[oid]
        
        if filled_ids:
            logger.info(f"約定済み注文クリーンアップ: {len(filled_ids)} 件")
    
    def get_active_order_count(self) -> int:
        """アクティブ注文数を取得"""
        return len([o for o in self.active_orders.values() if o["status"] != "FILLED"])
