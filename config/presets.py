"""グリッド取引プリセット設定

ファイルの役割: 取引ペアごとに最適化されたプリセット設定を提供
なぜ存在するか: JPYから直接USDTを購入できない環境で、最適なペアとパラメータを
            簡単に選択できるようにするため
関連ファイル: settings.py（設定読み込み）, main.py（--preset オプション）
"""

from dataclasses import dataclass


@dataclass
class GridPreset:
    """グリッド取引プリセット"""

    name: str
    symbol: str
    description: str
    grid_count: int
    grid_range_factor: float
    investment_amount: float
    stop_loss_percentage: float
    max_drawdown_pct: float
    max_positions: int
    trading_fee_rate: float
    risk_level: str  # "low", "medium", "high"
    min_capital_usdt: float  # このプリセットに必要な最低USDT
    expected_daily_return_pct: float  # 推定日次リターン（参考値）


# ── プリセット定義 ───────────────────────────────────────────────
#
# 【前提知識】Binance.com（国際版）でのJPY → グリッド取引のルート
#
#   1. 日本の取引所（bitFlyer / Coincheck / GMO etc.）で JPY → BTC/ETH を購入
#   2. Binance.com へ BTC/ETH を送金
#   3. Binance.com で BTC/ETH → USDT に変換（スポット売却）
#   4. USDT を使ってグリッド取引を開始
#
#   ※ Binance P2P で直接 USDT を買う方法もあるが、スプレッドが広い場合がある
#   ※ Binance Japan は別プラットフォーム（API非対応の場合あり）
#
# ─────────────────────────────────────────────────────────────────

