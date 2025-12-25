import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Transparent", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    progress_bar = st.progress(0)
    status_text = st.empty()
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    for i, ticker in enumerate(tickers):
        status_text.text(f"🦅 データ照合中... {ticker}")
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            hist = stock.history(period="1y")
            
            if hist.empty: continue

            # --- A. 生データの抽出 (Raw Data) ---
            # 1. 価格データ
            price = info.get('currentPrice', hist['Close'].iloc[-1])
            
            # 2. バリュエーション (PEG計算用)
            # 定義: Trailing PEG = Trailing PE / Earnings Growth (Yahoo Finance取得値)
            pe = info.get('trailingPE') # 実績PER
            growth = info.get('earningsGrowth') # EPS成長率(直近)
            
            # 欠損値処理: データが無い場合は計算不可とする
            peg_raw = np.nan
            peg_display = "-"
            if pe is not None and growth is not None and growth > 0:
                peg_raw = pe / (growth * 100)
                peg_display = f"{peg_raw:.2f}倍"
            
            # 3. トレンドデータ (SMA)
            sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
            sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
            
            # 4. コンセンサス
            target = info.get('targetMeanPrice')
            upside_raw = np.nan
            if target:
                upside_raw = (target - price) / price

            # --- B. スコアリング (採点) ---
            score = 0
            breakdown = [] # 加点理由のログ

            # 1. 割安性 (PEG) - Max 30点
            if pd.notna(peg_raw):
                if 0 < peg_raw < 1.0:
                    score += 30
                    breakdown.append("★PEG<1.0 (超割安): +30点")
                elif peg_raw < 1.5:
                    score += 20
                    breakdown.append("PEG<1.5 (割安): +20点")
                elif peg_raw < 2.0:
                    score += 10
                    breakdown.append("PEG<2.0 (適正): +10点")
            else:
                 breakdown.append("PEG算出不可: 0点")

            # 2. トレンド (SMA配列) - Max 30点
            trend_status = "不明"
            if price > sma50 > sma200:
                score += 30
                trend_status = "📈 上昇(パーフェクトオーダー)"
                breakdown.append("トレンド(Pオーダー): +30点")
            elif price < sma50:
                trend_status = "📉 調整/下落"
                breakdown.append("トレンド(50日線割れ): 0点")
            else:
                trend_status = "➡️ レンジ"
                breakdown.append("トレンド(レンジ): 0点")

            # 3. アップサイド - Max 20点
            if pd.notna(upside_raw):
                if upside_raw > 0.2:
                    score += 20
                    breakdown.append(f"上値余地20%超: +20点")
                elif upside_raw > 0.1:
                    score += 10
                    breakdown.append(f"上値余地10%超: +10点")

            # 4. RSI (過熱感) - Max 20点
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            if 40 <= rsi <= 60 and "上昇" in trend_status:
                score += 20
                breakdown.append("RSI押し目(40-60): +20点")
            elif rsi > 80:
                score -= 10
                breakdown.append("RSI過熱(80超): -10点")

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
                "Breakdown": " / ".join(breakdown), # 内訳を保存
                "PEG_Display": peg_display,
                "Raw_PE": pe,         # 検証用生データ
                "Raw_Growth": growth, # 検証用生データ
                "Trend": trend_status,
                "SMA50": sma50,
                "SMA200": sma200,
                "RSI": rsi,
                "Target": target,
                "FetchTime": fetch_time
            })
            
        except Exception:
            continue
        
        progress_bar.progress((i + 1) / len(tickers))
    
    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 3. チャート描画関数 ---
def plot_chart(ticker, hist):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=hist.index,
                open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='Price'))
    
    # SMA計算（再掲）
    sma50 = hist['Close'].rolling(window=50).mean()
    sma200 = hist['Close'].rolling(window=200).mean()
    
    fig.add_trace(go.Scatter(x=hist.index, y=sma50, line=dict(color='orange', width=1.5), name='SMA 50'))
    fig.add_trace(go.Scatter(x=hist.index, y=sma200, line=dict(color='blue', width=1.5), name='SMA 200'))
    fig.update_layout(title=f"{ticker} Verification Chart", height=400, template="plotly_dark")
    return fig

