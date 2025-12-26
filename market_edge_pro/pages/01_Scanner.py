import streamlit as st
import pandas as pd
import yfinance as yf
import json
import os
import sqlite3
import ta
import time
import sys

# ---------------------------------------------------------
# セットアップ & パス解決
# ---------------------------------------------------------
st.set_page_config(page_title="Scanner", layout="wide")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

# パスの定義
LOGIC_PATH = os.path.join(BASE_DIR, "core", "logic.py")
RULES_PATH = os.path.join(BASE_DIR, "config", "default_rules.json")
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# ファイル存在チェック
if not os.path.exists(LOGIC_PATH):
    st.error(f"⚠️ ファイルが見つかりません: {LOGIC_PATH}")
    st.stop()
if not os.path.exists(RULES_PATH):
    st.error(f"⚠️ ファイルが見つかりません: {RULES_PATH}")
    st.stop()

# ロジックエンジンの読み込み
try:
    from core.logic import RuleEngine
except ImportError:
    st.error("ロジックエンジンの読み込みに失敗しました。")
    st.stop()

# ---------------------------------------------------------
# ★緊急修理機能：データベース初期化★
# ---------------------------------------------------------
def force_init_db():
    """テーブルがない場合に無理やり作成する関数"""
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    
    # 1. 監視リストテーブル作成
    c.execute('''
        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            symbols TEXT NOT NULL
        )
    ''')
    
    # 2. データが空なら初期データを入れる
    c.execute("SELECT count(*) FROM watchlists")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO watchlists (name, symbols) VALUES (?, ?)", 
                  ("Default Watchlist", "AAPL,MSFT,TSLA,NVDA,GOOGL,AMZN,META,AMD"))

    # その他のテーブルも念のため作成
    c.execute('''
        CREATE TABLE IF NOT EXISTS rule_sets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            json_body TEXT NOT NULL
        )
    ''')
    c.execute('''
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            rule_set_id TEXT,
            symbol TEXT,
            is_match BOOLEAN,
            match_details JSON,
            market_data_snapshot JSON
        )
    ''')
    conn.commit()
    conn.close()

# ---------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------
def get_db_connection():
    # 接続時にテーブルチェックを行う（なければ直す）
    conn = sqlite3.connect(DB_PATH)
    try:
        conn.execute("SELECT * FROM watchlists LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        # エラーが出たら修理実行
        force_init_db()
        # 再接続
        conn = sqlite3.connect(DB_PATH)
    return conn

@st.cache_data(ttl=3600)
def fetch_market_data(symbols):
    data_map = {}
    tickers = " ".join(symbols)
    if not tickers: return {}

    try:
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

            close_price = float(stock_df['Close'].iloc[-1])
            sma_indicator = ta.trend.SMAIndicator(stock_df['Close'], window=50)
            sma_50 = sma_indicator.sma_indicator().iloc[-1]
            rsi_indicator = ta.momentum.RSIIndicator(stock_df['Close'], window=14)
            rsi_14 = rsi_indicator.rsi().iloc[-1]
            volume = float(stock_df['Volume'].iloc[-1])

            data_map[symbol] = {
                "symbol": symbol, "price": close_price, "close": close_price,
                "sma": sma_50, "rsi": rsi_14, "volume": volume
            }
        except Exception:
            continue
    return data_map

# ---------------------------------------------------------
# メイン画面処理
# ---------------------------------------------------------
def main():
    st.title("📡 Market Scanner")
    
    # DB接続 & 監視リスト取得
    try:
        conn = get_db_connection() # ここで自動修復が走る
        watchlist_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        conn.close()
    except Exception as e:
        st.error(f"データベースエラー: {e}")
        if st.button("データベースを強制リセットする"):
            force_init_db()
            st.rerun()
        return

    if watchlist_df.empty:
        st.warning("監視リストが空です。")
        return

    target_symbols = watchlist_df.iloc[0]['symbols'].split(',')
    target_list_name = watchlist_df.iloc[0]['name']

    # ルール読み込み
    with open(RULES_PATH, "r", encoding='utf-8') as f:
        rule_set = json.load(f)

    # 設定表示
    with st.expander("Scanner Settings", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Target List:** `{target_list_name}` ({len(target_symbols)} symbols)")
            st.caption(", ".join(target_symbols))
        with c2:
            st.markdown(f"**Strategy:** `{rule_set['name']}`")
            st.markdown(f"_{rule_set['description']}_")

    # スキャン実行
    if st.button("Run Scan (Simulation)", type="primary"):
        st.divider()
        engine = RuleEngine()
        results = []

        with st.spinner(f"Scanning {len(target_symbols)} stocks..."):
            market_data_map = fetch_market_data(target_symbols)

        if not market_data_map:
            st.error("データ取得失敗、またはデータ不足です。")
            return

        progress_bar = st.progress(0)
        for i, symbol in enumerate(target_symbols):
            progress_bar.progress((i + 1) / len(target_symbols))
            
            if symbol not in market_data_map: continue

            data = market_data_map[symbol]
            is_match, details = engine.evaluate(rule_set, data)
            status_icon = "✅ Candidate" if is_match else "unmatched"
            
            row = {
                "Symbol": symbol,
                "Status": status_icon,
                "Price": f"${data['price']:.2f}",
                "RSI": f"{data['rsi']:.1f}",
                "SMA50": f"${data['sma']:.2f}",
                "Details": details
            }
            results.append(row)

        time.sleep(0.5)
        progress_bar.empty()

        st.subheader("Scan Results")
        df_results = pd.DataFrame(results)
        
        candidates = df_results[df_results["Status"] == "✅ Candidate"]
        if not candidates.empty:
            st.success(f"{len(candidates)} 銘柄が条件一致！")
            for _, row in candidates.iterrows():
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
                    c1.metric("Symbol", row["Symbol"])
                    c1.write(f"**{row['Price']}**")
                    c2.metric("RSI(14)", row["RSI"])
                    c3.metric("SMA(50)", row["SMA50"])
                    
                    c4.write("📋 **Match Reason:**")
                    if isinstance(row["Details"], dict):
                        for code, res in row["Details"].items():
                            icon = "🟢" if res.get('result') else "🔴"
                            desc = res.get('desc', '')
                            val = res.get('left_val', 0)
                            c4.write(f"{icon} {desc} (Val: {val:.2f})")
        else:
            st.info("条件に一致する銘柄はありませんでした。")

        with st.expander("See Unmatched Stocks"):
            st.dataframe(df_results.drop(columns=["Details"]))

if __name__ == "__main__":
    main()
