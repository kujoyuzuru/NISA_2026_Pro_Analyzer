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

# --- ★修正: 鉄壁のデータ取得ロジック ---
# サーバーでブロックされにくいよう、キャッシュ時間を少し伸ばし(60秒)、
# 失敗したら別の方法で取りに行く「二段構え」にします。
@st.cache_data(ttl=60)
def get_market_status():
    target = "SPY"
    
    # 【作戦1】まずは最も確実な「history (過去データ)」から取得
    # ※サーバー上ではこれが一番安定します
    try:
        ticker = yf.Ticker(target)
        # 直近5日分のデータを取得（休日またぎ対策）
        hist = ticker.history(period="5d", interval="1d")
        
        if not hist.empty and len(hist) >= 1:
            # 最新の終値（または現在値）
            current_price = float(hist['Close'].iloc[-1])
            
            # 前日終値の取得（データが2行以上あれば1つ前を使う）
            if len(hist) >= 2:
                prev_close = float(hist['Close'].iloc[-2])
            else:
                # データが1行しかない場合は、infoから前日比を探す（バックアップ）
                prev_close = float(ticker.info.get('previousClose', current_price))

            delta = current_price - prev_close
            delta_percent = (delta / prev_close) * 100
            
            return "S&P 500 ETF (SPY)", f"${current_price:,.2f}", f"{delta:+.2f} ({delta_percent:+.2f}%)"
    except:
        pass # 作戦1が失敗したら、作戦2へ

    # 【作戦2】historyがダメなら「fast_info (板情報)」を試す
    try:
        ticker = yf.Ticker(target)
        curr = ticker.fast_info.last_price
        prev = ticker.fast_info.previous_close
        if curr and prev:
            delta = curr - prev
            pct = (delta / prev) * 100
            return "S&P 500 ETF (SPY)", f"${curr:,.2f}", f"{delta:+.2f} ({pct:+.2f}%)"
    except:
        pass

    # 全部ダメだった場合
    return "S&P 500 (SPY)", "$---", "Loading..."

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
    
    # リンクアイコン風の装飾を削除してシンプルに
    st.markdown("""
        <h1 style='text-align: center; margin-bottom: 10px;'>
            📊 Market Edge Pro
        </h1>
    """, unsafe_allow_html=True)

    idx_name, sp500_price, sp500_delta = get_market_status()

    st.markdown("---")
    
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("📊 市場ステータス")
        st.metric(idx_name, sp500_price, sp500_delta)
        st.caption("Target: SPY (S&P 500 ETF)")
    
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
