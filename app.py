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
PROTOCOL_VER = "v18.0_Consistent_Logic"
MIN_INTERVAL_DAYS = 7       
MAX_SPREAD_TOLERANCE = 0.8  
PORTFOLIO_SIZE = 5
MAX_SECTOR_ALLOCATION = 2

# --- 2. 裏方ロジック ---

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

# --- 3. 分析エンジン (矛盾排除ロジック) ---

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 データ整合性チェック・分析中..."):
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
                
                # --- 1. 割安性 (Valuation) ---
                peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                val_score = 0
                val_msg = "データなし"
                
                est_peg = None
                if peg is not None: est_peg = peg
                elif fwd_pe is not None and growth is not None and growth > 0:
                    try: est_peg = fwd_pe / (growth * 100)
                    except: pass
                
                if est_peg is not None:
                    if est_peg < 1.0: val_score = 30; val_msg = "超割安"
                    elif est_peg < 1.5: val_score = 20; val_msg = "割安"
                    elif est_peg < 2.0: val_score = 10; val_msg = "適正"
                    else: val_msg = "割高"
                elif fwd_pe is not None:
                    if fwd_pe < 20: val_score = 20; val_msg = "PER割安"
                    else: val_msg = "PER評価"

                # --- 2. トレンド (Trend) - 厳格化 ---
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else price
                
                trend_score = 0
                trend_msg = "下降/レンジ"
                is_uptrend = False
                
                if price > sma50 > sma200: 
                    trend_score = 30
                    trend_msg = "上昇トレンド"
                    is_uptrend = True
                elif price > sma50: 
                    trend_score = 15
                    trend_msg = "短期上昇"
                    is_uptrend = True
                
                # --- 3. 需給・リスク ---
                target_mean = info.get('targetMeanPrice', price)
                upside = (target_mean - price) / price
                
                target_high = info.get('targetHighPrice', target_mean)
                target_low = info.get('targetLowPrice', target_mean)
                spread = (target_high - target_low) / target_mean if target_mean else 0.5
                
                analysts = info.get('numberOfAnalystOpinions', 0)
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0
                
                # 安全弁
                safety_status = "OK"
                reject_reason = ""
                if spread > MAX_SPREAD_TOLERANCE: 
                    safety_status = "REJECT"
                    reject_reason = "変動リスク過大"
                elif analysts < 3: 
                    safety_status = "REJECT"
                    reject_reason = "情報不足"
                
                cons_score = 0
                if upside > 0:
                    base = 20 if upside > 0.2 else (10 if upside > 0.1 else 0)
                    cons_score = int(base * decay_function(spread) * conf_factor)
                
                total_score = val_score + trend_score + cons_score
                
                # --- 4. タイミング & 損切り ---
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # 損切りライン (矛盾回避: 必ず現在値より下にする)
                # SMA50の-3% と 現在値の-7% のうち、低い方（遠い方）を採用
                stop_loss_sma = sma50 * 0.97
                stop_loss_vol = price * 0.93
                stop_loss = min(stop_loss_sma, stop_loss_vol)
                
                # Action判定
                dist_to_sma = (price - sma50) / price
                
                action = "待機" 
                # 理由は動的に生成して矛盾を防ぐ
                reason_dynamic = f"{trend_msg}かつ{val_msg}"
                
                if safety_status == "REJECT":
                    action = "除外"
                    reason_dynamic = reject_reason
                elif not is_uptrend:
                    # トレンドが悪いなら、スコアが高くても「待機」
                    action = "待機"
                    reason_dynamic = "トレンド弱含み"
                elif total_score >= 40:
                    if dist_to_sma < 0.08 and rsi < 75: 
                        action = "候補"
                    elif dist_to_sma >= 0.08 or rsi >= 75:
                        action = "監視"
                        reason_dynamic = "過熱感あり"
                    else:
                        action = "待機"
                else:
                    action = "待機"
                    reason_dynamic = "スコア不足"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Price": price,
                    "Total_Score": total_score,
                    "Action": action, 
                    "Reason": reason_dynamic, # 動的理由
                    "Val_Msg": val_msg,
                    "Trend_Msg": trend_msg,
                    "Buy_Level": sma50, 
                    "Stop_Loss": stop_loss, 
                    "RSI": rsi,
                    "Dist_SMA": dist_to_sma
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

# --- 4. UI構築 (誠実な表示) ---

