import streamlit as st
import sqlite3
import pandas as pd
import os

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

    # データベースの存在チェック
    if not os.path.exists("trading_journal.db"):
        st.error("データベースが見つかりません。 `python data/init_db.py` を実行してください。")
        return

    # 3カラムレイアウト
    col1, col2, col3 = st.columns(3)

    with col1:
        st.subheader("📊 Market Status")
        st.info("Market Open (Simulation)") # ここは後でAPIから取得
        st.metric("S&P 500", "4,780.20", "+0.5%")

    with col2:
        st.subheader("👁 Watchlist")
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

    with col3:
        st.subheader("🛡 Risk Rules")
        st.write("Daily Loss Limit: **$200**")
        st.progress(0, text="Current Loss: $0 (0%)")

    st.markdown("---")
    st.markdown("### Next Actions")
    st.write("左のサイドバーから **Scanner** を選択して、今日の候補銘柄を抽出してください。")

if __name__ == "__main__":
    main()
