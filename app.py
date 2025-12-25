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
PROTOCOL_VER = "v17.0_Transparent_Logic"
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

# --- 3. 分析エンジン (透明性強化) ---

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    # ユーザーに見せるための「データ基準時刻」
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner(f"🦅 {fetch_time} 時点のデータを取得・計算中..."):
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
                
                # --- 1. 割安性 (根拠の明示) ---
                peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                val_score = 0
                val_msg = "データなし"
                
                # ロジックの透明化
                est_peg = None
                if peg is not None: 
                    est_peg = peg
                    metric_source = "公式PEG"
                elif fwd_pe is not None and growth is not None and growth > 0:
                    try: 
                        est_peg = fwd_pe / (growth * 100)
                        metric_source = "推定PEG(PER/成長率)"
                    except: 
                        metric_source = "算出不能"
                else:
                    metric_source = "PERのみ"

                if est_peg is not None:
                    if est_peg < 1.0: val_score = 30; val_msg = f"超割安 ({metric_source} {est_peg:.2f})"
                    elif est_peg < 1.5: val_score = 20; val_msg = f"割安 ({metric_source} {est_peg:.2f})"
                    elif est_peg < 2.0: val_score = 10; val_msg = f"適正 ({metric_source} {est_peg:.2f})"
                    else: val_msg = f"割高 ({metric_source} {est_peg:.2f})"
                elif fwd_pe is not None:
                    if fwd_pe < 20: val_score = 20; val_msg = f"PER割安 (PER {fwd_pe:.1f})"
                    else: val_msg = f"PER評価のみ (PER {fwd_pe:.1f})"

                # --- 2. トレンド ---
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else price
                
                trend_score = 0
                trend_msg = "下降/レンジ"
                if price > sma50 > sma200: trend_score = 30; trend_msg = "上昇トレンド (価格 > SMA50 > SMA200)"
                elif price > sma50: trend_score = 15; trend_msg = "短期上昇 (価格 > SMA50)"
                
                # --- 3. リスク・需給 ---
                target_mean = info.get('targetMeanPrice', price)
                upside = (target_mean - price) / price
                
                target_high = info.get('targetHighPrice', target_mean)
                target_low = info.get('targetLowPrice', target_mean)
                # Spreadの計算
                spread = (target_high - target_low) / target_mean if target_mean else 0.0
                
                analysts = info.get('numberOfAnalystOpinions', 0)
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0
                
                # 安全弁 (理由を数値化)
                safety_status = "OK"
                reject_reason = ""
                
                if spread > MAX_SPREAD_TOLERANCE: 
                    safety_status = "REJECT"
                    reject_reason = f"変動リスク過大 (乖離率 {spread:.1%} > 許容 {MAX_SPREAD_TOLERANCE:.0%})"
                elif analysts < 3: 
                    safety_status = "REJECT"
                    reject_reason = f"情報不足 (アナリスト {analysts}名 < 3名)"
                
                cons_score = 0
                if upside > 0:
                    base = 20 if upside > 0.2 else (10 if upside > 0.1 else 0)
                    cons_score = int(base * decay_function(spread) * conf_factor)
                
                total_score = val_score + trend_score + cons_score
                
                # --- 4. タイミング & ライン算出 ---
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # 損切りライン (計算式の明示)
                # 基本はSMA50の3%下、または現在値の7%下（ボラティリティ許容）
                stop_loss_sma = sma50 * 0.97
                stop_loss_vol = price * 0.93
                
                stop_loss = stop_loss_sma
                stop_reason = "SMA50の-3%"
                
                # SMA50より現在値がはるかに高い場合は、現在値基準のストップに切り替え
                if stop_loss_sma < price * 0.85:
                    stop_loss = stop_loss_vol
                    stop_reason = "現在値の-7%"
                
                # Action判定
                dist_to_sma = (price - sma50) / price
                
                action = "待機" 
                reason_short = "条件不一致"
                
                if safety_status == "REJECT":
                    action = "除外"
                    reason_short = reject_reason
                elif total_score >= 40:
                    if dist_to_sma < 0.08 and rsi < 75: 
                        action = "候補"
                        reason_short = f"上昇中 + 押し目 (乖離 {dist_to_sma:.1%})"
                    elif dist_to_sma >= 0.08 or rsi >= 75:
                        action = "監視"
                        reason_short = f"過熱気味 (乖離 {dist_to_sma:.1%} / RSI {rsi:.0f})"
                    else:
                        action = "待機"
                        reason_short = "モメンタム不足"
                else:
                    action = "待機"
                    reason_short = "総合スコア不足"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Sector": sector,
                    "Price": price,
                    "Total_Score": total_score,
                    "Action": action, 
                    "Reason": reason_short,
                    "Filter_Status": safety_status,
                    "Val_Msg": val_msg,
                    "Trend_Msg": trend_msg,
                    "Target": target_mean,
                    "Upside": upside,
                    "Buy_Level": sma50, 
                    "Stop_Loss": stop_loss, 
                    "Stop_Reason": stop_reason, # 根拠
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

