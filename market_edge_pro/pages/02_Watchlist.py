import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import time
import yfinance as yf
import ta  # テクニカル分析用

# --- セットアップ ---
st.set_page_config(page_title="Watchlist Pro", layout="wide")
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- マスタデータ (セクター情報) ---
STOCK_MASTER = {
    "AAPL": {"name": "Apple", "sector": "Tech"},
    "MSFT": {"name": "Microsoft", "sector": "Tech"},
    "GOOGL": {"name": "Alphabet", "sector": "Comm"},
    "AMZN": {"name": "Amazon", "sector": "Consum"},
    "NVDA": {"name": "NVIDIA", "sector": "Tech"},
    "META": {"name": "Meta", "sector": "Comm"},
    "TSLA": {"name": "Tesla", "sector": "Consum"},
    "AMD": {"name": "AMD", "sector": "Tech"},
    "AVGO": {"name": "Broadcom", "sector": "Tech"},
    "JPM": {"name": "JPMorgan", "sector": "Fin"},
    "V": {"name": "Visa", "sector": "Fin"},
    "LLY": {"name": "Eli Lilly", "sector": "Health"},
    "WMT": {"name": "Walmart", "sector": "Consum"},
    "XOM": {"name": "Exxon", "sector": "Energy"},
    "SPY": {"name": "S&P 500", "sector": "ETF"},
    "QQQ": {"name": "NASDAQ", "sector": "ETF"},
    "VOO": {"name": "S&P 500", "sector": "ETF"},
    "VTI": {"name": "Total US", "sector": "ETF"},
    "SOXL": {"name": "Semi Bull", "sector": "ETF"},
    "TLT": {"name": "Bond 20y", "sector": "ETF"},
}
ALL_OPTIONS = sorted(list(STOCK_MASTER.keys()))

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
    clean_list = sorted(list(set([s.strip().upper() for s in symbols_list if s.strip()])))
    clean_str = ",".join(clean_list)
    conn = get_connection()
    try:
        conn.execute("UPDATE watchlists SET name = ?, symbols = ? WHERE id = (SELECT id FROM watchlists LIMIT 1)", (name, clean_str))
        conn.commit()
        return clean_list
    except: return []
    finally: conn.close()

# --- ★核心機能: 本格的な売買判定ロジック ---
@st.cache_data(ttl=600)
def analyze_stocks_pro(symbols):
    if not symbols: return pd.DataFrame()
    tickers = " ".join(symbols)
    
    try:
        # 過去半年分のデータを取得（SMA50計算のため）
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

            # --- テクニカル指標の計算 ---
            close = float(sdf['Close'].iloc[-1])
            prev_close = float(sdf['Close'].iloc[-2])
            change_pct = (close - prev_close) / prev_close * 100
            
            # SMA50 (中期トレンド)
            sma50 = ta.trend.SMAIndicator(sdf['Close'], window=50).sma_indicator().iloc[-1]
            # RSI14 (過熱感)
            rsi = ta.momentum.RSIIndicator(sdf['Close'], window=14).rsi().iloc[-1]
            
            # --- 判定ロジック (ここが脳みそ) ---
            trend_up = close > sma50
            
            # 結論（Verdict）の生成
            verdict = ""
            reason = ""
            score = 0 # 並び替え用スコア

            if trend_up:
                # 上昇トレンド中
                if rsi < 35:
                    verdict = "💎 超・買い時 (Deep Dip)"
                    reason = "上昇中の暴落。絶好の拾い場"
                    score = 100
                elif rsi < 50:
                    verdict = "◎ 押し目買い (Buy)"
                    reason = "トレンド継続＋過熱感なし"
                    score = 80
                elif rsi > 75:
                    verdict = "⚡ 利確検討 (Danger)"
                    reason = "上がりすぎ。急落警戒"
                    score = -10
                else:
                    verdict = "○ 保有/継続 (Hold)"
                    reason = "順調に推移中"
                    score = 50
            else:
                # 下降トレンド中 (SMA50より下)
                if rsi < 30:
                    verdict = "△ リバウンド狙い"
                    reason = "売られすぎだが逆張り注意"
                    score = 40
                else:
                    verdict = "× 様子見 (Wait)"
                    reason = "トレンド弱含み。手出し無用"
                    score = 0

            meta = STOCK_MASTER.get(sym, {"name": sym, "sector": "-"})
            
            results.append({
                "Symbol": sym,
                "Name": meta["name"],
                "Price": close,
                "Change": change_pct / 100, # パーセント表示用に小数化
                "RSI": rsi,
                "Trend": "📈 上昇" if trend_up else "📉 下降",
                "Verdict": verdict,
                "Reason": reason,
                "Score": score
            })
        except: continue
    
    # スコア順（買い時が高い順）に並び替え
    df_res = pd.DataFrame(results)
    if not df_res.empty:
        df_res = df_res.sort_values(by="Score", ascending=False)
    
    return df_res

