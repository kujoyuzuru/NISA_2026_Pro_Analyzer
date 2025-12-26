import streamlit as st
import sqlite3
import pandas as pd
import os
import time

# パス解決とDB初期化
try: from data.init_db import init_db
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    from data.init_db import init_db

st.set_page_config(page_title="Market Edge Pro", layout="wide", initial_sidebar_state="expanded")

def get_connection(): return sqlite3.connect("trading_journal.db")

def ensure_db():
    if not os.path.exists("trading_journal.db"): run_init("データベースを作成中...")
    try:
        c = get_connection(); c.execute("SELECT count(*) FROM watchlists"); c.close()
    except: run_init("データベースを修復中...")

def run_init(m):
    with st.spinner(m): init_db(); time.sleep(1); st.rerun()

def main():
    st.title("Market Edge Pro v3.1")
    ensure_db()

    # ★改善点：威圧感のない、スマートな免責表示
    st.warning("⚠️ **検証用デモ版:** 本アプリはシミュレーション専用です。データは遅延を含み、実際の投資判断には使用できません。")

    st.markdown("---")
    
    # ★改善点：見出しを日本語（英語）に統一して信頼感アップ
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.subheader("📊 市場ステータス (Status)")
        st.info("モード: **シミュレーション (Demo)**")
        st.metric("S&P 500 (参考値)", "4,780.20", "サンプルデータ")
    
    with c2:
        st.subheader("👁 監視リスト (Watchlist)")
        try:
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
            conn.close()
            if not df.empty:
                syms = df.iloc[0]['symbols'].split(',')
                st.write(f"**対象:** {df.iloc[0]['name']} ({len(syms)} 銘柄)")
                with st.expander("銘柄一覧を見る"): st.code(", ".join(syms))
            else: st.warning("リストがありません")
        except: st.error("DBエラー")
    
    with c3:
        st.subheader("🛡 リスク管理 (Risk Rules)")
        st.write("1日の損失許容額: **$200**")
        st.progress(0, "現在の損失: $0")

    st.markdown("---")
    st.success("👉 左のサイドバーから **Scanner** を選択し、デモ・スキャンを実行してください。")

if __name__ == "__main__": main()
