"""GridBot 統合テスト"""

from unittest.mock import MagicMock, patch

from src.grid_strategy import GridStrategy
from tests.conftest import BASE_PRICE, LOWER_PRICE, UPPER_PRICE


def test_bot_initialization_sets_price(mock_settings):
    mock_client = MagicMock()
    mock_client.get_symbol_price.return_value = BASE_PRICE
    mock_client.get_account_balance.return_value = {
        "USDT": {"free": 10000.0, "locked": 0.0},
    }

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

                        mock_client.get_symbol_price.assert_called_once_with("BTCUSDT")
                        assert bot.is_running is False
                        assert bot.consecutive_errors == 0


def test_tick_processes_fills():
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
    bot._last_status_time = 0.0

    bot._tick()
    mock_client.get_symbol_price.assert_called()
    mock_om.check_order_fills.assert_called_once()


def test_tick_halts_on_stop_loss():
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
    bot._last_status_time = 0.0
    bot._last_persist_time = 0.0
    bot._last_detail_time = 0.0
    bot.current_price = BASE_PRICE
    mock_client.get_symbol_price.return_value = BASE_PRICE
    bot._close_open_positions = MagicMock()
    bot._persist_state = MagicMock()

    def fake_emergency_stop(self):
        self.is_running = False

    with patch.object(GridBot, "_emergency_stop", fake_emergency_stop):
        bot._tick()
    assert bot.is_running is False


def test_handle_grid_shift_preserves_filled_positions():
    strategy = GridStrategy(
        symbol="BTCUSDT",
        current_price=BASE_PRICE,
        lower_price=LOWER_PRICE,
        upper_price=UPPER_PRICE,
        grid_count=10,
        investment_amount=1000.0,
    )

    spacing = strategy.grid_spacing
    for i in [0, 2, 4]:
        strategy.grids[i].position_filled = True

    # シフト後の価格: +20%（本番で起こり得る大幅シフト）
    shift_price = BASE_PRICE * 1.2

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

    bot._handle_grid_shift()

    filled_after = [g for g in bot.strategy.grids if g.position_filled]
    assert len(filled_after) == 3
    original_prices = [
        LOWER_PRICE + spacing * 0,
        LOWER_PRICE + spacing * 2,
        LOWER_PRICE + spacing * 4,
    ]
    for filled_grid in filled_after:
        closest = min(original_prices, key=lambda p: abs(p - filled_grid.buy_price))
        assert abs(filled_grid.buy_price - closest) <= spacing