# --- メイン画面 ---
def main():
    st.title("⚡ 監視リスト & 売買シグナル")
    
    df = load_watchlist()
    if df.empty: st.warning("DBエラー"); return

    curr_list = [s.strip().upper() for s in df.iloc[0]['symbols'].split(",") if s.strip()]

    # レイアウト
    col1, col2 = st.columns([1, 2.5])
    
    # 左：銘柄選択
    with col1:
        with st.container(border=True):
            st.subheader("🛠 リスト編集")
            
            def fmt(t):
                m = STOCK_MASTER.get(t)
                return f"{t} | {m['name']}" if m else t

            merged_opts = sorted(list(set(ALL_OPTIONS + curr_list)))
            sel = st.multiselect("銘柄を追加/削除", merged_opts, default=curr_list, format_func=fmt)
            
            manual = st.text_input("手動追加 (例: GME)", placeholder="コードを入力")
            
            if st.button("保存して分析 (Update)", type="primary", use_container_width=True):
                final = sel.copy()
                if manual: final.extend([x.strip().upper() for x in manual.split(',')])
                save_watchlist(df.iloc[0]['name'], final)
                st.rerun()

    # 右：分析結果（ここを神UIにする）
    with col2:
        if not curr_list:
            st.info("銘柄を選んでください")
        else:
            st.subheader("📊 AI 売買判断ダッシュボード")
            with st.spinner("市場データを分析中..."):
                df_anl = analyze_stocks_pro(curr_list)

            if not df_anl.empty:
                # 上部にサマリーを表示
                buy_count = len(df_anl[df_anl["Score"] >= 80])
                danger_count = len(df_anl[df_anl["Score"] < 0])
                
                m1, m2, m3 = st.columns(3)
                m1.metric("今の買い推奨", f"{buy_count} 銘柄", delta="チャンス到来" if buy_count > 0 else "待機", delta_color="normal")
                m2.metric("警戒/売り推奨", f"{danger_count} 銘柄", delta="利確の目安" if danger_count > 0 else None, delta_color="inverse")
                m3.caption(f"最終更新: {time.strftime('%H:%M:%S')}")

                # ★メインの分析テーブル
                st.dataframe(
                    df_anl,
                    column_order=["Verdict", "Symbol", "Price", "Change", "RSI", "Trend", "Reason"],
                    column_config={
                        "Verdict": st.column_config.TextColumn("🤖 AI判定", width="medium"),
                        "Symbol": st.column_config.TextColumn("銘柄", width="small"),
                        "Price": st.column_config.NumberColumn("株価", format="$%.2f"),
                        "Change": st.column_config.NumberColumn("前日比", format="%.2f%%"),
                        "RSI": st.column_config.ProgressColumn(
                            "過熱感 (RSI)", 
                            format="%d", 
                            min_value=0, max_value=100,
                            help="30以下: 売られすぎ(買い) / 70以上: 買われすぎ(売り)"
                        ),
                        "Trend": st.column_config.TextColumn("トレンド", width="small"),
                        "Reason": st.column_config.TextColumn("分析コメント", width="large"),
                    },
                    hide_index=True,
                    use_container_width=True,
                    height=500
                )
                
                st.markdown("""
                ##### 💡 判定の見方
                - **💎 超・買い時**: 上昇トレンド中に一時的に暴落した状態。最高のエントリー・ポイント。
                - **◎ 押し目買い**: トレンドは上向きで、過熱感もない状態。素直に買って良い。
                - **⚡ 利確検討**: 上がりすぎてRSIが75を超えている。そろそろ落ちる可能性大。
                - **× 様子見**: 下降トレンド中。触ると火傷する。
                """)
            else:
                st.error("データ取得に失敗しました。")

if __name__ == "__main__": main()
