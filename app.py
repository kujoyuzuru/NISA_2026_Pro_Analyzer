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
PROTOCOL_VER = "v19.0_Zero_Contradiction"
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

# --- 3. 分析エンジン (矛盾ゼロ・ロジック) ---

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 厳格スキャン実行中... (Trend check, Logic verification)"):
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
                
                # --- A. トレンド判定 (絶対基準) ---
                # SMA50を「生命線」とする。これを割っていたら上昇トレンドとは呼ばない。
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else sma50
                
                # ロジック: 価格がSMA50の上にあるか？
                is_above_sma50 = price >= sma50
                trend_status = "上昇中" if is_above_sma50 else "調整/下降"
                
                # --- B. 割安性 (根拠の明示) ---
                peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                val_status = "不明"
                val_detail = "データなし"
                is_undervalued = False
                
                est_peg = None
                if peg is not None: est_peg = peg
                elif fwd_pe is not None and growth is not None and growth > 0:
                    try: est_peg = fwd_pe / (growth * 100)
                    except: pass
                
                if est_peg is not None:
                    if est_peg < 1.5: 
                        val_status = "割安"
                        val_detail = f"PEG {est_peg:.2f} < 1.5"
                        is_undervalued = True
                    elif est_peg < 2.0: 
                        val_status = "適正"
                        val_detail = f"PEG {est_peg:.2f} (適正圏)"
                        is_undervalued = True
                    else: 
                        val_status = "割高"
                        val_detail = f"PEG {est_peg:.2f} > 2.0"
                elif fwd_pe is not None:
                    if fwd_pe < 25: 
                        val_status = "PER割安"
                        val_detail = f"PER {fwd_pe:.1f} < 25"
                        is_undervalued = True
                    else:
                        val_status = "PER割高"
                        val_detail = f"PER {fwd_pe:.1f}"

                # --- C. リスク・需給 ---
                target_mean = info.get('targetMeanPrice', price)
                upside = (target_mean - price) / price
                
                target_high = info.get('targetHighPrice', target_mean)
                target_low = info.get('targetLowPrice', target_mean)
                spread = (target_high - target_low) / target_mean if target_mean else 0.0
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                # 安全弁
                is_safe = True
                safety_msg = "OK"
                if spread > MAX_SPREAD_TOLERANCE: 
                    is_safe = False
                    safety_msg = f"除外: 値動き過大 (Spread {spread:.1%})"
                elif analysts < 3: 
                    is_safe = False
                    safety_msg = f"除外: 情報不足 (Analysts {analysts})"
                
                # --- D. タイミング & 損切り ---
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # 損切りライン (ロジック固定: SMA50の-3%)
                # 理由: トレンドフォローなので、トレンドライン(SMA50)を明確に割ったら前提崩れで撤退
                stop_loss = sma50 * 0.97
                
                # 乖離率
                dist_sma = (price - sma50) / sma50
                
                # --- 最終判定 (Logic Tree) ---
                action = "WAIT"
                reason = "ー"
                
                if not is_safe:
                    action = "AVOID"
                    reason = safety_msg
                elif not is_above_sma50:
                    action = "WAIT"
                    reason = f"トレンド弱含み (現在値 ${price:.2f} < SMA50 ${sma50:.2f})"
                elif not is_undervalued:
                    action = "WAIT"
                    reason = f"割安感なし ({val_status})"
                else:
                    # ここまで来たら「安全」「上昇中」「割安」
                    # あとはタイミングのみ
                    if dist_sma < 0.05 and rsi < 70:
                        action = "ENTRY"
                        reason = f"★ 押し目好機 (乖離 {dist_sma:.1%} / RSI {rsi:.0f})"
                    elif dist_sma >= 0.05 or rsi >= 70:
                        action = "WATCH"
                        reason = f"過熱感あり (乖離 {dist_sma:.1%} / RSI {rsi:.0f})"
                    else:
                        action = "WAIT"
                        reason = "モメンタム不足"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Price": price,
                    "Action": action, 
                    "Reason": reason,
                    "Val_Detail": val_detail,
                    "Trend_Status": trend_status,
                    "SMA50": sma50, 
                    "Stop_Loss": stop_loss, 
                    "RSI": rsi,
                    "Dist_SMA": dist_sma,
                    "Spread": spread,
                    "Upside": upside,
                    "Target": target_mean
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
    
    # 簡略化してハッシュ計算
    content = df_save[['Run_ID', 'Ticker', 'Action', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return note == "Practice"

# --- 4. UI構築 (シンプル・整合性重視) ---

st.sidebar.title("メニュー")
mode = st.sidebar.radio("モード切替", ["🚀 朝の点検 (スキャン)", "⚙️ 記録・監査 (ログ)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "🚀 朝の点検 (スキャン)":
    st.title("🦅 Market Edge Pro")
    st.caption("【短期スイング用】上昇トレンドの押し目銘柄を検知します。")
    
    if st.button("🔄 市場を点検する", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            log_execution(df)
            
            scan_time = df['Scan_Time'].iloc[0]
            st.caption(f"🕒 データ基準: {scan_time}")

            # --- 1. 候補 (ENTRY) ---
            entries = df[df['Action'] == "ENTRY"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"✅ 候補リスト ({len(entries)}銘柄)")
            if not entries.empty:
                st.info("条件：上昇トレンド維持 + 割安圏 + 押し目水準 (SMA50付近)")
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
                            st.write(f"SMA50乖離: **{diff:+.1%}**")
                        with c3:
                            st.success(f"{row['Reason']}")
                        
                        # 根拠とプラン
                        c_act1, c_act2 = st.columns(2)
                        c_act1.write(f"📈 **トレンド基準(SMA50):** ${row['SMA50']:.2f}")
                        c_act2.error(f"🛑 **撤退ライン:** ${row['Stop_Loss']:.2f} (SMA50の-3%)")
                        
                        with st.expander("詳細判定ロジックを見る"):
                            st.write(f"1. トレンド: {row['Trend_Status']} (Price ${row['Price']:.2f} >= SMA ${row['SMA50']:.2f})")
                            st.write(f"2. 割安度: {row['Val_Detail']}")
                            st.write(f"3. 過熱感: RSI {row['RSI']:.1f} (70以下OK)")
                            st.write(f"4. 目標株価: ${row['Target']:.2f} (Upside {row['Upside']:.1%})")
                        st.divider()
            else:
                st.write("現在、条件（トレンド・割安・押し目）を全て満たす銘柄はありません。")

            # --- 2. 監視 (WATCH) ---
            watches = df[df['Action'] == "WATCH"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"👀 監視リスト ({len(watches)}銘柄)")
            if not watches.empty:
                st.caption("トレンド・割安度は良好ですが、価格が高すぎます。調整を待ちます。")
                for _, row in watches.iterrows():
                    with st.expander(f"{row['Ticker']} (${row['Price']:.2f}) -> {row['Reason']}"):
                        st.warning(f"⏰ **待機:** 株価が **${row['SMA50']:.2f}** 付近まで落ちてきたら再確認")
                        st.write(f"乖離率: {row['Dist_SMA']:+.1%} / RSI: {row['RSI']:.0f}")
            else:
                st.write("監視対象はありません。")

            # --- 3. 対象外 (AVOID/WAIT) ---
            waits = df[df['Action'].isin(["AVOID", "WAIT"])]
            with st.expander(f"🗑️ 対象外・除外 ({len(waits)}銘柄)"):
                st.dataframe(waits[['Ticker', 'Action', 'Reason', 'Trend_Status']])
                
            st.markdown("---")
            st.caption("※ 本ツールは「短期スイング（数週間）」を想定した判断補助ツールです。最終売買はご自身の責任で行ってください。")
                
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
        st.write(f"総記録数: {len(hist_df)}件")
        
        st.divider()
        st.subheader("📜 実行ログ (Raw)")
        
        if 'Violation' in hist_df.columns: hist_df.rename(columns={'Violation': 'Note'}, inplace=True)
        if 'Note' not in hist_df.columns: hist_df['Note'] = "-"
            
        st.dataframe(hist_df.sort_index(ascending=False))
        
        st.caption(f"System Version: {PROTOCOL_VER}")
        st.caption(f"Validation Code: {get_verification_code()}")
    else:
        st.write("履歴データなし")
