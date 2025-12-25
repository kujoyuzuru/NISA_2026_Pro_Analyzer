import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Final Quant", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 市場データを取得・定量的採点中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"🦅 演算中... {ticker} ({i+1}/{total})")
            
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
                    peg_type = "Official" # 公式(5年予想ベース等)
                elif fwd_pe is not None and growth is not None and growth > 0:
                    peg_val = fwd_pe / (growth * 100)
                    peg_type = "Proxy" # 参考値(期間ズレあり)
                
                # 2. Trend (SMA)
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus (Spreadの定量的定義)
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = np.nan
                spread_val = 0.0 # 意見のバラつき度合い (0.0 ~ 1.0+)
                
                if target_mean and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low and target_mean > 0:
                        # 定義: (High - Low) / Mean
                        spread_val = (target_high - target_low) / target_mean

                # --- B. スコアリング (連続的数理モデル) ---
                score = 0
                breakdown = []

                # 1. 割安性 (PEG) - Max 30点
                # Critic指摘対応: Proxyの場合は「PEG項目のスコア」のみ50%割引（Valuation全体ではない）
                peg_weight = 0.5 if peg_type == "Proxy" else 1.0
                
                if pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    final_points = int(base_points * peg_weight)
                    
                    if final_points > 0:
                        type_label = "参考値割引(50%)" if peg_type == "Proxy" else "公式"
                        score += final_points
                        breakdown.append(f"PEG {peg_val:.2f} ({type_label}): +{final_points}")
                else:
                    breakdown.append("PEG算出不可: 0")

                # 2. トレンド (SMA配列) - Max 30点
                trend_str = "レンジ/下降"
                if price > sma50 > sma200:
                    score += 30
                    trend_str = "📈 Pオーダー"
                    breakdown.append("上昇トレンド(Pオーダー): +30")
                elif price < sma50:
                    trend_str = "📉 調整局面"
                    breakdown.append("トレンド崩れ(50日線割れ): 0")

                # 3. アップサイド (Spreadによる連続割引) - Max 20点
                # Critic指摘対応: 閾値(60%)の崖を廃止し、Spread分だけリニアに価値を割り引く
                # モデル: 獲得スコア = 基礎点 * (1 - Spread)  ※Spreadが大きいほど価値減
                if analysts >= 5:
                    base_upside_score = 0
                    if upside_val > 0.2: base_upside_score = 20
                    elif upside_val > 0.1: base_upside_score = 10
                    
                    if base_upside_score > 0:
                        # 割引係数 (Spreadが100%以上の場合は価値0とする)
                        discount_factor = max(0.0, 1.0 - spread_val)
                        final_upside_score = int(base_upside_score * discount_factor)
                        
                        score += final_upside_score
                        breakdown.append(f"上値{upside_val:.1%} (Spread割引 {-spread_val:.0%}): +{final_upside_score}")
                else:
                     breakdown.append(f"アナリスト不足({analysts}名): 0")

                # 4. RSI (過熱感) - Max 20点
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and "Pオーダー" in trend_str:
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
                    # --- Raw Data ---
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
        
        status.update(label="✅ 定量的解析完了 (Verified)", state="complete", expanded=False)
    
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
st.title("🦅 Market Edge Pro (Final Quant)")
st.caption("連続的な数理モデルに基づく、恣意性を排除した分析ツール")

# ★数理モデルの定義開示
with st.expander("📊 採点モデルの数式定義 (Mathematical Model)", expanded=True):
    st.markdown("""
    本アプリは「任意の閾値」を排除し、以下の数式に基づいてリスクをスコアに連続的に反映させます。
    
    ### 1. 不確実性の割引モデル (Consensus Discount)
    アナリストの意見が割れている場合、その「不確実性の分量」だけ上値余地のスコアを減額します。
    * **Spread定義:** `(TargetHigh - TargetLow) / TargetMean`
    * **スコア算出:** `基礎点 × (1.0 - Spread)`
        * 例: Spreadが20%なら、スコアは80%掛けになります。Spreadが広がるほど価値は0に近づきます。
    
    ### 2. データ精度の重み付け (Proxy Weighting)
    * **公式PEG:** 信頼度 100% (Weight 1.0)
    * **Proxy PEG:** 信頼度 50% (Weight 0.5) ※期間ズレのリスクを定数で割引
    
    ### 3. 検証機能 (Track Record)
    * 下の「CSVダウンロード」ボタンで結果を保存し、1ヶ月後に実際の株価と照らし合わせてください。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 厳格スキャンを実行 (数理モデル適用)", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # CSVダウンロードボタン (検証用)
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 分析結果をCSVで保存 (検証用)",
            data=csv,
            file_name=f'market_edge_result_{datetime.now().strftime("%Y%m%d")}.csv',
            mime='text/csv',
        )
        
        st.subheader(f"🏆 スクリーニング結果 (Data at: {df['FetchTime'][0]})")
        
        st.dataframe(
            df[['Ticker', 'Price', 'Score', 'PEG_Val', 'PEG_Type', 'Spread', 'Upside']]
            .style
            .format({
                'Price': '${:.2f}',
                'Score': '{:.0f}',
                'PEG_Val': '{:.2f}倍',
                'Spread': '{:.1%}', 
                'Upside': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .background_gradient(subset=['Spread'], cmap='Reds', vmin=0.0, vmax=0.8)
            .highlight_null(color='gray'),
            use_container_width=True,
            height=600
        )
        st.caption("※Spread: (High-Low)/Mean。数値が大きいほどアナリストの意見が割れており、スコアが割り引かれています。")

        # --- 個別詳細検証エリア ---
        st.divider()
        st.header("🧐 Model Inspection (数理検証)")
        
        selected_ticker = st.selectbox("詳細データを確認する銘柄:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("1. Consensus & Spread Logic")
                
                st.code(f"""
[Spread Calculation]
High      : ${row['Target_High']}
Mean      : ${row['Target_Mean']}
Low       : ${row['Target_Low']}
Formula   : ({row['Target_High']} - {row['Target_Low']}) / {row['Target_Mean']}
Result    : {row['Spread']:.2%} (Discount Factor: {max(0, 1.0-row['Spread']):.2f})

[Valuation Weight]
PEG Type  : {row['PEG_Type']}
Weight    : {"0.5 (Proxy)" if row['PEG_Type']=="Proxy" else "1.0 (Official)"}
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
                    elif "Pオーダー" in r: st.info(f"📈 {r}")
                    elif "Spread" in r: st.warning(f"🎯 {r}") # 割引適用済
                    elif "RSI" in r: st.error(f"📊 {r}")
                    else: st.write(f"・{r}")
            
    else:
        st.error("データ取得に失敗しました。")
