import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import hashlib
import uuid

# --- 1. システム設定 ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

# ファイル・パラメータ定数
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v14.0_Action_First"
MIN_INTERVAL_DAYS = 7       
MAX_SPREAD_TOLERANCE = 0.8  
PORTFOLIO_SIZE = 5
MAX_SECTOR_ALLOCATION = 2

# --- 2. 裏方ロジック (監査・計算) ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

def get_last_hash():
    if not os.path.exists(HISTORY_FILE): return "GENESIS"
    try:
        df = pd.read_csv(HISTORY_FILE)
        return df.iloc[-1]['Record_Hash'] if not df.empty else "GENESIS"
    except:
        return "BROKEN"

def calculate_chain_hash(prev_hash, content):
    combined = f"{prev_hash}|{content}"
    return hashlib.sha256(combined.encode()).hexdigest()

def get_last_execution_time():
    if not os.path.exists(HISTORY_FILE): return None
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return None
        return pd.to_datetime(df.iloc[-1]['Scan_Time'])
    except:
        return None

def decay_function(spread):
    return 1.0 / (1.0 + spread)

# --- 3. 分析エンジン (ロジック) ---

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 市場をスキャン中..."):
        for i, ticker in enumerate(tickers):
            try:
                stock = yf.Ticker(ticker)
                try: info = stock.info
                except: continue 

                hist = stock.history(period="6mo")
                if hist.empty: continue

                # Basic
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                name = info.get('shortName', ticker)
                sector = info.get('sector', 'Unknown')
                
                # 1. 割安性 (Valuation)
                peg = info.get('pegRatio', np.nan)
                val_score = 0
                val_msg = "判定不可"
                
                if pd.notna(peg):
                    if peg < 1.0: val_score = 30; val_msg = "S (超割安)"
                    elif peg < 1.5: val_score = 20; val_msg = "A (割安)"
                    elif peg < 2.0: val_score = 10; val_msg = "B (適正)"
                    else: val_msg = "C (割高圏)"
                
                # 2. トレンド (Trend)
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else price
                
                trend_score = 0
                trend_msg = "下降/レンジ"
                if price > sma50 > sma200: trend_score = 30; trend_msg = "S (上昇トレンド)"
                elif price > sma50: trend_score = 15; trend_msg = "A (短期上昇)"
                
                # 3. 需給・期待 (Consensus)
                target_mean = info.get('targetMeanPrice', 0)
                upside = (target_mean - price) / price if target_mean else 0
                
                target_high = info.get('targetHighPrice', target_mean)
                target_low = info.get('targetLowPrice', target_mean)
                spread = (target_high - target_low) / target_mean if target_mean else 0.5
                
                analysts = info.get('numberOfAnalystOpinions', 0)
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0
                
                # 安全弁
                safety_status = "OK"
                if spread > MAX_SPREAD_TOLERANCE: safety_status = "REJECT_RISK"
                elif analysts < 3: safety_status = "REJECT_DATA"
                
                cons_score = 0
                if upside > 0:
                    base = 20 if upside > 0.2 else (10 if upside > 0.1 else 0)
                    cons_score = int(base * decay_function(spread) * conf_factor)
                
                total_score = val_score + trend_score + cons_score
                
                # 4. タイミング (RSI) & Action
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # --- 結論（Action）の判定 ---
                # SMA50との乖離
                dist_to_sma = (price - sma50) / price
                
                action = "WAIT" # デフォルト
                
                if safety_status != "OK":
                    action = "AVOID" # 除外
                elif total_score >= 50:
                    # スコア良し。タイミングは？
                    if -0.03 < dist_to_sma < 0.05 and rsi < 70:
                        action = "ENTRY" # 押し目かつ過熱なし
                    elif dist_to_sma >= 0.05 or rsi >= 70:
                        action = "WATCH" # 良いが高すぎる
                    else:
                        action = "WAIT" # まだ弱い
                else:
                    action = "WAIT" # スコア不足

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Sector": sector,
                    "Price": price,
                    "Total_Score": total_score,
                    "Action": action, # 結論
                    "Filter_Status": safety_status,
                    "Val_Msg": val_msg,
                    "Trend_Msg": trend_msg,
                    "Target": target_mean,
                    "Upside": upside,
                    "Buy_Zone": sma50,
                    "RSI": rsi,
                    "Spread": spread
                })
            except: continue
            
    return pd.DataFrame(data_list)

