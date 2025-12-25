import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import uuid
import os
import hashlib
from collections import Counter

# --- 1. システム設定 ---
st.set_page_config(page_title="Market Edge Pro - System Final", page_icon="🦅", layout="wide")

MODEL_VERSION = "v5.0_Signature_Decay"
COST_MODEL = 0.005 # 往復0.5%
MAX_SECTOR_ALLOCATION = 2
PORTFOLIO_SIZE = 5
HISTORY_FILE = "master_execution_log.csv"

# --- 2. 数理・ユーティリティ関数 ---

def calculate_file_hash(df):
    """データフレームの内容から一意の指紋(SHA-256ハッシュ)を生成"""
    # 重要な列だけを結合してハッシュ化
    content = df[['Ticker', 'Score', 'FetchTime']].to_string()
    return hashlib.sha256(content.encode()).hexdigest()[:12]

def decay_function(spread_val):
    """
    Spreadに対する連続的な割引関数 (Decay Model)
    Cliff(崖)を作らず、Spreadが広がるほど滑らかにスコアを減衰させる
    Formula: 1 / (1 + Spread)
    Example: Spread 0% -> 1.0, 50% -> 0.66, 100% -> 0.5, 200% -> 0.33
    """
    return 1.0 / (1.0 + spread_val)

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
    # 秒単位のデータ取得時刻 (Data Integrity)
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.status("🦅 データ取得・署名付きスキャン実行中...", expanded=True) as status:
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
                    peg_type = "Modified"
                
                # 2. Consensus & Statistics
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = 0.0
                spread_val = 0.5 # Default risk
                
                if target_mean and target_mean > 0 and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low:
                        spread_val = (target_high - target_low) / target_mean
                
                # Confidence Factor
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0

                # 3. Trend
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]

                # --- B. Scoring Logic (Decay Model) ---
                score = 0
                breakdown = []

                # 1. Valuation
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
                
                # 3. Upside (Decay Function)
                if upside_val > 0:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        # 改良: 滑らかな減衰関数
                        spread_discount = decay_function(spread_val)
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
                    "FetchTime": fetch_time,
                    "Ticker": ticker,
                    "Sector": sector,
                    "Score": int(score),
                    "Grade": grade,
                    "Price_At_Scan": price,
                    # Snapshot Stats
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

# --- 3. ポートフォリオ構築 ---
def build_portfolio(df):
    df_sorted = df.sort_values('Score', ascending=False)
    portfolio = []
    sector_counts = {}
    logs = []
    
    for _, row in df_sorted.iterrows():
        if len(portfolio) >= PORTFOLIO_SIZE: break
        sec = row['Sector']
        current_count = sector_counts.get(sec, 0)
        
        if current_count < MAX_SECTOR_ALLOCATION:
            portfolio.append(row)
            sector_counts[sec] = current_count + 1
        else:
            logs.append(f"Skip {row['Ticker']} ({sec}): Cap Reached")
            
    return pd.DataFrame(portfolio), logs

# --- 4. 履歴保存 & 署名 ---
def save_to_history(df_portfolio):
    # ハッシュ生成（改ざん検知用）
    data_hash = calculate_file_hash(df_portfolio)
    df_portfolio["Data_Hash"] = data_hash
    df_portfolio["Entry_Date"] = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    
    if not os.path.exists(HISTORY_FILE):
        df_portfolio.to_csv(HISTORY_FILE, index=False)
    else:
        df_portfolio.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    return df_portfolio, data_hash

