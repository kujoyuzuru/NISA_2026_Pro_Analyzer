import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta

# --- 1. アプリ設定 ---
st.set_page_config(page_title="Market Edge Pro - Robust Quant", page_icon="🦅", layout="wide")

# --- 2. データ取得・分析ロジック ---
@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M')
    
    with st.status("🦅 データ取得・定量的採点プロセス実行中...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"Processing... {ticker} ({i+1}/{total})")
            
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
                    peg_type = "Official"
                elif fwd_pe is not None and growth is not None and growth > 0:
                    peg_val = fwd_pe / (growth * 100)
                    peg_type = "Proxy"
                
                # 2. Trend (SMA)
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
                
                # 3. Consensus (Spread定義: (High-Low)/Mean)
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = np.nan
                spread_val = 0.0
                
                if target_mean and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low and target_mean > 0:
                        spread_val = (target_high - target_low) / target_mean

                # --- B. スコアリング (堅牢化モデル) ---
                score = 0
                breakdown = []

                # 1. Valuation (PEG) - Max 30
                peg_weight = 0.5 if peg_type == "Proxy" else 1.0
                
                if pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    final_points = int(base_points * peg_weight)
                    
                    if final_points > 0:
                        type_label = "Weight 0.5" if peg_type == "Proxy" else "Weight 1.0"
                        score += final_points
                        breakdown.append(f"PEG {peg_val:.2f} ({type_label}): +{final_points}")
                else:
                    breakdown.append("PEG算出不可: 0")

                # 2. Trend (SMA) - Max 30
                trend_str = "Range/Down"
                if price > sma50 > sma200:
                    score += 30
                    trend_str = "📈 Perfect Order"
                    breakdown.append("Trend (P-Order): +30")
                elif price < sma50:
                    trend_str = "📉 Downtrend"
                    breakdown.append("Trend (Below SMA50): 0")

                # 3. Upside (Discount Model) - Max 20
                # Critic修正: Spreadが100%を超えても破綻しないよう、係数を0.0でClipする
                if analysts >= 5:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        # 割引係数: 0.0 〜 1.0 の範囲に収める (Clamping)
                        discount_factor = max(0.0, 1.0 - spread_val)
                        final_upside = int(base_upside * discount_factor)
                        
                        score += final_upside
                        # 内訳表示も正確に
                        breakdown.append(f"Upside {upside_val:.1%} (Factor {discount_factor:.2f}): +{final_upside}")
                else:
                     breakdown.append(f"Low Coverage ({analysts}): 0")

                # 4. RSI - Max 20
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and "Perfect" in trend_str:
                    score += 20
                    breakdown.append("RSI Dip (40-60): +20")
                elif rsi > 75:
                    score -= 10
                    breakdown.append("RSI Overbought (>75): -10")

                # Grade
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
        
        status.update(label="✅ 計算完了 (Calculation Complete)", state="complete", expanded=False)
    
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
    fig.update_layout(title=f"{ticker} 1Y Chart", height=400, template="plotly_dark")
    return fig

# --- 4. メイン画面 ---
st.title("🦅 Market Edge Pro (Robust Quant)")
st.caption("定義された数理モデルと検証プロトコルに基づくスクリーニング")

# ★検証プロトコル（レギュレーション）の固定
with st.expander("📜 Verification Protocol (検証用運用規定)", expanded=True):
    st.markdown("""
    本ツールの有効性を検証する場合、以下の**「標準プロトコル」**に従ってください。
    都合の良い抽出を防ぐため、ルールを固定します。
    
    | 項目 | 規定内容 |
    | :--- | :--- |
    | **エントリー** | 抽出日の**翌営業日 始値 (Open)** |
    | **対象銘柄** | スコア上位 3〜5銘柄 (Sランク優先) |
    | **リバランス** | **1ヶ月後** の始値で売却・入れ替え |
    | **ベンチマーク** | 同期間の **NASDAQ100 (QQQ)** または **S&P500 (VOO)** |
    | **コスト考慮** | 売買手数料・税金は簡易的に **-1.0%** として計算すること |
    """)

# ★数理モデルの定義（修正版）
with st.expander("📊 Mathematical Model (数理定義)", expanded=False):
    st.markdown("""
    * **Spread Discount (不確実性割引):**
        * `Factor = max(0.0, 1.0 - Spread)`
        * ※Spreadが100%を超える場合、係数は0.0（価値ゼロ）となりマイナスにはなりません。
    * **Analyst Coverage:**
        * `n < 5` の場合、コンセンサススコアは一律 0点。
    * **Proxy Weight:**
        * PEGがProxy（簡易計算）の場合、加点幅を一律 `x 0.5` に減額。
    """)

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if st.button("🔍 データ取得・定量的スキャン実行", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        df = df.sort_values('Score', ascending=False).reset_index(drop=True)
        
        # 検証用CSV
        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 検証用データをCSVで保存 (Save for Backtest)",
            data=csv,
            file_name=f'quant_scan_{datetime.now().strftime("%Y%m%d")}.csv',
            mime='text/csv',
        )
        
        st.subheader(f"🏆 Screening Results (Data at: {df['FetchTime'][0]})")
        
        st.dataframe(
            df[['Ticker', 'Price', 'Score', 'PEG_Val', 'PEG_Type', 'Spread', 'Upside']]
            .style
            .format({
                'Price': '${:.2f}',
                'Score': '{:.0f}',
                'PEG_Val': '{:.2f}',
                'Spread': '{:.1%}', 
                'Upside': '{:.1%}'
            })
            .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
            .background_gradient(subset=['Spread'], cmap='Reds', vmin=0.0, vmax=1.0)
            .highlight_null(color='gray'),
            use_container_width=True,
            height=600
        )
        st.caption("※Spread > 100% の場合、Upside評価は0点となります（係数0.0）")

        # --- 詳細検証エリア ---
        st.divider()
        st.header("🧐 Factor Inspection")
        
        selected_ticker = st.selectbox("Select Ticker for Inspection:", df['Ticker'].tolist())
        
        if selected_ticker:
            row = df[df['Ticker'] == selected_ticker].iloc[0]
            
            # Spread係数の計算（表示用）
            discount_factor = max(0.0, 1.0 - row['Spread'])
            
            c1, c2 = st.columns([1, 1])
            
            with c1:
                st.subheader("1. Quant Metrics")
                st.code(f"""
[Uncertainty Model]
Spread (H-L/Mean): {row['Spread']:.2%}
Discount Factor  : {discount_factor:.2f} (Min 0.0)

[Valuation Logic]
PEG Type         : {row['PEG_Type']}
Applied Weight   : {"0.5" if row['PEG_Type']=="Proxy" else "1.0"}
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
                    elif "Trend" in r: st.info(f"📈 {r}")
                    elif "Upside" in r: st.warning(f"🎯 {r}") 
                    elif "RSI" in r: st.error(f"📊 {r}")
                    else: st.write(f"・{r}")
            
    else:
        st.error("Data fetch failed.")