# --- 4. UI構築 (透明性重視) ---

st.sidebar.title("メニュー")
mode = st.sidebar.radio("モード切替", ["🚀 今日の整理 (リスト)", "⚙️ 記録・監査 (裏)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "🚀 今日の整理 (リスト)":
    st.title("🦅 Market Edge Pro")
    st.caption("感情を排し、ルールに基づいて監視リストを整理します。")
    
    if st.button("🔄 条件チェックを実行", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            log_execution(df)
            
            # タイムスタンプ表示 (情報の鮮度保証)
            scan_time = df['Scan_Time'].iloc[0]
            st.caption(f"🕒 データ基準時刻: {scan_time} | 対象: 米国株主要銘柄")

            # --- 1. 候補 (Conditions Met) ---
            entries = df[df['Action'] == "候補"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"1. 条件合致・候補 ({len(entries)}銘柄)")
            if not entries.empty:
                st.info("以下の銘柄は「上昇トレンド」かつ「基準価格付近」にあります。")
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
                            st.write(f"✅ **判定理由**: {row['Reason']}")
                        
                        # 根拠付きのアクションプラン
                        c_act1, c_act2 = st.columns(2)
                        c_act1.success(f"🎯 **基準価格(SMA50):** ${row['Buy_Level']:.2f} 付近")
                        c_act2.error(f"🛑 **撤退ライン:** ${row['Stop_Loss']:.2f} 割れ")
                        
                        # 詳細データ (開閉式)
                        with st.expander("詳細データと根拠を見る"):
                            st.write(f"・撤退根拠: {row['Stop_Reason']}")
                            st.write(f"・割安度: {row['Val_Msg']}")
                            st.write(f"・トレンド: {row['Trend_Msg']}")
                            st.write(f"・過熱感(RSI): {row['RSI']:.1f}")
                        st.divider()
            else:
                st.write("現在、条件を満たす銘柄はありません。")

            # --- 2. 監視 (Watch) ---
            watches = df[df['Action'] == "監視"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"2. 監視リスト ({len(watches)}銘柄)")
            if not watches.empty:
                st.caption("トレンドは良好ですが、過熱感があるか価格が高すぎます。調整を待ちます。")
                for _, row in watches.iterrows():
                    with st.expander(f"👀 **{row['Ticker']}** (${row['Price']:.2f}) -> 調整待ち"):
                        st.warning(f"⏰ **待機条件:** 株価が **${row['Buy_Level']:.2f}** 付近まで調整したら確認")
                        st.write(f"現状: 基準より {row['Dist_SMA']:+.1%} 高い位置 / RSI {row['RSI']:.0f}")
                        st.caption(f"理由: {row['Reason']}")
            else:
                st.write("監視対象はありません。")

            # --- 3. 除外 (Excluded) ---
            waits = df[df['Action'].isin(["除外", "待機"])]
            with st.expander(f"🗑️ 除外・対象外 ({len(waits)}銘柄) - 理由一覧"):
                # 理由を明確に表示
                st.dataframe(waits[['Ticker', 'Reason', 'Val_Msg']])
                
            st.markdown("---")
            st.caption("※ 本ツールは投資助言ではなく、設定されたルールに基づくスクリーニング結果を表示するものです。最終判断はご自身の責任で行ってください。")
                
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
