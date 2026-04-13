"""
ファイルパス: src/backtest.py
概要: バックテスト機能
説明: 過去の価格データを使ってグリッド戦略をシミュレーション
関連ファイル: src/grid_strategy.py, src/portfolio.py, config/settings.py
"""

import time
from datetime import datetime
from typing import Optional

import requests
from src.grid_strategy import GridStrategy
from src.portfolio import Portfolio, Trade
from utils.logger import setup_logger

logger = setup_logger("backtest")


class BacktestDataFetcher:
    """過去の価格データを取得するクラス"""
    
    BINANCE_KLINE_URL = "https://api.binance.com/api/v3/klines"
    
    @classmethod
    def fetch_klines(cls, symbol: str, interval: str = "1h", limit: int = 500) -> list[dict]:
        """K線データを取得
        
        Args:
            symbol: 取引ペア
            interval: 時間足 (1m, 5m, 15m, 1h, 4h, 1d)
            limit: 取得件数（最大1000）
            
        Returns:
            K線データのリスト
        """
        params = {
            "symbol": symbol,
            "interval": interval,
            "limit": min(limit, 1000)
        }
        
        try:
            response = requests.get(cls.BINANCE_KLINE_URL, params=params, timeout=10)
            response.raise_for_status()
            data = response.json()
            
            klines = []
            for k in data:
                klines.append({
                    "open_time": datetime.fromtimestamp(k[0] / 1000),
                    "open": float(k[1]),
                    "high": float(k[2]),
                    "low": float(k[3]),
                    "close": float(k[4]),
                    "volume": float(k[5]),
                    "close_time": datetime.fromtimestamp(k[6] / 1000),
                })
            
            return klines
            
        except requests.exceptions.RequestException as e:
            logger.error(f"K線データ取得失敗: {e}")
            return []


