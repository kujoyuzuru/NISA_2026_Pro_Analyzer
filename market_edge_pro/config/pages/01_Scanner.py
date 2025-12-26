import streamlit as st
import pandas as pd
import yfinance as yf
import json
import os
import sqlite3
import ta
import time

# ---------------------------------------------------------
# セットアップ & 設定
# ---------------------------------------------------------
st.set_page_config(page_title="Scanner", layout="wide")

# 必要なファイルがあるかチェック
if not os.path.exists("core/logic.py"):
    st.error("⚠️ `core/logic.py` が見つかりません。作成してください。")
    st.stop()
if not os.path.exists("config/default_rules.json"):
    st.error("⚠️ `config/default_rules.json` が見つかりません。作成してください。")
    st.stop()

# ロジックエンジンの読み込み
from core.logic import RuleEngine

# ---------------------------------------------------------
# ヘルパー関数
# ---------------------------------------------------------
def get_db_connection():
    return sqlite3.connect("trading_journal.db")

@st.cache_data(ttl=3600) # 1時間キャッシュ（API制限対策）
def fetch_market_data(symbols):
    """
    Yahoo Financeからデータを一括取得し、テクニカル指標を計算する
    """
    data_map = {}
    
    # yfinanceは "AAPL MSFT" のようなスペース区切り文字列を受け付ける
    tickers = " ".join(symbols)
    
    if not tickers:
        return {}

    # 過去データ取得（日足、長めに取ってSMA200などを計算可能にする）
    df = yf.download(tickers, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)

    for symbol in symbols:
        try:
            # 単一銘柄か複数銘柄かでdfの構造が変わるための対策
            if len(symbols) == 1:
                stock_df = df
            else:
                stock_df = df[symbol]
            
            # データ不足のチェック
            if stock_df.empty or len(stock_df) < 50:
                continue

            # --- テクニカル指標の計算 (v1仕様) ---
            # 1. 終値
            close_price = stock_df['Close'].iloc[-1]
            
            # 2. SMA (50日) - ルールJSONの "sma" に対応
            sma_indicator = ta.trend.SMAIndicator(stock_df['Close'], window=50)
            sma_50 = sma_indicator.sma_indicator().iloc[-1]
            
            # 3. RSI (14日) - ルールJSONの "rsi" に対応
            rsi_indicator = ta.momentum.RSIIndicator(stock_df['Close'], window=14)
            rsi_14 = rsi_indicator.rsi().iloc[-1]

            # 4. 出来高
            volume = stock_df['Volume'].iloc[-1]

            # エンジンに渡す辞書を作成
            data_map[symbol] = {
                "symbol": symbol,
                "price": close_price,
                "close": close_price, # ルールでの参照用
                "sma": sma_50,        # ルールでの参照用
                "rsi": rsi_14,        # ルールでの参照用
                "volume": volume
            }
            
        except Exception as e:
            print(f"Error processing {symbol}: {e}")
            continue
            
    return data_map

# ---------------------------------------------------------
# メイン画面処理
# ---------------------------------------------------------
def main():
    st.title("📡 Market Scanner")
    
    # 1. 監視リストの読み込み
    conn = get_db_connection()
    watchlist_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
    conn.close()

    if watchlist_df.empty:
        st.warning("監視リストが空です。まずはリストを作成してください。")
        return

    # 銘柄リストを配列化
    target_symbols = watchlist_df.iloc[0]['symbols'].split(',')
    target_list_name = watchlist_df.iloc[0]['name']

    # 2. ルールの読み込み
    with open("config/default_rules.json", "r", encoding='utf-8') as f:
        rule_set = json.load(f)

    # 3. UI: 設定表示
    with st.expander("Scanner Settings", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            st.markdown(f"**Target List:** `{target_list_name}` ({len(target_symbols)} symbols)")
            st.caption(", ".join(target_symbols))
        with c2:
            st.markdown(f"**Strategy:** `{rule_set['name']}`")
            st.markdown(f"_{rule_set['description']}_")

    # 4. スキャン実行ボタン
    if st.button("Run Scan (Simulation)", type="primary"):
        st.divider()
        engine = RuleEngine()
        results = []

        with st.spinner(f"Fetching data for {len(target_symbols)} stocks..."):
            # データ取得 & 計算
            market_data_map = fetch_market_data(target_symbols)

        # 判定ループ
        progress_bar = st.progress(0)
        for i, symbol in enumerate(target_symbols):
            # プログレスバー更新
            progress_bar.progress((i + 1) / len(target_symbols))
            
            if symbol not in market_data_map:
                # データ取得失敗時
                results.append({
                    "Symbol": symbol,
                    "Status": "Error/No Data",
                    "Price": 0.0,
                    "Details": "データ取得不可"
                })
                continue

            data = market_data_map[symbol]
            
            # ★判定実行★
            is_match, details = engine.evaluate(rule_set, data)
            
            status_icon = "✅ Candidate" if is_match else "unmatched"
            
            # 結果行の作成
            row = {
                "Symbol": symbol,
                "Status": status_icon,
                "Price": f"${data['price']:.2f}",
                "RSI": f"{data['rsi']:.1f}",
                "SMA50": f"${data['sma']:.2f}",
                "Details": details # デバッグ用に詳細保持
            }
            results.append(row)

        time.sleep(0.5) # UIのちらつき防止
        progress_bar.empty()

        # 5. 結果表示
        st.subheader("Scan Results")
        
        # 候補（Match）とそれ以外（Unmatched）に分ける
        df_results = pd.DataFrame(results)
        
        # 候補の表示
        candidates = df_results[df_results["Status"] == "✅ Candidate"]
        
        if not candidates.empty:
            st.success(f"{len(candidates)} 銘柄が条件に合致しました！")
            for _, row in candidates.iterrows():
                with st.container(border=True):
                    c1, c2, c3, c4 = st.columns([1, 1, 1, 3])
                    c1.metric("Symbol", row["Symbol"])
                    c1.write(f"**{row['Price']}**")
                    c2.metric("RSI(14)", row["RSI"])
                    c3.metric("SMA(50)", row["SMA50"])
                    
                    # 理由の表示
                    c4.write("📋 **Match Reason:**")
                    match_reasons = []
                    for code, res in row["Details"].items():
                        icon = "🟢" if res['result'] else "🔴"
                        c4.write(f"{icon} {res['desc']} (Val: {res.get('left_val', 0):.2f})")
        else:
            st.info("条件に合致する銘柄はありませんでした。")

        # 除外リストの表示（折りたたみ）
        with st.expander("See Unmatched Stocks"):
            st.dataframe(df_results[df_results["Status"] != "✅ Candidate"])

if __name__ == "__main__":
    main()
