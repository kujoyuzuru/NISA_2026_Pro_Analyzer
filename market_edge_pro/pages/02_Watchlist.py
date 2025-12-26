import streamlit as st
import pandas as pd
import sqlite3
import os
import sys
import time

# --- セットアップ ---
st.set_page_config(page_title="Watchlist Editor", layout="wide")

BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- 定数: 米国株 主要100銘柄+人気ETFリスト ---
DEFAULT_TICKERS = [
    # Magnificent 7 / Big Tech
    "AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "TSLA",
    # Semiconductors
    "AMD", "AVGO", "INTC", "QCOM", "TXN", "MU", "AMAT", "LRCX", "SMCI", "ARM", "TSM",
    # Finance
    "JPM", "BAC", "V", "MA", "WFC", "MS", "GS", "BLK", "AXP", "PYPL",
    # Healthcare
    "LLY", "UNH", "JNJ", "MRK", "ABBV", "PFE", "TMO", "DHR", "ISRG",
    # Consumer / Retail
    "WMT", "PG", "COST", "KO", "PEP", "HD", "MCD", "NKE", "SBUX", "DIS", "NFLX",
    # Industrial / Energy / Others
    "XOM", "CVX", "GE", "CAT", "DE", "BA", "LMT", "RTX", "HON", "UPS", "FDX",
    # ETFs (Popular)
    "SPY", "VOO", "QQQ", "VTI", "SOXL", "TQQQ", "TLT", "GLD",
    # Trending / Others
    "PLTR", "U", "CRWD", "PANW", "SNOW", "SQ", "COIN", "MARA", "MSTR", "UBER", "ABNB"
]
DEFAULT_TICKERS.sort() # アルファベット順に整列

# --- DBヘルパー ---
def get_connection():
    return sqlite3.connect(DB_PATH)

def load_watchlist():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        return df
    except:
        return pd.DataFrame()
    finally:
        conn.close()

def save_watchlist(name, symbols_list):
    # リストをカンマ区切り文字列に変換
    clean_list = [s.strip().upper() for s in symbols_list if s.strip()]
    # 重複排除しつつソート
    clean_list = sorted(list(set(clean_list)))
    clean_str = ",".join(clean_list)
    
    conn = get_connection()
    c = conn.cursor()
    try:
        c.execute("UPDATE watchlists SET name = ?, symbols = ? WHERE id = (SELECT id FROM watchlists LIMIT 1)", (name, clean_str))
        conn.commit()
        st.success(f"✅ 更新完了！ (計 {len(clean_list)} 銘柄)")
        time.sleep(1)
        st.rerun()
    except Exception as e:
        st.error(f"Save Error: {e}")
    finally:
        conn.close()

# --- メイン画面 ---
def main():
    st.title("📝 監視リスト編集 (Easy Editor)")
    st.markdown("主要銘柄リストから選択するか、検索して追加してください。")

    df = load_watchlist()
    if df.empty: st.warning("DB未初期化"); return

    current_name = df.iloc[0]['name']
    current_symbols_str = df.iloc[0]['symbols']
    
    # DBの文字列をリストに変換
    current_list = [s.strip().upper() for s in current_symbols_str.split(",") if s.strip()]

    with st.container(border=True):
        st.subheader("設定フォーム")
        new_name = st.text_input("リスト名", value=current_name)
        
        st.markdown("---")
        
        # ★ここが新機能: マルチセレクトUI
        # 選択肢 = (デフォルトリスト + 現在登録されている銘柄) の重複なし和集合
        all_options = sorted(list(set(DEFAULT_TICKERS + current_list)))
        
        selected_stocks = st.multiselect(
            "💎 主要銘柄から選択 (検索可能)",
            options=all_options,
            default=current_list,
            placeholder="銘柄を選択、または入力して検索..."
        )
        
        # ★補完機能: リストにない銘柄を手動追加
        with st.expander("リストにない銘柄を手動で追加する"):
            st.caption("※ 上記のリストにない銘柄 (例: 日本株コードやマイナー株) はここに追記してください")
            manual_add = st.text_input("手動追加 (カンマ区切り)", placeholder="例: GME, AMC")
        
        # 保存ボタン
        st.markdown("###")
        if st.button("変更を保存する (Save Changes)", type="primary"):
            # セレクトボックスの中身 + 手動入力の中身 を合体させる
            final_list = selected_stocks.copy()
            if manual_add:
                extras = [x.strip().upper() for x in manual_add.split(',')]
                final_list.extend(extras)
            
            save_watchlist(new_name, final_list)

    # プレビュー
    st.markdown("---")
    st.markdown(f"**現在の登録銘柄 ({len(current_list)}):**")
    st.code(", ".join(current_list))

if __name__ == "__main__": main()
