import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import time
import yfinance as yf
import ta

# --- セットアップ ---
# ページ設定でアイコンとタイトルを指定
st.set_page_config(
    page_title="Market Edge Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed" # スマホで見やすいようサイドバーは閉じておく
)

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- 銘柄マスターデータ (省略なし) ---
STOCK_MASTER = {
    "SPY": {"name": "SPDR S&P 500", "sector": "INDEX: S&P500"},
    "QQQ": {"name": "Invesco QQQ", "sector": "INDEX: NASDAQ100"},
    "VOO": {"name": "Vanguard S&P 500", "sector": "INDEX: S&P500"},
    "VTI": {"name": "Vanguard Total Stock", "sector": "INDEX: All US"},
    "DIA": {"name": "SPDR Dow Jones", "sector": "INDEX: Dow"},
    "IWM": {"name": "iShares Russell 2000", "sector": "INDEX: Small Cap"},
    "SOXL": {"name": "Direxion Daily Semi 3x", "sector": "ETF: Semi 3x"},
    "TQQQ": {"name": "ProShares UltraPro QQQ", "sector": "ETF: Nasdaq 3x"},
    "TLT": {"name": "iShares 20+ Year Treasury", "sector": "ETF: Bond 20y"},
    "NVDA": {"name": "NVIDIA Corp.", "sector": "Tech"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Auto"},
    "AAPL": {"name": "Apple Inc.", "sector": "Tech"},
    "AMD": {"name": "Advanced Micro Devices", "sector": "Tech"},
    "AMZN": {"name": "Amazon.com", "sector": "Retail"},
    "MSFT": {"name": "Microsoft Corp.", "sector": "Tech"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Comm"},
    "META": {"name": "Meta Platforms", "sector": "Comm"},
    "PLTR": {"name": "Palantir Technologies", "sector": "Software"},
    "COIN": {"name": "Coinbase Global", "sector": "Crypto"},
    "MARA": {"name": "Marathon Digital", "sector": "Crypto"},
    "MSTR": {"name": "MicroStrategy", "sector": "Software"},
    "AVGO": {"name": "Broadcom Inc.", "sector": "Semi"},
    "TSM": {"name": "Taiwan Semi", "sector": "Semi"},
    "ARM": {"name": "Arm Holdings", "sector": "Semi"},
    "SMCI": {"name": "Super Micro Computer", "sector": "Hardware"},
    "CRWD": {"name": "CrowdStrike", "sector": "Security"},
    "PANW": {"name": "Palo Alto Networks", "sector": "Security"},
    "SNOW": {"name": "Snowflake Inc.", "sector": "Software"},
    "U": {"name": "Unity Software", "sector": "Software"},
    "UBER": {"name": "Uber Technologies", "sector": "App"},
    "ABNB": {"name": "Airbnb Inc.", "sector": "Travel"},
    "JPM": {"name": "JPMorgan Chase", "sector": "Bank"},
    "BAC": {"name": "Bank of America", "sector": "Bank"},
    "V": {"name": "Visa Inc.", "sector": "Credit"},
    "MA": {"name": "Mastercard", "sector": "Credit"},
    "WMT": {"name": "Walmart Inc.", "sector": "Retail"},
    "COST": {"name": "Costco Wholesale", "sector": "Retail"},
    "KO": {"name": "Coca-Cola", "sector": "Beverage"},
    "PEP": {"name": "PepsiCo", "sector": "Beverage"},
    "PG": {"name": "Procter & Gamble", "sector": "Household"},
    "MCD": {"name": "McDonald's", "sector": "Food"},
    "DIS": {"name": "Walt Disney", "sector": "Media"},
    "NFLX": {"name": "Netflix Inc.", "sector": "Media"},
    "XOM": {"name": "Exxon Mobil", "sector": "Energy"},
    "CVX": {"name": "Chevron Corp.", "sector": "Energy"},
    "LLY": {"name": "Eli Lilly", "sector": "Pharma"},
    "UNH": {"name": "UnitedHealth", "sector": "Health"},
    "PFE": {"name": "Pfizer Inc.", "sector": "Pharma"},
    "JNJ": {"name": "Johnson & Johnson", "sector": "Health"},
    "BA": {"name": "Boeing Co.", "sector": "Aero"},
    "CAT": {"name": "Caterpillar", "sector": "Industry"},
    "GE": {"name": "General Electric", "sector": "Industry"},
}
POPULAR_ORDER = list(STOCK_MASTER.keys())

# --- DBヘルパー ---
def get_connection(): return sqlite3.connect(DB_PATH)

def load_watchlist():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        return df
    except: return pd.DataFrame()
    finally: conn.close()

def save_watchlist(name, symbols_list):
    clean_list = []
    seen = set()
    for s in symbols_list:
        clean_s = s.strip().upper()
        if clean_s and clean_s not in seen:
            clean_list.append(clean_s)
            seen.add(clean_s)
    clean_str = ",".join(clean_list)
    conn = get_connection()
    try:
        conn.execute("UPDATE watchlists SET name = ?, symbols = ? WHERE id = (SELECT id FROM watchlists LIMIT 1)", (name, clean_str))
        conn.commit()
        return clean_list
    except: return []
    finally: conn.close()

# --- 分析ロジック (リアルタイム・高精度版) ---
@st.cache_data(ttl=15)
def analyze_stocks_pro(symbols):
    if not symbols: return pd.DataFrame()
    tickers_str = " ".join(symbols)
    try:
        df_hist = yf.download(tickers_str, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except: return pd.DataFrame()

    results = []
    for sym in symbols:
        try:
            if len(symbols) == 1: sdf = df_hist
            else: 
                if sym not in df_hist: continue
                sdf = df_hist[sym]
            
            if sdf.empty or len(sdf) < 50: continue

            current_close = float(sdf['Close'].iloc[-1])
            prev_close = float(sdf['Close'].iloc[-2])
            
            # 前日比の計算（パーセント）
            change_val = current_close - prev_close
            change_pct = (change_val / prev_close) * 100
            
            sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
            rsi = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
            trend_up = current_close > sma50
            
            verdict, score = "", 0
            if trend_up:
                if rsi < 35: verdict, score = "💎 超・買い時", 100
                elif rsi < 50: verdict, score = "◎ 押し目買い", 80
                elif rsi > 75: verdict, score = "⚡ 利確検討", -10
                else: verdict, score = "○ 保有/継続", 50
            else:
                if rsi < 30: verdict, score = "△ リバウンド狙い", 40
                else: verdict, score = "× 様子見", 0

            results.append({
                "Symbol": sym,
                "Price": current_close,
                "Change": change_pct,
                "Verdict": verdict,
                "Score": score
            })
        except: continue
    
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res = df_res.sort_values(by="Score", ascending=False)
    return df_res

# --- スタイリング関数 ---
def color_change_text(val):
    """前日比の数値に基づいてテキスト色を変える"""
    if pd.isna(val):
        return 'color: white'
    # アイキャッチ画像に合わせた鮮やかな色設定
    color = '#00FF00' if val >= 0 else '#FF0000' 
    return f'color: {color}'

# --- メイン画面 ---
def main():
    # アイキャッチ画像と同じロゴとタイトルをヘッダーとして表示
    st.markdown("""
        <h1 style='text-align: center; margin-bottom: 20px;'>
            📊 Market Edge Pro
        </h1>
    """, unsafe_allow_html=True)
    
    df = load_watchlist()
    if df.empty: st.warning("DBエラー"); return
    curr_list = [s.strip().upper() for s in df.iloc[0]['symbols'].split(",") if s.strip()]

    # スマホでの表示を意識し、メインコンテンツを中央寄せにする
    col_main, = st.columns([1])

    with col_main:
        if not curr_list:
             st.info("👈 サイドバーから監視銘柄を追加してください")
        else:
            # ダッシュボードのヘッダーと更新ボタン
            c_head, c_btn = st.columns([3, 1])
            with c_head:
                st.subheader("AI 売買判断ダッシュボード")
            with c_btn:
                if st.button("🔄 更新"):
                    st.cache_data.clear()
                    st.rerun()

            with st.spinner("市場データを分析中..."):
                df_anl = analyze_stocks_pro(curr_list)

            if not df_anl.empty:
                # --- アイキャッチ画像のテーブル再現 ---
                
                # 1. 表示用のDataFrameを作成（カラム名に改行を入れて狭い幅に対応）
                display_df = df_anl[["Verdict", "Symbol", "Price", "Change"]].copy()
                display_df.columns = ["Verdict\n(AI判定)", "Symbol\n(銘柄)", "Price\n(現在値)", "Change\n(前日比)"]
                
                # 2. Pandas Stylerで色とフォーマットを適用
                styled_df = display_df.style.format({
                    "Price\n(現在値)": "${:,.2f}",
                    "Change\n(前日比)": "{:+.2f}%"
                }).map(color_change_text, subset=["Change\n(前日比)"])

                # 3. Streamlitで表示（高さを固定してスマホで見やすく）
                st.dataframe(
                    styled_df,
                    hide_index=True,
                    use_container_width=True,
                    height=600
                )
                
            else:
                st.error("データ取得失敗。時間をおいて再試行してください。")
    
    # 銘柄管理はサイドバーに移動（スマホではメニューから開く）
    with st.sidebar:
        st.header("🛠 銘柄管理")
        def fmt(t):
            m = STOCK_MASTER.get(t)
            return f"{t} | {m['name']} ({m['sector']})" if m else t
        merged_opts = POPULAR_ORDER + [x for x in curr_list if x not in POPULAR_ORDER]
        sel = st.multiselect("監視リスト", options=merged_opts, default=curr_list, format_func=fmt, placeholder="銘柄を検索...")
        manual = st.text_input("手動追加", placeholder="例: GME")
        if st.button("リストを保存して更新", type="primary", use_container_width=True):
            final = sel.copy()
            if manual: final.extend([x.strip().upper() for x in manual.split(',')])
            save_watchlist(df.iloc[0]['name'], final)
            st.cache_data.clear()
            st.rerun()

if __name__ == "__main__": main()
