import streamlit as st
import sqlite3
import pandas as pd
import os
import time
import yfinance as yf # 追加: 株価取得用

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

# --- 追加: 市場データを取得する関数 ---
@st.cache_data(ttl=600) # 10分間キャッシュして高速化
def get_market_status():
    try:
        # S&P 500のティッカーは ^GSPC
        ticker = yf.Ticker("^GSPC")
        # 過去2日分のデータを取得（前日比を出すため）
        hist = ticker.history(period="2d")
        
        if len(hist) < 2:
            return "N/A", "0.00"
        
        current_price = hist['Close'].iloc[-1]
        prev_close = hist['Close'].iloc[-2]
        delta = current_price - prev_close
        delta_percent = (delta / prev_close) * 100
        
        return f"{current_price:,.2f}", f"{delta:+.2f} ({delta_percent:+.2f}%)"
    except:
        return "Error", "0.00"

def main():
    # 利用規約チェック
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
            st.stop()

    st.title("Market Edge Pro")
    ensure_db()

    # ★修正: リアルタイムデータの取得
    sp500_price, sp500_delta = get_market_status()

    st.markdown("---")
    
    c1, c2, c3 = st.columns(3)
    
    with c1:
        st.subheader("📊 市場ステータス")
        # ここに変数をセット
        st.metric("S&P 500", sp500_price, sp500_delta)
        st.caption("Data: Yahoo Finance (Delayed)")
    
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
