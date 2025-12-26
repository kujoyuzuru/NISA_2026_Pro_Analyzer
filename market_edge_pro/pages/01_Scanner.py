import streamlit as st
import pandas as pd
import yfinance as yf
import json
import os
import sqlite3
import ta
import time
import sys
from datetime import datetime

# ---------------------------------------------------------
# セットアップ & パス解決（迷子防止）
# ---------------------------------------------------------
st.set_page_config(page_title="Scanner v2", layout="wide")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# パス定義
LOGIC_PATH = os.path.join(BASE_DIR, "core", "logic.py")
RULES_PATH = os.path.join(BASE_DIR, "config", "default_rules.json")
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# ファイルチェック
if not os.path.exists(LOGIC_PATH) or not os.path.exists(RULES_PATH):
    st.error("⚠️ 必要なシステムファイルが見つかりません。")
    st.stop()

# エンジン読み込み
try:
    from core.logic import RuleEngine
except ImportError:
    st.error("ロジックエンジンの読み込みに失敗しました。")
    st.stop()

# ---------------------------------------------------------
# 強制DB修復機能
# ---------------------------------------------------------
def force_init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS watchlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, symbols TEXT)''')
    c.execute("SELECT count(*) FROM watchlists")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO watchlists (name, symbols) VALUES (?, ?)", 
                  ("Default Watchlist", "AAPL,MSFT,TSLA,NVDA,GOOGL,AMZN,META,AMD"))
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------
def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("SELECT * FROM watchlists LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        force_init_db()
        conn = sqlite3.connect(DB_PATH)
    return conn

@st.cache_data(ttl=300) # 5分キャッシュ（鮮度重視）
def fetch_market_data(symbols):
    data_map = {}
    tickers = " ".join(symbols)
    if not tickers: return {}

    try:
        # 過去データ取得（日足）
        df = yf.download(tickers, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except Exception:
        return {}

    for symbol in symbols:
        try:
            if len(symbols) == 1:
                stock_df = df
            else:
                if symbol not in df: continue
                stock_df = df[symbol]
            
            if stock_df.empty or len(stock_df) < 50: continue

            # 指標計算
            close_price = float(stock_df['Close'].iloc[-1])
            sma_indicator = ta.trend.SMAIndicator(stock_df['Close'], window=50)
            sma_50 = sma_indicator.sma_indicator().iloc[-1]
            rsi_indicator = ta.momentum.RSIIndicator(stock_df['Close'], window=14)
            rsi_14 = rsi_indicator.rsi().iloc[-1]
            volume = float(stock_df['Volume'].iloc[-1])

            data_map[symbol] = {
                "symbol": symbol, "price": close_price, "close": close_price,
                "sma": sma_50, "rsi": rsi_14, "volume": volume,
                "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
        except Exception:
            continue
    return data_map

# ---------------------------------------------------------
# メイン画面処理
# ---------------------------------------------------------
def main():
    st.title("📡 Market Scanner v2.0")
    
    # ★重要：誤解防止の免責表示
    st.warning("⚠️ **DEMO MODE:** 表示データは遅延またはシミュレーションを含みます。実取引には使用しないでください。")

    # DB接続
    try:
        conn = get_db_connection()
        watchlist_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        conn.close()
    except Exception as e:
        st.error(f"Database Error: {e}")
        if st.button("Fix Database"):
            force_init_db()
            st.rerun()
        return

    target_symbols = watchlist_df.iloc[0]['symbols'].split(',')

    # ルール読み込み
    with open(RULES_PATH, "r", encoding='utf-8') as f:
        rule_set = json.load(f)

    # 設定表示
    with st.expander("⚙️ Current Strategy & Target", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**List:** `{watchlist_df.iloc[0]['name']}`")
            st.caption(", ".join(target_symbols))
        with c2:
            st.markdown(f"**Strategy:** `{rule_set['name']}`")
            st.markdown(f"_{rule_set['description']}_")

    # スキャン実行
    if st.button("Run Scan", type="primary"):
        st.divider()
        engine = RuleEngine()
        results = []
        
        with st.spinner("Fetching market data..."):
            market_data_map = fetch_market_data(target_symbols)

        if not market_data_map:
            st.error("データ取得に失敗しました。時間をおいて再試行してください。")
            return

        # ★重要：データ時点の明示
        scan_time = datetime.now().strftime("%H:%M:%S")
        st.caption(f"🕒 Data fetched at: {scan_time} (JST)")

        progress_bar = st.progress(0)
        for i, symbol in enumerate(target_symbols):
            progress_bar.progress((i + 1) / len(target_symbols))
            
            if symbol not in market_data_map: continue

            data = market_data_map[symbol]
            is_match, details = engine.evaluate(rule_set, data)
            
            # 不一致理由の生成（GPT指摘への対応）
            reject_reason = ""
            if not is_match:
                for code, res in details.items():
                    if not res['result']:
                        # 失敗した条件を見つけて理由を書く
                        val = res.get('left_val', 0)
                        threshold = res.get('right_val', 0)
                        op = res.get('operator', '')
                        reject_reason = f"❌ {res['name']} NG ({val:.1f} {op} {threshold})"
                        break # 最初の失敗理由だけ採用
            
            row = {
                "Symbol": symbol,
                "Status": "✅ MATCH" if is_match else "Wait",
                "Price": f"${data['price']:.2f}",
                "RSI": f"{data['rsi']:.1f}",
                "Reason": reject_reason, # 理由カラム
                "Details": details
            }
            results.append(row)

        time.sleep(0.5)
        progress_bar.empty()

        # 結果の振り分け
        df_results = pd.DataFrame(results)
        candidates = df_results[df_results["Status"] == "✅ MATCH"]
        unmatched = df_results[df_results["Status"] != "✅ MATCH"]

        # 1. 候補リスト
        st.subheader(f"Candidates ({len(candidates)})")
        if not candidates.empty:
            st.success("エントリー候補が見つかりました")
            for _, row in candidates.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([1, 1, 3])
                    c1.metric(row["Symbol"], row["Price"])
                    c2.metric("RSI", row["RSI"])
                    c3.success(f"**All Clear:** {rule_set['description']}")
        else:
            st.info("現在、条件に合致する銘柄はありません。")

        # 2. 不一致リスト（GPT指摘：ここをただの表にしない）
        st.subheader("Watch List (Unmatched)")
        if not unmatched.empty:
            # 表示用データの整理
            display_df = unmatched[["Symbol", "Price", "RSI", "Reason"]]
            st.dataframe(
                display_df,
                column_config={
                    "Reason": st.column_config.TextColumn("Miss Reason", width="medium"),
                },
                hide_index=True,
                use_container_width=True
            )

if __name__ == "__main__":
    main()
