import streamlit as st
import pandas as pd
import yfinance as yf
import json
import os
import sqlite3
import ta
import time
import sys
from datetime import datetime

# --- セットアップ ---
st.set_page_config(page_title="Scanner", layout="wide")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)

LOGIC_PATH = os.path.join(BASE_DIR, "core", "logic.py")
RULES_PATH = os.path.join(BASE_DIR, "config", "default_rules.json")
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

if not os.path.exists(LOGIC_PATH) or not os.path.exists(RULES_PATH):
    st.error("システムファイルが見つかりません"); st.stop()
try: from core.logic import RuleEngine
except ImportError: st.error("エンジン読み込み失敗"); st.stop()

# --- DB/Data Helper ---
def get_db_connection():
    return sqlite3.connect(DB_PATH)

@st.cache_data(ttl=300)
def fetch_market_data(symbols):
    data_map = {}
    tickers = " ".join(symbols)
    if not tickers: return {}
    try:
        df = yf.download(tickers, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except: return {}

    for sym in symbols:
        try:
            sdf = df if len(symbols)==1 else df[sym]
            if sdf.empty or len(sdf)<50: continue
            
            close = float(sdf['Close'].iloc[-1])
            sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
            rsi14 = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
            vol = float(sdf['Volume'].iloc[-1])
            
            data_map[sym] = {
                "symbol": sym, "price": close, "close": close,
                "sma": sma50, "rsi": rsi14, "volume": vol,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except: continue
    return data_map

# --- メイン画面 ---
def main():
    st.title("📡 市場スキャナー (Scanner)")
    st.warning("⚠️ **デモモード:** データは遅延しており、売買判断には使用できません。")

    # DB設定読み込み
    try:
        conn = get_db_connection()
        w_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        conn.close()
        if w_df.empty: st.warning("監視リストが空です"); return
        targets = w_df.iloc[0]['symbols'].split(',')
    except: st.error("DBエラー"); return

    # ルール読み込み
    with open(RULES_PATH, "r", encoding='utf-8') as f:
        rule_set = json.load(f)

    # ルール説明の生成
    rule_descs = []
    for c in rule_set["conditions"]:
        target_val = c["right"].get("value", "指標値")
        op_map = {">": "より上", "<": "より下"}
        op_txt = op_map.get(c["operator"], c["operator"])
        rule_descs.append(f"- **{c['name']}**: {target_val} {op_txt}")
    
    rule_summary = "\n".join(rule_descs)

    # ★改善点：設定エリアの日本語化
    with st.expander("⚙️ 適用中の戦略ロジック (Active Strategy)", expanded=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown(f"**監視対象:** `{w_df.iloc[0]['name']}` ({len(targets)} 銘柄)")
            st.caption(", ".join(targets))
        with c2:
            st.markdown(f"**戦略名:** `{rule_set['name']}`")
            st.markdown(rule_summary)

    # スキャン実行
    if st.button("スキャン実行 (Run Scan)", type="primary"):
        st.divider()
        engine = RuleEngine()
        results = []
        with st.spinner("市場データを取得・分析中..."):
            m_data = fetch_market_data(targets)
        
        if not m_data: st.error("データ取得に失敗しました"); return
        st.caption(f"🕒 データ取得時刻: {datetime.now().strftime('%H:%M:%S')} (JST)")

        prog = st.progress(0)
        for i, sym in enumerate(targets):
            prog.progress((i+1)/len(targets))
            if sym not in m_data: continue
            
            data = m_data[sym]
            is_match, details = engine.evaluate(rule_set, data)
            
            reason = ""
            if not is_match:
                for _, res in details.items():
                    if not res['result'] and 'error' not in res:
                        val_s = f"{res['left_val']:.2f}"
                        thr_s = f"{res['right_val']:.2f}"
                        diff_s = f"{res['diff']:.2f}"
                        # ★改善点：理由の日本語表記を自然に
                        reason = f"❌ {res['name']} NG (現在 {val_s} / 基準 {thr_s}) [あと {diff_s}]"
                        break
                    elif 'error' in res:
                        reason = f"⚠️ エラー: {res['error']}"
                        break

            results.append({
                "銘柄 (Symbol)": sym,
                "判定 (Status)": "✅ 合致" if is_match else "待機",
                "現在値": f"${data['price']:.2f}",
                "RSI": f"{data['rsi']:.1f}",
                "不一致の理由 / 乖離幅": reason,
                "Details": details
            })
        time.sleep(0.3); prog.empty()

        # 結果表示
        df_r = pd.DataFrame(results)
        candidates = df_r[df_r["判定 (Status)"] == "✅ 合致"]
        unmatched = df_r[df_r["判定 (Status)"] != "✅ 合致"]

        # ★改善点：見出しの日本語化
        st.subheader(f"条件合致（候補）: {len(candidates)} 件")
        if not candidates.empty:
            st.success("エントリー条件を満たす銘柄が見つかりました")
            for _, r in candidates.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([1, 3])
                    c1.metric(r["銘柄 (Symbol)"], r["現在値"])
                    c2.success(f"**全条件クリア** (RSI: {r['RSI']})")
        else: st.info("現在、条件に合致する銘柄はありません")

        st.subheader("監視継続（条件未達）")
        if not unmatched.empty:
            # 表示用データのカラム整理
            display_cols = ["銘柄 (Symbol)", "現在値", "RSI", "不一致の理由 / 乖離幅"]
            st.dataframe(
                unmatched[display_cols],
                column_config={
                    "不一致の理由 / 乖離幅": st.column_config.TextColumn("不一致の理由 / 乖離幅", width="large")
                },
                hide_index=True, use_container_width=True
            )

if __name__ == "__main__": main()
