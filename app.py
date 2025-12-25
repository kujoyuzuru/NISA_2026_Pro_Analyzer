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

# 定数・パラメータ
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v20.0_Systematic_Trade"
MIN_INTERVAL_DAYS = 7       

# トレードルール設定
SMA_PERIOD = 50                 # 基準トレンドライン
ATR_PERIOD = 14                 # ボラティリティ計算期間
ATR_MULTIPLIER = 2.0            # 損切り幅 (ATR x N)
MIN_RISK_REWARD = 2.0           # 最低許容リスクリワードレシオ
DIP_TOLERANCE = 0.05            # 押し目許容範囲 (SMA50 + 5%以内)
MAX_VOLATILITY = 0.05           # 除外する変動率 (日次変動5%以上は除外)

# --- 2. 裏方ロジック (記録・監査) ---

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

# --- 3. 分析エンジン (システムトレードロジック) ---

def calculate_atr(df, period=14):
    """Average True Range (値動きの平均幅) を計算"""
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(period).mean().iloc[-1]
    return atr

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 トレンド定義・ATRリスク・期待値を厳格に計算中..."):
        for i, ticker in enumerate(tickers):
            try:
                stock = yf.Ticker(ticker)
                try: info = stock.info
                except: continue 

                # 期間を少し長めに取る（SMA50の傾き計算のため）
                hist = stock.history(period="6mo")
                if len(hist) < 60: continue

                # Basic Data
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                name = info.get('shortName', ticker)
                
                # --- A. トレンド判定 (定義の固定) ---
                sma50 = hist['Close'].rolling(window=SMA_PERIOD).mean()
                sma50_now = sma50.iloc[-1]
                sma50_prev = sma50.iloc[-5] # 5日前と比較
                
                # 1. 価格がSMA50より上か？
                cond_price_above = price > sma50_now
                # 2. SMA50自体が上向きか？
                cond_sma_rising = sma50_now > sma50_prev
                
                trend_status = "上昇トレンド" if (cond_price_above and cond_sma_rising) else "調整/下降"
                
                # --- B. リスク管理 (ATR & 損切り) ---
                atr = calculate_atr(hist, ATR_PERIOD)
                volatility_pct = atr / price
                
                # 損切りライン (現在値 - ATR * 2.0)
                stop_loss = price - (atr * ATR_MULTIPLIER)
                risk_amt = price - stop_loss
                
                # --- C. 期待値 (Risk/Reward) ---
                target_mean = info.get('targetMeanPrice', 0)
                if not target_mean or target_mean <= price:
                    target_mean = price * 1.05 # データなしの場合は仮置き(スコア下げ要因)
                    reward_amt = 0
                else:
                    reward_amt = target_mean - price
                
                rr_ratio = reward_amt / risk_amt if risk_amt > 0 else 0
                
                # --- D. 押し目・過熱感判定 ---
                dist_sma = (price - sma50_now) / sma50_now
                
                # 押し目定義: SMA50より上、かつSMA50+5%以内
                is_dip = (0 < dist_sma <= DIP_TOLERANCE)
                
                # RSI
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # --- E. 最終仕分け (Logic Gate) ---
                action = "待機"
                reason = "ー"
                
                # 1. 除外チェック (安全性)
                if volatility_pct > MAX_VOLATILITY:
                    action = "除外"
                    reason = f"値動き過大 (日次変動 {volatility_pct:.1%} > {MAX_VOLATILITY:.0%})"
                
                # 2. トレンドチェック
                elif not (cond_price_above and cond_sma_rising):
                    action = "除外"
                    reason = "トレンド不適合 (SMA50以下または下向き)"
                    
                # 3. リスクリワードチェック
                elif rr_ratio < MIN_RISK_REWARD:
                    action = "待機"
                    reason = f"期待値不足 (R/R {rr_ratio:.1f} < {MIN_RISK_REWARD})"
                    
                # 4. 押し目・タイミングチェック
                elif is_dip and rsi < 70:
                    action = "候補"
                    reason = f"好条件: 上昇中 + 押し目 (乖離 {dist_sma:.1%})"
                elif dist_sma > DIP_TOLERANCE:
                    action = "待機"
                    reason = f"価格乖離 (SMA50より {dist_sma:.1%} 上)"
                else:
                    action = "待機"
                    reason = "条件不一致"

                # 割安性 (参考情報)
                fwd_pe = info.get('forwardPE', 0)
                val_msg = f"PER {fwd_pe:.1f}" if fwd_pe else "データなし"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Price": price,
                    "Action": action,
                    "Reason": reason,
                    "Trend": trend_status,
                    "ATR": atr,
                    "Stop_Loss": stop_loss,
                    "Target": target_mean,
                    "RR_Ratio": rr_ratio,
                    "Risk_Amt": risk_amt,
                    "Reward_Amt": reward_amt,
                    "Dist_SMA": dist_sma,
                    "SMA50": sma50_now,
                    "RSI": rsi,
                    "Vol_Pct": volatility_pct,
                    "Val_Msg": val_msg
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
    
    # ログには詳細な理由を残す
    content = df_save[['Run_ID', 'Ticker', 'Action', 'Reason', 'RR_Ratio']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return note == "Practice"

# --- 4. UI構築 (判断特化) ---

st.sidebar.title("メニュー")
mode = st.sidebar.radio("モード切替", ["🚀 市場スキャン (判断)", "⚙️ 記録・監査 (裏)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "🚀 市場スキャン (判断)":
    st.title("🦅 Market Edge Pro")
    st.caption("「トレンド・リスク・期待値」の3条件で、今日の行動を決定します。")
    
    if st.button("🔄 条件チェックを実行", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            log_execution(df)
            
            st.caption(f"🕒 データ基準: {df['Scan_Time'].iloc[0]} | 判定基準: Trend > SMA50, R/R > {MIN_RISK_REWARD}")

            # --- 1. 候補 (Candidates) ---
            candidates = df[df['Action'] == "候補"].sort_values('RR_Ratio', ascending=False)
            
            st.header(f"✅ エントリー候補 ({len(candidates)}銘柄)")
            
            if not candidates.empty:
                st.success("以下の銘柄は、トレンド・押し目・期待値の全条件をクリアしました。")
                for _, row in candidates.iterrows():
                    with st.container():
                        # ヘッダー
                        c1, c2 = st.columns([2, 1])
                        with c1:
                            st.subheader(f"{row['Ticker']} - {row['Name']}")
                        with c2:
                            st.metric("リスクリワード比", f"{row['RR_Ratio']:.1f}倍", delta="合格")

                        # プラン詳細
                        col_plan1, col_plan2, col_plan3 = st.columns(3)
                        
                        with col_plan1:
                            st.info("🔵 **エントリー目安**")
                            st.write(f"現在値: **${row['Price']:.2f}**")
                            st.caption(f"基準(SMA50): ${row['SMA50']:.2f}")
                            
                        with col_plan2:
                            st.error("🛑 **損切り (ATR x2.0)**")
                            st.write(f"撤退: **${row['Stop_Loss']:.2f}**")
                            st.caption(f"想定損失: -${row['Risk_Amt']:.2f}")

                        with col_plan3:
                            st.success("🎯 **目標 (アナリスト)**")
                            st.write(f"目標: **${row['Target']:.2f}**")
                            st.caption(f"想定利益: +${row['Reward_Amt']:.2f}")

                        # 理由
                        st.write(f"**判定理由:** {row['Reason']}")
                        st.divider()
            else:
                st.info("現在、すべての条件（トレンド・押し目・期待値2倍以上）を満たす銘柄はありません。")

            # --- 2. 待機 (Wait) ---
            waits = df[df['Action'] == "待機"].sort_values('Dist_SMA', ascending=True)
            
            st.header(f"⏳ 待機リスト ({len(waits)}銘柄)")
            if not waits.empty:
                st.caption("トレンドや期待値に課題があるか、価格が高すぎます。条件が整うのを待ちます。")
                for _, row in waits.iterrows():
                    with st.expander(f"{row['Ticker']} (${row['Price']:.2f}) : {row['Reason']}"):
                        st.write(f"現状のR/R比: {row['RR_Ratio']:.1f}倍 (目標 {MIN_RISK_REWARD}倍)")
                        st.write(f"SMA50乖離: {row['Dist_SMA']:+.1%} (目標 {DIP_TOLERANCE:.0%}以内)")
                        st.caption(f"損切り目安(ATR): ${row['Stop_Loss']:.2f}")
            else:
                st.write("待機リストなし")

            # --- 3. 除外 (Excluded) ---
            excludes = df[df['Action'] == "除外"]
            with st.expander(f"🗑️ 除外リスト ({len(excludes)}銘柄)"):
                st.dataframe(excludes[['Ticker', 'Reason', 'Vol_Pct']])
                
        else:
            st.error("データ取得エラー")

else:
    # --- 裏側 (監査) ---
    st.title("⚙️ 記録・監査室")
    
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        
        st.subheader("📊 実行サマリー")
        st.write(f"最終実行: {hist_df.iloc[-1]['Scan_Time']}")
        st.write(f"総記録数: {len(hist_df)}件")
        
        st.divider()
        st.subheader("📜 実行ログ (詳細)")
        
        # 表示調整
        if 'Violation' in hist_df.columns: hist_df.rename(columns={'Violation': 'Note'}, inplace=True)
        if 'Note' not in hist_df.columns: hist_df['Note'] = "-"
            
        st.dataframe(hist_df.sort_index(ascending=False))
        
        st.caption(f"System Version: {PROTOCOL_VER}")
        st.caption(f"Validation Code: {get_verification_code()}")
    else:
        st.write("履歴データなし")
