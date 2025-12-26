import streamlit as st
import sqlite3
import pandas as pd
import os
import time

# dataフォルダのinit_dbを読み込む
try:
    from data.init_db import init_db
except ImportError:
    # パスが解決できない場合の保険（絶対パスで再トライ）
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

# ★追加：DBが壊れていないかチェックして修復する関数★
def ensure_db_initialized():
    db_path = "trading_journal.db"
    
    # 1. ファイルがない場合 -> 作成
    if not os.path.exists(db_path):
        return run_init("データベースが見つかりません。新規作成します...")

    # 2. ファイルはあるが、テーブルがない場合（今回のエラーはここ） -> 再作成
    try:
        conn = get_connection()
        conn.execute("SELECT count(*) FROM watchlists") # テストクエリ
        conn.close()
    except sqlite3.OperationalError:
        # テーブルがないエラーが出たら、再作成する
        return run_init("データベースの中身が空です。テーブルを作成します...")
    except Exception as e:
        return run_init(f"DBエラー検知 ({e})。再構築します...")

def run_init(msg):
    with st.spinner(msg):
        init_db()
        st.success("セットアップ完了！")
        time.sleep(1)
        st.rerun()

# メイン処理
def main():
    st.title("Market Edge Pro v1.0")
    
    # 起動時に必ずDBチェックを行う
    ensure_db_initialized()

    st.markdown("---")

    col1, col2, col3 = st.columns(3)

    # 左カラム：市場ステータス
    with col1:
        st.subheader("📊 Market Status")
        st.info("Market Open (Simulation)")
        st.metric("S&P 500", "4,780.20", "+0.5%")

    # 中央カラム：監視リスト情報
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

    # 右カラム：リスク管理
    with col3:
        st.subheader("🛡 Risk Rules")
        st.write("Daily Loss Limit: **$200**")
        st.progress(0, text="Current Loss: $0 (0%)")

    st.markdown("---")
    st.markdown("### Next Actions")
    st.write("左のサイドバーから **Scanner** を選択して、今日の候補銘柄を抽出してください。")

if __name__ == "__main__":
    main()
