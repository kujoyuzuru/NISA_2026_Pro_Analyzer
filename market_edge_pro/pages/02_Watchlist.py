import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import time
import yfinance as yf
import ta

# --- セットアップ ---
st.set_page_config(
    page_title="Market Edge Pro",
    page_icon="📊",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# パス設定（ルートディレクトリを認識させる）
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- ★追加: DB修復ロジック (app.pyと同じものを移植) ---
try: from data.init_db import init_db
except ImportError:
    # パスが通っていない場合の保険
    import sys
    sys.path.append(BASE_DIR)
    from data.init_db import init_db

def ensure_db():
    # DBファイルがない、または壊れている場合に再生成する
    if not os.path.exists(DB_PATH):
        with st.spinner("System Initializing..."):
            init_db()
            time.sleep(1)
            st.rerun()
    try:
        conn = sqlite3.connect(DB_PATH)
        conn.execute("SELECT count(*) FROM watchlists")
        conn.close()
    except:
        with st.spinner("Database Repairing..."):
            init_db()
            time.sleep(1)
            st.rerun()

# --- 銘柄マスターデータ ---
STOCK_MASTER = {
    # --- 📊 主要インデックス & ETF ---
    "SPY": {"name": "SPDR S&P 500", "sector": "INDEX: S&P500"},
    "QQQ": {"name": "Invesco QQQ", "sector": "INDEX: NASDAQ100"},
    "VOO": {"name": "Vanguard S&P 500", "sector": "INDEX: S&P500"},
    "VTI": {"name": "Vanguard Total Stock", "sector": "INDEX: All US"},
    "DIA": {"name": "SPDR Dow Jones", "sector": "INDEX: Dow"},
    "IWM": {"name": "iShares Russell 2000", "sector": "INDEX: Small Cap"},
    "SOXL": {"name": "Direxion Daily Semi 3x", "sector": "ETF: Semi 3x"},
    "TQQQ": {"name": "ProShares UltraPro QQQ", "sector": "ETF: Nasdaq 3x"},
    "TLT": {"name": "iShares 20+ Year Treasury", "sector": "ETF: Bond 20y"},
    
    # --- 🔥 超人気・マグニフィセント7 ---
    "NVDA": {"name": "NVIDIA Corp.", "sector": "Tech"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Auto"},
    "AAPL": {"name": "Apple Inc.", "sector": "Tech"},
    "MSFT": {"name": "Microsoft Corp.", "sector": "Tech"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Comm"},
    "AMZN": {"name": "Amazon.com", "sector": "Retail"},
    "META": {"name": "Meta Platforms", "sector": "Comm"},
    
    # --- 🚀 半導体 & AI ---
    "AMD": {"name": "Advanced Micro Devices", "sector": "Tech"},
    "AVGO": {"name": "Broadcom Inc.", "sector": "Semi"},
    "TSM": {"name": "Taiwan Semi", "sector": "Semi"},
    "ARM": {"name": "Arm Holdings", "sector": "Semi"},
    "SMCI": {"name": "Super Micro Computer", "sector": "Hardware"},
    "INTC": {"name": "Intel Corp.", "sector": "Semi"},
    "MU": {"name": "Micron Technology", "sector": "Semi"},

    # --- 💻 グロース & ソフトウェア ---
    "PLTR": {"name": "Palantir Technologies", "sector": "Software"},
    "CRWD": {"name": "CrowdStrike", "sector": "Security"},
    "PANW": {"name": "Palo Alto Networks", "sector": "Security"},
    "SNOW": {"name": "Snowflake Inc.", "sector": "Software"},
    "U": {"name": "Unity Software", "sector": "Software"},
    "UBER": {"name": "Uber Technologies", "sector": "App"},
    "ABNB": {"name": "Airbnb Inc.", "sector": "Travel"},
    
    # --- 💰 クリプト関連 ---
    "COIN": {"name": "Coinbase Global", "sector": "Crypto"},
    "MARA": {"name": "Marathon Digital", "sector": "Crypto"},
    "MSTR": {"name": "MicroStrategy", "sector": "Software"},

    # --- 🏦 金融 & 伝統的大手 ---
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
    "JNJ": {"name": "Johnson & Johnson", "sector": "Health"},
    "BA": {"name": "Boeing Co.", "sector": "Aero"},
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

# --- 分析ロジック (Fast Info実装版) ---
@st.cache_data(ttl=15)
def analyze_stocks_pro(symbols):
    if not symbols: return pd.DataFrame()
    
    tickers_str = " ".join(symbols)
    try:
        df_hist = yf.download(tickers_str, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except: return pd.DataFrame()

    tickers_obj = yf.Tickers(tickers_str)

    results = []
    for sym in symbols:
        try:
            # A. 正確な価格データの取得
            try:
                info = tickers_obj.tickers[sym].fast_info
                current_price = info.last_price
                prev_close = info.previous_close
                if current_price is None or prev_close is None: continue
                
                change_val = current_price - prev_close
                change_pct = (change_val / prev_close) * 100
            except: continue

            # B. テクニカル指標
            if len(symbols) == 1: sdf = df_hist
            else: 
                if sym not in df_hist: continue
                sdf = df_hist[sym]
            
            if sdf.empty or len(sdf) < 50: continue
            
            sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
            rsi = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
            trend_up = current_price > sma50
            
            # C. 判定ロジック
            verdict, score, reason_short = "", 0, ""
            
            if trend_up:
                if rsi < 35:
                    verdict, score = "💎 超・買い時", 100
                    reason_short = "RSI<35: 絶好の拾い場"
                elif rsi < 50:
                    verdict, score = "◎ 押し目買い", 80
                    reason_short = "RSI<50: 買いチャンス"
                elif rsi < 55:
                    verdict, score = "○ 保有/監視", 60
                    reason_short = "あと少しで買い (RSI 50台)"
                elif rsi > 75:
                    verdict, score = "⚡ 利確検討", -10
                    reason_short = "RSI>75: 加熱しすぎ"
                else:
                    verdict, score = "○ 保有/継続", 50
                    reason_short = "順調に推移中"
            else:
                if rsi < 30:
                    verdict, score = "△ リバウンド狙い", 40
                    reason_short = "下降中だが売られすぎ"
                else:
                    verdict, score = "× 様子見", 0
                    reason_short = "下降トレンド中"

            results.append({
                "Symbol": sym,
                "Price": current_price,
                "Change": change_pct,
                "RSI": rsi,
                "Trend": "📈 上昇" if trend_up else "📉 下降",
                "Verdict": verdict,
                "Score": score,
                "Reason": reason_short
            })
        except: continue
    
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res = df_res.sort_values(by="Score", ascending=False)
    return df_res

# --- スタイリング ---
def color_change_text(val):
    if pd.isna(val): return 'color: white'
    color = '#00FF00' if val >= 0 else '#FF0000'
    return f'color: {color}'

# --- メイン画面 ---
def main():
    # ★ここが重要：起動時にDBチェックを行う
    ensure_db()

    st.markdown("""
        <h1 style='text-align: center; margin-bottom: 20px;'>
            📊 Market Edge Pro
        </h1>
    """, unsafe_allow_html=True)
    
    df = load_watchlist()
    if df.empty: 
        # 修復してもまだダメなら再試行ボタンを出す
        st.error("データベース読み込みエラー。再読み込みしてください。")
        if st.button("データベース修復・再接続"):
            with st.spinner("Repairing..."):
                init_db()
                time.sleep(1)
                st.rerun()
        return

    curr_list = [s.strip().upper() for s in df.iloc[0]['symbols'].split(",") if s.strip()]

    col_main, = st.columns([1])

    with col_main:
        if not curr_list:
             st.info("👈 サイドバーから監視銘柄を追加してください")
        else:
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
                display_df = df_anl[["Verdict", "Symbol", "Price", "Change", "RSI", "Reason"]].copy()
                display_df.columns = ["Verdict", "Symbol", "Price", "Change", "RSI (過熱感)", "状況コメント"]
                
                st.dataframe(
                    display_df.style.format({
                        "Price": "${:,.2f}",
                        "Change": "{:+.2f}%",
                    }).map(color_change_text, subset=["Change"]),
                    
                    column_config={
                        "Verdict": st.column_config.TextColumn("AI判定", width="medium"),
                        "Symbol": st.column_config.TextColumn("銘柄", width="small"),
                        "Price": st.column_config.NumberColumn("現在値", format="$%.2f"),
                        "Change": st.column_config.NumberColumn("前日比", format="%.2f%%"),
                        "RSI (過熱感)": st.column_config.ProgressColumn(
                            "RSI (50以下で買い)", 
                            help="【買い基準】50以下: 押し目買い / 35以下: 超・買い時",
                            format="%d",
                            min_value=0,
                            max_value=100,
                        ),
                        "状況コメント": st.column_config.TextColumn("状況コメント", width="medium"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=600
                )
                
                with st.expander("💡 判定基準（カンニングペーパー）", expanded=True):
                    st.markdown("""
                    **このAIは「上昇トレンドの押し目（一時的な下落）」を狙っています。**
                    
                    | 判定シグナル | RSIの基準値 | 意味 |
                    | :--- | :--- | :--- |
                    | 💎 **超・買い時** | **35 以下** | バーゲンセール状態。迷わずエントリー。 |
                    | ◎ **押し目買い** | **50 以下** | 加熱感が冷めた状態。ここから買い。 |
                    | ○ **保有/監視** | **50〜75** | 順調。慌てて買う必要なし（下がるのを待つ）。 |
                    | ⚡ **利確検討** | **75 以上** | 買われすぎ。急落に注意。 |
                    
                    ※ **前提条件:** 株価が50日移動平均線より上にあること（＝上昇トレンド）。
                    """)
                
            else:
                st.error("データ取得失敗。時間をおいて再試行してください。")
    
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
