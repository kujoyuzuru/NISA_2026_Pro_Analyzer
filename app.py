import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid

# --- 1. システム設定・憲法定義 ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v27.0_Final_Definition"

# 判定しきい値 (憲法)
RULES = {
    "SMA_PERIOD": 50,
    "ATR_PERIOD": 14,
    "STOP_MULT": 2.0,
    "TARGET_MULT": 4.0,
    "MIN_RR": 2.0,      # この数値「以上」を合格とする
    "MAX_VOL": 0.05,    # 5%以上のボラは除外
    "DIP_LIMIT": 0.05   # SMA+5%以内を押し目とする
}

# --- 2. ユーティリティ ---

def fmt_rr(val):
    """判定に使われる数値と表示を完全に一致させる (小数2桁)"""
    return round(float(val), 2) if pd.notnull(val) else 0.0

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

# --- 3. 分析エンジン (信頼性・再現性特化) ---

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
            
            # 指標計算
            sma50_series = hist['Close'].rolling(window=RULES["SMA_PERIOD"]).mean()
            sma50 = sma50_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5]
            atr = calculate_atr(hist, RULES["ATR_PERIOD"])
            
            # RSI計算 (0-100ガード)
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- 判定前バリデーション (不整合の排除) ---
            stop_price = price - (atr * RULES["STOP_MULT"])
            target_price = price + (atr * RULES["TARGET_MULT"])
            
            # リスクと報酬の生値
            risk = price - stop_price
            reward = target_price - price
            
            # R/R算出 (小数2桁で固定)
            rr_val = fmt_rr(reward / risk) if risk > 0 else -1.0
            
            # トレンド・乖離・ボラ
            is_above_sma = price > sma50
            is_sma_rising = sma50 > sma50_prev
            dist_sma = (price - sma50) / sma50
            vol = atr / price

            # --- 状態定義 (Action-Driven) ---
            action = "対象外"
            next_step = "ー"
            reason = "条件不一致"
            
            # 1. データ不整合ゲート
            if rr_val < 0 or np.isnan(rsi):
                action, reason, next_step = "対象外", "データ不整合 (R/R負値または欠損)", "データの正常化を待つ"
            
            # 2. 判定ロジック
            elif vol > RULES["MAX_VOL"]:
                action, reason, next_step = "対象外", f"変動過大 ({vol*100:.1f}%)", "ボラティリティ低下を待つ"
            elif not (is_above_sma and is_sma_rising):
                action, reason, next_step = "対象外", "トレンド不適合 (SMA50割れ/下向き)", "上昇トレンドへの回帰を待つ"
            elif rr_val < RULES["MIN_RR"]:
                # ここで 2.00 >= 2.0 の判定を厳格に行う
                action, reason, next_step = "条件待ち", f"期待値不足 (R/R {rr_val} < {RULES['MIN_RR']})", "価格調整による期待値向上を待つ"
            elif rsi >= 70 or dist_sma > RULES["DIP_LIMIT"]:
                action, reason, next_step = "価格待ち", f"過熱・乖離 (RSI:{rsi:.0f}/乖離:{dist_sma*100:.1f}%)", f"${sma50:.2f}付近までの調整を待つ"
            else:
                action, reason, next_step = "今すぐ検討", "全条件合致 (トレンド・押し目・R/R)", "本日終値の維持を確認し発注準備"

            results.append({
                "Run_ID": run_id, "時刻": fetch_time, "銘柄": ticker, "名称": name,
                "現在値": price, "状態": action, "理由": reason, "次の一手": next_step,
                "損切り": stop_price, "目標": target_price, "RR": rr_val,
                "SMA50": sma50, "RSI": rsi, "ATR": atr, "乖離": dist_sma, "判定ルール": str(RULES)
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI構築 (行動直結型) ---

st.sidebar.title("🦅 Navigator")
page = st.sidebar.radio("機能", ["🚀 市場スキャン", "⚙️ 記録・監査室"])

if page == "🚀 市場スキャン":
    st.title("🦅 Market Edge Pro")
    st.info(f"⚖️ **判定憲法:** トレンド(Price>SMA50 & 向き↑) | R/R {RULES['MIN_RR']}以上 | 損切 ATR×{RULES['STOP_MULT']} | 押し目 乖離{RULES['DIP_LIMIT']*100:.0f}%以内")

    if st.button("🔄 憲法に基づき全銘柄をスキャン", type="primary"):
        df = analyze_market(["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"])
        
        if not df.empty:
            # 1. サマリー
            s = df['状態'].value_counts()
            st.markdown(f"### 📋 スキャン結果: ✅検討 **{s.get('今すぐ検討',0)}** | ⏳価格待ち **{s.get('価格待ち',0)}** | 🛠️条件待ち **{s.get('条件待ち',0)}** | 🗑️対象外 **{s.get('対象外',0)}**")
            
            # 2. 今すぐ検討 (Actionable)
            st.subheader("✅ 今すぐ検討 (エントリー候補)")
            for _, r in df[df['状態']=="今すぐ検討"].iterrows():
                with st.expander(f"**{r['銘柄']}** | {r['理由']} | R/R: {r['RR']:.2f}x", expanded=True):
                    c = st.columns(4)
                    c[0].metric("現在値", f"${r['現在値']:.2f}")
                    c[1].metric("損切り", f"${r['損切り']:.2f}", f"{(r['損切り']-r['現在値'])/r['現在値']:.1%}")
                    c[2].metric("目標", f"${r['目標']:.2f}", f"{(r['目標']-r['現在値'])/r['現在値']:.1%}")
                    c[3].metric("利得損失比(R/R)", f"{r['RR']:.2f}x")
                    st.success(f"👉 **次の一手:** {r['次の一手']}")

            # 3. 価格待ち・条件待ち
            st.subheader("⏳ 待機 (シナリオ準備)")
            col1, col2 = st.columns(2)
            with col1:
                st.write("**【価格待ち】** (位置が悪い)")
                for _, r in df[df['状態']=="価格待ち"].iterrows():
                    with st.expander(f"{r['銘柄']} (${r['現在値']:.2f})"):
                        st.write(f"理由: {r['理由']}")
                        st.warning(f"待機指示: {r['次の一手']}")
            with col2:
                st.write("**【条件待ち】** (形が悪い)")
                for _, r in df[df['状態']=="条件待ち"].iterrows():
                    with st.expander(f"{r['銘柄']} (${r['現在値']:.2f})"):
                        st.write(f"理由: {r['理由']}")
                        st.info(f"待機指示: {r['次の一手']}")

            # 4. 対象外
            st.subheader("🗑️ 対象外")
            st.dataframe(df[df['状態']=="対象外"][["銘柄", "理由", "次の一手"]], hide_index=True)

else:
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist_df.sort_index(ascending=False), hide_index=True)
        st.caption(f"Verification Code: {get_verification_code()}")
    else: st.write("記録がありません。")
