import streamlit as st
import sqlite3
import pandas as pd
import os
import time

# ★重要修正：初期化スクリプトをインポート
# （dataフォルダに __init__.py が必要です）
from data.init_db import init_db

# ページ設定（必ず最初に記述）
st.set_page_config(
    page_title="Market Edge Pro",
    layout="wide",
    initial_sidebar_state="expanded"
)

# DB接続ヘルパー
def get_connection():
    return sqlite3.connect("trading_journal.db")

# メイン処理
def main():
    st.title("Market Edge Pro v1.0")
    st.markdown("---")

    # データベースの自動セットアップ
    # 起動時にDBファイルがなければ、init_db() を実行して作成する
    if not os.path.exists("trading_journal.db"):
        with st.spinner("初回セットアップ中：データベースを作成しています..."):
            try:
                init_db()
                # 作成完了のメッセージを一瞬表示
                st.success("データベース作成完了！")
                time.sleep(1) # ユーザーがメッセージを読めるように少し待機
                st.rerun()    # 画面をリロードして通常起動へ
            except Exception as e:
                st.error(f"データベース作成に失敗しました: {e}")
                return

    # ここから通常画面の描画
    col1, col2, col3 = st.columns(3)

    # 左カラム：市場ステータス
    with col1:
        st.subheader("📊 Market Status")
        st.info("Market Open (Simulation)") # 将来的にAPI連携
        st.metric("S&P 500", "4,780.20", "+0.5%")

    # 中央カラム：監視リスト情報
    with col2:
        st.subheader("👁 Watchlist")
        try:
            conn = get_connection()
            # 監視リストの最初の1つを取得
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
            st.error(f"データ読み込みエラー: {e}")

    # 右カラム：リスク管理ルール
    with col3:
        st.subheader("🛡 Risk Rules")
        st.write("Daily Loss Limit: **$200**")
        st.progress(0, text="Current Loss: $0 (0%)")

    st.markdown("---")
    st.markdown("### Next Actions")
    st.write("左のサイドバーから **Scanner** を選択して、今日の候補銘柄を抽出してください。")

if __name__ == "__main__":
    main()