def log_execution(df_candidates):
    """実行ログ保存（裏方）"""
    prev_hash = get_last_hash()
    last_time = get_last_execution_time()
    current_time = pd.to_datetime(df_candidates['Scan_Time'].iloc[0])
    
    note = "Official"
    if last_time is not None and (current_time - last_time).days < MIN_INTERVAL_DAYS:
        note = "Practice"
    
    df_save = df_candidates.copy()
    df_save["Prev_Hash"] = prev_hash
    df_save["Note"] = note
    
    content = df_save[['Run_ID', 'Ticker', 'Total_Score', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return note == "Practice"

# --- 4. UI構築 (表: シンプル / 裏: 玄人) ---

# タブではなくサイドバーで完全に世界を分ける
st.sidebar.title("🦅 Menu")
mode = st.sidebar.radio("モード", ["🚀 市場スキャナー (判断)", "⚙️ 管理室 (記録・監査)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

# === 表の顔：判断支援 ===
if mode == "🚀 市場スキャナー (判断)":
    st.title("🦅 Market Edge Pro")
    st.caption("今日の「入るべき」と「待つべき」を即座に判断します。")
    
    if st.button("🔍 市場をスキャンする", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            # ログ保存 (裏でひっそりと)
            is_practice = log_execution(df)
            if is_practice:
                st.toast("練習モードで記録しました", icon="ℹ️")
            else:
                st.toast("公式記録として保存しました", icon="💾")

            # --- 結論ファーストで表示 ---
            
            # 1. ENTRY (今がチャンス)
            entries = df[df['Action'] == "ENTRY"].sort_values('Total_Score', ascending=False)
            if not entries.empty:
                st.subheader(f"🚀 今がチャンス ({len(entries)}銘柄)")
                st.caption("ファンダメンタルズが良好で、押し目（適正価格帯）にある銘柄です。")
                
                for _, row in entries.iterrows():
                    with st.container():
                        # カード風デザイン
                        st.markdown(f"#### **{row['Ticker']}** : {row['Name']}")
                        c1, c2, c3 = st.columns([2, 2, 1])
                        
                        with c1:
                            st.write(f"💰 **割安性:** {row['Val_Msg']}")
                            st.write(f"📈 **トレンド:** {row['Trend_Msg']}")
                        
                        with c2:
                            st.metric("現在株価", f"${row['Price']:.2f}")
                            st.write(f"**買い目安:** ${row['Buy_Zone']:.2f} 付近")
                            
                        with c3:
                            st.metric("スコア", f"{row['Total_Score']}")
                        
                        st.divider()

            # 2. WATCH (良いが高い)
            watches = df[df['Action'] == "WATCH"].sort_values('Total_Score', ascending=False)
            if not watches.empty:
                st.subheader(f"👀 監視リスト ({len(watches)}銘柄)")
                st.caption("モノは良いですが、少し過熱気味です。押し目を待ちましょう。")
                
                for _, row in watches.iterrows():
                    with st.expander(f"**{row['Ticker']}** (${row['Price']:.2f}) - 調整待ち"):
                        st.info(f"現在値 ${row['Price']:.2f} は、目安の ${row['Buy_Zone']:.2f} から離れています。")
                        st.write(f"RSI: {row['RSI']:.1f} (70以上は過熱)")
                        st.write(f"総合スコア: {row['Total_Score']}")

            # 3. WAIT/AVOID (今はパス)
            waits = df[df['Action'].isin(["WAIT", "AVOID"])]
            with st.expander(f"✋ 対象外・様子見 ({len(waits)}銘柄)"):
                st.dataframe(waits[['Ticker', 'Action', 'Total_Score', 'Val_Msg', 'Trend_Msg']])
                st.caption("スコア不足、またはリスク過多の銘柄です。")
                
        else:
            st.error("データ取得エラー")

# === 裏の顔：管理室 ===
else:
    st.title("⚙️ 管理室 (Audit & Logs)")
    st.info("ここは運用記録の検証、ハッシュ確認、生データのエクスポートを行うエンジニア向けの画面です。")
    
    tab1, tab2 = st.tabs(["📜 実行ログ", "🛡️ プロトコル定義"])
    
    with tab1:
        st.subheader("検証用ID (Verification Code)")
        st.code(get_verification_code(), language="text")
        st.caption("公開運用の際は、このコードを外部に記録してください。")
        
        st.divider()
        st.subheader("Raw Execution Log")
        if os.path.exists(HISTORY_FILE):
            hist_df = pd.read_csv(HISTORY_FILE)
            st.dataframe(hist_df.sort_index(ascending=False))
            
            # CSVダウンロード
            csv = hist_df.to_csv(index=False).encode('utf-8')
            st.download_button("📥 ログをCSVでダウンロード", csv, "market_edge_log.csv", "text/csv")
        else:
            st.write("履歴データなし")

    with tab2:
        st.subheader("System Constitution")
        st.code(f"""
        Protocol Version: {PROTOCOL_VER}
        Execution Interval: {MIN_INTERVAL_DAYS} days (Official)
        Safety Valve (Max Spread): {MAX_SPREAD_TOLERANCE:.0%}
        Portfolio Size: {PORTFOLIO_SIZE}
        Sector Limit: {MAX_SECTOR_ALLOCATION}
        """, language="yaml")
