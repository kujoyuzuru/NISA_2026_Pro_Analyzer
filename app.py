import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime
import uuid
from collections import Counter

# --- 1. アプリ設定 & 定数 ---
st.set_page_config(page_title="Market Edge Pro - Production", page_icon="🦅", layout="wide")

MODEL_VERSION = "v2.0_Hybrid_RiskManaged"
COST_ASSUMPTION = 0.005 # 往復0.5%
PORTFOLIO_SIZE = 5

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_market_context():
    try:
        bench = yf.Ticker("QQQ")
        hist = bench.history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
        return 0.0
    except:
        return 0.0

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers, benchmark_price):
    data_list = []
    run_id = str(uuid.uuid4())[:8] # 今回のスキャン固有ID
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 データ取得・ハイブリッド採点実行中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"Scanning... {ticker} ({i+1}/{total})")
            
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
                sector = info.get('sector', 'Unknown') # セクター取得
                
                # 1. Valuation Inputs
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
                    peg_type = "Modified" # 改名: Modified PEG (簡易版)
                
                # 2. Trend Inputs
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus Inputs (防御的取得)
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = np.nan
                spread_val = 0.0
                
                # ゼロ除算・異常値ガード
                if target_mean and target_mean > 0 and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low:
                        spread_val = (target_high - target_low) / target_mean
                else:
                    # ターゲット異常時は評価対象外とする
                    upside_val = 0.0 
                    spread_val = 1.0 # 最大ペナルティ

                # --- B. Scoring Logic (Hybrid Model) ---
                score = 0
                breakdown = []

                # 1. Valuation (Discrete Buckets)
                # 視認性重視のため段階評価を採用
                peg_weight = 0.5 if peg_type == "Modified" else 1.0
                if pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    final_points = int(base_points * peg_weight)
                    if final_points > 0:
                        type_str = "Wt 0.5" if peg_type == "Modified" else "Wt 1.0"
                        score += final_points
                        breakdown.append(f"PEG +{final_points} ({type_str})")
                else:
                    breakdown.append("No PEG")

                # 2. Trend (Discrete Rules)
                trend_ok = False
                if price > sma50 > sma200:
                    score += 30
                    trend_ok = True
                    breakdown.append("Trend +30")
                elif price < sma50:
                    breakdown.append("Trend 0")

                # 3. Upside (Continuous Discount Model)
                # 不確実性は連続関数で割引
                if analysts >= 5 and spread_val < 2.0: # 異常なSpreadは除外
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        discount_factor = max(0.0, 1.0 - spread_val)
                        final_upside = int(base_upside * discount_factor)
                        score += final_upside
                        breakdown.append(f"Upside +{final_upside} (Factor {discount_factor:.2f})")
                else:
                     breakdown.append("Low/Bad Coverage")

                # 4. RSI (Discrete Range)
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

                data_list.append({
                    "Run_ID": run_id,
                    "Ticker": ticker,
                    "Sector": sector, # セクター追加
                    "Score": int(score),
                    "Grade": grade,
                    "Price_Reference": price,
                    "Benchmark_Ref": benchmark_price,
                    # --- Snapshot Data ---
                    "PEG_Val": peg_val,
                    "PEG_Type": peg_type,
                    "Spread": spread_val,
                    "Upside": upside_val,
                    "Analysts": analysts,
                    "RSI": rsi,
                    "Breakdown": " / ".join(breakdown),
                    "FetchTime": fetch_time,
                    "Model_Ver": MODEL_VERSION
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Scan Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 3. ユーティリティ関数 ---
def check_concentration(df_top):
    """上位銘柄のセクター集中度をチェック"""
    if df_top.empty: return []
    sectors = df_top['Sector'].tolist()
    counts = Counter(sectors)
    warnings = []
    for sec, count in counts.items():
        if count >= 3: # 5銘柄中3つ以上が同セクターなら警告
            warnings.append(f"⚠️ {sec} セクターに集中しています ({count}銘柄)。分散投資の観点から注意が必要です。")
    return warnings

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
st.title("🦅 Market Edge Pro (Production Ver.)")
st.caption(f"Ver: {MODEL_VERSION} | Rule: Top{PORTFOLIO_SIZE} EqualWeight | ID-Tracked")

# ベンチマーク
bench_price = fetch_market_context()
col_b1, col_b2 = st.columns([1, 3])
with col_b1:
    st.metric("Ref: QQQ Price", f"${bench_price:.2f}")
with col_b2:
    st.info("💡 **Benchmark:** この価格は参照用です。検証の際は、必ず『翌営業日の始値』同士で比較してください。")

# ★ハイブリッドモデルの定義（正直な開示）
with st.expander("📊 Hybrid Scoring Model (評価ロジック定義)", expanded=True):
    st.markdown("""
    本アプリは、**「連続的なリスク評価」**と**「明確な段階基準」**を組み合わせたハイブリッドモデルを採用しています。
    
    1.  **Continuous Discount (連続評価):**
        * **不確実性 (Spread):** アナリスト意見のバラつきに応じて、上値余地スコアをリニアに減額します。
        * `Factor = max(0.0, 1.0 - Spread)`
    2.  **Discrete Buckets (段階評価):**
        * **PEG / Trend / RSI:** 投資判断の明確化のため、閾値による段階加点を採用しています。
    3.  **Risk Management:**
        * **Modified PEG:** 公式値がない場合、簡易計算値を使いますが、重みを0.5に引き下げます。
        * **Sector Limit:** ポートフォリオ内のセクター集中を監視します。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 ポートフォリオ構築スキャン実行", type="primary"):
    df = fetch_stock_data(TARGETS, bench_price)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # Run IDの表示
        run_id = df['Run_ID'][0]
        st.caption(f"Run ID: {run_id} (このIDで検証データを管理します)")

        # --- CSV保存 ---
        csv = df.to_csv(index=False).encode('utf-8')
        filename = f'MarketEdge_{datetime.now().strftime("%Y%m%d")}_{run_id}.csv'
        st.download_button(
            label="💾 検証用データをCSV保存 (With Run ID)",
            data=csv,
            file_name=filename,
            mime='text/csv'
        )
        
        # --- 結果表示 & 集中リスクチェック ---
        top_picks = df.head(PORTFOLIO_SIZE)
        warnings = check_concentration(top_picks)
        
        if warnings:
            for w in warnings:
                st.error(w)
        else:
            st.success("✅ ポートフォリオのセクター分散は良好です。")

        st.subheader(f"🏆 Top Candidate List")
        st.dataframe(
            df[['Ticker', 'Sector', 'Price_Reference', 'Score', 'PEG_Val', 'PEG_Type', 'Spread']]
            .style
            .format({
                'Price_Reference': '${:.2f}',
                'Score': '{:.0f}',
                'PEG_Val': '{:.2f}',
                'Spread': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .background_gradient(subset=['Spread'], cmap='Reds', vmin=0.0, vmax=0.8)
            .highlight_null(color='gray'),
            use_container_width=True,
            height=600
        )

        # --- 詳細監査 ---
        st.divider()
        st.header("🧐 Data Audit")
        selected_ticker = st.selectbox("Select Ticker:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            discount_factor = max(0.0, 1.0 - row['Spread'])
            
            c1, c2 = st.columns([1, 1])
            with c1:
                st.subheader("1. Risk Profile")
                st.code(f"""
[Uncertainty]
Spread     : {row['Spread']:.2%}
Discount   : {discount_factor:.2f}

[Valuation Quality]
Type       : {row['PEG_Type']}
Weight     : {"0.5" if "Modified" in row['PEG_Type'] else "1.0"}

[Context]
Sector     : {row['Sector']}
Run ID     : {row['Run_ID']}
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
