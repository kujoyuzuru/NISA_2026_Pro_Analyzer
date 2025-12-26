import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
import os
import hashlib
import uuid
import pytz

# --- 1. アプリ憲法 & 用語辞書 (v1.2 仕様) ---
st.set_page_config(page_title="Market Edge Pro v1.2", page_icon="🦅", layout="wide")

VERSION = "v1.2_Public_Beta"
HISTORY_FILE = "public_execution_log_v1_2.csv"

# 判定基準 (仕様6)
SPEC = {
    "SMA_PERIOD": 50,
    "ATR_PERIOD": 14,
    "STOP_MULT": 2.0,
    "TARGET_MULT": 4.0,
    "RR_THRESHOLD": 2.00,
    "DIP_LIMIT": 0.05
}

# プリセット (仕様C)
PRESETS = {
    "🇺🇸 米国・大型テック": ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "NVDA", "TSLA"],
    "🏎️ 半導体・AI": ["AVGO", "AMD", "ARM", "SMCI", "ASML", "TSM", "INTC"],
    "🦅 厳選ウォッチ": ["PLTR", "CRWD", "LLY", "NFLX", "COST", "COIN", "MSTR"]
}

# 表示文言 (仕様4, 8)
LBL = {
    "CAT_BUY": "買い候補",
    "CAT_WATCH": "監視・待機",
    "CAT_EXCL": "対象外",
    "ACT_BUY": "本日終値が条件を満たすか確認 → 条件一致なら自身のルールで検討",
    "ACT_WAIT_PRICE": "再確認ライン(SMA50)付近までの調整を待つ",
    "ACT_WAIT_COND": "R/Rなどの条件が整うのを待つ",
    "ACT_NONE": "現在は何もしない（トレンド不適合など）"
}

# --- 2. ユーティリティ ---

def get_verification_code():
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

def log_feedback(data):
    """フィードバック記録 (要件5)"""
    with open("feedback_log.txt", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now()} | {data}\n")

def convert_df(df):
    """CSVダウンロード用 (要件6-2)"""
    return df.to_csv(index=False).encode('utf-8')

# --- 3. 分析エンジン ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    return ranges.max(axis=1).rolling(period).mean().iloc[-1]

@st.cache_data(ttl=1800) # 30分キャッシュ (要件10)
def scan_market(tickers):
    results = []
    run_id = str(uuid.uuid4())[:8]
    now_jp = datetime.now(pytz.timezone('Asia/Tokyo')).strftime('%Y-%m-%d %H:%M')
    
    # プログレス表示
    prog_text = st.empty()
    prog_bar = st.progress(0)
    
    for i, ticker in enumerate(tickers):
        prog_text.text(f"データ取得・判定中... ({i+1}/{len(tickers)}): {ticker}")
        prog_bar.progress((i + 1) / len(tickers))
        try:
            stock = yf.Ticker(ticker)
            hist = stock.history(period="6mo")
            
            # データ異常検知 (仕様5)
            if len(hist) < 60:
                results.append({"銘柄": ticker, "判定": LBL["CAT_EXCL"], "理由": "データ不足", "詳細": "履歴なし"})
                continue
            
            # 鮮度チェック
            last_date = hist.index[-1]
            price = hist['Close'].iloc[-1]
            
            # 指標計算
            sma_series = hist['Close'].rolling(window=SPEC["SMA_PERIOD"]).mean()
            sma50 = sma_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5]
            atr = calculate_atr(hist, SPEC["ATR_PERIOD"])
            
            # 判定ロジック
            is_uptrend = price > sma50 and sma50 > sma50_prev
            dist_sma = (price - sma50) / sma50
            
            stop = round(price - (atr * SPEC["STOP_MULT"]), 2)
            target = round(price + (atr * SPEC["TARGET_MULT"]), 2)
            risk = price - stop
            rr = round((target - price) / risk, 2) if risk > 0 else -1
            
            # RSI (0-100クリップ)
            delta = hist['Close'].diff()
            gain = delta.where(delta > 0, 0).rolling(14).mean()
            loss = -delta.where(delta < 0, 0).rolling(14).mean()
            rsi = (100 - (100 / (1 + (gain / loss)))).clip(0, 100).iloc[-1]

            # 分類 & 要約生成 (仕様2-3, 4)
            if rr < 0 or np.isnan(rsi):
                cat, reason, act = LBL["CAT_EXCL"], "データ不整合", LBL["ACT_NONE"]
                cond_summary = "計算不能"
            elif not is_uptrend:
                cat, reason, act = LBL["CAT_EXCL"], "トレンド不適合", LBL["ACT_NONE"]
                cond_summary = "SMA50割れ/下向き"
            elif rr < SPEC["RR_THRESHOLD"]:
                cat, reason, act = LBL["CAT_WATCH"], f"R/R不足({rr:.2f})", LBL["ACT_WAIT_COND"]
                cond_summary = "期待値不足"
            elif rsi >= 70:
                cat, reason, act = LBL["CAT_WATCH"], f"過熱感(RSI{rsi:.0f})", LBL["ACT_WAIT_PRICE"]
                cond_summary = "買われすぎ"
            elif dist_sma > SPEC["DIP_LIMIT"]:
                cat, reason, act = LBL["CAT_WATCH"], f"乖離大(+{dist_sma*100:.1f}%)", LBL["ACT_WAIT_PRICE"]
                cond_summary = "移動平均から遠い"
            else:
                cat, reason, act = LBL["CAT_BUY"], "好条件", LBL["ACT_BUY"]
                cond_summary = "上昇中 / 押し目 / R/R合格"

            results.append({
                "Run_ID": run_id, "時刻": now_jp, "データ日": last_date.strftime('%Y-%m-%d'),
                "銘柄": ticker, "名称": stock.info.get('shortName', ticker), "現在値": price,
                "判定": cat, "理由": reason, "次の行動": act, "条件要約": cond_summary,
                "損切": stop, "目標": target, "RR": rr,
                "SMA50": sma50, "RSI": rsi, "乖離": dist_sma
            })
        except:
            results.append({"銘柄": ticker, "判定": LBL["CAT_EXCL"], "理由": "取得エラー", "詳細": "API接続失敗"})
            continue
            
    prog_text.empty()
    prog_bar.empty()
    return pd.DataFrame(results)

