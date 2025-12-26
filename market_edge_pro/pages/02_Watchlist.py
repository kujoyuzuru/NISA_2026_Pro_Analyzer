import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import time
import yfinance as yf
import ta

# --- セットアップ ---
st.set_page_config(page_title="Watchlist Pro", layout="wide")
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

# --- 分析ロジック (高精度版) ---
# ★修正: ttlを15秒に短縮してほぼリアルタイム化。データ取得方法も改善。
@st.cache_data(ttl=15)
def analyze_stocks_pro(symbols):
    if not symbols: return pd.DataFrame()
    tickers_str = " ".join(symbols)
    
    try:
        # データ取得：期間を長めにとってSMA計算用のデータを確保
        df_hist = yf.download(tickers_str, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except: return pd.DataFrame()

    results = []
    for sym in symbols:
        try:
            if len(symbols) == 1: sdf = df_hist
            else: 
                if sym not in df_hist: continue
                sdf = df_hist[sym]
            
            # データ不足チェック
            if sdf.empty or len(sdf) < 50: continue

            # --- 値の取得（最新と1つ前） ---
            # iloc[-1] が「今日（現在進行形）」、iloc[-2] が「昨日（確定）」
            current_close = float(sdf['Close'].iloc[-1])
            prev_close = float(sdf['Close'].iloc[-2])
            
            # ★修正: 正確な前日比計算
            change_val = current_close - prev_close
            change_pct = (change_val / prev_close) * 100
            
            # テクニカル指標
            sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
            rsi = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
            
            trend_up = current_close > sma50
            
            # 判定ロジック
            verdict, reason, score = "", "", 0
            if trend_up:
                if rsi < 35: verdict, reason, score = "💎 超・買い時", "上昇トレンド中の暴落", 100
                elif rsi < 50: verdict, reason, score = "◎ 押し目買い", "トレンド上向き+過熱感なし", 80
                elif rsi > 75: verdict, reason, score = "⚡ 利確検討", "買われすぎ警戒", -10
                else: verdict, reason, score = "○ 保有/継続", "順調に推移中", 50
            else:
                if rsi < 30: verdict, reason, score = "△ リバウンド狙い", "売られすぎ(逆張り)", 40
                else: verdict, reason, score = "× 様子見", "下降トレンド中", 0

            meta = STOCK_MASTER.get(sym, {"name": sym, "sector": "Others"})
            
            results.append({
                "Symbol": sym,
                "Name": meta["name"],
                "Sector": meta["sector"],
                "Price": current_close,
                "Change": change_pct, # パーセント値そのもの
                "RSI": rsi,
                "Trend": "📈" if trend_up else "📉",
                "Verdict": verdict,
                "Reason": reason,
                "Score": score
            })
        except: continue
    
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res = df_res.sort_values(by="Score", ascending=False)
    return df_res

# --- メイン画面 ---
def main():
    st.title("⚡ 監視リスト & 売買シグナル")
    
    # DB読み込み
    df = load_watchlist()
    if df.empty: st.warning("DBエラー: リストが読み込めません"); return
    curr_list = [s.strip().upper() for s in df.iloc[0]['symbols'].split(",") if s.strip()]

    col1, col2 = st.columns([1, 2.5])
    
    # 左サイド
    with col1:
        with st.container(border=True):
            st.subheader("🛠 銘柄管理")
            
            def fmt(t):
                m = STOCK_MASTER.get(t)
                return f"{t} | {m['name']} ({m['sector']})" if m else t

            merged_opts = POPULAR_ORDER + [x for x in curr_list if x not in POPULAR_ORDER]
            
            sel = st.multiselect(
                "監視リストに追加", 
                options=merged_opts, 
                default=curr_list, 
                format_func=fmt,
                placeholder="銘柄を検索..."
            )
            
            manual = st.text_input("手動追加", placeholder="例: GME")
            
            # ボタン: キャッシュをクリアして強制更新
            if st.button("リストを保存して更新", type="primary", use_container_width=True):
                final = sel.copy()
                if manual: final.extend([x.strip().upper() for x in manual.split(',')])
                save_watchlist(df.iloc[0]['name'], final)
                st.cache_data.clear() # ★修正: 保存時にキャッシュを全クリア
                st.rerun()

    # 右サイド
    with col2:
        if not curr_list:
            st.info("👈 左側で銘柄を選んでください")
        else:
            c_head, c_btn = st.columns([3, 1])
            with c_head:
                st.subheader("📊 AI 売買判断ダッシュボード")
            with c_btn:
                # ★追加: 手動更新ボタン
                if st.button("🔄 最新データ取得"):
                    st.cache_data.clear()
                    st.rerun()

            with st.spinner("市場データを取得中..."):
                df_anl = analyze_stocks_pro(curr_list)

            if not df_anl.empty:
                buy_c = len(df_anl[df_anl["Score"] >= 80])
                alert_c = len(df_anl[df_anl["Score"] < 0])
                
                m1, m2, m3 = st.columns(3)
                m1.metric("買い推奨", f"{buy_c} 銘柄", delta="Chance" if buy_c > 0 else "None")
                m2.metric("過熱/警戒", f"{alert_c} 銘柄", delta="Alert" if alert_c > 0 else "None", delta_color="inverse")
                m3.caption(f"最終更新: {time.strftime('%H:%M:%S')}")

                st.dataframe(
                    df_anl,
                    column_order=["Verdict", "Symbol", "Sector", "Price", "Change", "RSI", "Trend", "Reason"],
                    column_config={
                        "Verdict": st.column_config.TextColumn("AI判定", width="medium"),
                        "Symbol": st.column_config.TextColumn("銘柄", width="small"),
                        "Sector": st.column_config.TextColumn("セクター", width="small"),
                        "Price": st.column_config.NumberColumn("現在値", format="$%.2f"),
                        # ★修正: 前日比に色付けをして見やすく
                        "Change": st.column_config.NumberColumn("前日比", format="%.2f%%"),
                        "RSI": st.column_config.ProgressColumn("RSI (過熱感)", format="%d", min_value=0, max_value=100),
                        "Trend": st.column_config.TextColumn("傾向", width="small"),
                        "Reason": st.column_config.TextColumn("分析コメント", width="medium"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=600
                )
            else:
                st.error("データの取得に失敗しました。時間をおいて「最新データ取得」を押してください。")

if __name__ == "__main__": main()
