import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid
import pytz

# --- 1. アプリ憲法 & 用語辞書 (仕様 v1.1) ---
st.set_page_config(page_title="Market Edge Pro v1.1", page_icon="🦅", layout="wide")

VERSION = "v1.1_Public_Release"
HISTORY_FILE = "public_execution_log.csv"

# 判定基準の固定 (要件B)
SPEC = {
    "SMA_PERIOD": 50,
    "ATR_PERIOD": 14,
    "STOP_MULT": 2.0,      # 損切り幅: ATRの2倍
    "TARGET_MULT": 4.0,    # 目標幅: ATRの4倍 (短期)
    "RR_THRESHOLD": 2.00,  # R/R 閾値: 2.00以上
    "DIP_LIMIT": 0.05      # 押し目許容: SMA+5%以内
}

# プリセット銘柄 (要件C)
PRESETS = {
    "🇺🇸 米国・大型テック": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "🏎️ 半導体・AI": ["AVGO", "AMD", "ARM", "SMCI", "ASML", "TSM", "INTC"],
    "🦅 厳選ウォッチ": ["PLTR", "CRWD", "LLY", "NFLX", "COST", "COIN", "MSTR"]
}

# --- 2. ユーティリティ & 監査 (要件B, D) ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

def log_feedback(run_id, sentiment, comment):
    """簡易的なフィードバック記録 (本番は外部DBやメール連携推奨)"""
    fb_file = "feedback_log.txt"
    with open(fb_file, "a", encoding="utf-8") as f:
        f.write(f"[{datetime.now()}] ID:{run_id} | Rank:{sentiment} | Msg:{comment}\n")

# --- 3. 分析エンジン (要件A, E) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return ranges.max(axis=1).rolling(period).mean().iloc[-1]

@st.cache_data(ttl=1800) # 30分キャッシュ (要件E)
def scan_market(tickers):
    results = []
    run_id = str(uuid.uuid4())[:8]
    now_jp = datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M')
    
    progress_text = st.empty()
    bar = st.progress(0)
    
    for i, ticker in enumerate(tickers):
        progress_text.text(f"スキャン中: {ticker} ({i+1}/{len(tickers)})")
        bar.progress((i+1)/len(tickers))
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            if len(hist) < 60: continue
            
            price = hist['Close'].iloc[-1]
            sma_series = hist['Close'].rolling(window=SPEC["SMA_PERIOD"]).mean()
            sma50 = sma_series.iloc[-1]
            sma50_prev = sma_series.iloc[-5]
            atr = calculate_atr(hist, SPEC["ATR_PERIOD"])
            
            # ロジック判定
            is_uptrend = price > sma50 and sma50 > sma50_prev
            dist_sma = (price - sma50) / sma50
            
            stop = round(price - (atr * SPEC["STOP_MULT"]), 2)
            target = round(price + (atr * SPEC["TARGET_MULT"]), 2)
            rr = round((target - price) / (price - stop), 2) if (price - stop) > 0 else -1
            
            # 分類
            action = "除外"
            reason = "トレンド不適合"
            if rr < 0: action, reason = "除外", "データ不整合"
            elif not is_uptrend: action, reason = "除外", "SMA50割れ/下向き"
            elif rr < SPEC["RR_THRESHOLD"]: action, reason = "待機", f"R/R不足({rr:.2f})"
            elif dist_sma > SPEC["DIP_LIMIT"]: action, reason = "監視", "乖離過大"
            else: action, reason = "買い候補", "条件合致"

            results.append({
                "Run_ID": run_id, "時刻": now_jp, "銘柄": ticker, "価格": price,
                "判定": action, "理由": reason, "損切": stop, "目標": target, "RR": rr,
                "SMA50": sma50, "距離": dist_sma
            })
        except:
            results.append({"銘柄": ticker, "判定": "除外", "理由": "取得失敗"})
            continue
            
    progress_text.empty()
    bar.empty()
    return pd.DataFrame(results)

# --- 4. UI 構築 (要件A, C, D) ---

# サイドバー: 銘柄カスタム (要件C)
st.sidebar.title("🦅 Setting")
preset_choice = st.sidebar.selectbox("銘柄セット選択", list(PRESETS.keys()))
custom_input = st.sidebar.text_area("銘柄をカスタム (カンマ区切り)", value=",".join(PRESETS[preset_choice]))
tickers = [t.strip().upper() for t in custom_input.split(",") if t.strip()]

page = st.sidebar.radio("機能切替", ["🚀 戦略ボード", "⚙️ 過去ログ・監査室", "💬 フィードバック"])

