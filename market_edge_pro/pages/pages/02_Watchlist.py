import streamlit as st
import pandas as pd
import sqlite3
import os
import sys

# --- セットアップ ---
st.set_page_config(page_title="Watchlist Editor", layout="wide")

# パス解決（他のページと同じロジック）
BASE_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
if BASE_DIR not in sys.path: sys.path.append(BASE_DIR)
DB_PATH = os.path.join(BASE_DIR, "trading_journal.db")

# --- DB接続ヘルパー ---
def get_connection():
    return sqlite3.connect(DB_PATH)

def load_watchlist():
    conn = get_connection()
    try:
        df = pd.read_sql("SELECT * FROM watchlists LIMIT 1", conn)
        return df
    except Exception as e:
        st.error(f"DB読み込みエラー: {e}")
        return pd.DataFrame()
    finally:
        conn.close()

def save_watchlist(name, symbols_str):
    # データを整形（空白削除、大文字化、重複排除はあえてしない＝並び順維持のため）
    # カンマで区切ってリスト化し、また文字列に戻す
    clean_list = [s.strip().upper() for s in symbols_str.split(",") if s.strip()]
    clean_str = ",".join(clean_list)
    
    conn = get_connection()
    cursor = conn.cursor()
    try:
        # 既存のリスト（ID=1と仮定、またはLIMIT 1の行）を更新
        # ※もっと複雑にするならID指定だが、今回は「1つのリスト」を使い回す運用
        cursor.execute("UPDATE watchlists SET name = ?, symbols = ? WHERE id = (SELECT id FROM watchlists LIMIT 1)", (name, clean_str))
        conn.commit()
        st.success(f"✅ 保存しました！ (登録数: {len(clean_list)} 銘柄)")
        st.balloons()
    except Exception as e:
        st.error(f"保存エラー: {e}")
    finally:
        conn.close()

# --- メイン画面 ---
def main():
    st.title("📝 監視リスト編集 (Watchlist Editor)")
    st.markdown("ここで **Market Edge Pro** 全体で使用する監視対象銘柄を設定できます。")

    # 現在のデータを読み込み
    df = load_watchlist()
    
    if df.empty:
        st.warning("リストが見つかりません。DBを初期化してください。")
        return

    current_name = df.iloc[0]['name']
    current_symbols = df.iloc[0]['symbols']

    # 編集フォーム
    with st.container(border=True):
        st.subheader("設定フォーム")
        
        new_name = st.text_input("リスト名 (List Name)", value=current_name)
        
        st.markdown("**監視銘柄 (Symbols)**")
        st.caption("※ カンマ (`,`) で区切って入力してください。スペースは自動で削除されます。")
        
        # テキストエリアで自由に編集
        new_symbols = st.text_area(
            "Ticker Symbols", 
            value=current_symbols, 
            height=200,
            help="例: AAPL, MSFT, TSLA, NVDA"
        )

        # プレビュー表示
        preview_list = [s.strip().upper() for s in new_symbols.split(",") if s.strip()]
        st.info(f"現在の入力数: **{len(preview_list)}** 銘柄")
        if len(preview_list) > 0:
            st.code(", ".join(preview_list))

        # 保存ボタン
        if st.button("変更を保存する (Save Changes)", type="primary"):
            if not preview_list:
                st.error("銘柄が空です！少なくとも1つ入力してください。")
            else:
                save_watchlist(new_name, new_symbols)
                # 保存後にリロードを促す（または自動rerun）
                time.sleep(1)
                st.rerun()

    st.markdown("---")
    st.markdown("### 👉 使い方")
    st.markdown("""
    1. 上記のボックスに、監視したい米国株のティッカー（例: `GOOGL`, `XOM`, `KO`）を入力します。
    2. 銘柄の間は **カンマ (`,`)** で区切ってください。
    3. **「変更を保存する」** ボタンを押すと、データベースが更新されます。
    4. 左のメニューから **Scanner** に移動すると、新しいリストで分析が始まります。
    """)

import time # rerun用にインポート

if __name__ == "__main__":
    main()