# --- 4. UI 構築 ---

# サイドバー (要件C)
st.sidebar.title("🦅 Setting")
preset = st.sidebar.selectbox("銘柄セットを選ぶ", list(PRESETS.keys()))
custom_tickers = st.sidebar.text_area("銘柄を追加・編集 (カンマ区切り)", value=",".join(PRESETS[preset]))
target_tickers = [t.strip().upper() for t in custom_tickers.split(",") if t.strip()]

page = st.sidebar.radio("メニュー", ["🚀 戦略ボード", "💬 感想を送る", "⚙️ 記録・監査"])

if page == "🚀 戦略ボード":
    st.title("🦅 Market Edge Pro v1.2")
    
    # 2-1. 3ステップ操作 & 4-2. 免責 (上部固定)
    st.info("""
    🔰 **使い方:** ①左で銘柄を選ぶ ➔ ②下のボタンでスキャン ➔ ③「次の行動」を確認  
    ⚠️ **免責:** 本アプリは機械的な判定結果を表示する道具であり、投資助言ではありません。データには遅延(約15分以上)が含まれます。最終判断はご自身で行ってください。
    """)
    
    # 3-1. データ情報
    st.caption("📡 データソース: Yahoo Finance | 更新頻度: 随時 (遅延あり) | 判定足: 日足")

    # 2-2. 折りたたみ説明
    with st.expander("📖 詳しい用語解説とルールの詳細"):
        st.markdown(f"""
        - **SMA50 (50日移動平均線):** トレンドの基準線。これより上で、線が上向きなら上昇トレンドと判定。
        - **R/R (利幅/損幅比):** リスク1に対してリターンがいくら見込めるか。{SPEC['RR_THRESHOLD']}倍以上を合格とする。
        - **ATR:** 1日の平均的な値動き幅。損切りや目標の計算に使用。
        - **損切り目安:** 現在値 - (ATR × {SPEC['STOP_MULT']})
        - **目標目安:** 現在値 + (ATR × {SPEC['TARGET_MULT']})
        """)

    if st.button("🔄 市場をスキャンして結果を更新", type="primary"):
        if not target_tickers: st.error("銘柄が入力されていません")
        else:
            df = scan_market(target_tickers)
            st.session_state['v1_2_data'] = df

    # 結果表示
    if 'v1_2_data' in st.session_state:
        df = st.session_state['v1_2_data']
        # 6-2. CSV保存
        st.download_button("📥 結果をCSVで保存", convert_df(df), "market_edge_result.csv", "text/csv")
        
        # サマリー
        counts = df['判定'].value_counts()
        st.markdown(f"**診断結果:** ✅候補 **{counts.get(LBL['CAT_BUY'],0)}** | ⏳監視・待機 **{counts.get(LBL['CAT_WATCH'],0)}** | 🗑️対象外 **{counts.get(LBL['CAT_EXCL'],0)}**")
        
        # タブ構成
        t1, t2, t3 = st.tabs(["✅ 買い候補", "⏳ 監視・待機", "🗑️ 対象外"])
        
        # --- 買い候補 (6-1. R/R順) ---
        with t1:
            buy_df = df[df['判定'] == LBL['CAT_BUY']].sort_values('RR', ascending=False)
            if buy_df.empty:
                st.info("現在、条件（トレンド・押し目・R/R）を全て満たす銘柄はありません。無理に動かずチャンスを待ちましょう。")
            else:
                for _, r in buy_df.iterrows():
                    with st.container():
                        # ヘッダー
                        c1, c2 = st.columns([3, 1])
                        c1.subheader(f"{r['銘柄']} {r['名称']}")
                        c2.caption(f"現在値: ${r['現在値']:.2f}")
                        
                        # 2-3. 条件要約
                        st.caption(f"💡 条件: {r['条件要約']}")
                        
                        # 4-1. 次の行動
                        st.success(f"👉 **次の行動:** {r['次の行動']}")
                        
                        # 数値
                        kc1, kc2, kc3, kc4 = st.columns(4)
                        kc1.metric("利幅/損幅(R/R)", f"{r['RR']}x")
                        kc2.metric("損切り目安", f"${r['損切']:.2f}", f"{(r['損切']-r['現在値'])/r['現在値']:.1%}")
                        kc3.metric("目標目安", f"${r['目標']:.2f}", f"{(r['目標']-r['現在値'])/r['現在値']:.1%}")
                        kc4.metric("基準線(SMA50)", f"${r['SMA50']:.2f}")
                        
                        # 詳細
                        with st.expander("詳細データ"):
                            st.write(f"RSI: {r['RSI']:.0f} | 乖離: {r['乖離']:.1%} | データ日: {r['データ日']}")
                        st.divider()

        # --- 監視・待機 (6-1. 乖離順=近い順) ---
        with t2:
            watch_df = df[df['判定'] == LBL['CAT_WATCH']].sort_values('乖離')
            if watch_df.empty: st.write("なし")
            else:
                st.write("※条件や価格が整うのを待つリストです。")
                for _, r in watch_df.iterrows():
                    with st.expander(f"**{r['銘柄']}** (${r['現在値']:.2f}) | {r['理由']}"):
                        # 2-4. 待つ価格の明示
                        st.warning(f"👀 **待つ目安:** ${r['SMA50']:.2f} 付近 (SMA50)")
                        st.write(f"判定理由: {r['理由']}")
                        st.write(f"次の行動: {r['次の行動']}")

        # --- 対象外 ---
        with t3:
            excl_df = df[df['判定'] == LBL['CAT_EXCL']]
            if excl_df.empty: st.write("なし")
            else:
                st.dataframe(excl_df[["銘柄", "理由", "次の行動"]], hide_index=True, use_container_width=True)

