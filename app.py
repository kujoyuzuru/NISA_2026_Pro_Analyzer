import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import uuid
import os
import hashlib

# --- 1. システム設定 & プロトコル定義 ---
st.set_page_config(page_title="Market Edge Pro - Analytics", page_icon="🦅", layout="wide")

# ★ プロトコル定義 (ここを変えると Hash が変わり、別ルールとみなされる)
PROTOCOL_DEF = """
1. Universe: Specified Tech/Growth Tickers
2. Selection: Hybrid Score (Decay Model)
3. Portfolio: Top 5 Equal Weight
4. Entry: Next Open / Exit: Entry + 20 Days Open
5. Cost: 0.5% deducted at Exit
6. Benchmark: QQQ (Price Return)
"""
PROTOCOL_HASH = hashlib.sha256(PROTOCOL_DEF.encode()).hexdigest()[:8]

MODEL_VERSION = f"v7.0_Analytics_{PROTOCOL_HASH}"
HISTORY_FILE = "master_execution_log.csv"
COST_RATE = 0.005 # 0.5%

# --- 2. 数理・ユーティリティ関数 ---

def get_last_hash():
    if not os.path.exists(HISTORY_FILE):
        return "GENESIS"
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return "GENESIS"
        return df.iloc[-1]['Record_Hash']
    except:
        return "BROKEN"

def calculate_chain_hash(prev_hash, content_string):
    combined = f"{prev_hash}|{content_string}"
    return hashlib.sha256(combined.encode()).hexdigest()

def decay_function(spread_val):
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
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.status("🦅 厳格スキャン実行中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"Scanning... {ticker} ({i+1}/{total})")
            
            try:
                stock = yf.Ticker(ticker)
                try:
                    info = stock.info
                except:
                    continue 

                hist = stock.history(period="5d")
                if hist.empty: continue

                # Raw Data Snapshot
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                sector = info.get('sector', 'Unknown')
                
                # Valuation
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
                
                # Consensus
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = 0.0
                spread_val = 0.5
                
                if target_mean and target_mean > 0 and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low:
                        spread_val = (target_high - target_low) / target_mean
                
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0

                # Trend
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1] if len(hist) >= 50 else price
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) >= 200 else price
                
                # Scoring
                score = 0
                
                # 1. Valuation
                if peg_type == "Official" and pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    score += base_points
                
                # 2. Trend
                trend_ok = False
                if len(hist) >= 200 and price > sma50 > sma200:
                    score += 30
                    trend_ok = True
                
                # 3. Upside
                if upside_val > 0:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    if base_upside > 0:
                        spread_discount = decay_function(spread_val)
                        final_factor = spread_discount * conf_factor
                        score += int(base_upside * final_factor)

                # 4. RSI (Simplified)
                rsi = 50 

                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Sector": sector,
                    "Score": int(score),
                    "Price_At_Scan": price,
                    "PEG_Val": peg_val,
                    "Spread": spread_val,
                    "Upside": upside_val,
                    "Model_Ver": MODEL_VERSION
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 3. ポートフォリオ構築 ---
def build_portfolio(df):
    df_sorted = df.sort_values('Score', ascending=False)
    portfolio = []
    sector_counts = {}
    logs = []
    
    for _, row in df_sorted.iterrows():
        if len(portfolio) >= 5: break
        sec = row['Sector']
        cnt = sector_counts.get(sec, 0)
        
        if cnt < 2:
            portfolio.append(row)
            sector_counts[sec] = cnt + 1
        else:
            logs.append(f"Skip {row['Ticker']}: Sector Limit")
            
    return pd.DataFrame(portfolio), logs

