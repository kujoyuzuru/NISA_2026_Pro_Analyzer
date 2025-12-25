import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import uuid
import os
import hashlib

# --- 1. システム設定 & 定数 ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

# ★ プロトコル定数 (裏側の憲法)
PROTOCOL_VER = "v11.1_Compatibility_Fixed"
HISTORY_FILE = "master_execution_log.csv"
COST_RATE = 0.005          
MIN_INTERVAL_DAYS = 7      
MAX_SPREAD_TOLERANCE = 0.8 
PORTFOLIO_SIZE = 5         
MAX_SECTOR_ALLOCATION = 2  

# --- 2. 計算・セキュリティ関数 (裏方の仕事) ---

def get_last_execution_time():
    if not os.path.exists(HISTORY_FILE): return None
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return None
        return pd.to_datetime(df.iloc[-1]['Scan_Time'])
    except:
        return None

def get_integrity_anchor():
    """公開用検証コード (Anchor) を生成"""
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:16]

def calculate_chain_hash(prev_hash, content):
    combined = f"{prev_hash}|{content}"
    return hashlib.sha256(combined.encode()).hexdigest()

def get_last_hash():
    if not os.path.exists(HISTORY_FILE): return "GENESIS"
    try:
        df = pd.read_csv(HISTORY_FILE)
        return df.iloc[-1]['Record_Hash'] if not df.empty else "GENESIS"
    except:
        return "BROKEN"

def decay_function(spread):
    return 1.0 / (1.0 + spread)

# --- 3. データ取得・分析ロジック ---

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 市場データを分析中..."):
        for i, ticker in enumerate(tickers):
            try:
                stock = yf.Ticker(ticker)
                try: info = stock.info
                except: continue 

                hist = stock.history(period="5d")
                if hist.empty: continue

                price = info.get('currentPrice', hist['Close'].iloc[-1])
                sector = info.get('sector', 'Unknown')
                
                # Valuation
                peg_type = "-"
                peg_val = np.nan
                if info.get('pegRatio'):
                    peg_val = info.get('pegRatio')
                    peg_type = "Official"
                
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
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1] if len(hist) >= 50 else price
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) >= 200 else price
                
                # Scoring
                score = 0
                filter_status = "OK"
                
                # Safety Valve
                if spread_val > MAX_SPREAD_TOLERANCE:
                    filter_status = "REJECT_RISK"
                elif analysts < 3:
                    filter_status = "REJECT_DATA"
                else:
                    if peg_type == "Official" and pd.notna(peg_val):
                        if 0 < peg_val < 1.0: score += 30
                        elif peg_val < 1.5: score += 20
                        elif peg_val < 2.0: score += 10
                    
                    if len(hist) >= 5 and price > sma50 > sma200:
                        score += 30
                    
                    if upside_val > 0:
                        base = 20 if upside_val > 0.2 else (10 if upside_val > 0.1 else 0)
                        if base > 0:
                            score += int(base * decay_function(spread_val) * conf_factor)

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Sector": sector,
                    "Score": int(score),
                    "Filter_Status": filter_status,
                    "Price": price,
                    "Spread": spread_val,
                    "PEG": peg_val
                })
            except: continue
            
    return pd.DataFrame(data_list)

def build_portfolio(df):
    df_valid = df[df['Filter_Status'] == "OK"].copy()
    df_sorted = df_valid.sort_values('Score', ascending=False)
    portfolio = []
    sector_counts = {}
    
    for _, row in df_sorted.iterrows():
        if len(portfolio) >= PORTFOLIO_SIZE: break
        sec = row['Sector']
        cnt = sector_counts.get(sec, 0)
        if cnt < MAX_SECTOR_ALLOCATION:
            portfolio.append(row)
            sector_counts[sec] = cnt + 1
            
    return pd.DataFrame(portfolio)

