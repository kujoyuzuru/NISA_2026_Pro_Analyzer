import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import time
import yfinance as yf

# --- セットアップ ---
st.set_page_config(page_title="Watchlist Editor", layout="wide")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- 銘柄マスターデータ（初心者向け: 名前とセクター付き） ---
# ここに主要銘柄の情報を定義しておきます
STOCK_MASTER = {
    "AAPL": {"name": "Apple Inc.", "sector": "Technology"},
    "MSFT": {"name": "Microsoft Corp.", "sector": "Technology"},
    "GOOGL": {"name": "Alphabet Inc.", "sector": "Communication"},
    "AMZN": {"name": "Amazon.com", "sector": "Consumer Cyclical"},
    "NVDA": {"name": "NVIDIA Corp.", "sector": "Technology"},
    "META": {"name": "Meta Platforms", "sector": "Communication"},
    "TSLA": {"name": "Tesla Inc.", "sector": "Consumer Cyclical"},
    "AMD": {"name": "Advanced Micro Devices", "sector": "Technology"},
    "AVGO": {"name": "Broadcom Inc.", "sector": "Technology"},
    "TSM": {"name": "Taiwan Semi", "sector": "Technology"},
    "JPM": {"name": "JPMorgan Chase", "sector": "Financial"},
    "V": {"name": "Visa Inc.", "sector": "Financial"},
    "LLY": {"name": "Eli Lilly", "sector": "Healthcare"},
    "UNH": {"name": "UnitedHealth", "sector": "Healthcare"},
    "WMT": {"name": "Walmart Inc.", "sector": "Consumer Defensive"},
    "PG": {"name": "Procter & Gamble", "sector": "Consumer Defensive"},
    "KO": {"name": "Coca-Cola", "sector": "Consumer Defensive"},
    "XOM": {"name": "Exxon Mobil", "sector": "Energy"},
    "CVX": {"name": "Chevron Corp.", "sector": "Energy"},
    "BA": {"name": "Boeing Co.", "sector": "Industrials"},
    "DIS": {"name": "Walt Disney", "sector": "Communication"},
    "NFLX": {"name": "Netflix Inc.", "sector": "Communication"},
    "SPY": {"name": "SPDR S&P 500 ETF", "sector": "ETF"},
    "QQQ": {"name": "Invesco QQQ ETF", "sector": "ETF"},
    "VOO": {"name": "Vanguard S&P 500", "sector": "ETF"},
    "VTI": {"name": "Vanguard Total Stock", "sector": "ETF"},
    "SOXL": {"name": "Direxion Daily Semi", "sector": "ETF (Lev)"},
    "TLT": {"name": "iShares 20+ Year Treas", "sector": "ETF (Bond)"},
    "PLTR": {"name": "Palantir Tech", "sector": "Technology"},
    "IONQ": {"name": "IonQ Inc.", "sector": "Technology"},
    "COIN": {"name": "Coinbase Global", "sector": "Financial"},
    "UBER": {"name": "Uber Technologies", "sector": "Technology"},
}

# リスト選択用の選択肢を作成
ALL_OPTIONS = sorted(list(STOCK_MASTER.keys()))

# --- DBヘルパー ---
def get_connection():
    return sqlite3.connect(DB_PATH)

def load_watchlist():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        return df
    except: return pd.DataFrame()
    finally: conn.close()

def save_watchlist(name, symbols_list):
    clean_list = [s.strip().upper() for s in symbols_list if s.strip()]
    clean_list = sorted(list(set(clean_list)))
    clean_str = ",".join(clean_list)
    
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE watchlists SET name = ?, symbols = ? WHERE id = (SELECT id FROM watchlists LIMIT 1)", (name, clean_str))
        conn.commit()
        return clean_list
    except Exception as e:
        st.error(f"Save Error: {e}")
        return []
    finally:
        conn.close()

