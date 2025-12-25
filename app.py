import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid

# --- 1. v1.0 仕様定義 (憲法) ---
st.set_page_config(page_title="Market Edge Pro v1.0", page_icon="🦅", layout="wide")

HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v1.0_Final_Spec"

# 【仕様固定】判定パラメータ
SPEC = {
    "SMA_PERIOD": 50,       # 50日移動平均
    "ATR_PERIOD": 14,       # 14日平均ボラティリティ
    "STOP_MULT": 2.0,       # 損切幅: ATRの2倍
    "TARGET_MULT": 4.0,     # 目標幅: ATRの4倍 (短期)
    "RR_THRESHOLD": 2.00,   # R/R 閾値: 2.00以上で合格
    "DIP_LIMIT": 0.05       # 押し目許容: SMA+5%以内
}

# --- 2. ユーティリティ ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

# --- 3. 分析エンジン (検算・整合性重視) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return ranges.max(axis=1).rolling(period).mean().iloc[-1]

@st.cache_data(ttl=3600)
def analyze_market_v1(tickers):
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
            
            # --- 指標計算 ---
            sma_series = hist['Close'].rolling(window=SPEC["SMA_PERIOD"]).mean()
            sma50 = sma_series.iloc[-1]
            sma50_prev = sma_series.iloc[-5]
            atr = calculate_atr(hist, SPEC["ATR_PERIOD"])
            
            # --- 判定項目 (検算用生データ) ---
            c_trend = price > sma50 and sma50 > sma50_prev
            c_dist = (price - sma50) / sma50
            c_dip = 0 < c_dist <= SPEC["DIP_LIMIT"]
            
            # 損切・目標・R/R (小数2桁で固定)
            stop = round(price - (atr * SPEC["STOP_MULT"]), 2)
            target = round(price + (atr * SPEC["TARGET_MULT"]), 2)
            risk = price - stop
            reward = target - price
            rr_val = round(reward / risk, 2) if risk > 0 else -1.0
            
            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- 分類ロジック (唯一の正解) ---
            if rr_val < 0 or np.isnan(rsi):
                action, reason = "除外", "データ不整合"
            elif not c_trend:
                action, reason = "除外", "トレンド不適合(SMA50割れ/向き下)"
            elif rr_val < SPEC["RR_THRESHOLD"]:
                action, reason = "待機", f"利幅/損幅比不足 (R/R {rr_val:.2f} < {SPEC['RR_THRESHOLD']})"
            elif rsi >= 70 or c_dist > SPEC["DIP_LIMIT"]:
                action, reason = "監視", f"過熱・乖離 (RSI:{rsi:.0f}/乖離:{c_dist*100:.1f}%)"
            else:
                action, reason = "買い候補", "全条件合致 (検証済)"

            results.append({
                "Run_ID": run_id, "スキャン時刻": fetch_time, "銘柄": ticker, "名称": name,
                "価格": price, "分類": action, "理由": reason,
                "損切": stop, "目標": target, "RR": rr_val,
                "SMA50": sma50, "RSI": rsi, "乖離": c_dist, "ATR": atr
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI構築 (v1.0 固定仕様) ---

st.sidebar.title("🦅 Navigator v1.0")
page = st.sidebar.radio("機能", ["🚀 戦略ボード", "⚙️ 過去ログ・監査"])

if page == "🚀 戦略ボード":
    st.title("🦅 Market Edge Pro v1.0")
    st.caption(f"仕様: SMA{SPEC['SMA_PERIOD']} / R/R ≧ {SPEC['RR_THRESHOLD']} / 損切 ATR×{SPEC['STOP_MULT']}")

    if st.button("🔄 市場をスキャンして仕様を固定する", type="primary"):
        df = analyze_market_v1(["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"])
        if not df.empty:
            st.session_state['v1_df'] = df
            if not os.path.exists(HISTORY_FILE): df.to_csv(HISTORY_FILE, index=False)
            else: df.to_csv(HISTORY_FILE, mode='a', header=False, index=False)

    if 'v1_df' in st.session_state:
        df = st.session_state['v1_df']
        st.info(f"🕒 **基準時刻:** {df['スキャン時刻'].iloc[0]} | **ID:** {df['Run_ID'].iloc[0]}")
        
        # カテゴリ表示 (一貫性の担保)
        tabs = st.tabs(["✅ 買い候補", "⏳ 監視・待機", "🗑️ 除外"])
        
        with tabs[0]:
            target_df = df[df['分類']=="買い候補"]
            if not target_df.empty:
                for _, r in target_df.iterrows():
                    with st.expander(f"**{r['銘柄']}** | R/R {r['RR']:.2f}x | {r['理由']}", expanded=True):
                        c = st.columns(4)
                        c[0].metric("現在値", f"${r['価格']:.2f}")
                        c[1].metric("損切(撤退)", f"${r['損切']:.2f}", f"{(r['損切']-r['価格'])/r['価格']:.1%}")
                        c[2].metric("目標(短期)", f"${r['目標']:.2f}", f"{(r['目標']-r['価格'])/r['価格']:.1%}")
                        c[3].metric("利幅/損幅比", f"{r['RR']:.2f}x")
            else: st.write("現在、仕様を満たす候補はありません。")

        with tabs[1]:
            st.dataframe(df[df['分類'].isin(["監視", "待機"])][["銘柄", "分類", "理由", "価格", "RR"]])

        with tabs[2]:
            st.dataframe(df[df['分類']=="除外"][["銘柄", "理由"]])

else:
    st.title("⚙️ 過去ログ・分析室")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist_df.sort_index(ascending=False), use_container_width=True)
        st.caption(f"Verification Code: {get_verification_code()}")
