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
st.set_page_config(page_title="Scanner v3 RC", layout="wide")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)

LOGIC_PATH = os.path.join(BASE_DIR, "core", "logic.py")
RULES_PATH = os.path.join(BASE_DIR, "config", "default_rules.json")
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

if not os.path.exists(LOGIC_PATH) or not os.path.exists(RULES_PATH):
    st.error("System file missing."); st.stop()
try: from core.logic import RuleEngine
except ImportError: st.error("Engine load failed."); st.stop()

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
            
            # 指標計算（最新の値を取得）
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
    st.title("📡 Market Scanner v3.0 (RC)")
    st.warning("⚠️ **DEMO MODE:** データは遅延/シミュレーションを含みます。売買判断には使用しないでください。")

    # DBから設定読み込み
    try:
        conn = get_db_connection()
        w_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        conn.close()
        if w_df.empty: st.warning("Watchlist empty."); return
        targets = w_df.iloc[0]['symbols'].split(',')
    except: st.error("DB Error."); return

    # ルールファイル読み込み
    with open(RULES_PATH, "r", encoding='utf-8') as f:
        rule_set = json.load(f)

    # ★v3改善点：動的なルール説明生成★
    rule_descs = []
    for c in rule_set["conditions"]:
        # JSONから「何が」「どうなれば」を抽出して説明文を作る
        target_val = c["right"].get("value", "指標値")
        op_map = {">": "より上", "<": "より下"} # 簡易表示用
        op_txt = op_map.get(c["operator"], c["operator"])
        rule_descs.append(f"- **{c['name']}**: {target_val} {op_txt}")
    
    rule_summary = "\n".join(rule_descs)

    with st.expander("⚙️ Active Strategy Logic (Dynamic View)", expanded=True):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown(f"**List:** `{w_df.iloc[0]['name']}` ({len(targets)})")
            st.caption(", ".join(targets))
        with c2:
            st.markdown(f"**Strategy:** `{rule_set['name']}`")
            # ここに生成した説明文を表示。これでロジックと説明が絶対にズレない。
            st.markdown(rule_summary)

    # スキャン実行
    if st.button("Run Scan", type="primary"):
        st.divider()
        engine = RuleEngine()
        results = []
        with st.spinner("Processing..."):
            m_data = fetch_market_data(targets)
        
        if not m_data: st.error("Data fetch failed."); return
        st.caption(f"🕒 Data Fetched: {datetime.now().strftime('%H:%M:%S')} (JST)")

        prog = st.progress(0)
        for i, sym in enumerate(targets):
            prog.progress((i+1)/len(targets))
            if sym not in m_data: continue
            
            data = m_data[sym]
            is_match, details = engine.evaluate(rule_set, data)
            
            # ★v3改善点：不一致理由の整形（丸めと差分表示）★
            reason = ""
            if not is_match:
                for _, res in details.items():
                    if not res['result'] and 'error' not in res:
                        # 例: ❌ トレンド判定 NG (現在 488.02 / 基準 498.20) [あと 10.18]
                        val_s = f"{res['left_val']:.2f}"
                        thr_s = f"{res['right_val']:.2f}"
                        diff_s = f"{res['diff']:.2f}"
                        reason = f"❌ {res['name']} NG (現在 {val_s} / 基準 {thr_s}) [あと {diff_s}]"
                        break
                    elif 'error' in res:
                        reason = f"⚠️ Error: {res['error']}"
                        break

            results.append({
                "Symbol": sym,
                "Status": "✅ MATCH" if is_match else "Wait",
                "Price": f"${data['price']:.2f}",
                "RSI": f"{data['rsi']:.1f}",
                "Reason": reason,
                "Details": details
            })
        time.sleep(0.3); prog.empty()

        # 結果表示
        df_r = pd.DataFrame(results)
        candidates = df_r[df_r["Status"] == "✅ MATCH"]
        unmatched = df_r[df_r["Status"] != "✅ MATCH"]

        st.subheader(f"Candidates ({len(candidates)})")
        if not candidates.empty:
            st.success("条件合致銘柄あり")
            for _, r in candidates.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([1, 3])
                    c1.metric(r["Symbol"], r["Price"])
                    c2.success(f"**All Conditions Cleared** (RSI: {r['RSI']})")
        else: st.info("合致銘柄なし")

        st.subheader("Watch List (Unmatched)")
        if not unmatched.empty:
            st.dataframe(
                unmatched[["Symbol", "Price", "RSI", "Reason"]],
                column_config={"Reason": st.column_config.TextColumn("Miss Reason / Distance", width="large")},
                hide_index=True, use_container_width=True
            )

if __name__ == "__main__": main()