# --- フィードバック (要件5) ---
elif page == "💬 感想を送る":
    st.title("💬 改善フィードバック")
    st.write("使いにくい点や、欲しい機能があれば教えてください。Run_ID等が自動添付されます。")
    
    # 5-1. テンプレボタン
    col_fb1, col_fb2 = st.columns(2)
    fb_template = ""
    if col_fb1.button("「分かりにくい」を送る"):
        fb_template = "【分かりにくい点】\n・\n\n【どの画面で】\n・"
    if col_fb2.button("「機能要望」を送る"):
        fb_template = "【欲しい機能】\n・\n\n【なぜ必要か】\n・"

    with st.form("fb_form"):
        sentiment = st.selectbox("満足度", ["普通", "良い", "とても良い", "使いにくい"])
        comment = st.text_area("内容", value=fb_template, height=150)
        submitted = st.form_submit_button("送信")
        
        if submitted:
            # 5-2. 自動付与データ
            meta_info = {
                "Ver": VERSION,
                "Run_ID": st.session_state.get('v1_2_data', pd.DataFrame({'Run_ID':['N/A']}))['Run_ID'].iloc[0],
                "Preset": preset,
                "Tickers_Count": len(target_tickers)
            }
            log_feedback(f"{sentiment} | {comment} | {meta_info}")
            st.success("送信しました。開発の参考にさせていただきます！")

# --- 過去ログ ---
elif page == "⚙️ 記録・監査":
    st.title("⚙️ 過去ログ")
    if os.path.exists(HISTORY_FILE):
        st.dataframe(pd.read_csv(HISTORY_FILE).sort_index(ascending=False))
        st.caption(f"Verification: {get_verification_code()}")
    else: st.info("履歴なし")