PRESETS: dict[str, GridPreset] = {
    # ── JPYダイレクト（USDT変換不要）──────────────────────────────
    "sol-jpy-micro": GridPreset(
        name="SOL/JPY 小額向け",
        symbol="SOLJPY",
        description=(
            "SOL/JPYダイレクト。USDT変換なしでJPYから直接取引。"
            "Binance P2PまたはFiat入金でJPYを入金してすぐ開始。"
            "最小1,500JPYからP2Pで入金可能。"
        ),
        grid_count=5,
        grid_range_factor=0.08,
        investment_amount=5000,      # 5,000 JPY
        stop_loss_percentage=10.0,
        max_drawdown_pct=15.0,
        max_positions=3,
        trading_fee_rate=0.001,
        risk_level="medium",
        min_capital_usdt=5000,       # in JPY for JPY pairs
        expected_daily_return_pct=0.20,
    ),
    "sol-jpy-standard": GridPreset(
        name="SOL/JPY 標準",
        symbol="SOLJPY",
        description=(
            "SOL/JPY 標準設定。バランスの取れたグリッド数とレンジ。"
            "20,000JPYの資金で月1,500-2,300JPYの利益を推定。"
            "USDTへの変換不要。P2Pで銀行送金→JPY入金→即開始。"
        ),
        grid_count=6,
        grid_range_factor=0.08,
        investment_amount=20000,     # 20,000 JPY
        stop_loss_percentage=12.0,
        max_drawdown_pct=18.0,
        max_positions=4,
        trading_fee_rate=0.001,
        risk_level="medium",
        min_capital_usdt=10000,
        expected_daily_return_pct=0.25,
    ),
    "sol-jpy-rich": GridPreset(
        name="SOL/JPY 本格運用",
        symbol="SOLJPY",
        description=(
            "SOL/JPY 本格運用設定。50,000JPYで月3,700-5,800JPY推定。"
            "P2PまたはFiat入金でJPYをチャージ。"
            "グリッド8本で取引頻度を最大化。"
        ),
        grid_count=8,
        grid_range_factor=0.08,
        investment_amount=50000,     # 50,000 JPY
        stop_loss_percentage=10.0,
        max_drawdown_pct=15.0,
        max_positions=5,
        trading_fee_rate=0.001,
        risk_level="medium",
        min_capital_usdt=30000,
        expected_daily_return_pct=0.20,
    ),

    # ── 安定重視（低リスク）────────────────────────────────────────
    "eth-conservative": GridPreset(
        name="ETH コンサバティブ",
        symbol="ETHUSDT",
        description=(
            "イーサリアム・低リスク設定。ボラティリティが適度で流動性が高く、"
            "グリッド取引に最も適したペア。少ないグリッド数で確実な利益を狙う。"
        ),
        grid_count=6,
        grid_range_factor=0.06,
        investment_amount=300,
        stop_loss_percentage=8.0,
        max_drawdown_pct=12.0,
        max_positions=4,
        trading_fee_rate=0.001,
        risk_level="low",
        min_capital_usdt=100,
        expected_daily_return_pct=0.15,
    ),
    "bnb-conservative": GridPreset(
        name="BNB コンサバティブ",
        symbol="BNBUSDT",
        description=(
            "BNB・低リスク設定。Binanceエコシステムトークンは一定の需要があり、"
            "レンジ相場になりやすい。手数料をBNBで払うとさらに有利。"
        ),
        grid_count=6,
        grid_range_factor=0.06,
        investment_amount=300,
        stop_loss_percentage=8.0,
        max_drawdown_pct=12.0,
        max_positions=4,
        trading_fee_rate=0.00075,  # BNB支払いで割引
        risk_level="low",
        min_capital_usdt=100,
        expected_daily_return_pct=0.15,
    ),

    # ── バランス型（中リスク）──────────────────────────────────────
    "eth-balanced": GridPreset(
        name="ETH バランス",
        symbol="ETHUSDT",
        description=(
            "イーサリアム・バランス設定。グリッド数を増やして取引頻度を上げ、"
            "利益機会を最大化する。200-500USDTの資金に最適。"
        ),
        grid_count=10,
        grid_range_factor=0.08,
        investment_amount=500,
        stop_loss_percentage=10.0,
        max_drawdown_pct=15.0,
        max_positions=5,
        trading_fee_rate=0.001,
        risk_level="medium",
        min_capital_usdt=200,
        expected_daily_return_pct=0.25,
    ),
    "sol-balanced": GridPreset(
        name="SOL バランス",
        symbol="SOLUSDT",
        description=(
            "Solana・バランス設定。ETHよりボラティリティが高く、"
            "グリッド利益が大きくなる可能性がある。価格変動に注意。"
        ),
        grid_count=8,
        grid_range_factor=0.10,
        investment_amount=400,
        stop_loss_percentage=12.0,
        max_drawdown_pct=18.0,
        max_positions=5,
        trading_fee_rate=0.001,
        risk_level="medium",
        min_capital_usdt=150,
        expected_daily_return_pct=0.30,
    ),
    "bnb-balanced": GridPreset(
        name="BNB バランス",
        symbol="BNBUSDT",
        description=(
            "BNB・バランス設定。レンジ相場で安定しつつ、適度なグリッド数で"
            "バランスの取れた利益を狙う。"
        ),
        grid_count=8,
        grid_range_factor=0.08,
        investment_amount=400,
        stop_loss_percentage=10.0,
        max_drawdown_pct=15.0,
        max_positions=5,
        trading_fee_rate=0.00075,
        risk_level="medium",
        min_capital_usdt=150,
        expected_daily_return_pct=0.20,
    ),

    # ── 積極型（高リスク・高リターン）────────────────────────────
    "sol-aggressive": GridPreset(
        name="SOL アグレッシブ",
        symbol="SOLUSDT",
        description=(
            "Solana・積極設定。広いレンジと多いグリッド数で高ボラティリティを"
            "利益に変える。損切りを広めに設定。上級者向け。"
        ),
        grid_count=12,
        grid_range_factor=0.12,
        investment_amount=500,
        stop_loss_percentage=15.0,
        max_drawdown_pct=22.0,
        max_positions=6,
        trading_fee_rate=0.001,
        risk_level="high",
        min_capital_usdt=200,
        expected_daily_return_pct=0.45,
    ),
    "doge-aggressive": GridPreset(
        name="DOGE アグレッシブ",
        symbol="DOGEUSDT",
        description=(
            "Dogecoin・積極設定。価格が低くボラティリティが高いため、"
            "グリッド取引の機会が多い。ただし急落リスクに注意。"
        ),
        grid_count=12,
        grid_range_factor=0.10,
        investment_amount=300,
        stop_loss_percentage=12.0,
        max_drawdown_pct=20.0,
        max_positions=6,
        trading_fee_rate=0.001,
        risk_level="high",
        min_capital_usdt=100,
        expected_daily_return_pct=0.40,
    ),

    # ── 小額向け（100USDT以下）────────────────────────────────────
    "xrp-micro": GridPreset(
        name="XRP 小額向け",
        symbol="XRPUSDT",
        description=(
            "XRP・小額設定。最低資金でグリッド取引を体験できる。"
            "XRPは単価が低く、少額でも十分な数量を取引可能。"
        ),
        grid_count=6,
        grid_range_factor=0.08,
        investment_amount=50,
        stop_loss_percentage=10.0,
        max_drawdown_pct=15.0,
        max_positions=3,
        trading_fee_rate=0.001,
        risk_level="low",
        min_capital_usdt=30,
        expected_daily_return_pct=0.10,
    ),
    "doge-micro": GridPreset(
        name="DOGE 小額向け",
        symbol="DOGEUSDT",
        description=(
            "DOGE・小額設定。非常に低い単価で、最小投資額から始められる。"
            "グリッド取引の仕組みを学ぶのに最適。"
        ),
        grid_count=5,
        grid_range_factor=0.08,
        investment_amount=50,
        stop_loss_percentage=10.0,
        max_drawdown_pct=15.0,
        max_positions=3,
        trading_fee_rate=0.001,
        risk_level="medium",
        min_capital_usdt=30,
        expected_daily_return_pct=0.15,
    ),

    # ── 大口向け（1000USDT以上）───────────────────────────────────
    "btc-whale": GridPreset(
        name="BTC 大口向け",
        symbol="BTCUSDT",
        description=(
            "Bitcoin・大口設定。高い流動性と安定した値動きで、"
            "大きな資金を安全に運用する。グリッド間隔が広く利益も大きい。"
        ),
        grid_count=8,
        grid_range_factor=0.06,
        investment_amount=2000,
        stop_loss_percentage=6.0,
        max_drawdown_pct=10.0,
        max_positions=5,
        trading_fee_rate=0.001,
        risk_level="low",
        min_capital_usdt=1000,
        expected_daily_return_pct=0.10,
    ),
    "eth-whale": GridPreset(
        name="ETH 大口向け",
        symbol="ETHUSDT",
        description=(
            "Ethereum・大口設定。多数のグリッドで細かく利益を積み上げる。"
            "流動性が高く大きな注文でもスリッページが少ない。"
        ),
        grid_count=15,
        grid_range_factor=0.08,
        investment_amount=2000,
        stop_loss_percentage=8.0,
        max_drawdown_pct=12.0,
        max_positions=7,
        trading_fee_rate=0.001,
        risk_level="low",
        min_capital_usdt=1000,
        expected_daily_return_pct=0.20,
    ),
}

