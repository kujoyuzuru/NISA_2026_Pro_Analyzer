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
st.set_page_config(page_title="Market Edge Pro - Integrity", page_icon="🦅", layout="wide")

# プロトコル定義 (憲法)
PROTOCOL_VER = "v8.0_Integrity_Audit"
COST_RATE = 0.005 # 往復0.5% (Exit時に控除)
HOLDING_DAYS = 20 # 営業日換算
HISTORY_FILE = "master_execution_log.csv"

# --- 2. 数理・セキュリティ関数 ---

def get_file_integrity_hash():
    """履歴ファイル全体のハッシュ(Commitment ID)を生成"""
    if not os.path.exists(HISTORY_FILE):
        return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        bytes = f.read()
        return hashlib.sha256(bytes).hexdigest()[:16] # 16桁のショートコード

def calculate_row_hash(prev_hash, row_content):
    """行ごとの連鎖ハッシュ"""
    combined = f"{prev_hash}|{row_content}"
    return hashlib.sha256(combined.encode()).hexdigest()

def decay_function(spread_val):
    return 1.0 / (1.0 + spread_val)

def calculate_net_return(entry, exit, cost_rate):
    """
    厳格なリターン計算式
    (Exit / Entry) * (1 - Cost) - 1
    ※コストは資産取り崩しとして適用
    """
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
                if peg_type == "Official" and pd.notna(peg_val):
                    if 0 < peg_val < 1.0: score += 30
                    elif peg_val < 1.5: score += 20
                    elif peg_val < 2.0: score += 10
                
                trend_ok = False
                if len(hist) >= 5 and price > sma50 > sma200:
                    score += 30
                    trend_ok = True
                
                if upside_val > 0:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    if base_upside > 0:
                        spread_discount = decay_function(spread_val)
                        final_factor = spread_discount * conf_factor
                        score += int(base_upside * final_factor)

                rsi = 50 # SImplified for speed
                
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
                    "PEG_Type": peg_type,
                    "Spread": spread_val,
                    "Upside": upside_val,
                    "Data_Source": "yfinance_api",
                    "Protocol_Ver": PROTOCOL_VER
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 4. ポートフォリオ構築 ---
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

# --- 5. 履歴保存 (Hash Chain) ---
def save_to_history(df_portfolio):
    # 前のハッシュを取得
    if os.path.exists(HISTORY_FILE):
        try:
            prev_df = pd.read_csv(HISTORY_FILE)
            prev_hash = prev_df.iloc[-1]['Record_Hash']
        except:
            prev_hash = "GENESIS"
    else:
        prev_hash = "GENESIS"
    
    df_to_save = df_portfolio.copy()
    
    # メタデータ
    df_to_save["Prev_Hash"] = prev_hash
    
    # 今回のハッシュ生成
    content = df_to_save[['Run_ID', 'Ticker', 'Score', 'Scan_Time']].to_string()
    new_hash = calculate_row_hash(prev_hash, content)
    df_to_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_to_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_to_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return df_to_save

# --- 6. 監査機能 (Closed Trade Only) ---
def audit_performance():
    if not os.path.exists(HISTORY_FILE):
        return None, None

    history = pd.read_csv(HISTORY_FILE)
    if history.empty: return None, None
    
    run_ids = history['Run_ID'].unique()
    closed_trades = []
    active_trades = []
    
    progress = st.progress(0)
    
    for i, rid in enumerate(run_ids):
        run_data = history[history['Run_ID'] == rid]
        scan_time = pd.to_datetime(run_data['Scan_Time'].iloc[0])
        
        # プロトコル: EntryはScan翌日、ExitはScan+1+20日
        # 営業日計算は複雑なので、簡易的にカレンダー日で判定
        entry_date = scan_date = scan_time.date() + timedelta(days=1)
        exit_date_est = entry_date + timedelta(days=30) # Approx 20 trading days
        
        today = datetime.now().date()
        
        # 1. まだEntry日が来ていない -> Ignored
        if entry_date > today:
            continue
            
        # 2. 期間終了済み (Closed)
        is_closed = today >= exit_date_est
        
        # バッチ取得で高速化したいが、ここでは個別取得
        # (実運用では yf.download(..., group_by='ticker') を推奨)
        
        run_pnl = []
        
        for _, row in run_data.iterrows():
            ticker = row['Ticker']
            try:
                # 必要な期間のデータを取得
                df_price = yf.Ticker(ticker).history(start=entry_date, end=exit_date_est + timedelta(days=5))
                
                if df_price.empty: continue
                
                # Entry Price (期間初日のOpen)
                real_entry = df_price['Open'].iloc[0]
                
                if is_closed:
                    # Exit Price (20日目のOpen、あるいは期間末のOpen)
                    # インデックスエラー回避
                    idx = min(len(df_price)-1, 20) 
                    real_exit = df_price['Open'].iloc[idx]
                    
                    # 厳格なコスト控除リターン
                    net_ret = calculate_net_return(real_entry, real_exit, COST_RATE)
                    
                    closed_trades.append({
                        "Run_ID": rid,
                        "Ticker": ticker,
                        "Entry_Date": entry_date,
                        "Exit_Date": df_price.index[idx].date(),
                        "Entry_Price": real_entry,
                        "Exit_Price": real_exit,
                        "Net_Return": net_ret
                    })
                else:
                    # Active (含み損益)
                    curr_price = df_price['Close'].iloc[-1]
                    unrealized_ret = calculate_net_return(real_entry, curr_price, COST_RATE)
                    
                    active_trades.append({
                        "Run_ID": rid,
                        "Ticker": ticker,
                        "Entry_Date": entry_date,
                        "Entry_Price": real_entry,
                        "Current_Price": curr_price,
                        "Unrealized_Net": unrealized_ret
                    })
            except:
                continue
        
        progress.progress((i + 1) / len(run_ids))
        
    return pd.DataFrame(closed_trades), pd.DataFrame(active_trades)