st.sidebar.title("メニュー")
mode = st.sidebar.radio("モード切替", ["🚀 候補仕分け (表)", "⚙️ 記録・監査 (裏)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "🚀 候補仕分け (表)":
    st.title("🦅 Market Edge Pro")
    st.caption("「今日見るべき銘柄」を10秒で仕分けるためのツール")
    
    if st.button("🔄 市場をチェックする", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            log_execution(df)
            
            scan_time = df['Scan_Time'].iloc[0]
            st.caption(f"🕒 データ基準時刻: {scan_time}")

            # --- 1. 候補 (Actionable) ---
            entries = df[df['Action'] == "候補"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"1. 本日の注目候補 ({len(entries)}銘柄)")
            if not entries.empty:
                st.info("以下の銘柄は「上昇トレンド」かつ「基準価格付近」にあります。詳細を確認してください。")
                for _, row in entries.iterrows():
                    with st.container():
                        c1, c2, c3 = st.columns([1.5, 2, 2])
                        with c1:
                            st.subheader(f"{row['Ticker']}")
                            st.caption(f"{row['Name']}")
                        with c2:
                            st.write(f"現在値: **${row['Price']:.2f}**")
                            # 乖離率
                            diff = row['Dist_SMA']
                            diff_color = "red" if diff < 0 else "green"
                            st.write(f"基準乖離: :{diff_color}[{diff:+.1%}]")
                        with c3:
                            st.write(f"✅ **判定:** {row['Reason']}")
                        
                        # 根拠と確認ポイント
                        c_act1, c_act2 = st.columns(2)
                        c_act1.success(f"🎯 **基準価格(SMA50):** ${row['Buy_Level']:.2f} 付近")
                        c_act2.error(f"🛑 **防衛ライン:** ${row['Stop_Loss']:.2f} 割れ")
                        
                        with st.expander("⚠️ エントリー前の確認ポイント"):
                            st.markdown("""
                            * **決算発表:** 直近1週間以内に決算がありませんか？
                            * **ニュース:** 突発的な悪材料が出ていませんか？
                            * **地合い:** 全体相場(QQQ/SPY)は暴落していませんか？
                            """)
                            st.divider()
                            st.write(f"・トレンド: {row['Trend_Msg']}")
                            st.write(f"・割安度: {row['Val_Msg']}")
                            st.write(f"・過熱感(RSI): {row['RSI']:.1f}")
                        st.divider()
            else:
                st.write("現在、条件を満たす「注目候補」はありません。")

            # --- 2. 監視 (Watch) ---
            watches = df[df['Action'] == "監視"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"2. 監視リスト ({len(watches)}銘柄)")
            if not watches.empty:
                st.caption("トレンドは良好ですが、過熱感があるか価格が高すぎます。")
                for _, row in watches.iterrows():
                    with st.expander(f"👀 **{row['Ticker']}** (${row['Price']:.2f}) -> 調整待ち"):
                        st.warning(f"⏰ **待機条件:** 株価が **${row['Buy_Level']:.2f}** 付近まで調整したら確認")
                        st.write(f"判定: {row['Reason']}")
            else:
                st.write("監視対象はありません。")

            # --- 3. 除外 (Excluded) ---
            waits = df[df['Action'].isin(["除外", "待機"])]
            with st.expander(f"🗑️ 除外・対象外 ({len(waits)}銘柄)"):
                st.dataframe(waits[['Ticker', 'Action', 'Reason']])
                
            st.markdown("---")
            st.caption("※ 本ツールは投資判断の補助を行うものであり、利益を保証するものではありません。最終判断はご自身の責任で行ってください。")
                
        else:
            st.error("データ取得エラー")

else:
    # --- 裏側 (監査) ---
    st.title("⚙️ 記録・監査室")
    
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        
        st.subheader("📊 実行サマリー")
        last_run = hist_df.iloc[-1]
        st.write(f"最終実行: {last_run['Scan_Time']}")
        
        st.divider()
        st.subheader("📜 実行ログ (Raw)")
        
        if 'Violation' in hist_df.columns: hist_df.rename(columns={'Violation': 'Note'}, inplace=True)
        if 'Note' not in hist_df.columns: hist_df['Note'] = "-"
            
        st.dataframe(hist_df.sort_index(ascending=False))
        
        st.caption(f"System Version: {PROTOCOL_VER}")
        st.caption(f"Validation Code: {get_verification_code()}")
    else:
        st.write("履歴データなし")
