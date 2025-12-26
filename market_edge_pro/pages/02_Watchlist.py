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

# --- ★大幅強化: 銘柄マスターデータ (人気順 & カテゴリ分け) ---
# ユーザーが見つけやすいよう、取引量が多い順・人気順に定義します
STOCK_MASTER = {
    # --- 📊 主要インデックス & ETF (最優先) ---
    "SPY": {"name": "SPDR S&P 500", "sector": "[INDEX] S&P500"},
    "QQQ": {"name": "Invesco QQQ", "sector": "[INDEX] NASDAQ100"},
    "VOO": {"name": "Vanguard S&P 500", "sector": "[INDEX] S&P500"},
    "VTI": {"name": "Vanguard Total Stock", "sector": "[INDEX] 全米株式"},
    "DIA": {"name": "SPDR Dow Jones", "sector": "[INDEX] NYダウ"},
    "IWM": {"name": "iShares Russell 2000", "sector": "[INDEX] 小型株"},
    "SOXL": {"name": "Direxion Daily Semi 3x", "sector": "[ETF] 半導体3倍"},
    "TQQQ": {"name": "ProShares UltraPro QQQ", "sector": "[ETF] ナスダック3倍"},
    "TLT": {"name": "iShares 20+ Year Treasury", "sector": "[ETF] 米国債"},
    
    # --- 🔥 超人気・高出来高 (Magnificent 7 + α) ---
    "NVDA": {"name": "NVIDIA Corp.", "sector": "Technology"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Consumer Cyclical"},
    "AAPL": {"name": "Apple Inc.", "sector": "Technology"},
    "AMD": {"name": "Advanced Micro Devices", "sector": "Technology"},
    "AMZN": {"name": "Amazon.com", "sector": "Consumer Cyclical"},
    "MSFT": {"name": "Microsoft Corp.", "sector": "Technology"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Communication"},
    "META": {"name": "Meta Platforms", "sector": "Communication"},
    
    # --- 🚀 人気グロース・テック・仮想通貨関連 ---
    "PLTR": {"name": "Palantir Technologies", "sector": "Technology"},
    "COIN": {"name": "Coinbase Global", "sector": "Financial"},
    "MARA": {"name": "Marathon Digital", "sector": "Crypto Mining"},
    "MSTR": {"name": "MicroStrategy", "sector": "Technology"},
    "AVGO": {"name": "Broadcom Inc.", "sector": "Technology"},
    "TSM": {"name": "Taiwan Semi", "sector": "Technology"},
    "ARM": {"name": "Arm Holdings", "sector": "Technology"},
    "SMCI": {"name": "Super Micro Computer", "sector": "Technology"},
    "CRWD": {"name": "CrowdStrike", "sector": "Technology"},
    "PANW": {"name": "Palo Alto Networks", "sector": "Technology"},
    "SNOW": {"name": "Snowflake Inc.", "sector": "Technology"},
    "U": {"name": "Unity Software", "sector": "Technology"},
    "UBER": {"name": "Uber Technologies", "sector": "Technology"},
    "ABNB": {"name": "Airbnb Inc.", "sector": "Consumer Cyclical"},
    
    # --- 💰 金融・伝統的大手 (Blue Chips) ---
    "JPM": {"name": "JPMorgan Chase", "sector": "Financial"},
    "BAC": {"name": "Bank of America", "sector": "Financial"},
    "V": {"name": "Visa Inc.", "sector": "Financial"},
    "MA": {"name": "Mastercard", "sector": "Financial"},
    "WMT": {"name": "Walmart Inc.", "sector": "Consumer Defensive"},
    "COST": {"name": "Costco Wholesale", "sector": "Consumer Defensive"},
    "KO": {"name": "Coca-Cola", "sector": "Consumer Defensive"},
    "PEP": {"name": "PepsiCo", "sector": "Consumer Defensive"},
    "PG": {"name": "Procter & Gamble", "sector": "Consumer Defensive"},
    "MCD": {"name": "McDonald's", "sector": "Consumer Cyclical"},
    "DIS": {"name": "Walt Disney", "sector": "Communication"},
    "NFLX": {"name": "Netflix Inc.", "sector": "Communication"},
    "XOM": {"name": "Exxon Mobil", "sector": "Energy"},
    "CVX": {"name": "Chevron Corp.", "sector": "Energy"},
    "LLY": {"name": "Eli Lilly", "sector": "Healthcare"},
    "UNH": {"name": "UnitedHealth", "sector": "Healthcare"},
    "PFE": {"name": "Pfizer Inc.", "sector": "Healthcare"},
    "JNJ": {"name": "Johnson & Johnson", "sector": "Healthcare"},
    "BA": {"name": "Boeing Co.", "sector": "Industrials"},
    "CAT": {"name": "Caterpillar", "sector": "Industrials"},
    "GE": {"name": "General Electric", "sector": "Industrials"},
}

# 辞書のキー定義順（人気順）を維持してリスト化
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
    # 保存時も勝手にソートせず、ユーザーの追加順を維持する
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
@st.cache_data(ttl=600)
def analyze_stocks_pro(symbols):
    if not symbols: return pd.DataFrame()
    tickers = " ".join(symbols)
    try:
        df_hist = yf.download(tickers, period="6mo", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except: return pd.DataFrame()

    results = []
    for sym in symbols:
        try:
            if len(symbols) == 1: sdf = df_hist
            else: 
                if sym not in df_hist: continue
                sdf = df_hist[sym]
            
            if sdf.empty or len(sdf) < 50: continue

            close = float(sdf['Close'].iloc[-1])
            prev_close = float(sdf['Close'].iloc[-2])
            change_pct = (close - prev_close) / prev_close * 100
            
            sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
            rsi = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
            
            trend_up = close > sma50
            
            verdict, reason, score = "", "", 0
            if trend_up:
                if rsi < 35:
                    verdict, reason, score = "💎 超・買い時", "上昇トレンド中の暴落", 100
                elif rsi < 50:
                    verdict, reason, score = "◎ 押し目買い", "トレンド継続＋過熱感なし", 80
                elif rsi > 75:
                    verdict, reason, score = "⚡ 利確検討", "買われすぎ警戒", -10
                else:
                    verdict, reason, score = "○ 保有/継続", "順調に推移中", 50
            else:
                if rsi < 30:
                    verdict, reason, score = "△ リバウンド狙い", "売られすぎだが逆張り注意", 40
                else:
                    verdict, reason, score = "× 様子見", "下降トレンド中", 0

            meta = STOCK_MASTER.get(sym, {"name": sym, "sector": "Others"})
            
            results.append({
                "Symbol": sym,
                "Name": meta["name"],
                "Sector": meta["sector"], # セクター追加
                "Price": close,
                "Change": change_pct,
                "RSI": rsi,
                "Trend": "📈" if trend_up else "📉",
                "Verdict": verdict,
                "Reason": reason,
                "Score": score
            })
        except: continue
    
    df_res = pd.DataFrame(results)
    # スコア順に並び替え（チャンス銘柄を上に）
    if not df_res.empty:
        df_res = df_res.sort_values(by="Score", ascending=False)
    
    return df_res

# --- メイン画面 ---
def main():
    st.title("⚡ 監視リスト & 売買シグナル")
    
    df = load_watchlist()
    if df.empty: st.warning("DBエラー"); return

    curr_list = [s.strip().upper() for s in df.iloc[0]['symbols'].split(",") if s.strip()]

    # UIレイアウト
    col1, col2 = st.columns([1, 2.5])
    
    # --- 左サイド: リスト編集 ---
    with col1:
        with st.container(border=True):
            st.subheader("🛠 銘柄を選ぶ")
            st.caption("※ 人気順・取引量順に並んでいます")

            def fmt(t):
                m = STOCK_MASTER.get(t)
                if m:
                    # 見やすいフォーマット: [セクター] ティッカー | 社名
                    return f"【{m['sector']}】 {t} | {m['name']}"
                return t

            # 既存リスト + 人気リスト をマージ（重複なし、人気順を優先維持）
            # POPULAR_ORDERにあるものはその順序で、ないもの（手動追加分）は後ろに回す
            merged_opts = POPULAR_ORDER + [x for x in curr_list if x not in POPULAR_ORDER]
            
            sel = st.multiselect(
                "リストに追加・削除", 
                options=merged_opts, 
                default=curr_list, 
                format_func=fmt,
                placeholder="銘柄を検索..."
            )
            
            manual = st.text_input("手動追加 (コード入力)", placeholder="例: GME")
            
            if st.button("保存して分析 (Update)", type="primary", use_container_width=True):
                final = sel.copy()
                if manual: final.extend([x.strip().upper() for x in manual.split(',')])
                save_watchlist(df.iloc[0]['name'], final)
                st.rerun()

    # --- 右サイド: 分析結果 ---
    with col2:
        if not curr_list:
            st.info("👈 左のメニューから銘柄を選んでください")
        else:
            st.subheader("📊 AI 売買判断ダッシュボード")
            with st.spinner("最新データを取得中..."):
                df_anl = analyze_stocks_pro(curr_list)

            if not df_anl.empty:
                buy_c = len(df_anl[df_anl["Score"] >= 80])
                alert_c = len(df_anl[df_anl["Score"] < 0])
                
                m1, m2, m3 = st.columns(3)
                m1.metric("買い推奨", f"{buy_c} 銘柄", delta="Chance!" if buy_c > 0 else "Wait")
                m2.metric("過熱/警戒", f"{alert_c} 銘柄", delta="Alert" if alert_c > 0 else None, delta_color="inverse")
                m3.caption(f"Update: {time.strftime('%H:%M:%S')}")

                st.dataframe(
                    df_anl,
                    column_order=["Verdict", "Symbol", "Sector", "Price", "Change", "RSI", "Trend", "Reason"],
                    column_config={
                        "Verdict": st.column_config.TextColumn("AI判定", width="medium"),
                        "Symbol": st.column_config.TextColumn("銘柄", width="small"),
                        "Sector": st.column_config.TextColumn("セクター", width="medium"),
                        "Price": st.column_config.NumberColumn("株価", format="$%.2f"),
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
                st.error("データ取得エラー。少し待ってから再読み込みしてください。")

if __name__ == "__main__": main()
