import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid

# --- 1. システム憲法 (合格条件の定義) ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v28.0_Final_Product"

# 判定ロジックの定数固定
RULES = {
    "SMA_PERIOD": 50,
    "ATR_PERIOD": 14,
    "STOP_MULT": 2.0,      # 損切り幅
    "TARGET_SHORT_MULT": 4.0, # 短期目標幅 (ATR基準)
    "MIN_RR_QUALIFY": 2.0, # 合格R/R
    "DIP_LIMIT": 0.05      # 押し目許容 (SMA+5%以内)
}

# --- 2. ユーティリティ ---

def fmt_pct(val):
    return f"{val * 100:.1f}%" if pd.notnull(val) else "-"

def fmt_price(val):
    return f"${val:.2f}" if pd.notnull(val) else "-"

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

# --- 3. 分析エンジン (一貫性・透明性重視) ---

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
            
            # --- ロジック固定 ---
            sma50_series = hist['Close'].rolling(window=RULES["SMA_PERIOD"]).mean()
            sma50 = sma50_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5]
            atr = calculate_atr(hist, RULES["ATR_PERIOD"])
            
            # トレンド判定
            is_above_sma = price > sma50
            is_sma_rising = sma50 > sma50_prev
            dist_sma = (price - sma50) / sma50

            # 損切り・目標算出 (電卓で再計算可能な固定値)
            stop_price = round(price - (atr * RULES["STOP_MULT"]), 2)
            target_short = round(price + (atr * RULES["TARGET_SHORT_MULT"]), 2)
            target_mid = info.get('targetMeanPrice', 0)
            
            # R/R (短期を判定基準にする)
            risk = price - stop_price
            reward_short = target_short - price
            rr_short = round(reward_short / risk, 2) if risk > 0 else 0
            
            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- 結論の固定 (次の一手を1つに絞る) ---
            action = "除外"
            next_step = "トレンド回帰まで静観"
            reason = "条件不一致"
            
            if not (is_above_sma and is_sma_rising):
                action, reason, next_step = "除外", "トレンド不適合 (SMA50下/向き下)", "上昇トレンドへの回帰を待つ"
            elif rr_short < RULES["MIN_RR_QUALIFY"]:
                action, reason, next_step = "待機", f"短期R/R不足 ({rr_short} < {RULES['MIN_RR_QUALIFY']})", "価格調整によるR/R向上を待つ"
            elif rsi >= 70 or dist_sma > RULES["DIP_LIMIT"]:
                action, reason, next_step = "監視", "過熱・乖離あり", f"${sma50:.2f}付近までの調整を待つ"
            else:
                action, reason, next_step = "買い候補", "全条件合致", "本日終値の維持を確認し発注準備"

            results.append({
                "Run_ID": run_id, "スキャン時刻": fetch_time, "銘柄": ticker, "名称": name,
                "現在値": price, "結論": action, "判定理由": reason, "次の一手": next_step,
                "損切りライン": stop_price, "短期目標": target_short, "短期RR": rr_short,
                "中期目標": target_mid, "RSI": rsi, "SMA50": sma50, "乖離率": dist_sma
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI構築 (完成版) ---

st.sidebar.title("🦅 Navigator")
page = st.sidebar.radio("機能", ["🚀 戦略ボード", "⚙️ 過去ログ・監査"])

if page == "🚀 戦略ボード":
    st.title("🦅 Market Edge Pro")
    st.caption(f"Protocol: {PROTOCOL_VER} | 憲法: 価格>SMA50 且つ SMA50向き向上 且つ 短期R/R≧{RULES['MIN_RR_QUALIFY']}")

    if st.button("🔄 市場をスキャンして「型」を固定する", type="primary"):
        df = analyze_market(["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"])
        
        if not df.empty:
            st.session_state['last_df'] = df
            # ログ保存
            if not os.path.exists(HISTORY_FILE): df.to_csv(HISTORY_FILE, index=False)
            else: df.to_csv(HISTORY_FILE, mode='a', header=False, index=False)

    if 'last_df' in st.session_state:
        df = st.session_state['last_df']
        st.markdown(f"🕒 **スキャン時刻:** {df['スキャン時刻'].iloc[0]} | **Run_ID:** {df['Run_ID'].iloc[0]}")
        
        # カテゴリ表示
        tab1, tab2, tab3 = st.tabs(["✅ 買い候補", "⏳ 監視・待機", "🗑️ 除外"])
        
        with tab1:
            targets = df[df['結論']=="買い候補"]
            if not targets.empty:
                for _, r in targets.iterrows():
                    with st.container():
                        st.markdown(f"### **{r['銘柄']}** : {r['名称']}")
                        c = st.columns(4)
                        c[0].metric("現在値", f"${r['現在値']:.2f}")
                        c[1].metric("損切り", f"${r['損切りライン']:.2f}", f"{(r['損切りライン']-r['現在値'])/r['現在値']:.1%}")
                        c[2].metric("短期目標", f"${r['短期目標']:.2f}", f"{(r['短期目標']-r['現在値'])/r['現在値']:.1%}")
                        c[3].metric("利得損失比(R/R)", f"{r['短期RR']}x")
                        st.success(f"📌 **次の一手:** {r['次の一手']}")
                        st.divider()
            else: st.info("現在、即戦力となる候補はありません。")

        with tab2:
            st.write("※価格または条件が整うまで待機すべき銘柄です。")
            st.dataframe(df[df['結論'].isin(["監視", "待機"])][["銘柄", "結論", "判定理由", "次の一手", "現在値", "SMA50"]])

        with tab3:
            st.dataframe(df[df['結論']=="除外"][["銘柄", "判定理由", "次の一手"]])

else:
    st.title("⚙️ 過去ログ・分析室")
    st.write("過去の判断を振り返り、ルールの有効性を検証します。")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        # 振り返り用のデータ操作
        st.dataframe(hist_df.sort_index(ascending=False), use_container_width=True)
        st.caption(f"Verification Code: {get_verification_code()}")
    else: st.write("データがありません。")
