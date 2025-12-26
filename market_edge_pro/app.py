import streamlit as st
import sqlite3
import pandas as pd
import os
import time

# dataフォルダのinit_dbを読み込む。パスが見つからない場合の保険付き
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

# ★ここが修復機能★
# 起動時にDBの中身をチェックし、空っぽならテーブルを作成する
def ensure_db_initialized():
    db_path = "trading_journal.db"
    
    # ケース1: ファイル自体がない -> 作成
    if not os.path.exists(db_path):
        return run_init("データベースファイルが見つかりません。新規作成します...")

    # ケース2: ファイルはあるが中身（テーブル）がない -> 再作成
    try:
        conn = get_connection()
        # わざとテーブルを読みに行ってみる
        conn.execute("SELECT count(*) FROM watchlists") 
        conn.close()
    except sqlite3.OperationalError:
        # 「そんなテーブルないよ」と言われたら、ここに来る
        return run_init("データベースの中身が空でした。テーブルを作成します...")
    except Exception as e:
        return run_init(f"DBエラーを検知しました ({e})。初期化します...")

def run_init(msg):
    with st.spinner(msg):
        init_db() # ここで data/init_db.py を実行
        st.success("セットアップ完了！")
        time.sleep(1)
        st.rerun()

# メイン画面の表示
def main():
    st.title("Market Edge Pro v1.0")
    
    # ★重要：ここで必ずチェックを実行★
    ensure_db_initialized()

    st.markdown("---")

    col1, col2, col3 = st.columns(3)

    # 左：市場情報
    with col1:
        st.subheader("📊 Market Status")
        st.info("Market Open (Simulation)")
        st.metric("S&P 500", "4,780.20", "+0.5%")

    # 中：監視リスト
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
        except Exception as e:
            st.error(f"読み込みエラー: {e}")

    # 右：リスク設定
    with col3:
        st.subheader("🛡 Risk Rules")
        st.write("Daily Loss Limit: **$200**")
        st.progress(0, text="Current Loss: $0 (0%)")

    st.markdown("---")
    st.markdown("### Next Actions")
    st.write("左のサイドバーから **Scanner** を選択して、今日の候補銘柄を抽出してください。")

if __name__ == "__main__":
    main()
