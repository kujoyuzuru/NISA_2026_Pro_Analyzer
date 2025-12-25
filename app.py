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

# パラメータ設定
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v25.0_Tactical_Exec"
SMA_PERIOD = 50
ATR_PERIOD = 14
STOP_MULT = 2.0
TARGET_SHORT_MULT = 4.0
MIN_RR_THRESHOLD = 2.0
RISK_PER_TRADE = 100.0  # 1トレードの許容損失(USD) - 本来はユーザー設定

# --- 2. ユーティリティ ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

def fmt_rr(val):
    """R/Rを表示用に整形 (丸め事故防止のため小数2桁)"""
    return f"{val:.2f}x" if pd.notnull(val) else "-"

# --- 3. 分析エンジン (厳格判定・発注数計算) ---

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
            
            # --- 指標診断 ---
            sma50_series = hist['Close'].rolling(window=SMA_PERIOD).mean()
            sma50_now = sma50_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5]
            atr = calculate_atr(hist, ATR_PERIOD)
            
            is_above_sma = price > sma50_now
            is_sma_rising = sma50_now > sma50_prev
            dist_sma = (price - sma50_now) / sma50_now

            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- リスク報酬比 (R/R) 計算 ---
            stop_price = price - (atr * STOP_MULT)
            risk_per_share = price - stop_price
            
            # 短期（値動き由来）
            target_short = price + (atr * TARGET_SHORT_MULT)
            rr_short = (target_short - price) / risk_per_share if risk_per_share > 0 else 0
            
            # 中期（外部予測由来）
            target_mid = info.get('targetMeanPrice')
            if target_mid and target_mid > price:
                rr_mid = (target_mid - price) / risk_per_share
                mid_status = "有効"
            else:
                target_mid = 0; rr_mid = 0; mid_status = "無効"

            # --- 分類ロジック (厳格) ---
            action = "待機"
            reason = "条件不一致"
            
            vol = atr / price
            
            if vol > 0.05:
                action, reason = "除外", f"ボラ過大 ({vol*100:.1f}%)"
            elif not is_above_sma:
                action, reason = "除外", "SMA50割れ"
            elif not is_sma_rising:
                action, reason = "除外", "SMA50下向き"
            elif rsi >= 70:
                action, reason = "監視", "過熱(RSI)"
            elif dist_sma > 0.05:
                action, reason = "監視", "乖離過大"
            elif rr_short < MIN_RR_THRESHOLD:
                action, reason = "待機", f"R/R不足 ({rr_short:.2f} < {MIN_RR_THRESHOLD})"
            else:
                action, reason = "買い候補", "条件合致"

            # 資金管理: 推奨株数 (許容損失 $100 設定)
            shares = int(RISK_PER_TRADE / risk_per_share) if risk_per_share > 0 else 0

            results.append({
                "Run_ID": run_id, "時刻": fetch_time, "銘柄": ticker, "名称": name,
                "現在値": price, "判定": action, "理由": reason,
                "損切り": stop_price, "リスク額": risk_per_share,
                "短期目標": target_short, "短期RR": rr_short,
                "中期目標": target_mid, "中期RR": rr_mid, "中期状態": mid_status,
                "推奨株数": shares, "許容リスク": RISK_PER_TRADE,
                "SMA50": sma50_now, "RSI": rsi, "ATR": atr, "乖離": dist_sma
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI構築 ---

st.sidebar.title("🦅 Market Tactical")
page = st.sidebar.radio("モード", ["🚀 今日のプラン", "⚙️ 記録・監査室"])

if page == "🚀 今日のプラン":
    st.title("🦅 Market Edge Pro")
    st.info(f"""
    ⚖️ **厳格判定プロトコル** 1. **トレンド:** 価格 > SMA50 かつ SMA50上向き  
    2. **リスク報酬比 (R/R):** 短期目標において **{MIN_RR_THRESHOLD:.1f}x 以上** であること (内部未丸め値で判定)  
    3. **到達予測:** ATR(1日の平均値動き)に基づく価格レンジ換算
    """)

    if st.button("🔍 戦略プランを生成", type="primary"):
        df = analyze_market(["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"])
        
        if not df.empty:
            s = df['判定'].value_counts()
            st.markdown(f"### 📋 実行サマリー: ✅候補 {s.get('買い候補',0)} | 👀監視 {s.get('監視',0)} | ⏳待機 {s.get('待機',0)} | 🗑️除外 {s.get('除外',0)}")
            
            # --- 1. 買い候補 ---
            st.subheader("🚀 買い候補 (Action Plan)")
            for _, r in df[df['判定']=="買い候補"].iterrows():
                with st.container():
                    c1, c2 = st.columns([3, 1])
                    with c1: st.markdown(f"#### **{r['銘柄']}** | {r['名称']}")
                    with c2: st.success("ACTION: 成行/指値 準備")
                    
                    # 4大指標
                    col_exec = st.columns(4)
                    col_exec[0].metric("想定買付", f"${r['現在値']:.2f}")
                    col_exec[1].metric("損切りライン", f"${r['損切り']:.2f}", f"-{r['乖離']*100:.1f}%")
                    col_exec[2].metric("推奨株数", f"{r['推奨株数']}株", f"損失許容 ${r['許容リスク']}")
                    col_exec[3].metric("短期R/R (ATR由来)", fmt_rr(r['短期RR']))

                    # 戦術プラン
                    st.warning(f"📝 **今日のプラン:** 終値がSMA50 (${r['SMA50']:.2f}) を維持なら、{r['推奨株数']}株を発注。損切りは ${r['損切り']:.2f} 割れで自動執行。")
                    
                    with st.expander("期待値と目標の出どころを確認"):
                        cc1, cc2 = st.columns(2)
                        with cc1:
                            st.write("**[短期] 価格の動き（ATR）由来**")
                            st.write(f"目標価格: ${r['短期目標']:.2f}")
                            st.write(f"報酬比率: {fmt_rr(r['短期RR'])}")
                        with cc2:
                            st.write("**[中期] 外部予測（アナリスト）由来**")
                            if r['中期状態'] == "有効":
                                st.write(f"目標価格: ${r['中期目標']:.2f}")
                                st.write(f"報酬比率: {fmt_rr(r['中期RR'])}")
                            else:
                                st.write("ターゲット不明のため無効")
                    st.divider()

            # --- 2. 監視・待機 ---
            col_l, col_r = st.columns(2)
            with col_l:
                st.subheader("👀 監視 (過熱・乖離の調整待ち)")
                for _, r in df[df['判定']=="監視"].iterrows():
                    with st.expander(f"{r['銘柄']} | {r['理由']}"):
                        st.info(f"指値目安: ${r['SMA50']:.2f} (この価格なら R/R {fmt_rr(r['短期RR'])})")
            
            with col_r:
                st.subheader("⏳ 待機 (期待値・モメンタム不足)")
                for _, r in df[df['判定']=="待機"].iterrows():
                    with st.expander(f"{r['銘柄']} | {r['理由']}"):
                        st.write(f"短期R/R実測: {r['短期RR']:.2f}x (合格ライン: {MIN_RR_THRESHOLD}x)")

            # --- 3. 除外 ---
            st.subheader("🗑️ 除外 (トレンド不適合)")
            st.dataframe(df[df['判定']=="除外"][["銘柄", "理由", "現在値"]], hide_index=True, use_container_width=True)

else:
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        # 内部検証用の生値を含むデータ表示
        hist_df = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist_df.sort_index(ascending=False), use_container_width=True)
        st.caption(f"Verification Code: {get_verification_code()}")
    else: st.write("ログなし")
