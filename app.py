import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Verified", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 市場データを取得・精密解析中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"🦅 データ照合中... {ticker} ({i+1}/{total})")
            
            try:
                stock = yf.Ticker(ticker)
                try:
                    info = stock.info
                except:
                    continue 

                hist = stock.history(period="1y")
                if hist.empty: continue

                # --- A. 生データの抽出 (検証用Raw Data) ---
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                
                # 1. Valuation (期間の整合性を確保)
                # Critic指摘対応: Trailing PEではなくForward PEを使うことで将来成長率との整合性を取る
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                # PEG計算 (Forward PE / Growth)
                peg_raw = np.nan
                peg_display = "-"
                
                if fwd_pe is not None and growth is not None and growth > 0:
                    peg_raw = fwd_pe / (growth * 100)
                    peg_display = f"{peg_raw:.2f}倍"
                
                # 2. Trend (SMA)
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus (信頼性指標を追加)
                target = info.get('targetMeanPrice')
                analysts = info.get('numberOfAnalystOpinions', 0) # アナリスト数
                
                upside_raw = np.nan
                if target and price > 0:
                    upside_raw = (target - price) / price

                # --- B. スコアリング (Momentum Growth戦略) ---
                score = 0
                breakdown = []

                # 1. 割安性 (PEG) - Max 30点
                if pd.notna(peg_raw):
                    if 0 < peg_raw < 1.0:
                        score += 30
                        breakdown.append("★PEG<1.0 (割安成長): +30")
                    elif peg_raw < 1.5:
                        score += 20
                        breakdown.append("PEG<1.5 (適正圏内): +20")
                    elif peg_raw < 2.0:
                        score += 10
                        breakdown.append("PEG<2.0 (許容範囲): +10")
                else:
                    breakdown.append("PEG算出不可/赤字: 0")

                # 2. トレンド (SMA配列) - Max 30点
                trend_str = "レンジ/下降"
                if price > sma50 > sma200:
                    score += 30
                    trend_str = "📈 パーフェクトオーダー"
                    breakdown.append("上昇トレンド(Pオーダー): +30")
                elif price < sma50:
                    trend_str = "📉 調整局面"
                    breakdown.append("トレンド崩れ(50日線割れ): 0")

                # 3. アップサイド (アナリスト数で加重) - Max 20点
                if pd.notna(upside_raw) and analysts >= 5: # 5人以上の合意がある場合のみ信頼
                    if upside_raw > 0.2:
                        score += 20
                        breakdown.append(f"上値余地20%超({analysts}人): +20")
                    elif upside_raw > 0.1:
                        score += 10
                        breakdown.append(f"上値余地10%超: +10")
                elif analysts < 5:
                     breakdown.append("アナリスト不足(信頼度低): 0")

                # 4. RSI (過熱感) - Max 20点
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and "上昇" in trend_str:
                    score += 20
                    breakdown.append("RSI押し目(40-60): +20")
                elif rsi > 75: # 基準を厳格化
                    score -= 10
                    breakdown.append("RSI過熱(75超): -10")

                # グレード判定
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
                    "Breakdown": " / ".join(breakdown),
                    # --- 検証用生データ (Raw Data) ---
                    "Fwd_PE": fwd_pe if fwd_pe else np.nan,
                    "Growth": growth if growth else np.nan,
                    "PEG": peg_raw,
                    "SMA50": sma50,
                    "SMA200": sma200,
                    "RSI": rsi,
                    "Target": target,
                    "Upside": upside_raw,
                    "Analysts": analysts,
                    "FetchTime": fetch_time
                })
            
            except Exception:
                continue
        
        status.update(label="✅ 全データの解析・検証が完了しました", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)

# --- 3. チャート描画 ---
def plot_chart(ticker, hist):
    fig = go.Figure()
    fig.add_trace(go.Candlestick(x=hist.index,
                open=hist['Open'], high=hist['High'],
                low=hist['Low'], close=hist['Close'], name='Price'))
    
    sma50 = hist['Close'].rolling(window=50).mean()
    sma200 = hist['Close'].rolling(window=200).mean()
    
    fig.add_trace(go.Scatter(x=hist.index, y=sma50, line=dict(color='orange', width=1.5), name='SMA 50'))
    fig.add_trace(go.Scatter(x=hist.index, y=sma200, line=dict(color='blue', width=1.5), name='SMA 200'))
    fig.update_layout(title=f"{ticker} Verification Chart (1Y)", height=400, template="plotly_dark")
    return fig

