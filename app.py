import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime

# --- 1. アプリの基本設定 ---
st.set_page_config(
    page_title="最強の米国株AI診断",
    page_icon="🇺🇸",
    layout="wide" # スマホでも横幅いっぱいに使う設定
)

# --- 2. デザイン調整 (スマホで見やすくする魔法) ---
st.markdown("""
    <style>
    /* ボタンを大きく押しやすく */
    .stButton>button {
        width: 100%;
        font-size: 18px;
        font-weight: bold;
        padding: 15px;
        border-radius: 10px;
        background: linear-gradient(to right, #ff416c, #ff4b2b); /* 情熱の赤グラデーション */
        color: white;
        border: none;
    }
    .stButton>button:hover {
        opacity: 0.8;
        color: white;
    }
    /* テーブルの文字サイズ調整 */
    .dataframe {
        font-size: 14px !important;
    }
    </style>
    """, unsafe_allow_html=True)

# --- 3. 分析対象リスト (NASDAQ主要銘柄) ---
TICKERS = [
    "NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", # MAG7
    "AVGO", "AMD", "QCOM", "INTC", "TXN", "MU", "AMAT", "LRCX", "ADI", "MRVL", "KLAC", "ARM", "SMCI", # 半導体
    "ADBE", "CRM", "NFLX", "ORCL", "CSCO", "INTU", "NOW", "UBER", "ABNB", "PANW", "SNPS", "CDNS", "CRWD", "PLTR", # ソフトウェア
    "AMGN", "VRTX", "GILD", "REGN", "ISRG", "MDLZ", # バイオ・ヘルス
    "COST", "PEP", "SBUX", "TMUS", "CMCSA", "BKNG", "MAR", "LULU", "CSX" # 消費・その他
]

# --- 4. プロの分析ロジック (裏側の頭脳) ---
def analyze_stock(ticker):
    stock = yf.Ticker(ticker)
    try:
        info = stock.info
        current_price = info.get('currentPrice', 0)
        if current_price == 0: return None

        # データの取得
        rev_growth = info.get('revenueGrowth', 0)     # 売上成長率
        profit_margin = info.get('profitMargins', 0)  # 利益率
        avg_volume = info.get('averageVolume', 0)
        current_volume = info.get('volume', 0)
        
        # --- スコアリング計算 ---
        score = 0
        # 1. 成長性 (Growth)
        if rev_growth and rev_growth > 0.2: score += 30      # +20%以上なら凄い
        elif rev_growth and rev_growth > 0.1: score += 15    # +10%以上ならOK
        
        # 2. 収益性 (Profit)
        if profit_margin and profit_margin > 0.2: score += 20 # 利益率20%以上なら優秀
        
        # 3. 大口の動き (Volume)
        vol_ratio = 0
        if avg_volume > 0: vol_ratio = current_volume / avg_volume
        if vol_ratio > 1.2: score += 20  # 普段より1.2倍以上買われていたら加点
        
        # 4. テクニカル (RSI)
        hist = stock.history(period="3mo")
        rsi = 50
        if not hist.empty:
            delta = hist['Close'].diff()
            gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
            loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
            rs = gain / loss
            if loss.iloc[-1] != 0:
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
            
            # RSIの判定
            if 40 <= rsi <= 60: score += 30 # 押し目買いのチャンス
            if rsi > 80: score -= 20        # 買われすぎ（危険）

        # 総合判定シグナル
        signal = "様子見"
        if score >= 80: signal = "🔥最強買い"
        elif score >= 60: signal = "✅買い"
        elif score <= 20: signal = "⚠️売り"

        # 結果を返す
        return {
            "Ticker": ticker,
            "Name": info.get('shortName', ticker)[:10], # 社名は短く
            "Price": current_price,
            "Score": int(score),
            "Signal": signal,
            "Growth": rev_growth if rev_growth else 0,
            "Margin": profit_margin if profit_margin else 0,
            "VolRatio": vol_ratio,
            "RSI": rsi
        }
    except:
        return None

# --- 5. アプリ画面の構築 ---

# タイトルエリア
st.title("🇺🇸 米国株 AIスカウター")
st.markdown(f"**{datetime.now().strftime('%Y年%m月%d日')}** 時点の市場をAIが完全分析！")

# 免責事項（アコーディオンでスッキリ収納）
with st.expander("ℹ️ はじめにお読みください（利用規約）"):
    st.caption("""
    このアプリは投資の参考情報を提供するものであり、利益を保証するものではありません。
    最終的な投資判断はご自身の責任で行ってください。
    """)
    agree = st.checkbox("上記に同意して分析を始める")

if agree:
    st.write("") # 余白
    st.info("👇 下のボタンを押すと、NASDAQの主要銘柄を一斉スキャンします")
    
    # 実行ボタン
    if st.button("🚀 今すぐAI分析を開始する"):
        
        # 進捗バーの表示
        progress_text = "米国市場のデータを収集中... 0%"
        my_bar = st.progress(0, text=progress_text)
        
        results = []
        total = len(TICKERS)
        
        # 全銘柄をループ分析
        for i, ticker in enumerate(TICKERS):
            data = analyze_stock(ticker)
            if data:
                results.append(data)
            
            # バーを更新
            percent = int((i + 1) / total * 100)
            my_bar.progress(percent, text=f"🔍 分析中... {ticker} ({percent}%)")
            
        my_bar.empty() # バーを消す
        
        # --- 結果表示エリア ---
        if results:
            df = pd.DataFrame(results)
            
            # スコア順に並び替え
            df_sorted = df.sort_values('Score', ascending=False).reset_index(drop=True)
            df_sorted.index += 1 # 順位を1から開始
            
            st.balloons() # 完了時に風船を飛ばす演出！
            st.success(f"🎉 分析完了！ 今日の「買い」銘柄はこれだ！")
            
            # 日本語のカラム名に変換
            df_display = df_sorted.rename(columns={
                "Ticker": "コード",
                "Name": "社名",
                "Price": "株価($)",
                "Score": "総合点",
                "Signal": "AI判定",
                "Growth": "📈成長率",
                "Margin": "💰利益率",
                "VolRatio": "🐋大口",
                "RSI": "🔥過熱感"
            })

            # データフレームの表示（色付き）
            st.dataframe(
                df_display.style
                .format({
                    '株価($)': '${:.2f}',
                    '📈成長率': '{:.1%}',
                    '💰利益率': '{:.1%}',
                    '🐋大口': '{:.1f}倍',
                    '🔥過熱感': '{:.1f}'
                })
                # スコアが高いほど濃い緑にするヒートマップ設定
                .background_gradient(subset=['総合点'], cmap='RdYlGn', vmin=0, vmax=100),
                use_container_width=True, # スマホの幅に合わせる
                height=600
            )
            
            # 凡例ガイド
            st.markdown("### 💡 データの見方")
            col1, col2 = st.columns(2)
            with col1:
                st.info("""
                **🏆 総合点 (Score)**
                * **80点〜**: 迷わず買い！最強銘柄
                * **60点〜**: チャンスありの優良株
                """)
            with col2:
                st.warning("""
                **🔥 過熱感 (RSI)**
                * **40-60**: ちょうどいい買い時
                * **80以上**: 買われすぎ（高値掴み注意）
                """)

else:
    st.warning("☝️ 分析を始めるには、上のチェックボックスにチェックを入れてください。")