class BacktestEngine:
    """バックテストエンジン"""
    
    def __init__(self, symbol: str, investment_amount: float,
                 grid_count: int, lower_price: Optional[float] = None,
                 upper_price: Optional[float] = None,
                 stop_loss_percent: float = 5.0):
        """
        Args:
            symbol: 取引ペア
            investment_amount: 投資額
            grid_count: グリッド数
            lower_price: グリッド下限（Noneで自動）
            upper_price: グリッド上限（Noneで自動）
            stop_loss_percent: 損切り割合（%）
        """
        self.symbol = symbol
        self.investment_amount = investment_amount
        self.grid_count = grid_count
        self.lower_price = lower_price
        self.upper_price = upper_price
        self.stop_loss_percent = stop_loss_percent
        
        self.strategy: Optional[GridStrategy] = None
        self.portfolio: Optional[Portfolio] = None
        self.buy_orders: dict[int, float] = {}  # grid_level -> buy_price
        self.positions: dict[int, float] = {}  # grid_level -> quantity
        
        # 統計
        self.total_trades = 0
        self.total_profit = 0.0
        self.max_drawdown = 0.0
        self.stop_loss_triggered = False
    
    def run(self, klines: list[dict]) -> dict:
        """バックテストを実行
        
        Args:
            klines: K線データのリスト
            
        Returns:
            テスト結果
        """
        if not klines:
            logger.error("K線データが空です")
            return {}
        
        # 初期価格で戦略を設定
        initial_price = klines[0]["close"]
        
        if self.lower_price and self.upper_price:
            lower = self.lower_price
            upper = self.upper_price
        else:
            lower = initial_price * 0.85
            upper = initial_price * 1.15
        
        self.strategy = GridStrategy(
            symbol=self.symbol,
            current_price=initial_price,
            lower_price=lower,
            upper_price=upper,
            grid_count=self.grid_count,
            investment_amount=self.investment_amount
        )
        
        # ポートフォリオ初期化（モック）
        self.portfolio = Portfolio.__new__(Portfolio)
        self.portfolio.trades = []
        self.portfolio.stats = type('obj', (object,), {
            'initial_balance': self.investment_amount,
            'current_balance': self.investment_amount,
            'total_profit': 0.0,
            'realized_profit': 0.0,
            'unrealized_profit': 0.0,
            'total_trades': 0,
            'winning_trades': 0,
            'losing_trades': 0,
            'win_rate': 0.0,
            'avg_profit_per_trade': 0.0,
            'start_time': datetime.now(),
            'last_update': datetime.now(),
        })()
        
        # 初期注文配置
        self._place_initial_orders(initial_price)
        
        # 価格推移をシミュレーション
        peak_value = self.investment_amount
        
        for i, kline in enumerate(klines[1:], 1):
            current_price = kline["close"]
            self.strategy.update_current_price(current_price)
            
            # 損切りチェック
            entry_price = klines[0]["close"]
            if current_price <= entry_price * (1 - self.stop_loss_percent / 100):
                self.stop_loss_triggered = True
                logger.info(f"損切り発動: {i}番目のK線 @ {current_price:.2f}")
                break
            
            # グリッド内かチェック
            if not self.strategy.is_within_grid_range(current_price):
                continue
            
            # 約定チェック（簡易版：グリッド価格を通過したら約定）
            self._check_fills(current_price, kline)
            
            # 資産価値計算
            current_value = self._calculate_portfolio_value(current_price)
            if current_value > peak_value:
                peak_value = current_value
            
            # ドローダウン
            if peak_value > 0:
                drawdown = (peak_value - current_value) / peak_value * 100
                if drawdown > self.max_drawdown:
                    self.max_drawdown = drawdown
        
        return self._generate_report(klines)
    
    def _place_initial_orders(self, current_price: float):
        """初期注文を配置"""
        for grid in self.strategy.get_active_buy_grids():
            # 買い注文を記録（価格のみ）
            self.buy_orders[grid.level] = grid.buy_price
    
    def _check_fills(self, current_price: float, kline: dict):
        """約定をチェック"""
        # 簡易版：現在価格がグリッド価格をまたいだら約定
        for grid in self.strategy.grids:
            # 買い注文の約定チェック
            if grid.level in self.buy_orders and grid.level not in self.positions:
                if current_price <= grid.buy_price:
                    # 買い約定
                    quantity = self.strategy.get_order_quantity(
                        grid.buy_price, 0.00001, 0.00001
                    )
                    self.positions[grid.level] = quantity
                    logger.debug(f"買い約定: グリッド {grid.level} @ {grid.buy_price:.2f}")
            
            # 売り注文の約定チェック
            if grid.level in self.positions:
                buy_price = self.buy_orders.get(grid.level, grid.buy_price)
                if grid.sell_price and current_price >= grid.sell_price:
                    # 売り約定
                    quantity = self.positions.pop(grid.level)
                    profit = (grid.sell_price - buy_price) * quantity
                    self.total_profit += profit
                    self.total_trades += 1
                    
                    # ポジション解消後、再度買い注文を配置
                    del self.buy_orders[grid.level]
                    self.buy_orders[grid.level] = grid.buy_price
                    
                    logger.debug(f"売り約定: グリッド {grid.level} @ {grid.sell_price:.2f}, 利益={profit:.2f}")
    
    def _calculate_portfolio_value(self, current_price: float) -> float:
        """ポートフォリオ価値を計算"""
        cash = self.investment_amount
        
        # 約定済みの買い注文に使った資金を差し引き
        for level, qty in self.positions.items():
            buy_price = self.buy_orders.get(level, 0)
            cash -= buy_price * qty
        
        # BTCの価値
        btc_value = sum(self.positions.values()) * current_price
        
        return cash + btc_value + self.total_profit
    
    def _generate_report(self, klines: list[dict]) -> dict:
        """レポートを生成"""
        start_price = klines[0]["close"]
        end_price = klines[-1]["close"]
        price_change = (end_price - start_price) / start_price * 100
        
        total_value = self.investment_amount + self.total_profit
        roi = (total_value - self.investment_amount) / self.investment_amount * 100
        
        report = {
            "symbol": self.symbol,
            "period": f"{klines[0]['open_time']} ~ {klines[-1]['open_time']}",
            "kline_count": len(klines),
            "start_price": start_price,
            "end_price": end_price,
            "price_change_percent": price_change,
            "grid_count": self.grid_count,
            "grid_range": f"{self.strategy.lower_price:.2f} - {self.strategy.upper_price:.2f}",
            "total_trades": self.total_trades,
            "total_profit": self.total_profit,
            "roi_percent": roi,
            "max_drawdown_percent": self.max_drawdown,
            "stop_loss_triggered": self.stop_loss_triggered,
            "avg_profit_per_trade": self.total_profit / self.total_trades if self.total_trades > 0 else 0,
        }
        
        return report