# --- 戦略ボード (要件A, B) ---
if page == "🚀 戦略ボード":
    st.title("🦅 Market Edge Pro v1.1")
    
    # 使い方カード (要件A, B)
    with st.expander("📖 はじめての方へ：このアプリの使い方と免責", expanded=True):
        st.markdown(f"""
        **このアプリは何をするもの？** あらかじめ決めた「短期上昇トレンドの押し目」ルールを、選んだ銘柄に機械的に当てはめて「今日何をするか」を表示する道具です。
        
        **用語のかんたん説明:**
        - **損切り**: ここまで下がったら諦めて撤退する目安の価格。
        - **目標**: ここまで上がったら一旦利確を検討する目安の価格。
        - **利幅/損幅比 (R/R)**: リスク1に対してどれだけの利益が見込めるかの倍率（2.0以上を推奨）。
        - **SMA50**: 過去50日の平均価格。この線より上で、線が上を向いているのが上昇トレンドの条件。
        
        **⚠️ 免責事項:**
        本アプリは投資助言ではありません。計算結果を表示するツールであり、最終的な判断は必ずご自身の責任で行ってください。データには遅延や欠損が含まれる場合があります。
        """)

    if st.button("🔄 市場をスキャンして行動を決める", type="primary"):
        if not tickers: st.warning("銘柄を入力してください")
        else:
            df = scan_market(tickers)
            st.session_state['v1_1_data'] = df

    if 'v1_1_data' in st.session_state:
        df = st.session_state['v1_1_data']
        res = df['判定'].value_counts()
        st.success(f"スキャン完了: ✅候補 {res.get('買い候補',0)} | ⏳待機/監視 {res.get('待機',0)+res.get('監視',0)} | 🗑️除外 {res.get('除外',0)}")
        st.caption(f"ID: {df['時刻'].iloc[0]} | Run_ID: {df['Run_ID'].iloc[0]}")

        t1, t2, t3 = st.tabs(["✅ 買い候補", "⏳ 待機・監視", "🗑️ 除外"])
        
        with t1:
            buy_df = df[df['判定']=="買い候補"]
            if buy_df.empty: st.info("現在、条件を満たす『買い候補』はありません。")
            for _, r in buy_df.iterrows():
                with st.container():
                    c1, c2, c3 = st.columns([2, 1, 1])
                    c1.markdown(f"### **{r['銘柄']}**")
                    c2.metric("利幅/損幅比 (R/R)", f"{r['RR']:.2f}x")
                    c3.write("**次の行動:**\n本日終値の維持を確認し発注")
                    
                    cc1, cc2, cc3 = st.columns(3)
                    cc1.metric("現在値", f"${r['価格']:.2f}")
                    cc2.metric("損切り目安", f"${r['損切']:.2f}", f"{(r['損切']-r['価格'])/r['価格']:.1%}")
                    cc3.metric("目標目安", f"${r['目標']:.2f}", f"{(r['目標']-r['価格'])/r['価格']:.1%}")
                    
                    with st.expander("📊 判定の詳細根拠"):
                        st.write(f"- トレンド: 上昇 (SMA50:${r['SMA50']:.2f} を超えて推移)")
                        st.write(f"- 押し目状況: 良好 (SMA50から {r['距離']*100:.1f}% の位置)")
                        st.write(f"- 理由: {r['理由']}")
                    st.divider()

        with t2:
            st.dataframe(df[df['判定'].isin(["待機", "監視"])][["銘柄", "判定", "理由", "価格"]], use_container_width=True, hide_index=True)
            st.caption("※価格がSMA50付近まで調整するか、R/R条件が整うのを待ちます。")

        with t3:
            st.dataframe(df[df['判定']=="除外"][["銘柄", "理由"]], use_container_width=True, hide_index=True)
            st.caption("※上昇トレンドが崩れているか、ボラティリティが過大です。")

# --- 過去ログ・分析室 ---
elif page == "⚙️ 記録・監査室":
    st.title("⚙️ 過去の実行記録")
    if os.path.exists(HISTORY_FILE):
        hist = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist.sort_index(ascending=False), use_container_width=True, hide_index=True)
        st.caption(f"Verification Code: {get_verification_code()}")
    else: st.info("履歴がありません")

# --- フィードバック (要件D) ---
elif page == "💬 フィードバック":
    st.title("💬 改善へのご協力")
    st.write("NOTEでの公開をより良くするため、ご感想や不具合報告をお聞かせください。")
    with st.form("feedback_form"):
        sentiment = st.select_slider("このアプリの満足度は？", options=["😞", "😐", "🙂", "🤩"])
        comment = st.text_area("感想・要望・不具合報告（Run_IDが自動添付されます）")
        submitted = st.form_submit_button("送信する")
        if submitted:
            run_id = st.session_state.get('v1_1_data', pd.DataFrame([{'Run_ID':'N/A'}]))['Run_ID'].iloc[0]
            log_feedback(run_id, sentiment, comment)
            st.success("ありがとうございます！いただいた内容は大切に確認し、改善に役立てます。")
