import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Definitive", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_market_context():
    """ベンチマーク(QQQ)の現状を取得"""
    try:
        bench = yf.Ticker("QQQ")
        hist = bench.history(period="5d")
        price = hist['Close'].iloc[-1]
        prev = hist['Close'].iloc[-2]
        change = (price - prev) / prev
        return price, change
    except:
        return 0, 0

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers, benchmark_price):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 厳格スキャン実行中 (vs NASDAQ100)...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"Processing... {ticker} ({i+1}/{total})")
            
            try:
                stock = yf.Ticker(ticker)
                try:
                    info = stock.info
                except:
                    continue 

                hist = stock.history(period="1y")
                if hist.empty: continue

                # --- A. Raw Data ---
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                
                # 1. Valuation
                official_peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                peg_val = np.nan
                peg_type = "-" 
                
                if official_peg is not None:
                    peg_val = official_peg
                    peg_type = "Official"
                elif fwd_pe is not None and growth is not None and growth > 0:
                    peg_val = fwd_pe / (growth * 100)
                    peg_type = "Proxy"
                
                # 2. Trend
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus (Spread)
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = np.nan
                spread_val = 0.0
                
                if target_mean and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low and target_mean > 0:
                        spread_val = (target_high - target_low) / target_mean

                # --- B. Scoring Model ---
                score = 0
                breakdown = []

                # 1. Valuation (PEG)
                peg_weight = 0.5 if peg_type == "Proxy" else 1.0
                if pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    final_points = int(base_points * peg_weight)
                    if final_points > 0:
                        type_label = "Wt 0.5" if peg_type == "Proxy" else "Wt 1.0"
                        score += final_points
                        breakdown.append(f"PEG {peg_val:.2f} ({type_label}): +{final_points}")
                else:
                    breakdown.append("No PEG: 0")

                # 2. Trend
                trend_str = "Range/Down"
                if price > sma50 > sma200:
                    score += 30
                    trend_str = "📈 Perfect"
                    breakdown.append("Trend (P-Order): +30")
                elif price < sma50:
                    trend_str = "📉 Downtrend"
                    breakdown.append("Trend (Below SMA50): 0")

                # 3. Upside (Discount Model)
                if analysts >= 5:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        # Discount Factor (Min 0.0)
                        discount_factor = max(0.0, 1.0 - spread_val)
                        final_upside = int(base_upside * discount_factor)
                        score += final_upside
                        breakdown.append(f"Upside {upside_val:.1%} (Factor {discount_factor:.2f}): +{final_upside}")
                else:
                     breakdown.append(f"Low Coverage: 0")

                # 4. RSI
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and "Perfect" in trend_str:
                    score += 20
                    breakdown.append("RSI Dip: +20")
                elif rsi > 75:
                    score -= 10
                    breakdown.append("RSI High: -10")

                # Grade
                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"

                data_list.append({
                    "Ticker": ticker,
                    "Name": info.get('shortName', ticker),
                    "Price": price,
                    "Grade": grade,
                    "Score": int(score),
                    "Breakdown": " / ".join(breakdown),
                    "PEG_Val": peg_val,
                    "PEG_Type": peg_type,
                    "SMA50": sma50,
                    "SMA200": sma200,
                    "RSI": rsi,
                    "Target_Mean": target_mean,
                    "Spread": spread_val,
                    "Upside": upside_val,
                    "Analysts": analysts,
                    "Benchmark_Ref": benchmark_price, # 検証用ベンチマーク価格
                    "FetchTime": fetch_time
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 3. チャート描画 ---
def plot_chart(ticker, hist):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=hist.index,
                open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='Price'))
    
    sma50 = hist['Close'].rolling(window=50).mean()
    sma200 = hist['Close'].rolling(window=200).mean()
    
    fig.add_trace(go.Scatter(x=hist.index, y=sma50, line=dict(color='orange', width=1.5), name='SMA 50'))
    fig.add_trace(go.Scatter(x=hist.index, y=sma200, line=dict(color='blue', width=1.5), name='SMA 200'))
    fig.update_layout(title=f"{ticker} 1Y Chart", height=400, template="plotly_dark")
    return fig