# --- 分析ヘルパー: 簡易AI評価 ---
@st.cache_data(ttl=600)
def analyze_stocks(symbols):
    """Yahoo Financeからデータを取得し、簡易評価を行う"""
    if not symbols: return pd.DataFrame()
    
    tickers = " ".join(symbols)
    try:
        # info取得は重いので、基本的なデータのみ一括取得して計算する軽量版AI
        # ※本来はtickers.infoで詳細取れるが、数が多いと非常に遅いため、日足データから推測するアプローチを採用
        df_hist = yf.download(tickers, period="1y", interval="1d", group_by='ticker', auto_adjust=True, progress=False)
    except:
        return pd.DataFrame()

    analysis_results = []
    
    for sym in symbols:
        try:
            # データフレームの処理（単一銘柄対応）
            if len(symbols) == 1: stock_df = df_hist
            else: 
                if sym not in df_hist: continue
                stock_df = df_hist[sym]
            
            if stock_df.empty: continue

            # 最新価格データ
            current = float(stock_df['Close'].iloc[-1])
            prev = float(stock_df['Close'].iloc[-2])
            change_pct = (current - prev) / prev * 100
            
            # 52週高値・安値（簡易計算）
            high_52 = float(stock_df['Close'].max())
            low_52 = float(stock_df['Close'].min())
            
            # 簡易AI評価ロジック
            # 位置（高値圏か安値圏か）
            pos_ratio = (current - low_52) / (high_52 - low_52)
            
            status = "Neutral"
            if pos_ratio > 0.9: status = "🔥 加熱 (High)"
            elif pos_ratio < 0.2: status = "💰 割安圏 (Low)"
            elif change_pct > 3.0: status = "🚀 急騰 (Surge)"
            elif change_pct < -3.0: status = "😱 急落 (Drop)"
            
            # マスターデータから補足情報
            meta = STOCK_MASTER.get(sym, {"name": sym, "sector": "Unknown"})
            
            analysis_results.append({
                "Symbol": sym,
                "Name": meta["name"],
                "Sector": meta["sector"],
                "Price": current,
                "Change": change_pct,
                "Position": pos_ratio, # 0(安値)-1(高値)
                "AI Signal": status
            })
        except: continue
        
    return pd.DataFrame(analysis_results)

# --- メイン画面 ---
def main():
    st.title("📝 監視リスト管理 (Smart Editor)")
    st.info("💡 銘柄を選ぶと、自動的に最新データとAI評価が表示されます。")

    df = load_watchlist()
    if df.empty: st.warning("DB未初期化"); return

    current_name = df.iloc[0]['name']
    current_symbols_str = df.iloc[0]['symbols']
    current_list = [s.strip().upper() for s in current_symbols_str.split(",") if s.strip()]

    # --- UI: 2カラムレイアウト ---
    col1, col2 = st.columns([1, 2])
    
    with col1:
        st.subheader("1. 銘柄を選択")
        with st.container(border=True):
            new_name = st.text_input("リスト名", value=current_name)
            
            # ★改善点：フォーマット関数で「名前とセクター」を表示
            def format_option(ticker):
                meta = STOCK_MASTER.get(ticker)
                if meta:
                    return f"{ticker} | {meta['name']} ({meta['sector']})"
                return ticker

            # 選択肢のマージ（既存にあるけどマスターにない銘柄も対応）
            merged_options = sorted(list(set(ALL_OPTIONS + current_list)))

            selected_stocks = st.multiselect(
                "監視対象を追加・削除",
                options=merged_options,
                default=current_list,
                format_func=format_option, # ここで見やすくする
                placeholder="銘柄を検索..."
            )
            
            manual_add = st.text_input("リストにない銘柄を手動追加", placeholder="例: GME")
            
            if st.button("リストを更新・保存", type="primary"):
                final_list = selected_stocks.copy()
                if manual_add:
                    final_list.extend([x.strip().upper() for x in manual_add.split(',')])
                
                saved_list = save_watchlist(new_name, final_list)
                if saved_list:
                    st.success("保存しました！右側の分析を更新します...")
                    time.sleep(1)
                    st.rerun()

    with col2:
        st.subheader("2. AI分析・評価プレビュー")
        if not current_list:
            st.warning("銘柄が選択されていません。")
        else:
            with st.spinner(f"{len(current_list)} 銘柄の最新データを分析中..."):
                # データ取得＆分析実行
                df_analysis = analyze_stocks(current_list)
            
            if not df_analysis.empty:
                # 数値のフォーマットを整えて表示
                st.dataframe(
                    df_analysis,
                    column_order=["Symbol", "Name", "Sector", "Price", "Change", "AI Signal", "Position"],
                    column_config={
                        "Symbol": st.column_config.TextColumn("銘柄", width="small"),
                        "Name": st.column_config.TextColumn("企業名", width="medium"),
                        "Sector": st.column_config.TextColumn("セクター", width="small"),
                        "Price": st.column_config.NumberColumn("株価 ($)", format="$%.2f"),
                        "Change": st.column_config.NumberColumn("前日比 (%)", format="%.2f%%"),
                        "AI Signal": st.column_config.TextColumn("AI評価", width="medium"),
                        "Position": st.column_config.ProgressColumn(
                            "52週レンジ (安値→高値)",
                            help="左端が52週最安値、右端が52週最高値。右に近いほど高値圏。",
                            format="%.2f",
                            min_value=0,
                            max_value=1,
                        ),
                    },
                    hide_index=True,
                    use_container_width=True
                )
                st.caption(f"※ データ取得時刻: {time.strftime('%H:%M:%S')}")
                st.markdown("""
                **AI評価の読み方:**
                - **💰 割安圏**: 過去1年の最安値に近いため、反発狙いのチャンス。
                - **🔥 加熱**: 最高値に近いため、高値掴みに注意。
                - **🚀 急騰 / 😱 急落**: 本日3%以上の大きな動きがあります。
                """)
            else:
                st.error("データの取得に失敗しました。少し待ってから再読み込みしてください。")

if __name__ == "__main__": main()