# --- 7. UI構築 ---
tab1, tab2 = st.tabs(["🚀 Execution (Log & Anchor)", "⚖️ Integrity Audit"])

with tab1:
    st.title("🦅 Market Edge Pro (Integrity)")
    st.caption(f"Ver: {PROTOCOL_VER} | Cost: {COST_RATE:.1%} (Round-Trip) | Chain: Active")
    
    # アンカー情報の表示 (これが外部保存すべきID)
    integrity_hash = get_file_integrity_hash()
    if integrity_hash != "NO_DATA":
        st.info(f"🔒 **Commitment Anchor:** `{integrity_hash}`")
        st.caption("※このコードを手帳やSNSに記録してください。ファイルが改変されると、このコードが変わります。")

    TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

    if st.button("EXECUTE RUN", type="primary"):
        raw_df = fetch_stock_data(TARGETS)
        if not raw_df.empty:
            portfolio_df, logs = build_portfolio(raw_df)
            final_df = save_to_history(portfolio_df)
            
            st.success("✅ Logged. Update your anchor.")
            
            # 最新のアンカーを再計算して表示
            new_anchor = get_file_integrity_hash()
            st.code(new_anchor, language="text", label="New Commitment Anchor (Copy this)")
            
            if logs:
                for l in logs: st.warning(l)
            
            st.dataframe(final_df[['Ticker', 'Score', 'Spread', 'PEG_Val']].style.background_gradient(subset=['Score'], cmap='Greens'))
        else:
            st.error("Data Error")

with tab2:
    st.header("⚖️ Integrity Audit (Closed Trades Only)")
    st.caption("確定した取引（20営業日経過）のみを集計します。含み益はここには含まれません。")
    
    if st.button("🔄 Audit Performance"):
        df_closed, df_active = audit_performance()
        
        if df_closed is not None and not df_closed.empty:
            # 資産曲線の作成
            df_closed = df_closed.sort_values('Exit_Date')
            df_closed['Cumulative_Return'] = (1 + df_closed['Net_Return']).cumprod()
            
            # ドローダウン
            df_closed['Peak'] = df_closed['Cumulative_Return'].cummax()
            df_closed['Drawdown'] = (df_closed['Cumulative_Return'] - df_closed['Peak']) / df_closed['Peak']
            max_dd = df_closed['Drawdown'].min()
            total_ret = df_closed['Cumulative_Return'].iloc[-1] - 1
            
            # KPI表示
            k1, k2, k3 = st.columns(3)
            k1.metric("Realized Return", f"{total_ret:.2%}")
            k2.metric("Max Drawdown", f"{max_dd:.2%}", delta_color="inverse")
            k3.metric("Closed Trades", f"{len(df_closed)}")
            
            # チャート
            
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=df_closed['Exit_Date'], y=df_closed['Cumulative_Return'], mode='lines+markers', name='Equity (Net)'))
            st.plotly_chart(fig, use_container_width=True)
            
            st.subheader("Closed Trade Log")
            st.dataframe(df_closed)
        else:
            st.warning("No closed trades found yet. (Wait 20 days after first run)")
            
        if df_active is not None and not df_active.empty:
            st.divider()
            st.subheader("Active Positions (Unrealized)")
            st.dataframe(df_active)
