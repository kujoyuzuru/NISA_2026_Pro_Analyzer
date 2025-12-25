import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import uuid
import os
import hashlib

# --- 1. システム設定 & 定数定義 ---
st.set_page_config(page_title="Market Edge Pro - Final", page_icon="🦅", layout="wide")

# ★ プロトコル定数
PROTOCOL_VER = "v10.0_Final_Protocol"
HISTORY_FILE = "master_execution_log.csv"

# パラメータ設定 (★テスト用に制限を解除しました)
COST_RATE = 0.005          # 往復コスト 0.5%
MIN_INTERVAL_DAYS = 0      # ★テスト用: 0日に設定（連打可能）
MAX_SPREAD_TOLERANCE = 0.8 # Spread 80%以上は強制排除
PORTFOLIO_SIZE = 5         # ポートフォリオ銘柄数
MAX_SECTOR_ALLOCATION = 2  # 1セクターあたりの最大数

# --- 2. 数理・セキュリティ関数 ---

def get_last_execution_time():
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return None
        last_time_str = df.iloc[-1]['Scan_Time']
        return pd.to_datetime(last_time_str)
    except:
        return None

def get_file_integrity_hash():
    if not os.path.exists(HISTORY_FILE):
        return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        bytes = f.read()
        return hashlib.sha256(bytes).hexdigest()[:16]

def calculate_chain_hash(prev_hash, content_string):
    combined = f"{prev_hash}|{content_string}"
    return hashlib.sha256(combined.encode()).hexdigest()

def get_last_hash():
    if not os.path.exists(HISTORY_FILE):
        return "GENESIS"
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return "GENESIS"
        return df.iloc[-1]['Record_Hash']
    except:
        return "BROKEN"

def decay_function(spread_val):
    return 1.0 / (1.0 + spread_val)

def calculate_net_return(entry, exit, cost_rate):
    if entry == 0: return 0.0
    gross_return = exit / entry
    net_return = gross_return * (1.0 - cost_rate) - 1.0
    return net_return

# --- 3. データ取得ロジック ---

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.status("🦅 データ取得・プロトコル適合チェック中...", expanded=True) as status:
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

                price = info.get('currentPrice', hist['Close'].iloc[-1])
                sector = info.get('sector', 'Unknown')
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
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1] if len(hist) >= 50 else price
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) >= 200 else price
                
                score = 0
                filter_status = "OK"
                
                if spread_val > MAX_SPREAD_TOLERANCE:
                    filter_status = f"REJECT:Spread({spread_val:.1%})>Limit"
                elif analysts < 3:
                    filter_status = "REJECT:LowAnalysts"
                else:
                    if peg_type == "Official" and pd.notna(peg_val):
                        if 0 < peg_val < 1.0: score += 30
                        elif peg_val < 1.5: score += 20
                        elif peg_val < 2.0: score += 10
                    
                    if len(hist) >= 5 and price > sma50 > sma200:
                        score += 30
                    
                    if upside_val > 0:
                        base_upside = 0
                        if upside_val > 0.2: base_upside = 20
                        elif upside_val > 0.1: base_upside = 10
                        if base_upside > 0:
                            spread_discount = decay_function(spread_val)
                            final_factor = spread_discount * conf_factor
                            score += int(base_upside * final_factor)

                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"
                
                if "REJECT" in filter_status:
                    score = 0
                    grade = "REJECT"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Sector": sector,
                    "Score": int(score),
                    "Filter_Status": filter_status,
                    "Price_At_Scan": price,
                    "Spread_Raw": spread_val,
                    "PEG_Source": peg_type
                })
            except Exception:
                continue
        status.update(label="✅ Analysis Complete", state="complete", expanded=False)
    return pd.DataFrame(data_list)

# --- 4. ポートフォリオ構築 ---
def build_portfolio(df):
    df_valid = df[df['Filter_Status'] == "OK"].copy()
    df_sorted = df_valid.sort_values('Score', ascending=False)
    portfolio = []
    sector_counts = {}
    logs = []
    
    for _, row in df_sorted.iterrows():
        if len(portfolio) >= PORTFOLIO_SIZE: break
        sec = row['Sector']
        cnt = sector_counts.get(sec, 0)
        if cnt < MAX_SECTOR_ALLOCATION:
            portfolio.append(row)
            sector_counts[sec] = cnt + 1
        else:
            logs.append(f"Skip {row['Ticker']}: Sector Limit ({sec})")
    return pd.DataFrame(portfolio), logs

