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

# 定数・パラメータ
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v22.1_Final_Integrated"
MIN_INTERVAL_DAYS = 7       

# トレードルール定数
SMA_PERIOD = 50                 
ATR_PERIOD = 14                 
STOP_MULTIPLIER = 2.0           
TARGET_SHORT_MULT = 3.0         
MIN_RISK_REWARD = 2.0           
DIP_TOLERANCE = 0.05            
MAX_VOLATILITY = 0.05           

# --- 2. ユーティリティ ---

def fmt_pct(val):
    return f"{val * 100:.1f}%" if pd.notnull(val) else "-"

def fmt_price(val):
    return f"${val:.2f}" if pd.notnull(val) else "-"

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    try:
        with open(HISTORY_FILE, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()[:12]
    except: return "ERROR"

def get_last_hash():
    if not os.path.exists(HISTORY_FILE): return "GENESIS"
    try:
        df = pd.read_csv(HISTORY_FILE)
        return df.iloc[-1]['Record_Hash'] if not df.empty else "GENESIS"
    except: return "GENESIS"

def calculate_chain_hash(prev_hash, content):
    combined = f"{prev_hash}|{content}"
    return hashlib.sha256(combined.encode()).hexdigest()

# --- 3. 分析エンジン (Single Source of Truth) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    return true_range.rolling(period).mean().iloc[-1]

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    return rsi.clip(0, 100).iloc[-1]

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
            
            # 指標計算
            sma50_series = hist['Close'].rolling(window=SMA_PERIOD).mean()
            sma50_now = sma50_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5]
            atr = calculate_atr(hist, ATR_PERIOD)
            vol_pct = atr / price if price else 0
            rsi = calculate_rsi(hist['Close'])
            dist_sma = (price - sma50_now) / sma50_now
            
            # 目標・損切り
            stop_loss = price - (atr * STOP_MULTIPLIER)
            risk_amt = price - stop_loss
            
            if mode == "Short":
                target_price = price + (atr * TARGET_SHORT_MULT)
                target_src = "ATR目標"
            else:
                target_price = info.get('targetMeanPrice', price * 1.15)
                target_src = "アナリスト目標"

            rr = (target_price - price) / risk_amt if risk_amt > 0 else 0
            
            # 状態判定
            is_uptrend = (price > sma50_now) and (sma50_now > sma50_prev)
            is_dip = (0 < dist_sma <= DIP_TOLERANCE)
            is_volatile = (vol_pct > MAX_VOLATILITY)
            
            if is_volatile:
                action, state, reason = "除外", "変動過大", f"日率{fmt_pct(vol_pct)}"
            elif not is_uptrend:
                action, state, reason = "除外", "トレンド不適合", "SMA50割れ/下向き"
            elif rr < MIN_RISK_REWARD:
                action, state, reason = "待機", "期待値不足", f"R/R {rr:.1f}倍"
            elif rsi >= 70:
                action, state, reason = "監視", "過熱感", f"RSI {rsi:.0f}"
            elif dist_sma > DIP_TOLERANCE:
                action, state, reason = "監視", "乖離過大", f"SMA50+{fmt_pct(dist_sma)}"
            elif is_dip:
                action, state, reason = "買い候補", "条件合致", "トレンド・押し目・RRクリア"
            else:
                action, state, reason = "待機", "条件不一致", "形状不鮮明"

            results.append({
                "Run_ID": run_id, "Scan_Time": fetch_time, "Ticker": ticker, "Name": name,
                "Price": price, "Action": action, "State": state, "Reason": reason,
                "Target": target_price, "Target_Src": target_src, "Stop": stop_loss, "RR": rr,
                "SMA50": sma50_now, "Dist_SMA": dist_sma, "RSI": rsi, "Vol_Pct": vol_pct
            })
        except: continue
    return pd.DataFrame(results)

