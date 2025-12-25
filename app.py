import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta

# --- 1. アプリ設定とキャッシュ機能 ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

# APIコールの回数を減らして高速化する（12時間キャッシュ）
@st.cache_data(ttl=43200)
def fetch_stock_data(tickers):
    data_list = []
    
    # 進行状況バー
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    for i, ticker in enumerate(tickers):
        status_text.text(f"🦅 機関投資家データを解析中... {ticker}")
        try:
            stock = yf.Ticker(ticker)
            info = stock.info
            
            # --- A. ファンダメンタルズ分析 ---
            price = info.get('currentPrice', 0)
            if price == 0: continue
            
            # PEGレシオ（成長率を加味した割安度）
            pe_ratio = info.get('trailingPE', 0)
            growth_rate = info.get('earningsGrowth', 0) # 利益成長率
            peg = 999
            if growth_rate and growth_rate > 0:
                peg = pe_ratio / (growth_rate * 100) # 簡易PEG計算
            
            # アナリストターゲット
            target_price = info.get('targetMeanPrice', price)
            upside = (target_price - price) / price if target_price else 0

            # --- B. テクニカル分析 (過去1年分取得) ---
            hist = stock.history(period="1y")
            
            # 移動平均線
            sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
            sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]
            
            # トレンド判定 (パーフェクトオーダー)
            trend_score = 0
            trend_status = "レンジ"
            if price > sma50 > sma200:
                trend_score = 30
                trend_status = "📈上昇トレンド"
            elif price < sma50 < sma200:
                trend_score = -30
                trend_status = "📉下降トレンド"
            
            # RSI (14日)
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            rsi = 100 - (100 / (1 + rs)).iloc[-1]

            # --- C. 総合スコアリング (満点100) ---
            score = 0
            reasons = []

            # 1. 割安性 (Max 30点)
            if 0 < peg < 1.0: 
                score += 30
                reasons.append("★超割安(PEG<1)")
            elif 0 < peg < 1.5: 
                score += 20
                reasons.append("割安(PEG<1.5)")
            elif 0 < peg < 2.0:
                score += 10

            # 2. アナリスト期待値 (Max 20点)
            if upside > 0.3: # 30%以上の上値余地
                score += 20
                reasons.append(f"上値余地+{int(upside*100)}%")
            elif upside > 0.1:
                score += 10
            
            # 3. テクニカル強度 (Max 30点)
            score += max(0, trend_score) # 上昇トレンドなら加点
            if trend_score > 0: reasons.append("トレンド良")

            # 4. 需給・モメンタム (Max 20点)
            if 40 <= rsi <= 60 and trend_score >= 0:
                score += 20
                reasons.append("押し目好機")
            elif rsi < 30:
                score += 10
                reasons.append("売られすぎ反発狙い")
            elif rsi > 80:
                score -= 10
                reasons.append("⚠️過熱気味")

            # 最終ランク付け
            grade = "C"
            if score >= 85: grade = "S"
            elif score >= 70: grade = "A"
            elif score >= 50: grade = "B"

            data_list.append({
                "Ticker": ticker,
                "Name": info.get('shortName', ticker)[:10],
                "Price": price,
                "Grade": grade,
                "Score": int(score),
                "Upside": upside,
                "PEG": peg if peg != 999 else np.nan,
                "Trend": trend_status,
                "RSI": rsi,
                "Reason": " / ".join(reasons) if reasons else "特になし"
            })
            
        except Exception as e:
            continue
        
        # バー更新
        progress_bar.progress((i + 1) / len(tickers))
    
    status_text.empty()
    progress_bar.empty()
    return pd.DataFrame(data_list)

# --- 2. メイン画面デザイン ---
st.markdown("""
    <style>
    .big-font { font-size:20px !important; font-weight:bold; }
    .stMetric { background-color: #0e1117; border: 1px solid #303030; padding: 10px; border-radius: 5px; }
    </style>
""", unsafe_allow_html=True)

st.title("🦅 Market Edge Pro")
st.caption("機関投資家視点の「トレンド × 割安 × コンセンサス」複合分析")

with st.expander("📊 分析ロジックの開示（透明性）", expanded=False):
    st.markdown("""
    本アプリは以下の「3つの柱」で銘柄を厳しく採点します。
    1. **Valuation (PEGレシオ):** 単なるPERではなく、成長率に見合った株価か？(PEG 1.0倍以下はS級)
    2. **Trend (SMA配列):** 50日線が200日線の上にある「パーフェクトオーダー」か？
    3. **Consensus (Upside):** ウォール街のアナリスト目標株価とどれだけ乖離があるか？
    """)

# 対象銘柄（NASDAQ100主要 + 人気銘柄）
TARGETS = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA",
    "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "MSTR",
    "CRWD", "PANW", "ZS", "NET", "NOW", "DDOG",
    "LLY", "NVO", "VRTX", "ISRG", # ヘルスケア強者
    "COST", "WMT", "TGT", # 小売
]

if st.button("🦅 マーケットをスキャン開始 (Real-time)", type="primary"):
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        # Sランク、Aランクの抽出
        s_rank = df[df['Grade'] == 'S']
        a_rank = df[df['Grade'] == 'A']
        
        # --- ダッシュボード表示 ---
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("Sランク (即戦力)", f"{len(s_rank)} 銘柄", help="スコア85点以上の最強銘柄")
        with col2:
            st.metric("Aランク (監視)", f"{len(a_rank)} 銘柄", help="スコア70点以上の優良銘柄")
        with col3:
            market_trend = "強気" if len(df[df['Trend'].str.contains("上昇")]) > len(df)/2 else "弱気/調整"
            st.metric("市場トレンド", market_trend)

        st.markdown("### 🏆 推奨銘柄ランキング (S/A Grade)")
        
        # 表示用データフレームの整形
        df_show = df.sort_values('Score', ascending=False).reset_index(drop=True)
        df_show.index += 1
        
        # カラム名の日本語化と整理
        df_display = df_show[['Ticker', 'Name', 'Price', 'Grade', 'Score', 'Upside', 'PEG', 'Trend', 'Reason']].copy()
        df_display.columns = ['コード', '社名', '株価($)', '評価', 'スコア', '上値余地', 'PEG(割安)', 'トレンド', 'AIの根拠']
        
        # データフレーム表示（高度なスタイル）
        st.dataframe(
            df_display.style
            .format({
                '株価($)': '${:.2f}',
                'スコア': '{:.0f}点',
                '上値余地': '+{:.1%}',
                'PEG(割安)': '{:.2f}倍',
            })
            .applymap(lambda v: 'color: #00ff00; font-weight: bold;' if v == 'S' else '', subset=['評価'])
            .background_gradient(subset=['上値余地'], cmap='Greens', vmin=0, vmax=0.5)
            .background_gradient(subset=['PEG(割安)'], cmap='Reds_r', vmin=0.5, vmax=3.0), # PEGは低いほうが赤（熱い）
            height=800,
            use_container_width=True
        )
    else:
        st.error("データ取得に失敗しました。時間をおいて再度お試しください。")
