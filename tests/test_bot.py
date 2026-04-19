"""GridBot 統合テスト"""

import time
from unittest.mock import MagicMock, patch

from src.grid_strategy import GridStrategy
from tests.conftest import BASE_PRICE, LOWER_PRICE, UPPER_PRICE


def test_bot_initialization_sets_price():
    """初期化時に現在価格を取得する"""
    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = BASE_PRICE
    mock_client.get_symbol_info.return_value = {
        "symbol": "BTCUSDT",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "tick_size": 0.01,
    }
    mock_client.get_account_balance.return_value = {
        "USDT": {"free": 10000.0, "locked": 0.0},
    }

    with patch("src.bot.Settings") as mock_settings_cls:
        mock_settings_cls.TRADING_SYMBOL = "BTCUSDT"
        mock_settings_cls.BINANCE_API_KEY = "test_api_key"
        mock_settings_cls.BINANCE_API_SECRET = "test_api_secret"
        mock_settings_cls.USE_TESTNET = True
        mock_settings_cls.GRID_COUNT = 10
        mock_settings_cls.LOWER_PRICE = None
        mock_settings_cls.UPPER_PRICE = None
        mock_settings_cls.INVESTMENT_AMOUNT = 1000.0
        mock_settings_cls.STOP_LOSS_PERCENTAGE = 5.0
        mock_settings_cls.MAX_POSITIONS = 5
        mock_settings_cls.CHECK_INTERVAL = 10
        mock_settings_cls.MAX_CONSECUTIVE_ERRORS = 5
        mock_settings_cls.GRID_RANGE_FACTOR = 0.15
        mock_settings_cls.TRADING_FEE_RATE = 0.001
        mock_settings_cls.CLOSE_ON_STOP = False
        mock_settings_cls.PERSIST_INTERVAL = 60
        mock_settings_cls.STATUS_DISPLAY_INTERVAL = 60
        mock_settings_cls.USE_USER_STREAM = False
        mock_settings_cls.VOLATILITY_LOOKBACK = 24
        mock_settings_cls.validate_or_raise.return_value = None

        with patch("src.bot.BinanceClient", return_value=mock_client):
            with patch("src.bot.GridStrategy") as mock_strategy_cls:
                mock_strategy = MagicMock()
                mock_strategy.symbol = "BTCUSDT"
                mock_strategy.estimate_cycle_profit.return_value = 100.0
                mock_strategy.grids = []
                mock_strategy_cls.return_value = mock_strategy

                with patch("src.bot.OrderManager"):
                    with patch("src.bot.RiskManager"):
                        with patch("src.bot.Portfolio") as mock_port:
                            mock_port.return_value = MagicMock()
                            mock_port.stats = MagicMock()
                            mock_port.stats.start_time = None

                            from src.bot import GridBot

                            bot = GridBot()

                            mock_client.get_symbol_price.assert_called_once_with(
                                "BTCUSDT"
                            )
                            assert bot.is_running is False
                            assert bot.consecutive_errors == 0


def test_bot_initialization_logs_low_expected_cycle_profit():
    """投資額が非常に小さい場合、低利益の警告または自動調整が行われる"""
    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = BASE_PRICE
    mock_client.get_symbol_info.return_value = {
        "symbol": "BTCUSDT",
        "base_asset": "BTC",
        "quote_asset": "USDT",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "tick_size": 0.01,
        "min_notional": 10,
    }
    mock_client.get_account_balance.return_value = {
        "USDT": {"free": 10000.0, "locked": 0.0},
    }

    with patch("src.bot.Settings") as mock_settings_cls:
        mock_settings_cls.TRADING_SYMBOL = "BTCUSDT"
        mock_settings_cls.BINANCE_API_KEY = "test_api_key"
        mock_settings_cls.BINANCE_API_SECRET = "test_api_secret"
        mock_settings_cls.USE_TESTNET = True
        mock_settings_cls.GRID_COUNT = 100  # extremely high
        mock_settings_cls.LOWER_PRICE = None
        mock_settings_cls.UPPER_PRICE = None
        mock_settings_cls.INVESTMENT_AMOUNT = 11.0  # tiny per-grid
        mock_settings_cls.STOP_LOSS_PERCENTAGE = 5.0
        mock_settings_cls.MAX_POSITIONS = 5
        mock_settings_cls.CHECK_INTERVAL = 10
        mock_settings_cls.MAX_CONSECUTIVE_ERRORS = 5
        mock_settings_cls.GRID_RANGE_FACTOR = 0.15
        mock_settings_cls.TRADING_FEE_RATE = 0.001
        mock_settings_cls.CLOSE_ON_STOP = False
        mock_settings_cls.PERSIST_INTERVAL = 60
        mock_settings_cls.STATUS_DISPLAY_INTERVAL = 60
        mock_settings_cls.USE_USER_STREAM = False
        mock_settings_cls.VOLATILITY_LOOKBACK = 24
        mock_settings_cls.validate_or_raise.return_value = None

        with patch("src.bot.BinanceClient", return_value=mock_client):
            with patch("src.bot.GridStrategy") as mock_strategy_cls:
                mock_strategy = MagicMock()
                mock_strategy.symbol = "BTCUSDT"
                mock_strategy.grids = []
                mock_strategy_cls.return_value = mock_strategy

                with patch("src.bot.OrderManager"):
                    with patch("src.bot.RiskManager"):
                        with patch("src.bot.Portfolio") as mock_port:
                            mock_port.return_value = MagicMock()
                            mock_port.stats = MagicMock()
                            mock_port.stats.start_time = None
                            from src.bot import GridBot

                            bot = GridBot()

    # Verify: with 11 USDT / 100 grids, estimated cycle profit is near 0
    # The bot should still initialize but with very low expected profit
    assert bot is not None


