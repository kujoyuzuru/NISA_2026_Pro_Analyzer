import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid
import pytz

# --- 1. アプリ設定 & 用語辞書 (仕様固定) ---
st.set_page_config(page_title="Market Edge Pro v1.0", page_icon="🦅", layout="wide")

VERSION = "v1.0_Standard"
HISTORY_FILE = "execution_log_v1.csv"

# 用語・判定ルールの一括定義 (仕様 6, 8)
APP_SPEC = {
    "SMA_PERIOD": 50,
    "ATR_PERIOD": 14,
    "STOP_MULT": 2.0,      # 損切り幅算出用
    "TARGET_MULT": 4.0,    # 短期目標算出用
    "RR_THRESHOLD": 2.00,  # 合格R/R
    "DIP_LIMIT": 0.05      # 押し目許容(SMA50から+5%以内)
}

# 表示文言の統一 (仕様 4, 8)
LBL = {
    "ACTION_NOW": "今すぐ検討",
    "WATCH": "監視・待機",
    "EXCLUDE": "対象外",
    "STEP_BUY": "本日終値がルール条件を満たすか確認し、満たしたら発注準備",
    "STEP_RR": "損切り幅が想定内か再確認",
    "STEP_WAIT_PRICE": "再確認ライン付近までの調整を待つ",
    "STEP_WAIT_TREND": "上昇トレンドへの回帰を待つ",
    "STEP_NONE": "今は何もしない"
}

# --- 2. 内部エンジン (仕様 5, 6) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return ranges.max(axis=1).rolling(period).mean().iloc[-1]

@st.cache_data(ttl=3600)
def fetch_and_analyze(tickers):
    results = []
    run_id = str(uuid.uuid4())[:8]
    now_jp = datetime.now(pytz.timezone('Asia/Tokyo'))
    now_ny = datetime.now(pytz.timezone('America/New_York'))
    
    status_msg = st.empty()
    progress_bar = st.progress(0)
    
    for i, ticker in enumerate(tickers):
        status_msg.text(f"診断中... ({i+1}/{len(tickers)}): {ticker}")
        progress_bar.progress((i + 1) / len(tickers))
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            if len(hist) < 60: continue
            
            # データ鮮度確認 (仕様 5)
            last_date = hist.index[-1].strftime('%Y-%m-%d')
            price = hist['Close'].iloc[-1]
            
            # 指標計算
            sma_series = hist['Close'].rolling(window=APP_SPEC["SMA_PERIOD"]).mean()
            sma50 = sma_series.iloc[-1]
            sma50_prev = sma_series.iloc[-5]
            atr = calculate_atr(hist, APP_SPEC["ATR_PERIOD"])
            
            # 判定条件
            is_uptrend = price > sma50 and sma50 > sma50_prev
            dist_sma = (price - sma50) / sma50
            
            # 損切・目標・R/R (小数2桁固定 仕様 6)
            stop_price = round(price - (atr * APP_SPEC["STOP_MULT"]), 2)
            target_price = round(price + (atr * APP_SPEC["TARGET_MULT"]), 2)
            risk = price - stop_price
            reward = target_price - price
            rr_val = round(reward / risk, 2) if risk > 0 else -1.0
            
            # RSI
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # 分類ロジック (仕様 4, 8)
            if rr_val < 0 or np.isnan(rsi):
                cat, reason, step = LBL["EXCLUDE"], "データ不整合", LBL["STEP_NONE"]
            elif not is_uptrend:
                cat, reason, step = LBL["EXCLUDE"], "トレンド不適合", LBL["STEP_WAIT_TREND"]
            elif rr_val < APP_SPEC["RR_THRESHOLD"]:
                cat, reason, step = LBL["WATCH"], f"R/R不足({rr_val:.2f})", LBL["STEP_RR"]
            elif rsi >= 70 or dist_sma > APP_SPEC["DIP_LIMIT"]:
                cat, reason, step = LBL["WATCH"], "過熱・乖離あり", LBL["STEP_WAIT_PRICE"]
            else:
                cat, reason, step = LBL["ACTION_NOW"], "全条件合致", LBL["STEP_BUY"]

            results.append({
                "Run_ID": run_id, "日本時間": now_jp.strftime('%Y-%m-%d %H:%M'),
                "米国時間": now_ny.strftime('%Y-%m-%d %H:%M'), "データ最終日": last_date,
                "銘柄": ticker, "名称": stock.info.get('shortName', ticker), "現在値": price,
                "結論": cat, "判定理由": reason, "次の行動": step,
                "損切り": stop_price, "目標": target_price, "RR": rr_val,
                "SMA50": sma50, "RSI": rsi, "ATR": atr, "距離": dist_sma
            })
        except Exception as e:
            results.append({"銘柄": ticker, "結論": "エラー", "判定理由": "取得失敗", "次の行動": "再試行待ち"})
            continue
            
    status_msg.empty()
    progress_bar.empty()
    return pd.DataFrame(results)

