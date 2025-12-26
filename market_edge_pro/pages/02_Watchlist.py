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

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- 銘柄マスターデータ ---
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

# --- 分析ロジック ---
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

            # 理由を明確化
            reason_short = ""
            if rsi < 35: reason_short = "売られすぎ"
            elif rsi > 70: reason_short = "買われすぎ"
            elif trend_up: reason_short = "トレンド順行"
            else: reason_short = "トレンド逆行"

            results.append({
                "Symbol": sym,
                "Price": current_close,
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
    st.markdown("""
        <h1 style='text-align: center; margin-bottom: 20px;'>
            📊 Market Edge Pro
        </h1>
    """, unsafe_allow_html=True)
    
    df = load_watchlist()
    if df.empty: st.warning("DBエラー"); return
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
                # 1. 表示用データフレームの作成
                display_df = df_anl[["Verdict", "Symbol", "Price", "Change", "RSI", "Trend"]].copy()
                display_df.columns = ["Verdict", "Symbol", "Price", "Change", "RSI (過熱感)", "Trend"]
                
                # 2. StreamlitのColumnConfigを使ってビジュアル化
                # ここが「信頼」を作るカギです：理論を視覚化する
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
                        
                        # ★ここが追加ポイント: RSIをバーで見せる
                        "RSI (過熱感)": st.column_config.ProgressColumn(
                            "RSI (過熱感)",
                            help="売られすぎ(0) <---> 買われすぎ(100)。30以下は買いシグナル、70以上は売り警戒。",
                            format="%d",
                            min_value=0,
                            max_value=100,
                        ),
                        # トレンドをわかりやすく
                        "Trend": st.column_config.TextColumn("トレンド", width="small"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=600
                )
                
                # 3. 理論の解説セクション（ブラックボックスを開示する）
                with st.expander("💡 なぜこの判断なのか？ (AIロジックの解説)"):
                    st.markdown("""
                    このアプリは、プロの投資家が使う**2つの「王道理論」**を組み合わせて自動判定しています。
                    
                    #### 1. トレンド判定：グランビルの法則 (SMA50)
                    * **仕組み:** 過去50日の平均価格（SMA50）より、現在の株価が「上」にあれば**「上昇トレンド」**とみなします。
                    * **意味:** 「株価は波を描きながらトレンド方向に進む」という理論に基づき、上昇中の株のみをターゲットにします。
                    
                    #### 2. タイミング判定：RSI (相対力指数)
                    * **仕組み:** 「買われすぎ」「売られすぎ」を0〜100の数値で測ります。
                    * **意味:** 上昇トレンド中にRSIが低くなった瞬間（押し目）は、**「一時的に安くなっているだけ」**なので、絶好の買い場となります。
                    
                    **判定の根拠:**
                    * 💎 **超・買い時:** 上昇トレンド中 ＋ RSI < 35 (暴落レベルの安値)
                    * ◎ **押し目買い:** 上昇トレンド中 ＋ RSI < 50 (過熱感なし)
                    * ⚡ **利確検討:** RSI > 75 (加熱しすぎ。反落警戒)
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