# --- 4. メイン画面 ---
st.title("🦅 Market Edge Pro (Transparent Ver.)")
st.caption("検証可能性(Verifiability)を最優先した、ブラックボックスのない分析ツール")

# ★ 採点ルールの完全開示
with st.expander("📊 採点ルールとデータ定義（検証用）", expanded=False):
    st.markdown("""
    ### 1. データ定義 (Source: Yahoo Finance API)
    * **PEGレシオ (Trailing):** `Trailing PE` ÷ `Earnings Growth (直近四半期)` 
        * ※成長率がマイナスまたは取得不能な場合は計算除外(NaN)
    * **トレンド:** 過去1年間の終値に基づく単純移動平均(SMA)
    * **上値余地:** アナリストの平均目標株価 (`targetMeanPrice`) と現在値の乖離

    ### 2. 採点配分 (Total 100点)
    | 項目 | 条件 | 配点 |
    | :--- | :--- | :--- |
    | **割安性 (Max 30)** | PEG < 1.0 (超割安) | +30 |
    | | 1.0 ≦ PEG < 1.5 (割安) | +20 |
    | | 1.5 ≦ PEG < 2.0 (適正) | +10 |
    | **トレンド (Max 30)** | 株価 > SMA50 > SMA200 (Pオーダー) | +30 |
    | **期待値 (Max 20)** | 上値余地 > +20% | +20 |
    | | 上値余地 > +10% | +10 |
    | **需給 (Max 20)** | 上昇トレンド中のRSI 40-60 (押し目) | +20 |
    | **減点** | RSI > 80 (過熱) | -10 |
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST"]

if st.button("🔍 データ取得・完全解析を実行", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # メインテーブル表示
        st.subheader(f"🏆 スクリーニング結果 (Data at: {df['FetchTime'][0]})")
        
        display_df = df[['Ticker', 'Name', 'Price', 'Grade', 'Score', 'PEG_Display', 'Trend']].copy()
        display_df.columns = ['コード', '社名', '株価', '評価', 'スコア', 'PEG(実数値)', 'トレンド判定']
        
        st.dataframe(
            display_df.style
            .format({'株価': '${:.2f}', 'スコア': '{:.0f}'})
            .background_gradient(subset=['スコア'], cmap='Greens'),
            use_container_width=True
        )

        # --- 検証エリア (Deep Dive) ---
        st.divider()
        st.header("🧐 Calculation Breakdown (計算プロセスの検証)")
        st.info("計算に使われた「生データ」と「採点内訳」を全て表示します。AIの判断を鵜呑みにせず、検算してください。")
        
        selected_ticker = st.selectbox("詳細検証する銘柄を選択:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            # 2カラムレイアウト
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("1. 生データ (Raw Inputs)")
                st.code(f"""
[Valuation]
Trailing PE     : {row['Raw_PE']}
Earnings Growth : {row['Raw_Growth']}
=> PEG Calc     : {row['Raw_PE']} / ({row['Raw_Growth']} * 100) = {row['PEG_Display']}

[Trend]
Current Price   : ${row['Price']:.2f}
SMA 50          : ${row['SMA50']:.2f}
SMA 200         : ${row['SMA200']:.2f}

[Consensus]
Target Price    : ${row['Target']}
                """, language="yaml")
                
                # チャート表示
                stock = yf.Ticker(selected_ticker)
                hist = stock.history(period="1y")
                st.plotly_chart(plot_chart(selected_ticker, hist), use_container_width=True)

            with c2:
                st.subheader("2. 採点ロジック (Scoring)")
                st.write(f"**合計スコア: {row['Score']}点**")
                
                # 内訳をリスト表示
                reasons = row['Breakdown'].split(" / ")
                for r in reasons:
                    if "PEG" in r: st.success(f"💰 {r}")
                    elif "トレンド" in r: st.info(f"📈 {r}")
                    elif "上値" in r: st.warning(f"🎯 {r}")
                    elif "RSI" in r: st.error(f"📊 {r}")
                    else: st.write(f"・{r}")
            
    else:
        st.error("データ取得に失敗しました。")
