import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- 1. アプリ設定 & 定数定義 ---
st.set_page_config(page_title="Market Edge Pro - Snapshot", page_icon="🦅", layout="wide")

# ★ バージョン管理とプロトコル定数 (これをCSVに刻印する)
MODEL_VERSION = "v1.0_Quant_Robust"
COST_ASSUMPTION = 0.005 # 往復0.5%
PORTFOLIO_RULE = "Top5_EqualWeight"

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_market_context():
    """ベンチマーク(QQQ)の現在値をスナップショット用に取得"""
    try:
        bench = yf.Ticker("QQQ")
        # 直近のデータを取得（現在値の参照用）
        hist = bench.history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
        return 0.0
    except:
        return 0.0

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers, benchmark_price):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 データ取得・完全スナップショット作成中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"Snapshotting... {ticker} ({i+1}/{total})")
            
            try:
                stock = yf.Ticker(ticker)
                try:
                    info = stock.info
                except:
                    continue 

                hist = stock.history(period="1y")
                if hist.empty: continue

                # --- A. Raw Data Extraction (将来の検証用に全て保存) ---
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                
                # Valuation Inputs
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
                
                # Trend Inputs
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # Consensus Inputs
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

                # --- B. Scoring Logic (Model v1.0) ---
                score = 0
                breakdown = []

                # 1. Valuation
                peg_weight = 0.5 if peg_type == "Proxy" else 1.0
                if pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    final_points = int(base_points * peg_weight)
                    if final_points > 0:
                        score += final_points
                        breakdown.append(f"PEG +{final_points}")
                else:
                    breakdown.append("No PEG")

                # 2. Trend
                trend_ok = False
                if price > sma50 > sma200:
                    score += 30
                    trend_ok = True
                    breakdown.append("Trend +30")
                elif price < sma50:
                    breakdown.append("Trend 0")

                # 3. Upside (Discounted)
                if analysts >= 5:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        discount_factor = max(0.0, 1.0 - spread_val)
                        final_upside = int(base_upside * discount_factor)
                        score += final_upside
                        breakdown.append(f"Upside +{final_upside}")
                else:
                     breakdown.append("Low Coverage")

                # 4. RSI
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and trend_ok:
                    score += 20
                    breakdown.append("RSI Dip +20")
                elif rsi > 75:
                    score -= 10
                    breakdown.append("RSI High -10")

                # Grade
                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"

                # ★ Full Snapshot Data (検証に必要な全データを保存)
                data_list.append({
                    "FetchTime": fetch_time,
                    "Model_Version": MODEL_VERSION,
                    "Ticker": ticker,
                    "Score": int(score),
                    "Grade": grade,
                    "Price_At_Scan": price,
                    # --- Benchmark Reference ---
                    "Benchmark_Ticker": "QQQ",
                    "Benchmark_Ref_Price": benchmark_price,
                    # --- Raw Inputs (再現性担保のため全て保存) ---
                    "PEG_Val": peg_val,
                    "PEG_Type": peg_type,
                    "Fwd_PE": fwd_pe,
                    "Growth_Rate": growth,
                    "SMA50": sma50,
                    "SMA200": sma200,
                    "RSI": rsi,
                    "Target_Mean": target_mean,
                    "Target_High": target_high,
                    "Target_Low": target_low,
                    "Spread": spread_val,
                    "Upside": upside_val,
                    "Analysts": analysts,
                    "Breakdown": " / ".join(breakdown)
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Snapshot Complete", state="complete", expanded=False)
    
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
st.title("🦅 Market Edge Pro (Snapshot Edition)")
st.caption(f"Ver: {MODEL_VERSION} | Protocol: {PORTFOLIO_RULE} | Cost: {COST_ASSUMPTION:.1%}")

# ベンチマーク状況
bench_price = fetch_market_context()
col_b1, col_b2 = st.columns([1, 3])
with col_b1:
    st.metric("Ref: QQQ Price", f"${bench_price:.2f}")
with col_b2:
    st.info("💡 **Snapshot:** この価格は「スキャン時点」の参照値です。検証時は規定に従い「翌日始値」を使用してください。")

# ★検証プロトコル（運用ルール固定）
with st.expander("📜 Standard Protocol (標準運用規定)", expanded=True):
    st.markdown(f"""
    **再現性を担保するため、以下のルールで検証することを規定します。**
    
    1.  **Portfolio:** スコア上位 **5銘柄** を抽出
    2.  **Allocation:** **等金額 (Equal Weight)** で購入
    3.  **Entry:** 抽出日の **翌営業日 始値 (Open)**
    4.  **Exit:** **20営業日後** の始値 (Open)
    5.  **Benchmark:** 同期間の **QQQ (始値→始値)** と比較
    6.  **Cost:** リターンから一律 **-{COST_ASSUMPTION:.1%}** (往復) を控除
    
    ※CSVにはこの検証に必要な「スキャン時点の全ての元データ」が保存されます。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 データ保存・厳格スキャン実行", type="primary"):
    df = fetch_stock_data(TARGETS, bench_price)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # --- CSV保存ボタン (全データ入り) ---
        csv = df.to_csv(index=False).encode('utf-8')
        filename = f'MarketEdge_{datetime.now().strftime("%Y%m%d_%H%M")}_{MODEL_VERSION}.csv'
        
        st.download_button(
            label="💾 全データをCSV保存 (For Verification)",
            data=csv,
            file_name=filename,
            mime='text/csv',
            help="検証に必要な全ての生データ（アナリスト予想、PEG、Spread等）が含まれています。"
        )
        
        st.subheader(f"🏆 Screening Results (Top Candidates)")
        
        # 画面表示はシンプルに
        st.dataframe(
            df[['Ticker', 'Price_At_Scan', 'Score', 'Grade', 'PEG_Val', 'Spread', 'Upside']]
            .style
            .format({
                'Price_At_Scan': '${:.2f}',
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

        # --- 詳細確認エリア ---
        st.divider()
        st.header("🧐 Data Audit (データ監査)")
        
        selected_ticker = st.selectbox("Select Ticker:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            discount_factor = max(0.0, 1.0 - row['Spread'])
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("1. Recorded Inputs")
                st.code(f"""
[Model Info]
Version    : {row['Model_Version']}
Fetch Time : {row['FetchTime']}

[Consensus Data]
Mean Target: ${row['Target_Mean']}
High/Low   : ${row['Target_High']} / ${row['Target_Low']}
Spread     : {row['Spread']:.2%} (Used for Discount)
Analysts   : {row['Analysts']}

[Valuation Data]
PEG Value  : {row['PEG_Val']:.2f} ({row['PEG_Type']})
Raw FwdPE  : {row['Fwd_PE']}
Raw Growth : {row['Growth_Rate']}
                """, language="yaml")
                
                stock = yf.Ticker(selected_ticker)
                hist = stock.history(period="1y")
                st.plotly_chart(plot_chart(selected_ticker, hist), use_container_width=True)

            with c2:
                st.subheader("2. Score Logic Audit")
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
