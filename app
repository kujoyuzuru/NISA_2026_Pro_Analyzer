# @title
!pip install tqdm

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
from tqdm import tqdm
import sys
from IPython.display import display

class NisaAppFinalOptimized:
    def __init__(self):
        # NASDAQ主要銘柄リスト
        self.tickers = [
            "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA",
            "AVGO", "AMD", "QCOM", "INTC", "TXN", "MU", "AMAT", "LRCX", "ADI", "MRVL", "KLAC", "ARM", "SMCI",
            "ADBE", "CRM", "NFLX", "ORCL", "CSCO", "INTU", "NOW", "UBER", "ABNB", "PANW", "SNPS", "CDNS", "CRWD", "PLTR",
            "AMGN", "VRTX", "GILD", "REGN", "ISRG", "MDLZ",
            "COST", "PEP", "SBUX", "TMUS", "CMCSA", "BKNG", "MAR", "LULU", "CSX"
        ]

    def show_legal_disclaimer(self):
        print("\n" + "!"*60)
        print("【 重要：ご利用規約および免責事項 】")
        print("!"*60)
        print("1. 本システムは機関投資家向けファクター分析モデルを用いた参考情報です。")
        print("2. 投資助言ではありません。投資判断はご自身の責任で行ってください。")
        print("-" * 60)
        print(">> 上記に同意される場合は「同意」と入力してください。")
        
        user_input = input("入力欄: ")
        if user_input.strip() != "同意":
            sys.exit() 

    def analyze_stock(self, ticker):
        stock = yf.Ticker(ticker)
        try:
            info = stock.info
            current_price = info.get('currentPrice', 0)
            if current_price == 0: return None

            rev_growth = info.get('revenueGrowth')
            profit_margin = info.get('profitMargins')
            avg_volume = info.get('averageVolume', 0)
            current_volume = info.get('volume', 0)
            
            # --- スコアリング ---
            score = 0
            if rev_growth and rev_growth > 0.2: score += 30
            elif rev_growth and rev_growth > 0.1: score += 15
            
            if profit_margin and profit_margin > 0.2: score += 20
            
            vol_ratio = 0
            if avg_volume > 0: vol_ratio = current_volume / avg_volume
            if vol_ratio > 1.2: score += 20
            
            hist = stock.history(period="3mo")
            rsi = 50
            if not hist.empty:
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                if 40 <= rsi <= 60: score += 30
                if rsi > 80: score -= 20

            signal = "HOLD"
            if score >= 80: signal = "Strong Buy"
            elif score >= 60: signal = "Buy"
            elif score <= 20: signal = "SELL"

            return {
                "Ticker": ticker,
                "Name": info.get('shortName', ticker)[:10],
                "Price($)": current_price, # ここでは生の数値を持たせる
                "Score": int(score),
                "Signal": signal,
                "Growth": rev_growth if rev_growth else 0, # 数値で保持（表示時に整形）
                "Margin": profit_margin if profit_margin else 0,
                "VolRatio": vol_ratio,
                "RSI": rsi
            }
        except:
            return None

    def run_scan(self):
        self.show_legal_disclaimer()
        print(f"🔒 機関投資家グレード分析を実行中... (対象: {len(self.tickers)}銘柄)")
        results = []
        for ticker in tqdm(self.tickers):
            data = self.analyze_stock(ticker)
            if data:
                results.append(data)
        return pd.DataFrame(results)

# --- 実行部 ---
if __name__ == "__main__":
    app = NisaAppFinalOptimized()
    df = app.run_scan()
    
    # スコア順に並び替え
    df_sorted = df.sort_values('Score', ascending=False).reset_index(drop=True)
    df_sorted.index += 1 
    
    now_str = datetime.now().strftime('%Y年%m月%d日 %H時%M分')

    print("\n" + "="*80)
    print("      🇯🇵 新NISA戦略：機関投資家グレード・ダッシュボード      ")
    print("="*80)
    print(f"⏱️ ※{now_str} 時点の最新AI分析レポート")
    
    print("\n【 📊 データの見方と判断基準 】")
    print("--------------------------------------------------------------------------------")
    print("1️⃣ Score (総合スコア) : 80点以上は「最強」、60点以上は「優良」。")
    print("2️⃣ Growth (売上成長率) : +20%以上ならS級。マイナスは危険。")
    print("3️⃣ Margin (純利益率) : 20%以上なら高収益。")
    print("4️⃣ VolRatio (出来高倍率) : 1.5倍以上は大口介入の予兆。")
    print("5️⃣ RSI : 40〜60は押し目(買い場)。80以上は過熱。")
    print("--------------------------------------------------------------------------------\n")
    
    print("▼ AI分析結果一覧 (スコア順)")
    
    # ★ここが修正ポイント：表示フォーマットの強制適用
    # RSIは小数点1位、株価は2位、成長率は%表示に変換して表示
    format_dict = {
        'Price($)': '${:.2f}',   # $188.61
        'Growth': '{:.1%}',      # 25.4%
        'Margin': '{:.1%}',      # 53.0%
        'VolRatio': '{:.1f}x',   # 1.2x
        'RSI': '{:.1f}'          # 56.1
    }
    
    display(df_sorted.style.format(format_dict).background_gradient(subset=['Score'], cmap='RdYlGn', vmin=0, vmax=100))
