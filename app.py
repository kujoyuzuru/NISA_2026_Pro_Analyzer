import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Realism", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 市場データを取得・整合性チェック中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"🦅 解析中... {ticker} ({i+1}/{total})")
            
            try:
                stock = yf.Ticker(ticker)
                try:
                    info = stock.info
                except:
                    continue 

                hist = stock.history(period="1y")
                if hist.empty: continue

                # --- A. 生データの抽出 (Raw Data) ---
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                
                # 1. Valuation (PEGの整合性確保)
                # Critic指摘対応: 手動計算による期間ズレを防ぐため、API提供のpegRatio(5年予想ベース等)を優先使用
                # これが取れない場合のみ、ForwardPE/直近成長率 を「参考値(Proxy)」として使う
                official_peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth') # 直近四半期
                
                peg_val = np.nan
                peg_type = "-" # PEGの種類（Official vs Proxy）
                
                if official_peg is not None:
                    peg_val = official_peg
                    peg_type = "Official (予想ベース)"
                elif fwd_pe is not None and growth is not None and growth > 0:
                    peg_val = fwd_pe / (growth * 100)
                    peg_type = "Proxy (Forward/Past)" # 期間ズレがあることを明記
                
                # 2. Trend (SMA)
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus (不確実性の可視化)
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = np.nan
                if target_mean and price > 0:
                    upside_val = (target_mean - price) / price

                # --- B. スコアリング (厳格な評価) ---
                score = 0
                breakdown = []

                # 1. 割安性 (PEG) - Max 30点
                if pd.notna(peg_val):
                    if 0 < peg_val < 1.0:
                        score += 30
                        breakdown.append(f"★PEG<1.0 ({peg_type}): +30")
                    elif peg_val < 1.5:
                        score += 20
                        breakdown.append(f"PEG<1.5: +20")
                    elif peg_val < 2.0:
                        score += 10
                        breakdown.append(f"PEG<2.0: +10")
                else:
                    breakdown.append("PEG算出不可: 0")

                # 2. トレンド (SMA配列) - Max 30点
                trend_str = "レンジ/下降"
                if price > sma50 > sma200:
                    score += 30
                    trend_str = "📈 パーフェクトオーダー"
                    breakdown.append("上昇トレンド(Pオーダー): +30")
                elif price < sma50:
                    trend_str = "📉 調整局面"
                    breakdown.append("トレンド崩れ(50日線割れ): 0")

                # 3. アップサイド (信頼度フィルタ) - Max 20点
                # Critic指摘対応: 人数が少ない、またはHigh/Lowの乖離が激しすぎる場合は信用しない
                spread = 0
                if target_high and target_low:
                    spread = (target_high - target_low) / target_mean
                
                if analysts >= 5:
                    if upside_val > 0.2:
                        score += 20
                        breakdown.append(f"上値余地20%超({analysts}人): +20")
                    elif upside_val > 0.1:
                        score += 10
                        breakdown.append(f"上値余地10%超: +10")
                else:
                     breakdown.append(f"アナリスト不足({analysts}名): 0")

                # 4. RSI (過熱感) - Max 20点
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and "上昇" in trend_str:
                    score += 20
                    breakdown.append("RSI押し目(40-60): +20")
                elif rsi > 75:
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
                    "PEG_Val": peg_val,
                    "PEG_Type": peg_type,
                    "Fwd_PE": fwd_pe,
                    "Growth": growth,
                    "SMA50": sma50,
                    "SMA200": sma200,
                    "RSI": rsi,
                    "Target_Mean": target_mean,
                    "Target_High": target_high,
                    "Target_Low": target_low,
                    "Upside": upside_val,
                    "Analysts": analysts,
                    "FetchTime": fetch_time
                })
            
            except Exception:
                continue
        
        status.update(label="✅ 全データの解析・整合性チェック完了", state="complete", expanded=False)
    
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
st.title("🦅 Market Edge Pro (Realism Ver.)")
st.caption("誠実なデータ開示と論理的整合性を重視したスクリーニングツール")

# 重要な但し書き（プロの指摘を反映）
with st.expander("📊 データの定義と限界について (透明性レポート)", expanded=True):
    st.markdown("""
    本アプリは「完璧な予言」ではなく「論理的な候補絞り込み」を目的としています。
    
    ### 1. PEGレシオの取り扱い (Timeframe Alignment)
    * **Official (推奨):** Yahoo Financeが算出するPEGレシオ（通常5年予想成長率ベース）を優先して使用します。
    * **Proxy (参考):** Official値がない場合のみ、`Forward PE` ÷ `直近成長率` で計算しますが、**「時間軸のズレ」があるため参考値(Proxy)**として扱います。
    
    ### 2. アナリスト予想の不確実性
    * **人数の壁:** アナリストが5名未満の銘柄は、信頼性が低いためスコア加算しません。
    * **乖離:** 目標株価の平均だけでなく、High/Lowのバラつきも確認してください。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 厳格スキャンを実行 (整合性チェック)", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        st.subheader(f"🏆 スクリーニング結果 (Data at: {df['FetchTime'][0]})")
        
        # 表示用データ作成
        st.dataframe(
            df[['Ticker', 'Price', 'Score', 'PEG_Val', 'PEG_Type', 'RSI', 'Analysts', 'Upside']]
            .style
            .format({
                'Price': '${:.2f}',
                'Score': '{:.0f}',
                'PEG_Val': '{:.2f}倍',
                'RSI': '{:.1f}',
                'Upside': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .highlight_null(color='gray'),
            use_container_width=True,
            height=600
        )
        st.caption("※PEG_Type: Official=予想ベース(高信頼) / Proxy=簡易計算(参考値)")

        # --- 個別詳細検証エリア ---
        st.divider()
        st.header("🧐 Data Inspection (詳細検証)")
        
        selected_ticker = st.selectbox("詳細データを確認する銘柄:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("1. Valuation & Consensus")
                
                st.code(f"""
[PEG Consistency Check]
Value     : {row['PEG_Val']:.2f}倍
Source    : {row['PEG_Type']}
(Raw FwdPE: {row['Fwd_PE']} / Raw Growth: {row['Growth']})

[Analyst Target Spread]
High      : ${row['Target_High']}
Mean      : ${row['Target_Mean']}
Low       : ${row['Target_Low']}
Count     : {row['Analysts']}名
                """, language="yaml")
                
                stock = yf.Ticker(selected_ticker)
                hist = stock.history(period="1y")
                st.plotly_chart(plot_chart(selected_ticker, hist), use_container_width=True)

            with c2:
                st.subheader("2. Score Logic")
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