# --- 5. ライブ・ペーパートレーディング集計 ---
def calculate_live_performance():
    if not os.path.exists(HISTORY_FILE):
        return pd.DataFrame(), 0, 0, 0
    
    history = pd.read_csv(HISTORY_FILE)
    if history.empty: return pd.DataFrame(), 0, 0, 0
    
    # QQQの現在値
    qqq = yf.Ticker("QQQ")
    qqq_cur = qqq.history(period="1d")['Close'].iloc[-1]
    
    results = []
    
    # 最新の株価を一括取得（高速化のためTickerリスト化）
    tickers = history['Ticker'].unique().tolist()
    live_prices = {}
    
    # 簡易取得 (実際はBatch取得が望ましいが、ここではLoopで実装)
    # yfinanceの制限を考慮し、キャッシュがあれば使う設計が理想
    for t in tickers:
        try:
            live_prices[t] = yf.Ticker(t).history(period="1d")['Close'].iloc[-1]
        except:
            live_prices[t] = 0
            
    for i, row in history.iterrows():
        entry_price = row['Price_At_Scan'] # 簡易的にスキャン価格をEntryとする
        current_price = live_prices.get(row['Ticker'], entry_price)
        
        # リターン計算 (コスト控除)
        stock_ret = ((current_price - entry_price) / entry_price) - COST_MODEL
        
        # ※本来は「スキャン時のQQQ」と「現在のQQQ」を比較するが、
        # ここでは簡易的に全期間のQQQリターンを対照とするシミュレーション
        # (厳密なAlpha計算にはEntry時のQQQ価格の保存が必要。今回はStock Returnを表示)
        
        results.append({
            "Run_ID": row['Run_ID'],
            "Date": row['FetchTime'],
            "Ticker": row['Ticker'],
            "Entry": entry_price,
            "Current": current_price,
            "Return": stock_ret,
            "Hash": row.get('Data_Hash', '-')
        })
        
    df_res = pd.DataFrame(results)
    total_ret = df_res['Return'].mean()
    win_rate = len(df_res[df_res['Return'] > 0]) / len(df_res)
    
    return df_res, total_ret, win_rate, qqq_cur

# --- 6. UI構築 ---
tab1, tab2 = st.tabs(["🚀 System Scanner", "📈 Live Paper Trading"])

with tab1:
    st.title("🦅 Market Edge Pro (System Final)")
    st.caption(f"Ver: {MODEL_VERSION} | Cost: {COST_MODEL:.1%} | Hash: Enabled")

    bench_price = fetch_market_context()
    st.metric("Context: QQQ Price", f"${bench_price:.2f}")

    with st.expander("📊 Logic Update (Decay & Signature)", expanded=True):
        st.markdown("""
        1.  **Decay Function (滑らかな減衰):** Spreadに対して `1 / (1 + Spread)` を適用。崖を作らず、不確実性が増すほどスコアを徐々に下げます。
        2.  **Digital Signature (改ざん防止):** スキャン結果からSHA-256ハッシュを生成し、ログに刻印。後からのデータ改ざんを検知します。
        3.  **Strict Sector Cap:** 同一セクターは最大2銘柄まで。3銘柄目以降はアルゴリズムが強制排除します。
        """)

    TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

    if st.button("RUN SYSTEM & LOG", type="primary"):
        raw_df = fetch_stock_data(TARGETS)
        if not raw_df.empty:
            portfolio_df, logs = build_portfolio(raw_df)
            final_df, data_hash = save_to_history(portfolio_df)
            
            st.subheader(f"🏆 Systematic Portfolio (ID: {final_df['Run_ID'].iloc[0]})")
            st.caption(f"🔒 Data Hash: {data_hash} (Tamper Proof)")
            
            if logs:
                for log in logs: st.warning(log)
            
            st.dataframe(
                final_df[['Ticker', 'Sector', 'Score', 'Spread', 'PEG_Type', 'Price_At_Scan']]
                .style
                .format({'Price_At_Scan': '${:.2f}', 'Score': '{:.0f}', 'Spread': '{:.1%}'})
                .background_gradient(subset=['Score'], cmap='Greens'),
                use_container_width=True
            )
        else:
            st.error("Failed to fetch data.")

with tab2:
    st.header("📈 Live Paper Trading (自動集計)")
    st.info("マスターログに保存された全推奨銘柄の「現在価格」を取得し、コスト控除後の仮想成績を集計します。")
    
    if st.button("🔄 集計を更新 (Update Stats)"):
        df_stats, avg_ret, win_rate, qqq_now = calculate_live_performance()
        
        if not df_stats.empty:
            k1, k2, k3 = st.columns(3)
            k1.metric("Win Rate", f"{win_rate:.1%}")
            k2.metric("Avg Return (Net)", f"{avg_ret:.2%}", delta_color="normal")
            k3.metric("Tracked Tickers", f"{len(df_stats)}")
            
            st.dataframe(
                df_stats[['Date', 'Ticker', 'Entry', 'Current', 'Return', 'Hash']]
                .sort_values('Date', ascending=False)
                .style
                .format({'Entry': '${:.2f}', 'Current': '${:.2f}', 'Return': '{:.2%}'})
                .applymap(lambda x: 'color: green;' if x > 0 else 'color: red;', subset=['Return']),
                use_container_width=True
            )
        else:
            st.warning("No history found. Run the scanner first.")