# ── マルチペア推奨構成 ────────────────────────────────────────────
#
# 複数ペアを同時稼働してリスク分散する推奨構成
# python main.py --multi ETHUSDT,SOLUSDT,XRPUSDT
#

MULTI_PRESETS: dict[str, dict] = {
    "balanced-3": {
        "name": "3ペア分散（バランス）",
        "symbols": ["ETHUSDT", "SOLUSDT", "XRPUSDT"],
        "description": "大手3銘柄に分散。リスクを抑えつつ安定運用。",
        "total_investment_usdt": 600,
        "allocation": {"ETHUSDT": 250, "SOLUSDT": 200, "XRPUSDT": 150},
    },
    "aggressive-3": {
        "name": "3ペア分散（積極）",
        "symbols": ["ETHUSDT", "SOLUSDT", "DOGEUSDT"],
        "description": "高ボラティリティ銘柄を混ぜてリターンを狙う。",
        "total_investment_usdt": 600,
        "allocation": {"ETHUSDT": 200, "SOLUSDT": 200, "DOGEUSDT": 200},
    },
    "safe-2": {
        "name": "2ペア分散（安全）",
        "symbols": ["ETHUSDT", "BNBUSDT"],
        "description": "最も流動性の高い2銘柄。初心者向け。",
        "total_investment_usdt": 400,
        "allocation": {"ETHUSDT": 250, "BNBUSDT": 150},
    },
}


def get_preset(name: str) -> GridPreset | None:
    """プリセット名から設定を取得"""
    return PRESETS.get(name)


def list_presets() -> list[GridPreset]:
    """全プリセットの一覧を返す"""
    return list(PRESETS.values())


def list_presets_by_risk(risk_level: str) -> list[GridPreset]:
    """リスクレベルで絞り込む"""
    return [p for p in PRESETS.values() if p.risk_level == risk_level]


def recommend_for_capital(capital_usdt: float) -> list[GridPreset]:
    """資金額に基づいて推奨プリセットを返す"""
    suitable = []
    for preset in PRESETS.values():
        if capital_usdt >= preset.min_capital_usdt:
            suitable.append(preset)
    # 資金に近い順（投資効率が良い順）にソート
    suitable.sort(key=lambda p: abs(p.investment_amount - capital_usdt))
    return suitable


def preset_to_env(preset: GridPreset) -> dict[str, str]:
    """プリセットを.env用の辞書に変換"""
    return {
        "TRADING_SYMBOL": preset.symbol,
        "GRID_COUNT": str(preset.grid_count),
        "GRID_RANGE_FACTOR": str(preset.grid_range_factor),
        "INVESTMENT_AMOUNT": str(preset.investment_amount),
        "STOP_LOSS_PERCENTAGE": str(preset.stop_loss_percentage),
        "MAX_DRAWDOWN_PCT": str(preset.max_drawdown_pct),
        "MAX_POSITIONS": str(preset.max_positions),
        "TRADING_FEE_RATE": str(preset.trading_fee_rate),
    }
