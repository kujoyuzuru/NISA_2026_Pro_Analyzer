import streamlit as st
import sqlite3
import pandas as pd
import os
import time
import yfinance as yf

# --- セットアップ ---
st.set_page_config(
    page_title="Market Edge Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# データベース初期化
try: from data.init_db import init_db
except ImportError:
    import sys
    sys.path.append(os.path.abspath(os.path.dirname(__file__)))
    from data.init_db import init_db

# --- DB接続 ---
def get_connection(): return sqlite3.connect("trading_journal.db")

def ensure_db():
    if not os.path.exists("trading_journal.db"): run_init("System Initializing...")
    try:
        c = get_connection(); c.execute("SELECT count(*) FROM watchlists"); c.close()
    except: run_init("Database Repairing...")

def run_init(m):
    with st.spinner(m): init_db(); time.sleep(1); st.rerun()

# --- ★修正: 最軽量・高速なデータ取得 (Fast Info) ---
# history()を使わず、fast_infoを使うことでエラーと待ち時間をなくす
@st.cache_data(ttl=30)
def get_market_status():
    target = "SPY"
    
    try:
        ticker = yf.Ticker(target)
        
        # fast_infoは通信量が少なく、一瞬で「現在値」と「前日終値」だけを取れる
        # これならタイムアウトやデータ欠損がほぼ起きない
        current_price = ticker.fast_info.last_price
        prev_close = ticker.fast_info.previous_close
        
        if current_price and prev_close:
            delta = current_price - prev_close
            delta_percent = (delta / prev_close) * 100
            
            return "S&P 500 ETF (SPY)", f"${current_price:,.2f}", f"{delta:+.2f} ({delta_percent:+.2f}%)"
            
    except:
        # 万が一失敗した場合は、エラーではなく「---」を表示してアプリを止めない
        pass
            
    return "S&P 500 (SPY)", "$---", "0.00%"

def main():
    if "tos_agreed" not in st.session_state: st.session_state.tos_agreed = False
    if not st.session_state.tos_agreed:
        st.info("👋 ようこそ。利用を開始する前に確認してください。")
        with st.expander("利用規約・免責事項", expanded=True):
            st.markdown("1. 本アプリは参考情報です。\n2. データは遅延する場合があります。\n3. 投資判断は自己責任でお願いします。")
            if st.button("上記に同意して利用を開始する"):
                st.session_state.tos_agreed = True
                st.rerun()
        return

    ensure_db()
    
    st.markdown("""
        <h1 style='text-align: center; margin-bottom: 10px;'>
            📊 Market Edge Pro
        </h1>
    """, unsafe_allow_html=True)

    # 高速データ取得
    idx_name, sp500_price, sp500_delta = get_market_status()

    st.markdown("---")
    
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("📊 市場ステータス")
        st.metric(idx_name, sp500_price, sp500_delta)
        # ちゃんとSPYであることを明記
        st.caption("Target: SPY (S&P 500 ETF) | Real-time Quote")
    
    with c2:
        st.subheader("👁 監視リスト")
        try:
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
            conn.close()
            if not df.empty:
                syms = [s.strip() for s in df.iloc[0]['symbols'].split(',') if s.strip()]
                st.write(f"**{df.iloc[0]['name']}**")
                if syms:
                    display_syms = syms[:8]
                    st.code(" ".join(display_syms) + (" ..." if len(syms)>8 else ""))
                else:
                    st.info("銘柄が登録されていません")
            else: st.warning("リスト未設定")
        except: st.error("DB接続エラー")

    st.markdown("---")
    
    st.info("👇 以下のメニューから分析を開始してください")
    
    st.markdown("""
    <div style="text-align: center;">
        <a href="/Watchlist" target="_self" style="
            display: inline-block;
            text-decoration: none;
            background-color: #FF4B4B;
            color: white;
            padding: 10px 20px;
            border-radius: 5px;
            font-weight: bold;
        ">🚀 AI分析ダッシュボードを起動 (Start)</a>
    </div>
    """, unsafe_allow_html=True)

if __name__ == "__main__": main()
