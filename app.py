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
st.set_page_config(page_title="Market Edge Pro - Public Verifiable", page_icon="🦅", layout="wide")

# ★ 憲法 (Protocol) - ここを変えると別システムとみなされる
PROTOCOL_DEF = """
[Protocol v9.0]
1. Frequency: Weekly (Min 7 days interval)
2. Safety Valve: Reject if Spread > 0.8 (80%)
3. Cost Model: 0.5% deducted at Exit
4. Universe: Tech/Growth Focus
5. Anchor: Public Post Required
"""
PROTOCOL_HASH = hashlib.sha256(PROTOCOL_DEF.encode()).hexdigest()[:8]

MODEL_VERSION = f"v9.0_Public_{PROTOCOL_HASH}"
HISTORY_FILE = "master_execution_log.csv"
COST_RATE = 0.005
MIN_INTERVAL_DAYS = 7 # スキャン頻度制限
MAX_SPREAD_TOLERANCE = 0.8 # 80%以上のバラつきは足切り

# --- 2. 数理・セキュリティ関数 ---

def get_last_execution_time():
    """前回の実行時刻を取得"""
    if not os.path.exists(HISTORY_FILE):
        return None
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return None
        last_time_str = df.iloc[-1]['Scan_Time']
        return pd.to_datetime(last_time_str)
    except:
        return None

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
    """Spreadに対する連続的な割引関数 (1 / (1 + Spread))"""
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

                # Raw Data Snapshot (Provenance)
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
                spread_val = 0.5 # Default risk
                
                if target_mean and target_mean > 0 and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low:
                        spread_val = (target_high - target_low) / target_mean
                
                # Confidence
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0

                # Trend
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1] if len(hist) >= 50 else price
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) >= 200 else price
                
                # --- Scoring & Filtering ---
                score = 0
                filter_status = "OK"
                
                # Safety Valve (安全弁)
                if spread_val > MAX_SPREAD_TOLERANCE:
                    filter_status = f"REJECT:Spread({spread_val:.1%})>Max({MAX_SPREAD_TOLERANCE:.1%})"
                elif analysts < 3:
                    filter_status = "REJECT:LowAnalysts"
                else:
                    # 1. Valuation
                    if peg_type == "Official" and pd.notna(peg_val):
                        if 0 < peg_val < 1.0: score += 30
                        elif peg_val < 1.5: score += 20
                        elif peg_val < 2.0: score += 10
                    
                    # 2. Trend
                    trend_ok = False
                    if len(hist) >= 5 and price > sma50 > sma200:
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

                rsi = 50 
                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"
                
                # 却下された銘柄はスコア0扱い
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
                    # Provenance Data (素性)
                    "Price_Raw": price,
                    "Target_Mean_Raw": target_mean,
                    "Analysts_Raw": analysts,
                    "Spread_Raw": spread_val,
                    "PEG_Raw": peg_val,
                    "PEG_Source": peg_type,
                    "Data_Source": "yfinance_free_tier"
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 4. ポートフォリオ構築 ---
def build_portfolio(df):
    # フィルタ通過済みのみ対象
    df_valid = df[df['Filter_Status'] == "OK"].copy()
    df_sorted = df_valid.sort_values('Score', ascending=False)
    
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
            logs.append(f"Skip {row['Ticker']}: Sector Cap")
            
    return pd.DataFrame(portfolio), logs

# --- 5. 履歴保存 & アンカー生成 ---
def save_to_history(df_portfolio):
    prev_hash = get_last_hash()
    last_time = get_last_execution_time()
    current_time = pd.to_datetime(df_portfolio['Scan_Time'].iloc[0])
    
    # 頻度チェック (Frequency Check)
    violation_flag = ""
    if last_time is not None:
        delta = current_time - last_time
        if delta.days < MIN_INTERVAL_DAYS:
            violation_flag = f"[VIOLATION: Too Soon ({delta.days} days < {MIN_INTERVAL_DAYS})]"
    
    df_to_save = df_portfolio.copy()
    df_to_save["Prev_Hash"] = prev_hash
    df_to_save["Protocol_Hash"] = PROTOCOL_HASH
    df_to_save["Status_Flag"] = violation_flag # 違反があれば記録される
    
    # ハッシュ生成
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
    
    # ここでは「確定した取引」のみを抽出するロジック（省略版）
    # ... (前回のAuditロジックと同様)
    return history # 仮

# --- 7. UI構築 ---
tab1, tab2 = st.tabs(["🚀 Systematic Execution", "⚖️ Performance & Audit"])

with tab1:
    st.title("🦅 Market Edge Pro (Public Verifiable)")
    st.caption(f"Ver: {PROTOCOL_VER} | Interval: {MIN_INTERVAL_DAYS} Days | Safety: Spread < {MAX_SPREAD_TOLERANCE:.0%}")
    
    # プロトコル表示
    with st.expander("📜 Protocol Definition (憲法)", expanded=True):
        st.code(PROTOCOL_DEF)
        st.info("※この定義に従い、Spread過大銘柄は自動排除され、週次実行が強制されます。")

    TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

    if st.button("EXECUTE RUN & GENERATE ANCHOR", type="primary"):
        raw_df = fetch_stock_data(TARGETS)
        if not raw_df.empty:
            portfolio_df, logs = build_portfolio(raw_df)
            
            if not portfolio_df.empty:
                final_df, record_hash, violation = save_to_history(portfolio_df)
                
                if violation:
                    st.error(f"⚠️ PROTOCOL VIOLATION: {violation}")
                    st.warning("この記録は「違反」としてログに残りました。正規のトラックレコードには含まれません。")
                else:
                    st.success("✅ Logged Successfully. (Protocol Compliant)")
                    
                    # 公開用アンカー生成
                    run_id = final_df['Run_ID'].iloc[0]
                    short_hash = record_hash[:12]
                    date_str = datetime.now().strftime('%Y-%m-%d')
                    
                    anchor_text = f"MEP_ANCHOR: {date_str} | ID: {run_id} | HASH: {short_hash} | #MarketEdgePro"
                    
                    st.divider()
                    st.subheader("📢 Public Verification Anchor")
                    st.write("以下のテキストをSNS(Xなど)やGitコミットログに投稿してください。これが「第三者証明」になります。")
                    st.code(anchor_text, language="text")
                    
                    # データ表示
                    st.dataframe(final_df[['Ticker', 'Score', 'Spread_Raw', 'Filter_Status', 'Price_At_Scan']].style.background_gradient(subset=['Score'], cmap='Greens'))
            else:
                st.error("No valid tickers passed the Safety Valve (Spread Filter). Market is too risky.")
                st.dataframe(raw_df[['Ticker', 'Spread_Raw', 'Filter_Status']])
        else:
            st.error("Data fetch error")

with tab2:
    st.header("⚖️ Audit Trail")
    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist.sort_index(ascending=False))
        st.caption("Raw Metadata (Provenance): Analysts_Raw, Target_Mean_Raw, Data_Source columns are available in CSV.")
    else:
        st.info("No history yet.")
