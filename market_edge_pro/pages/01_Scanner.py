import streamlit as st
import pandas as pd
import yfinance as yf
import requests  # 標準ライブラリで直接通信
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
    st.error("System Error: Config files missing."); st.stop()
try: from core.logic import RuleEngine
except ImportError: st.error("System Error: Logic engine failed."); st.stop()

# --- ★復活：DB自動修復機能 (Safety Net) ---
def force_init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute('''CREATE TABLE IF NOT EXISTS watchlists (
        id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT, symbols TEXT)''')
    # データがなければ初期値を投入
    c.execute("SELECT count(*) FROM watchlists")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO watchlists (name, symbols) VALUES (?, ?)", 
                  ("Default Watchlist", "AAPL,MSFT,TSLA,NVDA,GOOGL,AMZN,META,AMD"))
    conn.commit()
    conn.close()

def get_db_connection():
    conn = sqlite3.connect(DB_PATH)
    try:
        # テーブルがあるかテスト
        conn.execute("SELECT * FROM watchlists LIMIT 1")
    except sqlite3.OperationalError:
        conn.close()
        # なければ修復実行
        force_init_db()
        conn = sqlite3.connect(DB_PATH)
    return conn

# --- プロ仕様: データ取得 (Lightweight/No-Lib) ---
class DataProvider:
    def __init__(self):
        self.api_key = os.getenv("ALPACA_API_KEY") or st.secrets.get("ALPACA_API_KEY")
        self.api_secret = os.getenv("ALPACA_SECRET_KEY") or st.secrets.get("ALPACA_SECRET_KEY")
        self.use_alpaca = bool(self.api_key and self.api_secret)
        self.source_name = "Alpaca (Official)" if self.use_alpaca else "Yahoo Finance (Backup)"

    def fetch(self, symbols):
        if self.use_alpaca:
            try:
                return self._fetch_alpaca_direct(symbols)
            except Exception as e:
                st.warning(f"Alpaca Error: {e}. Switching to Backup.")
                self.source_name = "Yahoo Finance (Backup)"
                return self._fetch_yahoo(symbols)
        else:
            return self._fetch_yahoo(symbols)

    def _fetch_alpaca_direct(self, symbols):
        # ライブラリを使わずrequestsで直接叩く（エラー回避）
        url = "https://data.alpaca.markets/v2/stocks/bars"
        headers = {
            "APCA-API-KEY-ID": self.api_key,
            "APCA-API-SECRET-KEY": self.api_secret,
            "accept": "application/json"
        }
        params = {
            "symbols": ",".join(symbols),
            "timeframe": "1Day",
            "limit": 300,
            "feed": "iex"
        }
        # エラーハンドリング強化
        try:
            response = requests.get(url, headers=headers, params=params, timeout=5)
            response.raise_for_status()
        except requests.exceptions.RequestException as e:
            raise Exception(f"Connection failed: {e}")

        data_map = {}
        bars_data = response.json().get("bars", {})

        for sym, bars in bars_data.items():
            if not bars or len(bars) < 50: continue
            df = pd.DataFrame(bars)
            df = df.rename(columns={"c": "Close", "v": "Volume"})
            
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

    # DB接続（修復機能付き）
    try:
        conn = get_db_connection()
        w_df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        conn.close()
        if w_df.empty: st.warning("監視リストが空です"); return
        targets = w_df.iloc[0]['symbols'].split(',')
    except Exception as e:
        # 具体的なエラーを表示してデバッグしやすくする
        st.error(f"Critical DB Error: {e}")
        if st.button("データベースを強制リセット"):
            force_init_db()
            st.rerun()
        return

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
            st.error("データ取得失敗。市場が閉じているか、Yahoo/Alpaca両方が応答しません。")
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
            st.success(f"検出完了: {len(candidates)} 銘柄が合致")
            for _, r in candidates.iterrows():
                with st.container(border=True):
                    c1, c2 = st.columns([1, 3])
                    c1.metric(r["Symbol"], r["Price"])
                    c2.markdown(f"### 🚀 Signal Confirmed\n**RSI:** {r['RSI']} | 全条件クリア")
        else:
            st.info("条件を満たす銘柄はありません。")

        if not unmatched.empty:
            st.markdown("#### 監視継続リスト")
            st.dataframe(
                unmatched[["Symbol", "Price", "RSI", "Note"]],
                column_config={"Note": st.column_config.TextColumn("状況 / 乖離", width="large")},
                hide_index=True, use_container_width=True
            )

if __name__ == "__main__": main()