def save_to_history(df_portfolio):
    prev_hash = get_last_hash()
    last_time = get_last_execution_time()
    current_time = pd.to_datetime(df_portfolio['Scan_Time'].iloc[0])
    
    violation = ""
    if last_time is not None:
        delta = current_time - last_time
        if delta.days < MIN_INTERVAL_DAYS:
            violation = f"Too Soon ({delta.days} days)"
    
    df_save = df_portfolio.copy()
    df_save["Prev_Hash"] = prev_hash
    df_save["Violation"] = violation
    
    # Hash Chain
    content = df_save[['Run_ID', 'Ticker', 'Score', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return df_save, violation

# --- 4. 画面構築 ---

mode = st.sidebar.radio("📱 モード選択", ["🚀 投資判断 (メイン)", "👮‍♂️ 監査・検証 (上級者)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

# === モード A: 投資判断 ===
if mode == "🚀 投資判断 (メイン)":
    st.title("🦅 Market Edge Pro")
    st.caption("AIとアルゴリズムによる、客観的なポートフォリオ提案")
    
    st.info("👇 下のボタンを押すと、最新の市場データを分析し「今日のエントリー候補」を表示します。")
    
    if st.button("🚀 候補銘柄をスキャンする", type="primary"):
        df = fetch_stock_data(TARGETS)
        if not df.empty:
            portfolio = build_portfolio(df)
            
            if not portfolio.empty:
                save_to_history(portfolio)
                
                st.success("✅ 分析完了。以下の銘柄が抽出されました。")
                st.markdown("### 📋 本日の推奨ポートフォリオ")
                
                display_df = portfolio[['Ticker', 'Sector', 'Price', 'Score', 'PEG']].copy()
                display_df.columns = ['銘柄', 'セクター', '現在値($)', '総合スコア', '割安度(PEG)']
                
                st.dataframe(
                    display_df.style
                    .format({'現在値($)': '${:.2f}', '割安度(PEG)': '{:.2f}'})
                    .background_gradient(subset=['総合スコア'], cmap='Greens'),
                    use_container_width=True
                )
                
                st.divider()
                st.subheader("⚡ 次のアクション")
                st.warning(f"""
                1. **明日の市場オープン（始値）** で、上記5銘柄を等金額ずつ注文してください。
                2. そのまま **20営業日（約1ヶ月）** 保有します。
                3. 次回のチェックは **{MIN_INTERVAL_DAYS}日後** です。
                """)
            else:
                st.error("⚠️ 本日は基準を満たす安全な銘柄がありませんでした。")
        else:
            st.error("データ取得エラー。時間をおいて再試行してください。")

# === モード B: 監査・検証 ===
else:
    st.title("👮‍♂️ 監査・検証モード")
    st.caption("内部ログの健全性確認、改ざん検知、パフォーマンス分析")
    
    tab1, tab2 = st.tabs(["📜 実行ログ & アンカー", "📈 パフォーマンス分析"])
    
    with tab1:
        st.subheader("公開用検証コード (Anchor)")
        anchor = get_integrity_anchor()
        if anchor != "NO_DATA":
            st.code(anchor, language="text")
            st.caption("※このコードをSNS等に投稿することで、データの存在証明になります。")
        else:
            st.write("履歴データがありません。")
            
        st.divider()
        st.subheader("システム内部ログ (Raw Data)")
        if os.path.exists(HISTORY_FILE):
            hist_df = pd.read_csv(HISTORY_FILE)
            st.dataframe(hist_df.sort_index(ascending=False))
        else:
            st.info("ログファイルはまだ生成されていません。")

    with tab2:
        st.subheader("確定損益の分析 (Closed Trades)")
        
        if st.button("再集計を実行"):
            if os.path.exists(HISTORY_FILE):
                hist = pd.read_csv(HISTORY_FILE)
                
                # --- ★ 自動互換処理 (過去ログ対応) ---
                if 'Violation' not in hist.columns:
                    if 'Status_Flag' in hist.columns:
                        hist.rename(columns={'Status_Flag': 'Violation'}, inplace=True)
                    else:
                        hist['Violation'] = np.nan
                # ------------------------------------
                
                # NaNも空文字として扱う
                hist['Violation'] = hist['Violation'].fillna("")
                
                valid_runs = hist[hist['Violation'] == ""].groupby('Run_ID').first()
                
                if not valid_runs.empty:
                    st.metric("有効な実行回数", len(valid_runs))
                    st.info("詳細な資産曲線（Equity Curve）は、20営業日経過後にここに表示されます。")
                    st.dataframe(valid_runs[['Scan_Time', 'Record_Hash']])
                else:
                    st.warning("有効な（違反のない）実行記録がまだありません。")
            else:
                st.warning("履歴がありません。")