# --- 5. 履歴保存 ---
def save_to_history(df_portfolio):
    prev_hash = get_last_hash()
    last_time = get_last_execution_time()
    current_time = pd.to_datetime(df_portfolio['Scan_Time'].iloc[0])
    
    violation_flag = ""
    if last_time is not None:
        delta = current_time - last_time
        if delta.days < MIN_INTERVAL_DAYS:
            violation_flag = f"VIOLATION: Too Soon ({delta.days} days)"
    
    df_to_save = df_portfolio.copy()
    df_to_save["Prev_Hash"] = prev_hash
    df_to_save["Protocol_Ver"] = PROTOCOL_VER
    df_to_save["Status_Flag"] = violation_flag
    
    content = df_to_save[['Run_ID', 'Ticker', 'Score', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_to_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_to_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_to_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return df_to_save, new_hash, violation_flag

# --- 6. 監査機能 ---
def audit_performance():
    if not os.path.exists(HISTORY_FILE): return None
    history = pd.read_csv(HISTORY_FILE)
    if history.empty: return None
    
    valid_history = history[history['Status_Flag'].isna() | (history['Status_Flag'] == "")]
    if valid_history.empty: return None
    
    run_ids = valid_history['Run_ID'].unique()
    closed_trades = []
    
    progress_bar = st.progress(0)
    
    for i, rid in enumerate(run_ids):
        run_data = valid_history[valid_history['Run_ID'] == rid]
        scan_time = pd.to_datetime(run_data['Scan_Time'].iloc[0])
        entry_date = scan_time.date() + timedelta(days=1)
        exit_date_est = entry_date + timedelta(days=30)
        
        today = datetime.now().date()
        if today < exit_date_est: continue
            
        for _, row in run_data.iterrows():
            ticker = row['Ticker']
            try:
                df_price = yf.Ticker(ticker).history(start=entry_date, end=exit_date_est + timedelta(days=5))
                if df_price.empty: continue
                real_entry = df_price['Open'].iloc[0]
                idx = min(len(df_price)-1, 20)
                real_exit = df_price['Open'].iloc[idx]
                net_ret = calculate_net_return(real_entry, real_exit, COST_RATE)
                
                closed_trades.append({
                    "Run_ID": rid,
                    "Ticker": ticker,
                    "Exit_Date": df_price.index[idx].date(),
                    "Net_Return": net_ret
                })
            except:
                continue
        progress_bar.progress((i + 1) / len(run_ids))
        
    return pd.DataFrame(closed_trades)

# --- 7. UI構築 ---
tab1, tab2 = st.tabs(["🚀 Execution & Anchor", "⚖️ Performance Audit"])

with tab1:
    st.title("🦅 Market Edge Pro (Public Verifiable)")
    st.caption(f"Ver: {PROTOCOL_VER} | Interval: {MIN_INTERVAL_DAYS} Days (Test Mode) | Safety: Spread < {MAX_SPREAD_TOLERANCE:.0%}")
    
    anchor = get_file_integrity_hash()
    if anchor != "NO_DATA":
        st.info(f"🔒 **Commitment Anchor (Current):** `{anchor}`")

    TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

    if st.button("EXECUTE RUN", type="primary"):
        raw_df = fetch_stock_data(TARGETS)
        if not raw_df.empty:
            portfolio_df, logs = build_portfolio(raw_df)
            
            if not portfolio_df.empty:
                final_df, record_hash, violation = save_to_history(portfolio_df)
                
                if violation:
                    st.error(f"⚠️ PROTOCOL VIOLATION: {violation}")
                else:
                    st.success("✅ Logged Successfully. (Protocol Compliant)")
                    new_anchor = get_file_integrity_hash()
                    
                    st.divider()
                    st.subheader("📢 New Public Anchor")
                    st.caption("Copy this text and post it publicly:")
                    # 修正済み: label引数なし
                    anchor_text = f"MEP_ANCHOR | Date:{datetime.now().date()} | Hash:{new_anchor}"
                    st.code(anchor_text, language="text")
                    
                    if logs:
                        for l in logs: st.warning(l)
                    st.dataframe(final_df[['Ticker', 'Score', 'Spread_Raw', 'Price_At_Scan']].style.background_gradient(subset=['Score'], cmap='Greens'))
            else:
                st.error("No valid tickers passed the Safety Valve.")
                st.dataframe(raw_df[['Ticker', 'Filter_Status', 'Spread_Raw']])
        else:
            st.error("Data fetch error")

with tab2:
    st.header("⚖️ Audit Trail (Closed Trades)")
    if st.button("🔄 Audit Performance"):
        df_closed = audit_performance()
        if df_closed is not None and not df_closed.empty:
            df_closed = df_closed.sort_values('Exit_Date')
            df_closed['Equity_Curve'] = (1 + df_closed['Net_Return']).cumprod()
            total_ret = df_closed['Equity_Curve'].iloc[-1] - 1
            peak = df_closed['Equity_Curve'].cummax()
            max_dd = ((df_closed['Equity_Curve'] - peak) / peak).min()
            
            c1, c2, c3 = st.columns(3)
            c1.metric("Total Return", f"{total_ret:.2%}")
            c2.metric("Max Drawdown", f"{max_dd:.2%}", delta_color="inverse")
            c3.metric("Trades", len(df_closed))
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_closed['Exit_Date'], y=df_closed['Equity_Curve'], mode='lines+markers', name='Equity'))
            st.plotly_chart(fig, use_container_width=True)
            st.dataframe(df_closed)
        else:
            st.warning("No closed trades found (or no history).")
