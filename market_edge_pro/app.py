import streamlit as st
import sqlite3
import pandas as pd
import os
import time

try: from data.init_db import init_db
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    from data.init_db import init_db

st.set_page_config(page_title="Market Edge Pro v3", layout="wide", initial_sidebar_state="expanded")

def get_connection(): return sqlite3.connect("trading_journal.db")

def ensure_db():
    if not os.path.exists("trading_journal.db"): run_init("Initializing DB...")
    try:
        c = get_connection(); c.execute("SELECT count(*) FROM watchlists"); c.close()
    except: run_init("Repairing DB...")

def run_init(m):
    with st.spinner(m): init_db(); time.sleep(1); st.rerun()

def main():
    st.title("Market Edge Pro v3.0 (RC)")
    ensure_db()

    # ★v3: より強い免責表示
    st.error("⚠️ **DISCLAIMER (重要免責事項):** 本アプリは教育・検証用デモです。表示されるデータやシグナルは遅延、不正確、またはシミュレーションを含みます。実際の金融取引の判断根拠として使用しないでください。開発者は本アプリの使用による損害について一切の責任を負いません。")

    st.markdown("---")
    c1, c2, c3 = st.columns(3)
    with c1:
        st.subheader("📊 Market Status")
        st.info("Mode: **DEMO / SIMULATION**")
        st.metric("S&P 500 (Ref)", "4,780.20", "Sample Data")
    with c2:
        st.subheader("👁 Watchlist Target")
        try:
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
            conn.close()
            if not df.empty:
                syms = df.iloc[0]['symbols'].split(',')
                st.write(f"**List:** {df.iloc[0]['name']} ({len(syms)})")
                with st.expander("View Symbols"): st.code(", ".join(syms))
            else: st.warning("No Watchlist")
        except: st.error("DB Error")
    with c3:
        st.subheader("🛡 Risk Rules (Demo)")
        st.write("Daily Loss Limit: **$200**")
        st.progress(0, "Current Loss: $0")

    st.markdown("---")
    st.success("👉 左サイドバーから **Scanner** を選択し、デモ・スキャンを実行してください。")

if __name__ == "__main__": main()
