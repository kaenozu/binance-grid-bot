"""
ファイルパス: src/portfolio.py
概要: 資産管理・PnL計算
説明: 取引履歴の追跡、損益計算、資産状況レポートを提供
関連ファイル: src/binance_client.py, src/risk_manager.py, src/bot.py
"""

from datetime import datetime
from dataclasses import dataclass, field
from typing import Optional

from src.binance_client import BinanceClient
from utils.logger import setup_logger

logger = setup_logger("portfolio")


@dataclass
class Trade:
    """取引記録"""
    timestamp: datetime
    symbol: str
    side: str  # BUY or SELL
    price: float
    quantity: float
    order_id: int
    grid_level: int
    profit: float = 0.0  # 売り約定時の利益


@dataclass
class PortfolioStats:
    """ポートフォリオ統計"""
    initial_balance: float = 0.0
    current_balance: float = 0.0
    total_profit: float = 0.0
    realized_profit: float = 0.0
    unrealized_profit: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    win_rate: float = 0.0
    avg_profit_per_trade: float = 0.0
    start_time: Optional[datetime] = None
    last_update: Optional[datetime] = None


class Portfolio:
    """資産管理クラス"""
    
    def __init__(self, client: BinanceClient, symbol: str, quote_asset: str = "USDT"):
        """
        Args:
            client: Binance API クライアント
            symbol: 取引ペア
            quote_asset: 証拠金資産（デフォルト: USDT）
        """
        self.client = client
        self.symbol = symbol
        self.quote_asset = quote_asset
        
        self.trades: list[Trade] = []
        self.stats = PortfolioStats()
        self.stats.start_time = datetime.now()
        self.stats.last_update = datetime.now()
        
        # 初期残高取得
        self._update_balance()
        self.stats.initial_balance = self.stats.current_balance
        
        logger.info(f"ポートフォリオ初期化: 初期残高={self.stats.initial_balance:.2f} {quote_asset}")
    
    def _update_balance(self):
        """残高を更新"""
        try:
            balances = self.client.get_account_balance()
            if self.quote_asset in balances:
                balance_info = balances[self.quote_asset]
                self.stats.current_balance = balance_info["free"] + balance_info["locked"]
        except Exception as e:
            logger.error(f"残高取得失敗: {e}")
    
    def record_trade(self, side: str, price: float, quantity: float, 
                    order_id: int, grid_level: int):
        """取引を記録
        
        Args:
            side: BUY or SELL
            price: 約定価格
            quantity: 数量
            order_id: 注文ID
            grid_level: グリッドレベル
        """
        trade = Trade(
            timestamp=datetime.now(),
            symbol=self.symbol,
            side=side,
            price=price,
            quantity=quantity,
            order_id=order_id,
            grid_level=grid_level
        )
        
        self.trades.append(trade)
        self.stats.total_trades += 1
        self.stats.last_update = datetime.now()
        
        # 売り約定時の利益計算
        if side == "SELL":
            # 対応する買い注文を探す
            buy_trade = self._find_matching_buy_trade(grid_level)
            if buy_trade:
                profit = (price - buy_trade.price) * quantity
                trade.profit = profit
                self.stats.realized_profit += profit
                
                if profit > 0:
                    self.stats.winning_trades += 1
                else:
                    self.stats.losing_trades += 1
                
                # 統計更新
                settled_trades = self.stats.winning_trades + self.stats.losing_trades
                if settled_trades > 0:
                    self.stats.win_rate = (self.stats.winning_trades / settled_trades) * 100
                self.stats.avg_profit_per_trade = self.stats.realized_profit / self.stats.total_trades
                
                logger.info(f"取引記録: グリッド {grid_level}, 利益={profit:.2f}")
        
        logger.info(f"取引記録追加: {side} {quantity} @ {price}")
    
    def _find_matching_buy_trade(self, grid_level: int) -> Optional[Trade]:
        """対応する買い注文を探す"""
        for trade in reversed(self.trades):
            if trade.side == "BUY" and trade.grid_level == grid_level:
                return trade
        return None
    
    def calculate_unrealized_pnl(self, current_price: float):
        """未実現損益を計算
        
        Args:
            current_price: 現在価格
        """
        unrealized = 0.0
        
        # ポジション持ちの買い注文
        for trade in self.trades:
            if trade.side == "BUY":
                # 対応する売り注文がない場合、まだポジション持ち
                has_sell = any(
                    t.side == "SELL" and t.grid_level == trade.grid_level 
                    for t in self.trades
                )
                if not has_sell:
                    unrealized += (current_price - trade.price) * trade.quantity
        
        self.stats.unrealized_profit = unrealized
        self.stats.total_profit = self.stats.realized_profit + unrealized
    
    def get_stats(self) -> PortfolioStats:
        """統計情報を返す"""
        self._update_balance()
        return self.stats
    
    def get_trade_history(self, limit: int = 20) -> list[Trade]:
        """取引履歴を返す
        
        Args:
            limit: 取得件数（デフォルト: 20）
        """
        return self.trades[-limit:]
    
    def generate_report(self) -> str:
        """レポートを生成"""
        self._update_balance()
        
        elapsed = datetime.now() - self.stats.start_time if self.stats.start_time else None
        hours = elapsed.total_seconds() / 3600 if elapsed else 0
        
        report = f"""
===== ポートフォリオレポート =====
実行時間: {hours:.2f} 時間
初期残高: {self.stats.initial_balance:.2f} {self.quote_asset}
現在残高: {self.stats.current_balance:.2f} {self.quote_asset}
--------------------------------
実現利益: {self.stats.realized_profit:.2f} {self.quote_asset}
未実現利益: {self.stats.unrealized_profit:.2f} {self.quote_asset}
総利益: {self.stats.total_profit:.2f} {self.quote_asset}
--------------------------------
取引回数: {self.stats.total_trades}
勝率: {self.stats.win_rate:.1f}%
平均利益/取引: {self.stats.avg_profit_per_trade:.2f} {self.quote_asset}
================================
"""
        return report.strip()
