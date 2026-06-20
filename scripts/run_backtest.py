"""
TODO: cargar historico con backtesting/data_loader.py, correr
backtesting/backtester.py con strategy/my_strategy.py, e imprimir metricas.
"""
from backtesting.backtester import Backtester
from strategy.my_strategy import MyStrategy
from backtesting.data_loader import load_from_csv


def main():
    quotes = load_from_csv("data/mnq_historico.csv")
    backtester = Backtester(MyStrategy())
    trades = backtester.run(quotes)
    print(f"Trades simulados: {len(trades)}")


if __name__ == "__main__":
    main()