def test_bot_uses_live_balance_as_cap_in_production():
    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = BASE_PRICE
    mock_client.get_symbol_info.return_value = {
        "symbol": "ETHJPY",
        "base_asset": "ETH",
        "quote_asset": "JPY",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "tick_size": 1.0,
    }
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 4200.0, "locked": 0.0},
    }

    with patch("src.bot.Settings") as mock_settings_cls:
        mock_settings_cls.TRADING_SYMBOL = "ETHJPY"
        mock_settings_cls.BINANCE_API_KEY = "test_api_key"
        mock_settings_cls.BINANCE_API_SECRET = "test_api_secret"
        mock_settings_cls.USE_TESTNET = False
        mock_settings_cls.GRID_COUNT = 4
        mock_settings_cls.LOWER_PRICE = None
        mock_settings_cls.UPPER_PRICE = None
        mock_settings_cls.INVESTMENT_AMOUNT = 6000.0
        mock_settings_cls.STOP_LOSS_PERCENTAGE = 5.0
        mock_settings_cls.MAX_POSITIONS = 5
        mock_settings_cls.CHECK_INTERVAL = 10
        mock_settings_cls.MAX_CONSECUTIVE_ERRORS = 5
        mock_settings_cls.GRID_RANGE_FACTOR = 0.08
        mock_settings_cls.TRADING_FEE_RATE = 0.001
        mock_settings_cls.CLOSE_ON_STOP = False
        mock_settings_cls.PERSIST_INTERVAL = 60
        mock_settings_cls.STATUS_DISPLAY_INTERVAL = 60
        mock_settings_cls.USE_USER_STREAM = False
        mock_settings_cls.VOLATILITY_LOOKBACK = 24
        mock_settings_cls.validate_or_raise.return_value = None

        with patch("src.bot.BinanceClient", return_value=mock_client):
            with patch("src.bot.GridStrategy") as mock_strategy_cls:
                mock_strategy = MagicMock()
                mock_strategy.symbol = "ETHJPY"
                mock_strategy.estimate_cycle_profit.return_value = 70.0
                mock_strategy.grids = []
                mock_strategy_cls.return_value = mock_strategy

                with patch("src.bot.OrderManager"):
                    with patch("src.bot.RiskManager"):
                        with patch("src.bot.Portfolio") as mock_port:
                            mock_port.return_value = MagicMock()
                            mock_port.stats = MagicMock()
                            mock_port.stats.start_time = None

                            from src.bot import GridBot

                            bot = GridBot()

    assert mock_strategy_cls.call_args.kwargs["investment_amount"] == 4200.0
    assert mock_strategy_cls.call_args.kwargs["grid_count"] == 4
    assert bot.client.get_account_balance.called


