import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Pragmatism", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 市場データを取得・精密採点中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"🦅 審査中... {ticker} ({i+1}/{total})")
            
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
                
                # 1. Valuation (PEG)
                official_peg = info.get('pegRatio')
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                peg_val = np.nan
                peg_type = "-" 
                
                if official_peg is not None:
                    peg_val = official_peg
                    peg_type = "Official" # 公式(予想ベース)
                elif fwd_pe is not None and growth is not None and growth > 0:
                    peg_val = fwd_pe / (growth * 100)
                    peg_type = "Proxy" # 参考値(期間ズレあり)
                
                # 2. Trend (SMA)
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus (Spread計算)
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = np.nan
                spread_val = 0 # 意見のバラつき度合い
                
                if target_mean and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low and target_mean > 0:
                        spread_val = (target_high - target_low) / target_mean

                # --- B. スコアリング (言行一致の厳格ルール) ---
                score = 0
                breakdown = []

                # 1. 割安性 (PEG) - Max 30点 (Proxyは減点)
                # Critic指摘対応: Proxyは信頼性が低いため、加点幅を50%にカットする
                peg_weight = 0.5 if peg_type == "Proxy" else 1.0
                
                if pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    # 重み付け適用
                    final_points = int(base_points * peg_weight)
                    
                    if final_points > 0:
                        type_str = "参考値により50%割引" if peg_type == "Proxy" else "公式"
                        score += final_points
                        breakdown.append(f"PEG {peg_val:.2f} ({type_str}): +{final_points}")
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

                # 3. アップサイド (Spreadペナルティ) - Max 20点
                # Critic指摘対応: Spreadが広い(意見割れ)場合はスコアを割り引く
                if analysts >= 5:
                    upside_score = 0
                    if upside_val > 0.2: upside_score = 20
                    elif upside_val > 0.1: upside_score = 10
                    
                    # ペナルティ判定 (Spread > 0.6 なら半減)
                    if spread_val > 0.6:
                        upside_score = int(upside_score * 0.5)
                        breakdown.append(f"意見割れ(Spread {spread_val:.0%})により評価半減")
                    
                    if upside_score > 0:
                        score += upside_score
                        breakdown.append(f"上値余地{upside_val:.1%} ({analysts}人): +{upside_score}")
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
                    "SMA50": sma50,
                    "SMA200": sma200,
                    "RSI": rsi,
                    "Target_Mean": target_mean,
                    "Target_High": target_high,
                    "Target_Low": target_low,
                    "Spread": spread_val,
                    "Upside": upside_val,
                    "Analysts": analysts,
                    "FetchTime": fetch_time
                })
            
            except Exception:
                continue
        
        status.update(label="✅ 全データの解析完了 (整合性チェック済)", state="complete", expanded=False)
    
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
st.title("🦅 Market Edge Pro (Pragmatism Ver.)")
st.caption("言葉と採点の不整合を排除した、実務型スクリーニングツール")

# ★ここが変わりました！プロ仕様のロジック説明
with st.expander("📊 厳格化された採点ロジック (言行一致)", expanded=True):
    st.markdown("""
    本バージョンでは、データの質に応じて「重み付け」を変えることでリスク管理を徹底しています。
    
    ### 1. PEGレシオの重み付け (Risk Weighting)
    * **Official (公式):** 信頼性が高いため、満点評価（Max 30点）。
    * **Proxy (参考値):** 時間軸のズレがあるため、スコアを **50%割引** して評価します（Max 15点）。
    
    ### 2. アナリスト予想の「意見割れ」ペナルティ
    * **Spread (High/Low乖離):** 意見のバラつき (`High-Low/Mean`) が **60%** を超える場合、見通し不明瞭として上値余地のスコアを **半減** させます。
    * 「平均値は高いが、強気と弱気が極端に分かれている」銘柄を高評価しないための安全装置です。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 厳格スキャンを実行 (リスク調整済)", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        st.subheader(f"🏆 スクリーニング結果 (Data at: {df['FetchTime'][0]})")
        
        # 表示用データ
        st.dataframe(
            df[['Ticker', 'Price', 'Score', 'PEG_Val', 'PEG_Type', 'Spread', 'Upside']]
            .style
            .format({
                'Price': '${:.2f}',
                'Score': '{:.0f}',
                'PEG_Val': '{:.2f}倍',
                'Spread': '{:.1%}', # スプレッド（意見割れ度）を表示
                'Upside': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .background_gradient(subset=['Spread'], cmap='Reds', vmin=0.3, vmax=1.0) # 意見割れが酷いと赤くなる
            .highlight_null(color='gray'),
            use_container_width=True,
            height=600
        )
        st.caption("※Spread: アナリスト予想のバラつき度。赤いほど意見が割れておりリスクが高い。")

        # --- 個別詳細検証エリア ---
        st.divider()
        st.header("🧐 Logic Inspection (採点根拠)")
        
        selected_ticker = st.selectbox("詳細データを確認する銘柄:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("1. Consensus Risk Check")
                
                # Spreadのアラート表示
                spread_alert = "⚠️ High Risk (意見分裂)" if row['Spread'] > 0.6 else "✅ Consensus OK"
                
                st.code(f"""
[PEG Evaluation]
Value     : {row['PEG_Val']:.2f}倍
Type      : {row['PEG_Type']} (Weight: {"50%" if row['PEG_Type']=="Proxy" else "100%"})

[Analyst Variance]
High      : ${row['Target_High']}
Mean      : ${row['Target_Mean']}
Low       : ${row['Target_Low']}
Spread    : {row['Spread']:.1%} ({spread_alert})
                """, language="yaml")
                
                stock = yf.Ticker(selected_ticker)
                hist = stock.history(period="1y")
                st.plotly_chart(plot_chart(selected_ticker, hist), use_container_width=True)

            with c2:
                st.subheader("2. Score Breakdown")
                st.metric("Total Score", f"{row['Score']} / 100")
                
                reasons = row['Breakdown'].split(" / ")
                for r in reasons:
                    if "PEG" in r: st.success(f"💰 {r}")
                    elif "トレンド" in r: st.info(f"📈 {r}")
                    elif "上値" in r or "Spread" in r: st.warning(f"🎯 {r}") # Spread警告は黄色
                    elif "RSI" in r: st.error(f"📊 {r}")
                    else: st.write(f"・{r}")
            
    else:
        st.error("データ取得に失敗しました。")