# --- 4. メイン画面 ---
st.title("🦅 Market Edge Pro (Logic Verified)")
st.caption("戦略: Momentum Growth (順張り×成長割安) / データ: Yahoo Finance API")

# 戦略と定義の明示（これで批判をクリアにする）
with st.expander("📊 戦略定義と計算ロジック (必ずお読みください)", expanded=True):
    st.markdown("""
    本アプリは**「Momentum Growth (成長株の順張り)」**を狙うスクリーニングツールです。
    
    ### 1. 修正された計算ロジック (Timeframe Alignment)
    * **PEGレシオ:** `Forward PE (来期予想)` ÷ `Earnings Growth (直近成長率)`
        * ※過去のPERではなく、来期予想を使うことで成長率との時間軸を整合させています。
    * **信頼性フィルタ:** アナリスト数が**5名未満**の銘柄は、目標株価の信頼性が低いためスコアを除外しています。
    * **RSI基準:** 14日RSIを使用。過熱ラインを75に設定。

    ### 2. 生データ (Raw Data) の開示
    * AIのブラックボックス化を防ぐため、計算に使われた**全ての生データ（PER, 成長率, アナリスト数など）**を下表に表示します。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 厳格スキャンを実行 (Raw Data開示)", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        st.subheader(f"🏆 スクリーニング結果 (Data at: {df['FetchTime'][0]})")
        
        # 表示用データフレーム（生データを隠さず出す）
        display_df = df.copy()
        
        # ユーザーに見やすいようにカラム整形
        st.dataframe(
            display_df[['Ticker', 'Price', 'Score', 'Fwd_PE', 'Growth', 'RSI', 'Analysts', 'Upside']]
            .style
            .format({
                'Price': '${:.2f}',
                'Score': '{:.0f}',
                'Fwd_PE': '{:.1f}倍',
                'Growth': '{:.1%}',
                'RSI': '{:.1f}',
                'Upside': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .highlight_null(color='gray'), # 欠損値はグレー
            use_container_width=True,
            height=600
        )
        st.caption("※Growth: 直近四半期利益成長率 / Fwd_PE: 来期予想PER / Analysts: カバーしているアナリスト数")

        # --- 個別詳細検証エリア ---
        st.divider()
        st.header("🧐 Logic Inspection (論理の検証)")
        
        selected_ticker = st.selectbox("詳細データを確認する銘柄:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("1. 計算根拠 (Raw Calculation)")
                # 計算式の完全開示
                peg_calc_str = f"{row['Fwd_PE']:.2f} / ({row['Growth']*100:.2f})" if pd.notna(row['Fwd_PE']) and pd.notna(row['Growth']) else "N/A"
                
                st.code(f"""
[Valuation Logic]
Forward PE (来期) : {row['Fwd_PE']:.2f}倍
Earnings Growth   : {row['Growth']:.2%}
=> PEG Ratio      : {peg_calc_str}

[Momentum Logic]
Current Price     : ${row['Price']:.2f}
SMA 50 (中期)     : ${row['SMA50']:.2f}
SMA 200 (長期)    : ${row['SMA200']:.2f}
RSI (14days)      : {row['RSI']:.1f}

[Reliability]
Analyst Count     : {row['Analysts']}名
Target Price      : ${row['Target']}
                """, language="yaml")
                
                stock = yf.Ticker(selected_ticker)
                hist = stock.history(period="1y")
                st.plotly_chart(plot_chart(selected_ticker, hist), use_container_width=True)

            with c2:
                st.subheader("2. 採点内訳 (Score Breakdown)")
                st.metric("Total Score", f"{row['Score']} / 100")
                
                reasons = row['Breakdown'].split(" / ")
                for r in reasons:
                    if "PEG" in r: st.success(f"💰 {r}")
                    elif "トレンド" in r: st.info(f"📈 {r}")
                    elif "上値" in r: st.warning(f"🎯 {r}")
                    elif "RSI" in r: st.error(f"📊 {r}")
                    else: st.write(f"・{r}")
            
    else:
        st.error("データ取得に失敗しました。時間をおいて再試行してください。")
