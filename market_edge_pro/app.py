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

st.set_page_config(page_title="Market Edge Pro", layout="wide", initial_sidebar_state="expanded")

def get_connection(): return sqlite3.connect("trading_journal.db")

def ensure_db():
    if not os.path.exists("trading_journal.db"): run_init("System Initializing...")
    try:
        c = get_connection(); c.execute("SELECT count(*) FROM watchlists"); c.close()
    except: run_init("Database Repairing...")

def run_init(m):
    with st.spinner(m): init_db(); time.sleep(1); st.rerun()

def main():
    st.title("Market Edge Pro") # バージョン表記も消してシンプルに
    ensure_db()

    # --- プロ仕様: 利用規約同意チェック ---
    if "tos_agreed" not in st.session_state:
        st.session_state.tos_agreed = False

    if not st.session_state.tos_agreed:
        st.info("👋 ようこそ。利用を開始する前に確認してください。")
        with st.expander("利用規約・免責事項 (Terms of Service)", expanded=True):
            st.markdown("""
            1. **情報の性質**: 本アプリが提供する分析結果は参考情報であり、投資勧誘を目的としたものではありません。
            2. **データ**: 市場データは提供元の状況により遅延または欠損する場合があります。
            3. **自己責任**: 本アプリの利用による損益について、開発者は一切の責任を負いません。
            """)
            agree = st.checkbox("上記に同意して利用を開始する")
            
        if agree:
            st.session_state.tos_agreed = True
            st.rerun()
        else:
            st.stop() # 同意しないと先に進めない

    # --- 本番ダッシュボード ---
    st.markdown("---")
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.subheader("📊 市場ステータス")
        # 本来はここもAPIで取るが、今回は静的表示でデザインを優先
        st.metric("S&P 500", "4,780.20", "+0.5%")
        st.caption("Market Status: OPEN")
    
    with c2:
        st.subheader("👁 監視リスト")
        try:
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
            conn.close()
            if not df.empty:
                syms = df.iloc[0]['symbols'].split(',')
                st.write(f"**{df.iloc[0]['name']}** ({len(syms)} 銘柄)")
                with st.expander("銘柄一覧"): st.code(", ".join(syms))
            else: st.warning("リスト未設定")
        except: st.error("DB接続エラー")
    
    with c3:
        st.subheader("🛡 アカウント設定")
        st.write("プラン: **Standard**")
        st.write("日次許容損失: **$200.00**")

    st.markdown("---")
    st.success("✅ 準備完了: 左サイドバーから **Scanner** を起動してください。")

if __name__ == "__main__": main()