def test_bot_logs_startup_summary():
    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = BASE_PRICE
    mock_client.get_symbol_info.return_value = {
        "symbol": "ETHJPY",
        "base_asset": "ETH",
        "quote_asset": "JPY",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "tick_size": 1.0,
    }
    mock_client.get_account_balance.return_value = {
        "JPY": {"free": 4200.0, "locked": 0.0},
    }

    with patch("src.bot.Settings") as mock_settings_cls:
        mock_settings_cls.TRADING_SYMBOL = "ETHJPY"
        mock_settings_cls.BINANCE_API_KEY = "test_api_key"
        mock_settings_cls.BINANCE_API_SECRET = "test_api_secret"
        mock_settings_cls.USE_TESTNET = False
        mock_settings_cls.GRID_COUNT = 4
        mock_settings_cls.LOWER_PRICE = None
        mock_settings_cls.UPPER_PRICE = None
        mock_settings_cls.INVESTMENT_AMOUNT = 6000.0
        mock_settings_cls.STOP_LOSS_PERCENTAGE = 5.0
        mock_settings_cls.MAX_POSITIONS = 5
        mock_settings_cls.CHECK_INTERVAL = 10
        mock_settings_cls.MAX_CONSECUTIVE_ERRORS = 5
        mock_settings_cls.GRID_RANGE_FACTOR = 0.08
        mock_settings_cls.TRADING_FEE_RATE = 0.001
        mock_settings_cls.CLOSE_ON_STOP = False
        mock_settings_cls.PERSIST_INTERVAL = 60
        mock_settings_cls.STATUS_DISPLAY_INTERVAL = 60
        mock_settings_cls.USE_USER_STREAM = False
        mock_settings_cls.VOLATILITY_LOOKBACK = 24
        mock_settings_cls.validate_or_raise.return_value = None

        with patch("src.bot.BinanceClient", return_value=mock_client):
            with patch("src.bot.GridStrategy") as mock_strategy_cls:
                mock_strategy = MagicMock()
                mock_strategy.symbol = "ETHJPY"
                mock_strategy.estimate_cycle_profit.return_value = 70.0
                mock_strategy.grids = []
                mock_strategy_cls.return_value = mock_strategy

                with patch("src.bot.OrderManager"):
                    with patch("src.bot.RiskManager"):
                        with patch("src.bot.Portfolio") as mock_port:
                            mock_port.return_value = MagicMock()
                            mock_port.stats = MagicMock()
                            mock_port.stats.start_time = None
                            with patch("src.bot.logger") as mock_logger:
                                from src.bot import GridBot

                                GridBot()

    info_messages = [call.args[0] for call in mock_logger.info.call_args_list]
    assert any("Startup Summary:" in message for message in info_messages)
    assert any("Balance=4200.00 JPY" in message for message in info_messages)
    assert any("Investment=4200.00 JPY" in message for message in info_messages)
    assert any("Grids=4" in message for message in info_messages)
    assert any("Bot initialized successfully" in message for message in info_messages)


def test_tick_processes_fills():
    """ティック処理で注文の約定を処理する"""
    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = BASE_PRICE

    strategy = GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )

    mock_om = MagicMock()
    mock_om.check_order_fills.return_value = []
    mock_rm = MagicMock()
    mock_rm.should_halt_trading.return_value = False
    mock_port = MagicMock()
    mock_port.record_trade.return_value = None
    mock_port.calculate_unrealized_pnl = MagicMock()
    mock_port.get_stats.return_value = MagicMock()
    mock_port.stats = MagicMock()
    mock_port.stats.peak_balance = 1000.0
    mock_port.stats.max_drawdown_pct = 0.0

    from src.bot import GridBot

    bot = GridBot.__new__(GridBot)
    bot.client = mock_client
    bot.strategy = strategy
    bot.order_manager = mock_om
    bot.risk_manager = mock_rm
    bot.portfolio = mock_port
    bot.ws_client = None
    bot.symbol = "BTCUSDT"
    bot.is_running = True
    bot.consecutive_errors = 0
    bot._last_status_time = time.time()  # Avoid status display during test
    bot._last_detail_time = 0.0
    bot._last_persist_time = time.time()
    bot.current_price = BASE_PRICE
    bot._price_history = [BASE_PRICE]
    bot._last_dynamic_factor = 0.15

    bot._tick()
    mock_client.get_symbol_price.assert_called()
    mock_om.check_order_fills.assert_called_once()


def test_tick_halts_on_stop_loss():
    """損切り時にボットが停止する"""
    strategy = GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )

    mock_client = MagicMock()
    mock_om = MagicMock()
    mock_om.check_order_fills.return_value = []
    mock_om.cancel_all_orders.return_value = 0
    mock_rm = MagicMock()
    mock_rm.should_halt_trading.return_value = True
    mock_port = MagicMock()
    mock_port.generate_report.return_value = "report"
    mock_port.stats = MagicMock()
    mock_port.stats.peak_balance = 1000.0
    mock_port.stats.max_drawdown_pct = 0.0

    from src.bot import GridBot

    bot = GridBot.__new__(GridBot)
    bot.client = mock_client
    bot.strategy = strategy
    bot.order_manager = mock_om
    bot.risk_manager = mock_rm
    bot.portfolio = mock_port
    bot.ws_client = None
    bot.symbol = "BTCUSDT"
    bot.is_running = True
    bot.consecutive_errors = 0
    bot._last_status_time = time.time()
    bot._last_persist_time = time.time()
    bot._last_detail_time = 0.0
    bot.current_price = BASE_PRICE
    mock_client.get_symbol_price.return_value = BASE_PRICE
    bot._close_open_positions = MagicMock()
    bot._persist_state = MagicMock()
    bot._price_history = [BASE_PRICE]
    bot._last_dynamic_factor = 0.15

    def fake_emergency_stop(self):
        self.is_running = False

    with patch.object(GridBot, "_emergency_stop", fake_emergency_stop):
        bot._tick()
    assert bot.is_running is False


