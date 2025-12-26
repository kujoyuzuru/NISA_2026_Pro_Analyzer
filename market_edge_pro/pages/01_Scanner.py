import streamlit as st
import pandas as pd
import yfinance as yf
import requests  # ★ライブラリの代わりにこれを使う
import json
import os
import sqlite3
import ta
import time
import sys
from datetime import datetime, timedelta

# --- セットアップ ---
st.set_page_config(page_title="Scanner", layout="wide")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)

# 依存ファイルチェック
LOGIC_PATH = os.path.join(BASE_DIR, "core", "logic.py")
RULES_PATH = os.path.join(BASE_DIR, "config", "default_rules.json")
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

if not os.path.exists(LOGIC_PATH) or not os.path.exists(RULES_PATH):
    st.error("System Error: Configuration files missing."); st.stop()
try: from core.logic import RuleEngine
except ImportError: st.error("System Error: Engine load failed."); st.stop()

# --- プロ仕様: データ取得クラス (Lightweight) ---
class DataProvider:
    def __init__(self):
        # APIキー取得
        self.api_key = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY")
        self.api_secret = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY")
        self.use_alpaca = bool(self.api_key and self.api_secret)
        self.source_name = "Alpaca (Official Data)" if self.use_alpaca else "Yahoo Finance (Backup)"

    def fetch(self, symbols):
        """ハイブリッドデータ取得"""
        if self.use_alpaca:
            try:
                return self._fetch_alpaca_direct(symbols)
            except Exception as e:
                st.warning(f"Alpaca Connection Failed: {e}. Switching to Backup.")
                self.source_name = "Yahoo Finance (Backup)"
                return self._fetch_yahoo(symbols)
        else:
            return self._fetch_yahoo(symbols)

    def _fetch_alpaca_direct(self, symbols):
        """ライブラリを使わず直接APIを叩く（高速・エラーなし）"""
        data_map = {}
        # Alpaca Data API v2 Endpoint
        url = "https://data.alpaca.markets/v2/stocks/bars"
        
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "accept": "application/json"
        }
        
        # 過去データの期間設定
        end_dt = datetime.now()
        start_dt = end_dt - timedelta(days=300)
        
        # パラメータ設定
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "start": start_dt.strftime("%Y-%m-%d"),
            "end": end_dt.strftime("%Y-%m-%d"),
            "limit": 1000,
            "adjustment": "raw",
            "feed": "iex"  # 無料プラン用データフィード
        }

        response = requests.get(url, headers=headers, params=params, timeout=10)
        
        if response.status_code != 200:
            raise Exception(f"API Error {response.status_code}: {response.text}")

        json_data = response.json()
        bars_data = json_data.get("bars", {})

        for sym, bars in bars_data.items():
            if not bars or len(bars) < 50: continue
            
            # DataFrameに変換
            df = pd.DataFrame(bars)
            # カラム名を統一 (Alpaca: c->Close, v->Volume)
            df = df.rename(columns={"c": "Close", "v": "Volume"})
            
            # 指標計算
            close = float(df['Close'].iloc[-1])
            sma50 = ta.trend.SMAIndicator(df['Close'], window=50).sma_indicator().iloc[-1]
            rsi14 = ta.momentum.RSIIndicator(df['Close'], window=14).rsi().iloc[-1]
            vol = float(df['Volume'].iloc[-1])
            
            data_map[sym] = {
                "symbol": sym, "price": close, "close": close,
                "sma": sma50, "rsi": rsi14, "volume": vol,
                "timestamp": datetime.now().strftime("%H:%M:%S")
            }
        
        return data_map

    def _fetch_yahoo(self, symbols):
        data_map = {}
        tickers = " ".join(symbols)
        if not tickers: return {}
        try:
            df = yf.download(tickers, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
        except: return {}

        for sym in symbols:
            try:
                sdf = df if len(symbols)==1 else df[sym]
                if sdf.empty or len(sdf)<50: continue
                
                close = float(sdf['Close'].iloc[-1])
                sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
                rsi14 = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
                vol = float(sdf['Volume'].iloc[-1])
                
                data_map[sym] = {
                    "symbol": sym, "price": close, "close": close,
                    "sma": sma50, "rsi": rsi14, "volume": vol,
                    "timestamp": datetime.now().strftime("%H:%M:%S")
                }
            except: continue
        return data_map

# --- メイン画面 ---
def main():
    if not st.session_state.get("tos_agreed", False):
        st.warning("⚠️ ホーム画面に戻り、利用規約に同意してください。")
        st.stop()

    st.title("📡 市場スキャナー")

    # DB接続
    conn = sqlite3.connect(DB_PATH)
    try:
        w_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        conn.close()
        if w_df.empty: st.warning("監視リストが空です"); return
        targets = w_df.iloc[0]['symbols'].split(',')
    except: st.error("System Error: DB Connection Failed"); return

    # ルール読み込み
    with open(RULES_PATH, "r", encoding='utf-8') as f:
        rule_set = json.load(f)

    # 動的ルール説明
    rule_descs = []
    for c in rule_set["conditions"]:
        target_val = c["right"].get("value", "指標値")
        op_map = {">": "より上", "<": "より下"}
        op_txt = op_map.get(c["operator"], c["operator"])
        rule_descs.append(f"- **{c['name']}**: {target_val} {op_txt}")

    with st.expander("⚙️ 適用ストラテジー詳細", expanded=False):
        c1, c2 = st.columns([1, 2])
        with c1:
            st.markdown(f"**監視対象:** `{w_df.iloc[0]['name']}`")
            st.code(", ".join(targets))
        with c2:
            st.markdown(f"**ロジック名:** `{rule_set['name']}`")
            st.markdown("\n".join(rule_descs))

    if st.button("スキャン実行 (Start Scan)", type="primary"):
        st.divider()
        provider = DataProvider()
        engine = RuleEngine()
        results = []
        
        with st.spinner(f"データ接続中... Source: {provider.source_name}"):
            m_data = provider.fetch(targets)
        
        if not m_data:
            st.error("データ取得に失敗しました。市場が閉じているか、接続エラーです。")
            return

        st.caption(f"ℹ️ Data Source: {provider.source_name} | Fetched at: {datetime.now().strftime('%H:%M:%S')}")

        prog = st.progress(0)
        for i, sym in enumerate(targets):
            prog.progress((i+1)/len(targets))
            if sym not in m_data: continue
            
            data = m_data[sym]
            is_match, details = engine.evaluate(rule_set, data)
            
            reason = ""
            if not is_match:
                for _, res in details.items():
                    if not res['result'] and 'error' not in res:
                        reason = f"❌ {res['name']} ({res['left_val']:.2f} / {res['right_val']:.2f}) [あと {res['diff']:.2f}]"
                        break
                    elif 'error' in res:
                        reason = f"⚠️ Err: {res['error']}"
                        break

            results.append({
                "Symbol": sym,
                "Signal": "🟢 ENTRY" if is_match else "WAIT",
                "Price": f"${data['price']:.2f}",
                "RSI": f"{data['rsi']:.1f}",
                "Note": reason,
                "Details": details
            })
        time.sleep(0.2); prog.empty()

        df_r = pd.DataFrame(results)
        candidates = df_r[df_r["Signal"] == "🟢 ENTRY"]
        unmatched = df_r[df_r["Signal"] != "🟢 ENTRY"]

        if not candidates.empty:
            st.success(f"検出完了: {len(candidates)} 銘柄が条件に合致します")
            for _, r in candidates.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([1, 3])
                    c1.metric(r["Symbol"], r["Price"])
                    c2.markdown(f"### 🚀 Signal Confirmed\n**RSI:** {r['RSI']} | 全条件クリア")
        else:
            st.info("現在、エントリー条件を満たす銘柄はありません。")

        if not unmatched.empty:
            st.markdown("#### 監視継続リスト")
            st.dataframe(
                unmatched[["Symbol", "Price", "RSI", "Note"]],
                column_config={"Note": st.column_config.TextColumn("状況 / 乖離", width="large")},
                hide_index=True, use_container_width=True
            )

if __name__ == "__main__": main()
