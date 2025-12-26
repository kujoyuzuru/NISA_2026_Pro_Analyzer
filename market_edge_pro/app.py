import streamlit as st
import sqlite3
import pandas as pd
import os
import time

# dataフォルダのinit_dbを読み込む（パス解決付き）
try:
    from data.init_db import init_db
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    from data.init_db import init_db

# ページ設定
st.set_page_config(
    page_title="Market Edge Pro",
    layout="wide",
    initial_sidebar_state="expanded"
)

# DB接続ヘルパー
def get_connection():
    return sqlite3.connect("trading_journal.db")

# DB自動修復ロジック
def ensure_db_initialized():
    db_path = "trading_journal.db"
    if not os.path.exists(db_path):
        run_init("Creating Database...")
        return
    try:
        conn = get_connection()
        conn.execute("SELECT count(*) FROM watchlists") 
        conn.close()
    except sqlite3.OperationalError:
        run_init("Repairing Database Tables...")
    except Exception:
        run_init("Initializing Database...")

def run_init(msg):
    with st.spinner(msg):
        init_db()
        time.sleep(1)
        st.rerun()

# メイン処理
def main():
    st.title("Market Edge Pro v2.0")
    
    # DBチェック
    ensure_db_initialized()

    # ★重要：全体免責事項
    st.warning("⚠️ **Disclaimer:** This application is for educational and simulation purposes only. Market data may be delayed. Do not use for financial decisions.")

    st.markdown("---")

    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("📊 Market Status")
        st.info("Status: Simulation Mode")
        st.metric("S&P 500", "4,780.20", "+0.5%")
        st.caption("※Sample Data")

    with col2:
        st.subheader("👁 Watchlist")
        try:
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
            conn.close()
            
            if not df.empty:
                symbols = df.iloc[0]['symbols'].split(',')
                st.write(f"**Target:** {df.iloc[0]['name']}")
                st.write(f"**Count:** {len(symbols)} stocks")
                with st.expander("Show Symbols"):
                    st.code(", ".join(symbols))
            else:
                st.warning("No watchlist found.")
        except Exception:
            st.error("Watchlist Error")

    with col3:
        st.subheader("🛡 Risk Rules")
        st.write("Daily Loss Limit: **$200**")
        st.progress(0, text="Current Loss: $0 (0%)")

    st.markdown("---")
    st.markdown("### Next Actions")
    st.success("👉 左サイドバーから **Scanner** を選択し、本日の候補を確認してください。")

if __name__ == "__main__":
    main()
