import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid

# --- 1. システム設定 ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

# 固定パラメータ
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v24.0_Combat_Navigator"
SMA_PERIOD = 50
ATR_PERIOD = 14
STOP_MULT = 2.0       # 損切り幅
TARGET_SHORT_MULT = 4.0 # 短期目標幅
MIN_RR_THRESHOLD = 2.0  # 合格期待値

# --- 2. ユーティリティ ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

# --- 3. 分析エンジン (時間軸分離・無効処理実装) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return ranges.max(axis=1).rolling(period).mean().iloc[-1]

@st.cache_data(ttl=3600)
def analyze_market(tickers):
    results = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist = stock.history(period="6mo")
            if len(hist) < 60: continue

            price = info.get('currentPrice', hist['Close'].iloc[-1])
            name = info.get('shortName', ticker)
            
            # --- 1. 指標診断 ---
            sma50_series = hist['Close'].rolling(window=SMA_PERIOD).mean()
            sma50_now = sma50_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5] # 5日前と比較
            atr = calculate_atr(hist, ATR_PERIOD)
            
            # トレンド診断
            is_above_sma = price > sma50_now
            is_sma_rising = sma50_now > sma50_prev
            
            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- 2. 分類ロジック (単一原因特定型) ---
            action = "待機"
            reason = "条件不一致"
            
            vol = atr / price
            dist_sma = (price - sma50_now) / sma50_now

            if vol > 0.05:
                action, reason = "除外", f"値動き過大 (日率{vol*100:.1f}%)"
            elif not is_above_sma:
                action, reason = "除外", "SMA50より下"
            elif not is_sma_rising:
                action, reason = "除外", "SMA50が下向き"
            elif rsi >= 70:
                action, reason = "監視", f"買われすぎ (RSI:{rsi:.0f})"
            elif dist_sma > 0.05:
                action, reason = "監視", f"乖離大 (SMA50+{dist_sma*100:.1f}%)"
            else:
                action, reason = "買い候補", "条件合致"

            # --- 3. 期待値計算 (短期/中期 分離) ---
            # 損切り (固定ロジック)
            stop_price = price - (atr * STOP_MULT)
            risk = price - stop_price
            
            # 短期目標 (ATRベース)
            target_short = price + (atr * TARGET_SHORT_MULT)
            reward_short = target_short - price
            rr_short = reward_short / risk if risk > 0 else 0
            days_short = (target_short - price) / atr if atr > 0 else 0
            
            # 中期目標 (アナリスト)
            target_mid = info.get('targetMeanPrice')
            if target_mid and target_mid > price:
                reward_mid = target_mid - price
                rr_mid = reward_mid / risk if risk > 0 else 0
                days_mid = (target_mid - price) / atr if atr > 0 else 0
                rr_mid_status = f"{rr_mid:.1f}倍"
            else:
                rr_mid_status = "無効 (目標が現在値以下)"
                days_mid = 0

            # 最終チェック: 期待値不足なら待機へ
            if action == "買い候補" and rr_short < MIN_RR_THRESHOLD:
                action, reason = "待機", f"短期期待値不足 (R/R:{rr_short:.1f})"

            results.append({
                "Run_ID": run_id, "時刻": fetch_time, "銘柄": ticker, "名称": name,
                "現在値": price, "判定": action, "理由": reason,
                "損切り": stop_price, 
                "短期目標": target_short, "短期RR": rr_short, "短期目安日数": days_short,
                "中期目標": target_mid if target_mid else 0, "中期RR": rr_mid_status, "中期目安日数": days_mid,
                "SMA50": sma50_now, "RSI": rsi, "ATR": atr, "乖離率": dist_sma
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI構築 ---

st.sidebar.title("🦅 Market Edge")
page = st.sidebar.radio("移動", ["🚀 今日の判断", "⚙️ 記録・監査室"])

if page == "🚀 今日の判断":
    st.title("🦅 Market Edge Pro")
    st.info(f"""
    📏 **判定プロトコル (Short-Swing)**
    - **上昇定義:** 価格 > SMA50 かつ SMA50(今日) > SMA50(5日前)
    - **期待値:** 短期R/R {MIN_RR_THRESHOLD}倍以上 | 目標日数 = (目標-現在値)/ATR
    """)

    if st.button("🔄 最新データで診断", type="primary"):
        df = analyze_market(["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"])
        
        if not df.empty:
            # サマリー
            s = df['判定'].value_counts()
            st.markdown(f"### 📋 診断結果: ✅候補 {s.get('買い候補',0)} | 👀監視 {s.get('監視',0)} | ⏳待機 {s.get('待機',0)} | 🗑️除外 {s.get('除外',0)}")
            
            # --- 1. 買い候補 ---
            st.subheader("✅ 買い候補 (Action Required)")
            for _, r in df[df['判定']=="買い候補"].iterrows():
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1: st.markdown(f"#### **{r['銘柄']}** | {r['名称']}")
                    with c2: st.success("NEXT: 本日終値で買い検討")
                    
                    # 期待値マトリクス
                    col_rr = st.columns(4)
                    col_rr[0].metric("現在値", f"${r['現在値']:.2f}")
                    col_rr[1].metric("損切り", f"${r['損切り']:.2f}", f"{(r['損切り']-r['現在値'])/r['現在値']:.1%}")
                    col_rr[2].metric("短期期待値", f"{r['短期RR']:.1f}倍", f"目安 {r['短期目安日数']:.0f}日")
                    col_rr[3].metric("中期期待値", r['中期RR'], f"目安 {r['中期目安日数']:.0f}日" if r['中期目安日数']>0 else None)
                    
                    st.write(f"👉 **診断結果:** {r['理由']}")
                    with st.expander("詳細データ"):
                        st.write(f"RSI: {r['RSI']:.0f} | SMA50乖離: {r['乖離率']:.1%} | 日次ボラ(ATR): ${r['ATR']:.2f}")
                    st.divider()

            # --- 2. 監視・待機 ---
            col_list1, col_list2 = st.columns(2)
            with col_list1:
                st.subheader("👀 監視 (条件待ち)")
                for _, r in df[df['判定']=="監視"].iterrows():
                    with st.expander(f"{r['銘柄']} | {r['理由']}"):
                        st.warning(f"再確認ライン: ${r['SMA50']:.2f} 付近")
                        st.write(f"短期R/R想定: {r['短期RR']:.1f}倍")
            
            with col_list2:
                st.subheader("⏳ 待機 (追加要素待ち)")
                for _, r in df[df['判定']=="待機"].iterrows():
                    with st.expander(f"{r['銘柄']} | {r['理由']}"):
                        st.write(f"現状の短期R/R: {r['短期RR']:.1f}倍")

            # --- 3. 除外 ---
            st.subheader("🗑️ 除外 (不適合)")
            st.dataframe(df[df['判定']=="除外"][["銘柄", "理由", "現在値"]], hide_index=True, use_container_width=True)

else:
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist_df.sort_index(ascending=False), use_container_width=True)
        st.caption(f"Verification Code: {get_verification_code()}")
    else: st.write("ログなし")
