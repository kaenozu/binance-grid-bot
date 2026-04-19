    def _restore_state(self):
        try:
            grids_data = persistence.load_grid_states(self.symbol)
            if grids_data:
                from src.grid_strategy import GridLevel
                self.strategy.grids = [GridLevel(**g) if isinstance(g, dict) else g for g in grids_data]
            stats = persistence.load_portfolio_stats()
            if stats:
                from src.portfolio import PortfolioStats
                self.portfolio.stats = PortfolioStats(**stats) if isinstance(stats, dict) else stats
        except: pass
