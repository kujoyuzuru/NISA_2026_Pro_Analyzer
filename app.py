import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Verifiable", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック (キャッシュ化で高速化) ---
@st.cache_data(ttl=3600) # 1時間キャッシュ
def fetch_stock_data(tickers):
    data_list = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, ticker in enumerate(tickers):
        status_text.text(f"🦅 データ照合中... {ticker}")
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist = stock.history(period="1y")
            
            if hist.empty: continue

            # --- A. 定義の明確化 (Yahoo Finance準拠) ---
            price = info.get('currentPrice', hist['Close'].iloc[-1])
            
            # PEG (Trailingベース: 過去の実績に基づく)
            # ※プロへの注釈: Forward PEGは有料データが必要なため、ここではTrailingを使用
            pe = info.get('trailingPE', 0)
            growth = info.get('earningsGrowth', 0) 
            peg = pe / (growth * 100) if growth > 0 else 999
            
            # トレンド判定 (SMA50 / SMA200)
            sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
            sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
            
            # アナリストターゲット
            target = info.get('targetMeanPrice', 0)
            upside = (target - price) / price if target > 0 else 0

            # --- B. スコアリング ---
            score = 0
            
            # 1. 割安性 (PEG)
            if 0 < peg < 1.0: score += 30
            elif 0 < peg < 1.5: score += 20
            
            # 2. トレンド (SMA配列)
            trend_str = "不明"
            if price > sma50 > sma200:
                score += 30
                trend_str = "📈 パーフェクトオーダー"
            elif price < sma50:
                trend_str = "📉 調整局面"
            else:
                trend_str = "➡️ レンジ/混在"

            # 3. アップサイド (期待値)
            if upside > 0.2: score += 20
            elif upside > 0.1: score += 10
            
            # 4. RSI (過熱感)
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            if 40 <= rsi <= 60 and trend_str.startswith("📈"): score += 20
            if rsi > 80: score -= 10

            # ランク付け
            grade = "C"
            if score >= 80: grade = "S"
            elif score >= 60: grade = "A"
            elif score >= 40: grade = "B"

            data_list.append({
                "Ticker": ticker,
                "Name": info.get('shortName', ticker),
                "Price": price,
                "Grade": grade,
                "Score": int(score),
                "PEG": peg if peg != 999 else np.nan,
                "Trend": trend_str,
                "Upside": upside,
                "SMA50": sma50,
                "SMA200": sma200,
                "RSI": rsi,
                "Target": target
            })
            
        except Exception:
            continue
        
        progress_bar.progress((i + 1) / len(tickers))
    
    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 3. チャート描画関数 (根拠の可視化) ---
def plot_chart(ticker):
    stock = yf.Ticker(ticker)
    hist = stock.history(period="1y")
    
    fig = go.Figure()
    
    # ローソク足
    fig.add_trace(go.Candlestick(x=hist.index,
                open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='株価'))
    
    # 移動平均線
    hist['SMA50'] = hist['Close'].rolling(window=50).mean()
    hist['SMA200'] = hist['Close'].rolling(window=200).mean()
    
    fig.add_trace(go.Scatter(x=hist.index, y=hist['SMA50'], line=dict(color='orange', width=1.5), name='50日線 (中期)'))
    fig.add_trace(go.Scatter(x=hist.index, y=hist['SMA200'], line=dict(color='blue', width=1.5), name='200日線 (長期)'))
    
    fig.update_layout(title=f"{ticker} トレンド確認チャート", height=400, template="plotly_dark")
    return fig

# --- 4. メイン画面 ---
st.title("🦅 Market Edge Pro (Verifiable)")
st.caption("データソース: Yahoo Finance (無料版) / 定義: Trailing PEG, SMA Trend")

# 重要な「限界」の明示（これで信頼性を担保する）
with st.expander("⚠️ 本アプリのデータ仕様と限界（必ず確認してください）", expanded=True):
    st.markdown("""
    * **データソース:** 米国Yahoo Financeの無料APIを使用しています。プロ向け有料端末(Bloomberg等)とは数値が異なる場合があります。
    * **PEGレシオ:** `Trailing P/E` ÷ `Earnings Growth(過去12ヶ月)` で算出しています。来期予想(Forward)ではありません。
    * **遅行性:** 移動平均線(SMA)は過去の値動きに基づくため、トレンド転換の初動は捉えられません。
    * **結論:** 本アプリは**「スクリーニング（候補の絞り込み）」**用です。売買判断は必ずご自身のチャート分析と合わせて行ってください。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "MSTR", "CRWD", "PANW", "LLY", "NVO", "VRTX", "COST"]

if st.button("🔍 厳格スキャンを実行 (証拠確認モード)", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # --- メインのランキング表 ---
        st.subheader(f"🏆 スクリーニング結果 ({len(df)}銘柄)")
        
        # 表示用データの作成
        display_df = df[['Ticker', 'Name', 'Price', 'Grade', 'Score', 'PEG', 'Trend', 'Upside']].copy()
        display_df.columns = ['コード', '社名', '株価', '評価', 'スコア', 'PEG(割安)', 'トレンド', '上値余地']
        
        st.dataframe(
            display_df.style
            .format({'株価': '${:.2f}', 'PEG(割安)': '{:.2f}倍', '上値余地': '{:.1%}'})
            .background_gradient(subset=['スコア'], cmap='Greens'),
            use_container_width=True
        )

        # --- 個別銘柄の「証拠」確認エリア ---
        st.divider()
        st.header("🧐 Deep Dive (根拠の確認)")
        st.info("上の表で気になった銘柄を選択してください。AIの判定根拠となるチャートとニュースを表示します。")
        
        selected_ticker = st.selectbox("詳しく見る銘柄を選択:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            col1, col2 = st.columns([2, 1])
            
            with col1:
                # チャート表示
                st.plotly_chart(plot_chart(selected_ticker), use_container_width=True)
            
            with col2:
                # 数値根拠の表示
                st.subheader("📊 判定データ")
                st.metric("現在の株価", f"${row['Price']:.2f}")
                st.metric("PEGレシオ (割安度)", f"{row['PEG']:.2f}倍", delta="1.0以下なら割安" if row['PEG'] < 1 else "-")
                st.metric("アナリスト目標", f"${row['Target']:.2f}", delta=f"余地 {row['Upside']:.1%}")
                
                st.write("---")
                st.write("**直近のニュース (Yahoo Finance):**")
                try:
                    news_list = yf.Ticker(selected_ticker).news[:3]
                    for news in news_list:
                        st.caption(f"・[{news['title']}]({news['link']})")
                except:
                    st.caption("ニュース取得不可")

    else:
        st.error("データ取得に失敗しました。")