# --- 4. メイン画面 ---
st.title("🦅 Market Edge Pro (Definitive Edition)")
st.caption("ベンチマーク比較とコスト控除を前提とした、相対リターン(Alpha)追求ツール")

# ベンチマーク状況の表示
bench_price, bench_change = fetch_market_context()
col_b1, col_b2 = st.columns([1, 3])
with col_b1:
    st.metric("Benchmark (QQQ)", f"${bench_price:.2f}", f"{bench_change:.2%}")
with col_b2:
    st.info("💡 **比較基準:** すべての結果は NASDAQ100 (QQQ) と比較して評価してください。")

# ★検証プロトコル（レギュレーション）完全版
with st.expander("📜 Verification Protocol (検証プロトコル・完全版)", expanded=True):
    st.markdown("""
    本ツールの成績は、単なる騰落率ではなく**「対ベンチマーク超過益 (Alpha)」**で判断します。
    
    | 項目 | 厳格規定 |
    | :--- | :--- |
    | **Benchmark** | **NASDAQ100 (QQQ)** を同時購入したと仮定して比較する |
    | **Entry** | 抽出日の **翌営業日 始値 (Open)** |
    | **Cost** | 往復手数料・スリッページとして **一律 -0.5%** をリターンから差し引く |
    | **Exit** | **20営業日後 (約1ヶ月)** の始値で手仕舞い |
    | **Win Condition** | `(銘柄リターン - 0.5%) > QQQリターン` の場合のみ「勝利」とする |
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 厳格スキャンを実行 (Benchmark Stamp)", type="primary"):
    df = fetch_stock_data(TARGETS, bench_price)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # 検証用CSV (ベンチマーク価格入り)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 検証用CSVを保存 (with QQQ Price)",
            data=csv,
            file_name=f'alpha_verify_{datetime.now().strftime("%Y%m%d")}.csv',
            mime='text/csv',
        )
        
        st.subheader(f"🏆 Screening Results (Data at: {df['FetchTime'][0]})")
        
        st.dataframe(
            df[['Ticker', 'Price', 'Score', 'PEG_Val', 'Spread', 'Upside']]
            .style
            .format({
                'Price': '${:.2f}',
                'Score': '{:.0f}',
                'PEG_Val': '{:.2f}',
                'Spread': '{:.1%}', 
                'Upside': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .background_gradient(subset=['Spread'], cmap='Reds', vmin=0.0, vmax=0.8)
            .highlight_null(color='gray'),
            use_container_width=True,
            height=600
        )
        st.caption("※CSVには比較用の『QQQ現在価格』が含まれています。1ヶ月後のQQQ騰落率と比較してください。")

        # --- 詳細検証エリア ---
        st.divider()
        st.header("🧐 Factor Inspection")
        
        selected_ticker = st.selectbox("Select Ticker:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            discount_factor = max(0.0, 1.0 - row['Spread'])
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("1. Quant Metrics")
                st.code(f"""
[Risk Model]
Spread     : {row['Spread']:.2%}
Discount   : {discount_factor:.2f} (Min 0.0)

[Benchmark Ref]
QQQ Price  : ${row['Benchmark_Ref']:.2f}
(Target: Beat QQQ + 0.5% Cost)
                """, language="yaml")
                stock = yf.Ticker(selected_ticker)
                hist = stock.history(period="1y")
                st.plotly_chart(plot_chart(selected_ticker, hist), use_container_width=True)

            with c2:
                st.subheader("2. Score Breakdown")
                st.metric("Total Score", f"{row['Score']} / 100")
                reasons = row['Breakdown'].split(" / ")
                for r in reasons:
                    if "PEG" in r: st.success(f"💰 {r}")
                    elif "Trend" in r: st.info(f"📈 {r}")
                    elif "Upside" in r: st.warning(f"🎯 {r}") 
                    elif "RSI" in r: st.error(f"📊 {r}")
                    else: st.write(f"・{r}")
            
    else:
        st.error("Data fetch failed.")