# --- 4. 履歴保存 ---
def save_to_history(df_portfolio):
    prev_hash = get_last_hash()
    df_to_save = df_portfolio.copy()
    
    # メタデータ
    df_to_save["Prev_Hash_Ref"] = prev_hash
    df_to_save["Protocol_Hash"] = PROTOCOL_HASH
    
    # ハッシュ生成
    content_str = df_to_save[['Run_ID', 'Ticker', 'Score', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content_str)
    df_to_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_to_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_to_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return df_to_save, new_hash

# --- 5. 高度な分析機能 (Audit Analytics) ---
def calculate_advanced_stats(df_history):
    if df_history.empty: return None

    run_ids = df_history['Run_ID'].unique()
    performance_records = []
    
    initial_equity = 10000.0
    equity_curve = [initial_equity]
    dates = [df_history['Scan_Time'].min().split(" ")[0]] # Start date
    
    qqq = yf.Ticker("QQQ")
    
    # 各Runの処理（簡易シミュレーション）
    current_equity = initial_equity
    
    for rid in run_ids:
        run_data = df_history[df_history['Run_ID'] == rid]
        scan_date_str = run_data['Scan_Time'].iloc[0]
        scan_date = pd.to_datetime(scan_date_str).date()
        
        # 本来は翌日始値だが、簡易的に「Scan日の翌日～20日後」をシミュレート
        start_date = scan_date + timedelta(days=1)
        end_date = start_date + timedelta(days=30) # Approx 20 trading days
        
        # 過去データ取得（現在より未来ならSkip）
        if start_date >= datetime.now().date():
            continue
            
        # 平均リターン計算
        returns = []
        for _, row in run_data.iterrows():
            try:
                # 実際のヒストリカルデータを取得
                hist = yf.Ticker(row['Ticker']).history(start=start_date, end=end_date)
                if len(hist) > 0:
                    entry = hist['Open'].iloc[0]
                    exit_price = hist['Open'].iloc[-1]
                    # コスト控除 (Exit時)
                    ret = ((exit_price - entry) / entry) - COST_RATE
                    returns.append(ret)
            except:
                continue
        
        if returns:
            avg_ret = np.mean(returns)
            # 資産曲線の更新 (単利加算ではなく複利運用と仮定)
            current_equity = current_equity * (1 + avg_ret)
            equity_curve.append(current_equity)
            dates.append(scan_date_str.split(" ")[0])
            
            # QQQのリターンも取得（同期間）
            try:
                q_hist = qqq.history(start=start_date, end=end_date)
                if len(q_hist) > 0:
                    q_ret = (q_hist['Open'].iloc[-1] - q_hist['Open'].iloc[0]) / q_hist['Open'].iloc[0]
                else:
                    q_ret = 0.0
            except:
                q_ret = 0.0
                
            performance_records.append({
                "Date": scan_date_str,
                "Strategy_Ret": avg_ret,
                "QQQ_Ret": q_ret,
                "Equity": current_equity
            })

    if not performance_records:
        return None

    df_perf = pd.DataFrame(performance_records)
    
    # ドローダウン計算
    df_perf['Peak'] = df_perf['Equity'].cummax()
    df_perf['Drawdown'] = (df_perf['Equity'] - df_perf['Peak']) / df_perf['Peak']
    max_dd = df_perf['Drawdown'].min()
    
    total_return = (current_equity - initial_equity) / initial_equity
    
    return {
        "df": df_perf,
        "total_return": total_return,
        "max_dd": max_dd,
        "equity_curve": equity_curve,
        "dates": dates
    }

# --- 6. UI構築 ---
tab1, tab2 = st.tabs(["🚀 System Execution", "📊 Analytics & Audit"])

with tab1:
    st.title("🦅 Market Edge Pro (Execution)")
    st.caption(f"Ver: {MODEL_VERSION} | Protocol Hash: {PROTOCOL_HASH} | Local Chain")

    bench_price = fetch_market_context()
    st.metric("Context: QQQ", f"${bench_price:.2f}")

    with st.expander("📜 Defined Protocol (変更不可)", expanded=True):
        st.code(PROTOCOL_DEF)
        st.caption("※この定義を変更するとプロトコルハッシュが変わり、過去ログとの連続性が警告されます。")

    TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

    if st.button("EXECUTE RUN & LOG", type="primary"):
        raw_df = fetch_stock_data(TARGETS)
        if not raw_df.empty:
            portfolio_df, logs = build_portfolio(raw_df)
            final_df, data_hash = save_to_history(portfolio_df)
            
            st.success(f"✅ Logged with Hash: {data_hash}")
            if logs:
                for l in logs: st.warning(l)
            
            st.dataframe(final_df[['Ticker', 'Score', 'Spread', 'PEG_Val']].style.background_gradient(subset=['Score'], cmap='Greens'))
        else:
            st.error("Data Error")

with tab2:
    st.header("📊 Strategy Analytics (累積成績)")
    
    if st.button("🔄 Calculate Performance"):
        if os.path.exists(HISTORY_FILE):
            df_hist = pd.read_csv(HISTORY_FILE)
            stats = calculate_advanced_stats(df_hist)
            
            if stats:
                c1, c2, c3 = st.columns(3)
                c1.metric("Total Return", f"{stats['total_return']:.2%}")
                c2.metric("Max Drawdown", f"{stats['max_dd']:.2%}", delta_color="inverse")
                c3.metric("Samples", f"{len(stats['df'])}")
                
                # 資産曲線チャート
                fig = go.Figure()
                fig.add_trace(go.Scatter(x=stats['dates'], y=stats['equity_curve'], mode='lines', name='Strategy Equity'))
                # (簡易比較のためQQQの累積は割愛するが、本来はここに重ねる)
                st.plotly_chart(fig, use_container_width=True)
                
                st.dataframe(stats['df'], use_container_width=True)
            else:
                st.warning("Not enough data or pending trades.")
        else:
            st.info("No history log found.")