# --- 3. UI 構築 (仕様 3, 4) ---

mode = st.sidebar.radio("機能メニュー", ["🚀 戦略ボード", "⚙️ 過去ログ・分析室"])

if mode == "🚀 戦略ボード":
    st.title("🦅 Market Edge Pro")
    
    # ヘッダー情報 (仕様 4)
    st.markdown(f"""
    <div style="background-color:#f0f2f6; padding:10px; border-radius:5px; font-size:0.9em;">
    <b>ルール:</b> 短期スイング（日足） | <b>対象:</b> 米国主要株 | <b>更新:</b> 市場をスキャンして結果を更新 ボタンを押してください
    </div>
    """, unsafe_allow_html=True)

    if st.button("🔄 市場をスキャンして結果を更新", type="primary"):
        tickers = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "CRWD", "LLY", "NFLX", "COST"]
        df = fetch_and_analyze(tickers)
        if not df.empty:
            st.session_state['v1_data'] = df
            # ログ保存
            if not os.path.exists(HISTORY_FILE): df.to_csv(HISTORY_FILE, index=False)
            else: df.to_csv(HISTORY_FILE, mode='a', header=False, index=False)

    if 'v1_data' in st.session_state:
        df = st.session_state['v1_data']
        r = df.iloc[0]
        st.caption(f"🕒 更新(日本): {r['日本時間']} | 更新(現地): {r['米国時間']} | データ末尾: {r['データ最終日']} | ID: {r['Run_ID']}")
        
        counts = df['結論'].value_counts()
        st.markdown(f"**診断結果:** 検討中 {len(df)} 銘柄中 ➔ ✅検討:{counts.get(LBL['ACTION_NOW'],0)} / ⏳待機:{counts.get(LBL['WATCH'],0)} / 🗑️対象外:{counts.get(LBL['EXCLUDE'],0)}")

        t1, t2, t3 = st.tabs([f"✅ {LBL['ACTION_NOW']}", f"⏳ {LBL['WATCH']}", f"🗑️ {LBL['EXCLUDE']}"])

        with t1:
            target = df[df['結論']==LBL['ACTION_NOW']]
            if target.empty: st.info("現在、条件を満たす銘柄はありません。")
            for _, row in target.iterrows():
                with st.container():
                    col1, col2 = st.columns([3, 1])
                    with col1: st.subheader(f"{row['銘柄']} : {row['名称']}")
                    with col2: st.metric("利得損失比(R/R)", f"{row['RR']}x")
                    
                    c = st.columns(4)
                    c[0].metric("現在値", f"${row['現在値']:.2f}")
                    c[1].metric("損切り", f"${row['損切り']:.2f}", f"{(row['損切り']-row['現在値'])/row['現在値']:.1%}")
                    c[2].metric("目標", f"${row['目標']:.2f}", f"{(row['目標']-row['現在値'])/row['現在値']:.1%}")
                    c[3].write(f"📌 **次の一手:**\n{row['次の行動']}")
                    
                    with st.expander("📊 根拠・詳細データ (クリックで開く)"):
                        st.markdown(f"""
                        - **RSI (過熱感):** {row['RSI']:.1f} （70以上は買われすぎ）
                        - **SMA50 (50日線):** ${row['SMA50']:.2f} （これより上で上昇中が条件）
                        - **SMA乖離率:** {row['距離']*100:.1f}% （5%以内の押し目を狙う）
                        - **ATR (平均値幅):** ${row['ATR']:.2f} （1日の平均的な値動き幅）
                        - **判定理由:** {row['判定理由']}
                        """)
                    st.divider()

        with t2:
            st.caption("定義: トレンドは良いが、価格が高すぎるか期待値が届かない銘柄です。")
            st.dataframe(df[df['結論']==LBL['WATCH']][["銘柄", "判定理由", "次の行動", "現在値", "SMA50", "RR"]], hide_index=True)

        with t3:
            st.caption("定義: 下落トレンド、またはボラティリティ過多でルールに適合しません。")
            st.dataframe(df[df['結論']==LBL['EXCLUDE']][["銘柄", "判定理由", "次の行動"]], hide_index=True)

    st.divider()
    st.caption("⚠️ 免責事項: 本アプリは設定されたルールに基づく計算結果を表示するツールであり、投資助言ではありません。最終的な投資判断は必ずご自身の責任で行ってください。")

else:
    st.title("⚙️ 過去ログ・分析室")
    if os.path.exists(HISTORY_FILE):
        log_df = pd.read_csv(HISTORY_FILE)
        st.write("### 実行履歴 (Run単位)")
        run_summary = log_df.groupby('Run_ID').agg({'日本時間':'first', '銘柄':'count', 'データ最終日':'first'}).sort_index(ascending=False)
        st.dataframe(run_summary, use_container_width=True)
        
        st.write("### 詳細ログ (銘柄単位)")
        st.dataframe(log_df.sort_index(ascending=False), hide_index=True)
    else:
        st.info("まだ実行履歴がありません。")
