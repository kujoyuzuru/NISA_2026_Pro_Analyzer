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

# 定数
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v15.0_30Sec_Decision"
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

# --- 3. 分析エンジン (ロジック強化版) ---

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 市場データ・ファンダメンタルズ詳細分析中..."):
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
                
                # --- 1. 割安性 (Valuation) : 3段構えの判定 ---
                # データ欠損(nan)をユーザーに見せないためのフォールバックロジック
                peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                val_score = 0
                val_msg = "データ不足"
                used_metric = "None"
                metric_val = 0.0

                # Plan A: 公式PEG
                if peg is not None:
                    used_metric = "PEG"
                    metric_val = peg
                
                # Plan B: 推定PEG (PE / Growth)
                elif fwd_pe is not None and growth is not None and growth > 0:
                    try:
                        est_peg = fwd_pe / (growth * 100) 
                        used_metric = "PEG(est)"
                        metric_val = est_peg
                    except: pass
                
                # 判定ロジック (PEG基準)
                if used_metric.startswith("PEG"):
                    if metric_val < 1.0: val_score = 30; val_msg = f"超割安 ({used_metric}:{metric_val:.2f})"
                    elif metric_val < 1.5: val_score = 20; val_msg = f"割安 ({used_metric}:{metric_val:.2f})"
                    elif metric_val < 2.0: val_score = 10; val_msg = f"適正 ({used_metric}:{metric_val:.2f})"
                    else: val_msg = f"割高圏 ({used_metric}:{metric_val:.2f})"
                
                # Plan C: 予想PER単体評価 (最終手段)
                elif fwd_pe is not None:
                    used_metric = "PER"
                    metric_val = fwd_pe
                    if fwd_pe < 20: val_score = 20; val_msg = f"割安圏 (PER:{fwd_pe:.1f})"
                    elif fwd_pe < 35: val_score = 10; val_msg = f"適正圏 (PER:{fwd_pe:.1f})"
                    else: val_msg = f"割高感 (PER:{fwd_pe:.1f})"
                else:
                    val_msg = "判断材料なし (中立)"

                # --- 2. トレンド (Trend) ---
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else price
                
                trend_score = 0
                trend_msg = "下降/レンジ"
                if price > sma50 > sma200: trend_score = 30; trend_msg = "上昇トレンド"
                elif price > sma50: trend_score = 15; trend_msg = "短期上昇"
                
                # --- 3. 需給・期待 (Consensus) ---
                target_mean = info.get('targetMeanPrice', 0)
                if not target_mean: target_mean = price # ターゲットなし対策
                    
                upside = (target_mean - price) / price
                
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
                
                # --- 4. タイミング (RSI) & Action ---
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # Action判定
                dist_to_sma = (price - sma50) / price
                
                action = "WAIT" 
                reason = "スコア不足"
                
                if safety_status != "OK":
                    action = "AVOID"
                    reason = "リスク過多 (Spread/Data)"
                elif total_score >= 40: # 合格ライン
                    # スコア良し。タイミング判定
                    if dist_to_sma < 0.08 and rsi < 75: 
                        action = "ENTRY"
                        reason = f"好条件 + 押し目水準 (乖離 {dist_to_sma:.1%})"
                    elif dist_to_sma >= 0.08 or rsi >= 75:
                        action = "WATCH"
                        reason = f"過熱感あり (乖離 {dist_to_sma:.1%} / RSI {rsi:.0f})"
                    else:
                        action = "WAIT"
                        reason = "モメンタム不足"
                else:
                    action = "WAIT"
                    reason = "基礎スコア不足"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Sector": sector,
                    "Price": price,
                    "Total_Score": total_score,
                    "Action": action, 
                    "Reason": reason,
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

# --- 4. UI構築 ---

st.sidebar.title("🦅 Menu")
mode = st.sidebar.radio("モード", ["🚀 30秒スキャナー", "⚙️ 管理室 (ログ・監査)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "🚀 30秒スキャナー":
    st.title("🦅 Market Edge Pro")
    st.caption("毎日30秒で「入る」か「待つ」かを決めるためのツール")
    
    if st.button("🔍 市場を分析する", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            log_execution(df)

            # --- 結論ファースト ---
            
            # 1. ENTRY: 今すぐ入るべき銘柄
            entries = df[df['Action'] == "ENTRY"].sort_values('Total_Score', ascending=False)
            if not entries.empty:
                st.success(f"🚀 **即エントリー候補 ({len(entries)}銘柄)**")
                for _, row in entries.iterrows():
                    # 非常にシンプルなカード
                    with st.container():
                        c1, c2, c3 = st.columns([3, 2, 2])
                        with c1:
                            st.markdown(f"### **{row['Ticker']}**")
                            st.caption(f"{row['Name']}")
                        with c2:
                            st.metric("現在値", f"${row['Price']:.2f}")
                        with c3:
                            st.metric("目安(SMA50)", f"${row['Buy_Zone']:.2f}", f"乖離 {(row['Price']-row['Buy_Zone'])/row['Price']:.1%}")
                        
                        st.info(f"💡 **理由:** {row['Trend_Msg']} かつ {row['Val_Msg']}。{row['Reason']}")
                        st.divider()
            else:
                st.info("ℹ️ 本日、即エントリー条件を満たす安全な銘柄はありません。")

            # 2. WATCH: 条件待ち
            watches = df[df['Action'] == "WATCH"].sort_values('Total_Score', ascending=False)
            if not watches.empty:
                with st.expander(f"👀 **監視リスト - 条件待ち ({len(watches)}銘柄)**", expanded=True):
                    for _, row in watches.iterrows():
                        c1, c2 = st.columns([3, 2])
                        with c1:
                            st.write(f"**{row['Ticker']}** (${row['Price']:.2f})")
                            st.caption(f"理由: {row['Reason']}")
                        with c2:
                            # 具体的なアクション条件を表示
                            target_price = row['Buy_Zone']
                            st.warning(f"⏰ **待機:** ${target_price:.2f} まで落ちたら拾う")

            # 3. AVOID: 除外
            waits = df[df['Action'].isin(["WAIT", "AVOID"])]
            with st.expander(f"✋ **対象外・除外 ({len(waits)}銘柄)**"):
                st.dataframe(waits[['Ticker', 'Action', 'Reason', 'Val_Msg']])
                
        else:
            st.error("データ取得エラー")

else:
    # --- 管理室 (裏側) ---
    st.title("⚙️ 管理室 (Audit Dashboard)")
    st.info("ここは過去の記録を検証するためのバックヤードです。")
    
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        
        # サマリーダッシュボード
        st.subheader("📊 実行サマリー")
        last_run = hist_df.iloc[-1]
        
        c1, c2, c3 = st.columns(3)
        c1.metric("最終実行", last_run['Scan_Time'][:16])
        c2.metric("総記録数", len(hist_df))
        c3.metric("最新ハッシュ (末尾)", last_run['Record_Hash'][-6:])
        
        st.divider()
        
        # 詳細ログ
        st.subheader("📜 Raw Execution Log")
        # 互換性処理
        if 'Violation' in hist_df.columns: hist_df.rename(columns={'Violation': 'Note'}, inplace=True)
        if 'Note' not in hist_df.columns: hist_df['Note'] = "-"
            
        st.dataframe(hist_df.sort_index(ascending=False))
        
        st.caption(f"System Version: {PROTOCOL_VER}")
        st.caption(f"Validation Code: {get_verification_code()}")
    else:
        st.write("履歴データなし")
