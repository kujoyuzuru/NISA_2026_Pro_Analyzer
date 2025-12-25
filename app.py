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

# パラメータ
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v23.0_Decision_Navigator"
SMA_PERIOD = 50
ATR_PERIOD = 14
STOP_MULT = 2.0
TARGET_MULT = 4.0
MIN_RR = 2.0
MAX_VOL = 0.05

# --- 2. ユーティリティ ---

def fmt_val(price, pct=None):
    """金額と割合のセット表示"""
    if pct is not None:
        color = "red" if pct < 0 else "green"
        return f"${price:.2f} (:{color}[{pct*100:+.1f}%])"
    return f"${price:.2f}"

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

# --- 3. 分析エンジン ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return ranges.max(axis=1).rolling(period).mean().iloc[-1]

@st.cache_data(ttl=3600)
def analyze_market(tickers, mode="Short"):
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
            
            # 指標
            sma50 = hist['Close'].rolling(window=SMA_PERIOD).mean().iloc[-1]
            sma50_prev = hist['Close'].rolling(window=SMA_PERIOD).mean().iloc[-5]
            atr = calculate_atr(hist, ATR_PERIOD)
            vol = atr / price
            
            # RSI計算
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- 判定ロジック ---
            is_uptrend = (price > sma50) and (sma50 > sma50_prev)
            dist_sma = (price - sma50) / sma50
            
            # カテゴリ決定
            action = "待機"
            reason = "条件不一致"
            
            if vol > MAX_VOL:
                action, reason = "除外", f"変動過大 (日率{vol*100:.1f}%)"
            elif not is_uptrend and price < sma50:
                action, reason = "除外", "トレンド崩壊 (SMA50下)"
            elif rsi >= 70:
                action, reason = "監視", "買われすぎ (RSI基準)"
            elif dist_sma > 0.05:
                action, reason = "監視", "乖離大 (移動平均から)"
            elif is_uptrend:
                action, reason = "買い候補", "押し目合致"

            # --- 価格シナリオ計算 ---
            # 候補なら現在値、待機/監視なら「想定エントリー(SMA50)」を基準にする
            base_entry = price if action == "買い候補" else sma50
            
            # 損切り・目標 (モード別)
            stop_price = base_entry - (atr * STOP_MULT)
            if mode == "Short":
                target_price = base_entry + (atr * TARGET_MULT)
                target_src = f"ATR基準(×{TARGET_MULT})"
            else:
                target_price = info.get('targetMeanPrice', base_entry * 1.15)
                target_src = "アナリスト平均"

            # R/R計算
            risk = base_entry - stop_price
            reward = target_price - base_entry
            rr = reward / risk if risk > 0 else 0

            # 最終フィルタ: 期待値不足
            if action == "買い候補" and rr < MIN_RR:
                action, reason = "待機", f"期待値不足 (R/R {rr:.1f})"

            results.append({
                "Run_ID": run_id, "時刻": fetch_time, "銘柄": ticker, "名称": name,
                "現在値": price, "判定": action, "理由": reason,
                "想定エントリー": base_entry, "損切り": stop_price, "目標": target_price,
                "RR": rr, "目標出所": target_src, "SMA50": sma50, "RSI": rsi, "変動率": vol,
                "乖離率": dist_sma
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI ---

st.sidebar.title("Menu")
page = st.sidebar.radio("機能", ["🚀 市場スキャン", "⚙️ 記録・監査室"])

if page == "🚀 市場スキャン":
    st.title("🦅 Market Edge Pro")
    st.caption(f"**Action Protocol:** R/R = (目標 - 想定エントリー) ÷ (想定エントリー - 損切り)")
    
    c_m, c_r = st.columns([1, 3])
    with c_m: mode = st.radio("判定モード", ["Short", "Mid"])
    with c_r: st.info(f"**判定基準:** トレンド(Price>SMA50 & 向き↑) | 損切(ATR×{STOP_MULT}) | 期待値({MIN_RR}倍以上)")

    if st.button("🔄 今日のプランを生成", type="primary"):
        df = analyze_market(["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"], mode=mode)
        
        if not df.empty:
            # サマリー
            s = df['判定'].value_counts()
            st.markdown(f"**判定結果:** ✅候補 **{s.get('買い候補',0)}** | 👀監視 **{s.get('監視',0)}** | ⏳待機 **{s.get('待機',0)}** | 🗑️除外 **{s.get('除外',0)}**")
            
            # 1. 候補 (今動く)
            st.subheader("🚀 買い候補 (Action Required)")
            for _, r in df[df['判定']=="買い候補"].iterrows():
                with st.expander(f"**{r['銘柄']}** | {r['理由']} | R/R: {r['RR']:.1f}倍", expanded=True):
                    c = st.columns(4)
                    c[0].metric("想定Entry", f"${r['想定エントリー']:.2f}")
                    c[1].metric("損切り", f"${r['損切り']:.2f}", f"{(r['損切り']-r['想定エントリー'])/r['想定エントリー']:.1%}")
                    c[2].metric("目標価格", f"${r['目標']:.2f}", f"{(r['目標']-r['想定エントリー'])/r['想定エントリー']:.1%}")
                    c[3].metric("期待値(R/R)", f"{r['RR']:.1f}倍")
                    st.caption(f"出所: 損切り=ATR×{STOP_MULT}, 目標={r['目標出所']}")

            # 2. 監視・待機 (想定シナリオ表示)
            st.subheader("⏳ 待機・監視 (条件成立時の想定シナリオ)")
            for _, r in df[df['判定'].isin(["監視", "待機"])].iterrows():
                with st.expander(f"**{r['銘柄']}** (${r['現在値']:.2f}) | {r['理由']}"):
                    st.write(f"⏰ **待機シナリオ:** ${r['想定エントリー']:.2f} (SMA50) まで調整した場合")
                    c = st.columns(4)
                    c[0].write(f"想定買付: **${r['想定エントリー']:.2f}**")
                    c[1].write(f"その時の損切: **${r['損切り']:.2f}**")
                    c[2].write(f"その時の目標: **${r['目標']:.2f}**")
                    c[3].write(f"期待値: **{r['RR']:.1f}倍**")
                    st.caption(f"現在のRSI: {r['RSI']:.0f} / 現在の乖離: {r['乖離率']:.1%}")

            # 3. 除外
            st.subheader("🗑️ 除外")
            st.dataframe(df[df['判定']=="除外"][["銘柄", "理由", "現在値"]], hide_index=True)

else:
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        # 高度なデータテーブル
        st.dataframe(
            hist_df.sort_index(ascending=False),
            column_config={
                "RR": st.column_config.NumberColumn("期待値(R/R)", format="%.1f"),
                "現在値": st.column_config.NumberColumn("価格", format="$%.2f"),
                "乖離率": st.column_config.ProgressColumn("乖離", min_value=-0.2, max_value=0.2)
            },
            hide_index=True
        )
        st.caption(f"Verification Code: {get_verification_code()}")
    else: st.write("No logs.")
