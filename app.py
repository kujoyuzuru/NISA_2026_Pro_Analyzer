import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import uuid
import os

# --- 1. システム設定 (Systematic Rules) ---
st.set_page_config(page_title="Market Edge Pro - Systematic", page_icon="🦅", layout="wide")

MODEL_VERSION = "v4.0_Auto_Balanced"
COST_MODEL = "0.5% (Round-Trip)" # 往復コスト
MAX_SECTOR_ALLOCATION = 2 # 1セクターあたりの最大銘柄数
PORTFOLIO_SIZE = 5
HISTORY_FILE = "master_execution_log.csv" # 全履歴保存用

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
def fetch_stock_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    cutoff_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.status("🦅 厳格スキャン & アルゴリズム選定中...", expanded=True) as status:
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
                sector = info.get('sector', 'Unknown')
                
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
                    peg_type = "Modified" # Modified PEG
                
                # 2. Consensus & Statistics
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = 0.0
                spread_val = 1.0
                
                if target_mean and target_mean > 0 and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low:
                        spread_val = (target_high - target_low) / target_mean
                
                # Confidence Factor (Sigmoid-like)
                # 人数が多いほど信頼度UP (15名でMAX)
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0

                # 3. Trend
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]

                # --- B. Scoring Logic ---
                score = 0
                breakdown = []

                # 1. Valuation (Official Only)
                if peg_type == "Official" and pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    score += base_points
                
                # 2. Trend
                trend_ok = False
                if price > sma50 > sma200:
                    score += 30
                    trend_ok = True
                
                # 3. Upside (Risk Adjusted)
                if upside_val > 0:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        # Spread割引と人数信頼度の二重フィルタ
                        spread_discount = max(0.0, 1.0 - spread_val)
                        final_factor = spread_discount * conf_factor
                        score += int(base_upside * final_factor)

                # 4. RSI
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and trend_ok:
                    score += 20
                elif rsi > 75:
                    score -= 10

                # Grade
                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": cutoff_time,
                    "Ticker": ticker,
                    "Sector": sector,
                    "Score": int(score),
                    "Grade": grade,
                    "Price_At_Scan": price,
                    # --- Snapshot Data ---
                    "PEG_Val": peg_val,
                    "PEG_Type": peg_type,
                    "Spread": spread_val,
                    "Analysts": analysts,
                    "Upside": upside_val,
                    "RSI": rsi,
                    "Model_Ver": MODEL_VERSION
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Analysis Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 3. ポートフォリオ構築アルゴリズム (強制分散) ---
def build_portfolio(df):
    """
    スコア順に選定するが、同セクターは最大2銘柄までとする。
    3銘柄目以降はスキップし、次点の別セクター銘柄を採用する。
    """
    df_sorted = df.sort_values('Score', ascending=False)
    portfolio = []
    sector_counts = {}
    
    logs = []
    
    for _, row in df_sorted.iterrows():
        if len(portfolio) >= PORTFOLIO_SIZE:
            break
            
        sec = row['Sector']
        current_count = sector_counts.get(sec, 0)
        
        if current_count < MAX_SECTOR_ALLOCATION:
            portfolio.append(row)
            sector_counts[sec] = current_count + 1
        else:
            logs.append(f"⚠️ Skip {row['Ticker']} ({sec}): Sector Limit Reached")
            
    return pd.DataFrame(portfolio), logs

# --- 4. 履歴保存機能 ---
def save_to_history(df_portfolio):
    """実行されたポートフォリオ案を強制的に追記保存する"""
    # 検証用カラムを追加（空欄）
    df_portfolio["Cost_Model"] = COST_MODEL
    df_portfolio["Entry_Date_Est"] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    df_portfolio["Exit_Date_Est"] = (datetime.now() + timedelta(days=30)).strftime('%Y-%m-%d')
    df_portfolio["Actual_Entry_Price"] = np.nan # 後で埋める
    df_portfolio["Actual_Exit_Price"] = np.nan  # 後で埋める
    df_portfolio["Benchmark_Entry"] = np.nan    # 後で埋める
    df_portfolio["Benchmark_Exit"] = np.nan     # 後で埋める
    
    # CSVに追記モードで保存
    if not os.path.exists(HISTORY_FILE):
        df_portfolio.to_csv(HISTORY_FILE, index=False)
    else:
        df_portfolio.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return df_portfolio

# --- 5. メイン画面 ---
st.title("🦅 Market Edge Pro (Systematic Trader)")
st.caption(f"Ver: {MODEL_VERSION} | Protocol: Auto-Sector-Cap (Max {MAX_SECTOR_ALLOCATION}) | Cost: {COST_MODEL}")

# コンテキスト表示
bench_price = fetch_market_context()
st.metric("Context: QQQ Current", f"${bench_price:.2f}")

with st.expander("🤖 System Logic (人間による改変不可)", expanded=True):
    st.markdown(f"""
    1.  **Auto Sector Cap:** 1つのセクターからは最大 **{MAX_SECTOR_ALLOCATION}銘柄** しか採用しません。3銘柄目以降はスコアが高くても自動的に却下されます。
    2.  **Master Logging:** スキャン結果は自動的にサーバー(ローカル)の `master_execution_log.csv` に記録されます。後出しの選択はできません。
    3.  **Strict Audit Schema:** 出力されるCSVには、検証に必要な「コスト」「Entry/Exit日」「ベンチマーク価格記入欄」が予め用意されています。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("RUN SYSTEM (Generate & Log)", type="primary"):
    # 1. 全銘柄スキャン
    raw_df = fetch_stock_data(TARGETS)
    
    if not raw_df.empty:
        # 2. アルゴリズムによるポートフォリオ構築
        portfolio_df, logic_logs = build_portfolio(raw_df)
        
        # 3. 強制ログ保存
        final_csv_df = save_to_history(portfolio_df)
        
        # --- UI表示 ---
        st.subheader(f"🏆 Systematic Portfolio (Run ID: {portfolio_df['Run_ID'].iloc[0]})")
        
        # 除外ログの表示
        if logic_logs:
            for log in logic_logs:
                st.warning(log)
        else:
            st.success("✅ No Sector Conflicts. Pure Score Selection.")
            
        # ポートフォリオ表
        st.dataframe(
            portfolio_df[['Ticker', 'Sector', 'Score', 'PEG_Val', 'Spread', 'Price_At_Scan']]
            .style
            .format({'Price_At_Scan': '${:.2f}', 'Score': '{:.0f}', 'PEG_Val': '{:.2f}', 'Spread': '{:.1%}'})
            .background_gradient(subset=['Score'], cmap='Greens')
            .highlight_null(color='gray'),
            use_container_width=True
        )

        # CSVダウンロード (検証用フォーマット付き)
        csv = final_csv_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Download Audit Plan (記入用CSV)",
            data=csv,
            file_name=f'TradePlan_{datetime.now().strftime("%Y%m%d_%H%M")}.csv',
            mime='text/csv',
            help="このCSVには『実際のEntry価格』『Benchmark価格』を記入する空欄が含まれています。"
        )

        # 履歴データの表示（簡易）
        st.divider()
        st.write("📜 Local Execution History (Last 10 entries)")
        if os.path.exists(HISTORY_FILE):
            history_df = pd.read_csv(HISTORY_FILE)
            st.dataframe(history_df.tail(10), use_container_width=True)
        else:
            st.caption("No history yet.")
            
    else:
        st.error("Data fetch failed.")
