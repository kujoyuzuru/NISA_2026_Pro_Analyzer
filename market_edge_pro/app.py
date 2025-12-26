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

# データベース初期化ロジック
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

# --- ★修正: 市場ステータス取得 (ハイブリッド版) ---
# ホーム画面のS&P500も、リストと同じく「15分足」で見に行き、正確な値を出す
@st.cache_data(ttl=60) # 1分キャッシュ
def get_market_status():
    # 取得候補: まず指数(^GSPC)を試し、ダメならETF(SPY)
    targets = ["^GSPC", "SPY"]
    
    for ticker_symbol in targets:
        try:
            ticker = yf.Ticker(ticker_symbol)
            
            # 1. 現在値用: 直近5日間の「15分足」を取得 (これで最新価格を強制取得)
            hist_live = ticker.history(period="5d", interval="15m")
            if hist_live.empty: continue
            current_price = float(hist_live['Close'].iloc[-1])
            
            # 2. 前日比用: 直近5日間の「日足」を取得 (確定した前日終値を知るため)
            hist_daily = ticker.history(period="5d", interval="1d")
            if len(hist_daily) < 2: continue
            
            # 日足の最後が「今日の作りかけ」か「昨日」か判定
            # (簡易的に、日足の最後と現在値がほぼ同じなら、日足の最後は今日とみなして1つ前と比較)
            last_daily_close = float(hist_daily['Close'].iloc[-1])
            if abs(current_price - last_daily_close) < 0.001:
                prev_close = float(hist_daily['Close'].iloc[-2])
            else:
                prev_close = last_daily_close

            # 計算
            delta = current_price - prev_close
            delta_percent = (delta / prev_close) * 100
            
            # 名前調整
            name = "S&P 500" if ticker_symbol == "^GSPC" else "S&P 500 (ETF)"
            
            return name, f"{current_price:,.2f}", f"{delta:+.2f} ({delta_percent:+.2f}%)"
            
        except:
            continue
            
    return "S&P 500", "Load Error", "0.00%"

def main():
    # 規約同意
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
    
    # ロゴ表示
    st.markdown("""
        <h1 style='text-align: center; margin-bottom: 10px;'>
            📊 Market Edge Pro
        </h1>
    """, unsafe_allow_html=True)

    # 市場データの取得 (エラー修正版)
    idx_name, sp500_price, sp500_delta = get_market_status()

    st.markdown("---")
    
    c1, c2 = st.columns([1, 1])
    
    with c1:
        st.subheader("📊 市場ステータス")
        # delta_color="normal" (緑=プラス, 赤=マイナス) を自動判定
        st.metric(idx_name, sp500_price, sp500_delta)
        st.caption("Data: Yahoo Finance (Real-time approx)")
    
    with c2:
        st.subheader("👁 監視リスト")
        try:
            conn = get_connection()
            df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
            conn.close()
            if not df.empty:
                syms = [s.strip() for s in df.iloc[0]['symbols'].split(',') if s.strip()]
                st.write(f"**{df.iloc[0]['name']}**")
                
                # スマホで見やすいよう、タグを並べる
                if syms:
                    # 先頭8個くらいを表示
                    display_syms = syms[:8]
                    # codeタグを使ってチップ風に見せる
                    st.code(" ".join(display_syms) + (" ..." if len(syms)>8 else ""))
                else:
                    st.info("銘柄が登録されていません")
            else: st.warning("リスト未設定")
        except: st.error("DB接続エラー")

    st.markdown("---")
    
    # 誘導ボタン
    st.info("👇 以下のメニューから分析を開始してください")
    
    # ページ遷移用リンク
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
