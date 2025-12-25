import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- ページ設定 ---
st.set_page_config(
    page_title="新NISA・米国株AI診断",
    page_icon="📈",
    layout="wide"
)

# --- スタイル調整 ---
st.markdown("""
    <style>
    .stButton>button {
        width: 100%;
        background-color: #ff4b4b;
        color: white;
        font-weight: bold;
        padding: 10px;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 銘柄リスト ---
TICKERS = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA",
    "AVGO", "AMD", "QCOM", "INTC", "TXN", "MU", "AMAT", "LRCX", "ADI", "MRVL", "KLAC", "ARM", "SMCI",
    "ADBE", "CRM", "NFLX", "ORCL", "CSCO", "INTU", "NOW", "UBER", "ABNB", "PANW", "SNPS", "CDNS", "CRWD", "PLTR",
    "AMGN", "VRTX", "GILD", "REGN", "ISRG", "MDLZ",
    "COST", "PEP", "SBUX", "TMUS", "CMCSA", "BKNG", "MAR", "LULU", "CSX"
]

# --- 分析ロジック ---
def analyze_stock(ticker):
    stock = yf.Ticker(ticker)
    try:
        info = stock.info
        current_price = info.get('currentPrice', 0)
        if current_price == 0: return None

        rev_growth = info.get('revenueGrowth', 0)
        profit_margin = info.get('profitMargins', 0)
        avg_volume = info.get('averageVolume', 0)
        current_volume = info.get('volume', 0)
        
        # スコアリング
        score = 0
        if rev_growth and rev_growth > 0.2: score += 30
        elif rev_growth and rev_growth > 0.1: score += 15
        
        if profit_margin and profit_margin > 0.2: score += 20
        
        vol_ratio = 0
        if avg_volume > 0: vol_ratio = current_volume / avg_volume
        if vol_ratio > 1.2: score += 20
        
        # テクニカル(簡易)
        hist = stock.history(period="3mo")
        rsi = 50
        if not hist.empty:
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            if loss.iloc[-1] != 0:
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
            if 40 <= rsi <= 60: score += 30
            if rsi > 80: score -= 20

        # シグナル
        signal = "HOLD"
        if score >= 80: signal = "Strong Buy"
        elif score >= 60: signal = "Buy"
        elif score <= 20: signal = "SELL"

        return {
            "Ticker": ticker,
            "Name": info.get('shortName', ticker)[:10],
            "Price": current_price,
            "Score": int(score),
            "Signal": signal,
            "Growth": rev_growth if rev_growth else 0,
            "Margin": profit_margin if profit_margin else 0,
            "VolRatio": vol_ratio,
            "RSI": rsi
        }
    except:
        return None

# --- アプリ画面の構築 ---
st.title("🇯🇵 新NISA対応：米国株AI診断")
st.caption(f"最終更新: {datetime.now().strftime('%Y/%m/%d %H:%M')}")

# 免責事項エリア
with st.expander("⚠️ ご利用規約・免責事項 (必ずお読みください)", expanded=True):
    st.markdown("""
    1. 本アプリは機関投資家向けモデルを用いた参考情報です。
    2. 投資助言ではありません。投資判断はご自身の責任で行ってください。
    3. 開発者は本アプリの使用による損害について責任を負いません。
    """)
    agree = st.checkbox("上記に同意して利用する")

if agree:
    st.write("---")
    st.info("👇 下のボタンを押すと、NASDAQ主要銘柄を一括スキャンします")
    
    if st.button("🚀 AI分析を開始する", type="primary"):
        progress_text = "米国市場のデータを取得中..."
        my_bar = st.progress(0, text=progress_text)
        
        results = []
        total = len(TICKERS)
        
        for i, ticker in enumerate(TICKERS):
            data = analyze_stock(ticker)
            if data:
                results.append(data)
            percent_complete = int((i + 1) / total * 100)
            my_bar.progress(percent_complete, text=f"分析中: {ticker} ({percent_complete}%)")
            
        my_bar.empty()
        
        if results:
            df = pd.DataFrame(results)
            df_sorted = df.sort_values('Score', ascending=False).reset_index(drop=True)
            df_sorted.index += 1
            
            st.success("✅ 分析完了！スコアランキングを表示します")
            
            st.dataframe(
                df_sorted.style.format({
                    'Price': '${:.2f}',
                    'Growth': '{:.1%}',
                    'Margin': '{:.1%}',
                    'VolRatio': '{:.1f}x',
                    'RSI': '{:.1f}'
                }).background_gradient(subset=['Score'], cmap='RdYlGn', vmin=0, vmax=100),
                use_container_width=True,
                height=600
            )
            
            st.markdown("### 📊 データの見方")
            st.info("""
            * **Score (80点~) :** 今すぐ買うべき「最強銘柄」
            * **Growth (+20%~) :** 売上が爆発的に伸びている企業
            * **VolRatio (1.5x~) :** 大口(機関投資家)が買い集めている兆候
            """)
            
else:
    st.warning("☝️ 分析を開始するには、免責事項に同意してください。")