def log_execution(df):
    prev_hash = get_last_hash()
    df_save = df.copy()
    df_save["Prev_Hash"] = prev_hash
    content = df_save[['Run_ID', 'Ticker', 'Action', 'Reason']].to_string()
    df_save["Record_Hash"] = calculate_chain_hash(prev_hash, content)
    
    # ParserError対策: 列不一致なら新規作成
    if os.path.exists(HISTORY_FILE):
        try:
            old_df = pd.read_csv(HISTORY_FILE)
            if set(old_df.columns) != set(df_save.columns):
                os.remove(HISTORY_FILE) # 構造が変わったので削除
        except: os.remove(HISTORY_FILE)
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)

# --- 4. UI構築 ---

st.sidebar.title("メニュー")
page = st.sidebar.radio("機能選択", ["🚀 市場スキャン", "⚙️ 記録・監査"])
TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if page == "🚀 市場スキャン":
    st.title("🦅 Market Edge Pro")
    c_m, c_r = st.columns([1, 3])
    with c_m: mode = st.radio("判定モード", ["Short", "Mid"])
    with c_r: st.info(f"**{mode} Mode:** 目標={'ATR×3' if mode=='Short' else 'アナリスト'} | 損切=ATR×2 | R/R>{MIN_RISK_REWARD}")

    if st.button("🔄 スキャン実行", type="primary"):
        df = analyze_market(TARGETS, mode=mode)
        if not df.empty:
            log_execution(df)
            
            # サマリー
            s = df['Action'].value_counts()
            st.markdown(f"**本日の判定:** ✅買い候補 **{s.get('買い候補',0)}** | 👀監視 **{s.get('監視',0)}** | ⏳待機 **{s.get('待機',0)}** | 🗑️除外 **{s.get('除外',0)}**")
            st.divider()

            # 買い候補
            buy_df = df[df['Action']=="買い候補"].sort_values('RR', ascending=False)
            for _, row in buy_df.iterrows():
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    c1.markdown(f"#### {row['Ticker']} {row['Name']}")
                    c2.caption(f"現在値: {fmt_price(row['Price'])}")
                    ac1, ac2, ac3, ac4 = st.columns(4)
                    ac1.info(f"🔵 **入る目安**\n\n{fmt_price(row['Price'])}")
                    ac2.error(f"🛑 **損切り**\n\n{fmt_price(row['Stop'])}")
                    ac3.success(f"🎯 **目標({row['Target_Src']})**\n\n{fmt_price(row['Target'])}")
                    ac4.metric("期待値 (R/R)", f"{row['RR']:.1f}倍")
                    st.write(f"**理由:** {row['Reason']}")
                    with st.expander("詳細データ"):
                        st.write(f"SMA50乖離: {fmt_pct(row['Dist_SMA'])} | RSI: {row['RSI']:.0f} | 変動率: {fmt_pct(row['Vol_Pct'])}")
                    st.divider()
            
            # その他
            cl, cr = st.columns(2)
            with cl:
                st.subheader("👀 監視 / 待機")
                others = df[df['Action'].isin(["監視", "待機"])].sort_values('Dist_SMA')
                for _, r in others.iterrows():
                    with st.expander(f"{r['Ticker']}: {r['Reason']}"):
                        st.write(f"R/R: {r['RR']:.1f}倍 | RSI: {r['RSI']:.0f} | 待機値: {fmt_price(r['SMA50'])}")
            with cr:
                st.subheader("🗑️ 除外")
                ex = df[df['Action']=="除外"]
                st.dataframe(ex[['Ticker', 'Reason']], hide_index=True)
        else: st.error("データ取得失敗")

else:
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        try:
            hist_df = pd.read_csv(HISTORY_FILE)
            st.dataframe(hist_df.sort_index(ascending=False).head(50))
            st.caption(f"Verification Code: {get_verification_code()}")
        except: st.warning("過去のログ形式が古いため読み込めません。スキャンを実行して新規作成してください。")
    else: st.write("ログなし")
