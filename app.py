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
PROTOCOL_VER = "v26.0_Swing_Navigator"
SMA_PERIOD = 50
ATR_PERIOD = 14
STOP_MULT = 2.0         # 損切り幅 (ATR x N)
TARGET_SWING_MULT = 4.0 # 短期スイング目標 (ATR x N)
MIN_RR_THRESHOLD = 2.0  # 合格R/R
ESTIMATED_WIN_RATE = 0.5 # 推定勝率 (期待値計算用)

# --- 2. ユーティリティ ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

# --- 3. 分析エンジン (ロジック整合性強化) ---

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
            sma50_prev = sma50_series.iloc[-5]
            atr = calculate_atr(hist, ATR_PERIOD)
            
            # トレンド：価格が上で、かつ50日線が上向き
            is_above_sma = price > sma50_now
            is_sma_rising = sma50_now > sma50_prev
            dist_sma = (price - sma50_now) / sma50_now
            
            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # --- 2. リスク・報酬の算出 (時間軸の統一) ---
            # 損切りライン
            stop_price = price - (atr * STOP_MULT)
            risk_amt = price - stop_price
            
            # 【短期スイング目標】ボラティリティ由来 (現実的な出口)
            target_swing = price + (atr * TARGET_SWING_MULT)
            reward_swing = target_swing - price
            rr_swing = reward_swing / risk_amt if risk_amt > 0 else 0
            
            # 【長期参考目標】アナリスト予測由来 (夢の出口)
            target_long = info.get('targetMeanPrice', 0)
            rr_long = (target_long - price) / risk_amt if (target_long > price and risk_amt > 0) else 0

            # 期待期待値（勝率50%と仮定した1トレードあたりの期待損益比）
            # 式: (勝率 * 平均利益) - (負率 * 平均損失) -> 比率化
            expected_value = (ESTIMATED_WIN_RATE * rr_swing) - ((1 - ESTIMATED_WIN_RATE) * 1.0)

            # --- 3. 損切りの「狩られやすさ」診断 ---
            # 過去20日間で、安値が「今日設定した損切りライン相当（現在値-ATR*2）」を割った日数を数える
            # (簡易的なバックテスト的視点)
            recent_hist = hist.tail(20)
            hit_count = (recent_hist['Low'] < (recent_hist['Close'] - (atr * STOP_MULT))).sum()

            # --- 4. 分類ロジック (厳格) ---
            action = "待機"
            reason = "条件不一致"
            
            if atr/price > 0.05:
                action, reason = "除外", f"ボラ過大 (日率{(atr/price)*100:.1f}%)"
            elif not is_above_sma:
                action, reason = "除外", "SMA50割れ"
            elif not is_sma_rising:
                action, reason = "除外", "SMA50下向き"
            elif rsi >= 70:
                action, reason = "監視", f"買われすぎ (RSI:{rsi:.0f})"
            elif dist_sma > 0.05:
                action, reason = "監視", f"乖離大 (SMA50+{dist_sma*100:.1f}%)"
            elif rr_swing < MIN_RR_THRESHOLD:
                action, reason = "待機", f"R/R不足 ({rr_swing:.1f}x)"
            else:
                action, reason = "買い候補", "条件合致"

            results.append({
                "Run_ID": run_id, "時刻": fetch_time, "銘柄": ticker, "名称": name,
                "現在値": price, "判定": action, "理由": reason,
                "損切り": stop_price, "リスク額": risk_amt,
                "短期目標": target_swing, "短期RR": rr_swing, "期待損益比": expected_value,
                "長期目標": target_long, "長期RR": rr_long,
                "SMA50": sma50_now, "RSI": rsi, "ATR": atr, "乖離": dist_sma,
                "損切到達回数": hit_count
            })
        except: continue
    return pd.DataFrame(results)

# --- 4. UI構築 (実戦コックピット) ---

st.sidebar.title("🦅 Tactical Swing")
page = st.sidebar.radio("モード", ["🚀 今日の判断", "⚙️ 記録・監査室"])

if page == "🚀 今日の判断":
    st.title("🦅 Market Edge Pro")
    st.info(f"""
    ⚖️ **Swing Trade Protocol ({PROTOCOL_VER})**
    1. **上昇定義:** 価格 > SMA50 かつ SMA50が上昇中  
    2. **短期目標:** ATR × {TARGET_SWING_MULT} (値動き由来の現実的出口)  
    3. **損切り:** ATR × {STOP_MULT} | **期待値:** 勝率{ESTIMATED_WIN_RATE*100:.0f}%想定の損益比を表示
    """)

    if st.button("🔍 市場を診断する", type="primary"):
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
                    with c2: st.success("ACTION: 本日終値で検討")
                    
                    # 戦術数値
                    col_exec = st.columns(4)
                    col_exec[0].metric("想定買付", f"${r['現在値']:.2f}")
                    col_exec[1].metric("損切り(撤退)", f"${r['損切り']:.2f}", f"-{r['リスク額']/r['現在値']*100:.1f}%")
                    col_exec[2].metric("短期目標(利確)", f"${r['短期目標']:.2f}", f"+{r['短期RR']*r['リスク額']/r['現在値']*100:.1f}%")
                    col_exec[3].metric("短期R/R比", f"{r['短期RR']:.1f}x")

                    # 期待値とリアリティ・チェック
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        st.write(f"📈 **期待損益比:** {r['期待損益比']:.2f} (勝率{ESTIMATED_WIN_RATE*100:.0f}%想定)")
                        st.caption("※1.0を超えると、統計的に資金が増える計算")
                    with cc2:
                        hit_color = "red" if r['損切到達回数'] > 3 else "green"
                        st.write(f"🛡️ **損切りの堅牢性:** :{hit_color}[過去20日で {r['損切到達回数']}回 到達]")
                        st.caption(f"※回数が多いほど、普段の揺れで狩られるリスク高")

                    with st.expander("長期ポテンシャル (参考)"):
                        st.write(f"・アナリスト目標: ${r['長期目標']:.2f} (長期R/R: {r['長期RR']:.1f}x)")
                        st.write(f"・SMA50基準価格: ${r['SMA50']:.2f}")
                    st.divider()

            # --- 2. 監視・待機 ---
            st.subheader("⏳ 監視・待機 (シナリオ準備)")
            for _, r in df[df['判定'].isin(["監視", "待機"])].iterrows():
                with st.expander(f"**{r['銘柄']}** (${r['現在値']:.2f}) | {r['理由']}"):
                    st.write(f"⏰ **狙い目:** ${r['SMA50']:.2f} (SMA50付近)")
                    c = st.columns(3)
                    c[0].write(f"想定Entry: **${r['想定エントリー' if '想定エントリー' in r else r['SMA50']]:.2f}**")
                    c[1].write(f"短期R/R想定: **{r['短期RR']:.1f}x**")
                    c[2].write(f"現在の過熱感: **RSI {r['RSI']:.0f}**")

            # --- 3. 除外 ---
            st.subheader("🗑️ 除外 (不適合)")
            st.dataframe(df[df['判定']=="除外"][["銘柄", "理由", "現在値"]], hide_index=True, use_container_width=True)

else:
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist_df.sort_index(ascending=False), use_container_width=True)
        st.caption(f"Verification Code: {get_verification_code()}")