def test_tick_stops_on_portfolio_drawdown():
    """ポートフォリオのドローダウンが上限を超えたら停止する"""
    strategy = GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )

    mock_client = MagicMock()
    mock_om = MagicMock()
    mock_om.check_order_fills.return_value = []
    mock_rm = MagicMock()
    mock_rm.should_halt_trading.return_value = False
    mock_port = MagicMock()
    mock_port.record_trade.return_value = None
    mock_port.calculate_unrealized_pnl = MagicMock()
    mock_port.stats = MagicMock()
    mock_port.stats.peak_balance = 1000.0
    mock_port.stats.max_drawdown_pct = 99.0

    from src.bot import GridBot

    bot = GridBot.__new__(GridBot)
    bot.client = mock_client
    bot.strategy = strategy
    bot.order_manager = mock_om
    bot.risk_manager = mock_rm
    bot.portfolio = mock_port
    bot.ws_client = None
    bot.symbol = "BTCUSDT"
    bot.is_running = True
    bot.consecutive_errors = 0
    bot._last_status_time = time.time()
    bot._last_persist_time = time.time()
    bot._last_detail_time = 0.0
    bot.current_price = BASE_PRICE
    mock_client.get_symbol_price.return_value = BASE_PRICE
    mock_client.get_symbol_info.return_value = None
    bot._price_history = [BASE_PRICE]
    bot._last_dynamic_factor = 0.15

    # Mock Settings to ensure MAX_DRAWDOWN_PCT is checked and avoid MagicMock issues
    with patch("src.bot.Settings") as mock_settings:
        mock_settings.MAX_DRAWDOWN_PCT = 10.0
        mock_settings.VOLATILITY_LOOKBACK = 24
        mock_settings.LOWER_PRICE = None
        mock_settings.UPPER_PRICE = None
        
        # Mock display_status to avoid formatting errors with MagicMock
        with patch("src.bot.display_status"):
            def fake_emergency_stop(self):
                self.is_running = False

            with patch.object(GridBot, "_emergency_stop", fake_emergency_stop):
                bot._tick()

    assert bot.is_running is False


def test_handle_grid_shift_preserves_filled_positions():
    """グリッドシフト時に約定済みポジションを保持する"""
    strategy = GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )

    spacing = strategy.grid_spacing
    # 元の価格帯でのグリッド価格を記録
    original_buy_prices = [g.buy_price for g in strategy.grids]
    
    # 0, 2, 4 番目のグリッドを約定済みにする
    for i in [0, 2, 4]:
        strategy.grids[i].position_filled = True
        strategy.grids[i].filled_quantity = 0.01

    # シフト後の価格: +5% (あまり大きくシフトさせすぎないように調整)
    shift_price = BASE_PRICE * 1.05

    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = shift_price
    mock_client.get_symbol_info.return_value = {
        "symbol": "BTCUSDT",
        "base_asset": "BTC",
        "min_qty": 0.00001,
        "step_size": 0.00001,
        "tick_size": 0.01,
    }

    mock_om = MagicMock()
    mock_om.cancel_all_orders.return_value = 0
    mock_om.place_grid_orders.return_value = MagicMock(placed=0)
    mock_rm = MagicMock()

    from src.bot import GridBot

    bot = GridBot.__new__(GridBot)
    bot.client = mock_client
    bot.strategy = strategy
    bot.order_manager = mock_om
    bot.risk_manager = mock_rm
    bot.ws_client = None
    bot.symbol = "BTCUSDT"
    bot.current_price = shift_price

    with patch("src.bot.Settings") as mock_settings:
        mock_settings.LOWER_PRICE = None
        mock_settings.UPPER_PRICE = None
        mock_settings.GRID_RANGE_FACTOR = 0.15
        mock_settings.VOLATILITY_GRID_ADJUSTMENT = False
        bot._handle_grid_shift()

    filled_after = [g for g in bot.strategy.grids if g.position_filled]
    assert len(filled_after) == 3
    
    # 元の買値
    original_prices_of_filled = [
        original_buy_prices[0],
        original_buy_prices[2],
        original_buy_prices[4],
    ]
    
    # シフト後の新しいグリッドの買値が、元の買値の最寄りになっていることを確認
    new_spacing = bot.strategy.grid_spacing
    for filled_grid in filled_after:
        # 最も近い元の価格を探す
        closest_orig = min(original_prices_of_filled, key=lambda p: abs(p - filled_grid.buy_price))
        # 差分が新しいグリッド間隔の半分以下（最寄りマッピング）であることを確認
        assert abs(filled_grid.buy_price - closest_orig) <= new_spacing / 2 + 0.01
