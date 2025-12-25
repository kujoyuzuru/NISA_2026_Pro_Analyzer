import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import hashlib

# --- 1. システム設定 ---
st.set_page_config(page_title="Market Edge Pro - Dashboard", page_icon="🦅", layout="wide")

# ファイル設定
HISTORY_FILE = "master_execution_log.csv"

# --- 2. 分析ロジック (詳細化) ---

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers):
    data_list = []
    
    with st.spinner("🦅 市場データを詳細分析中..."):
        for i, ticker in enumerate(tickers):
            try:
                stock = yf.Ticker(ticker)
                try: info = stock.info
                except: continue 

                hist = stock.history(period="6mo")
                if hist.empty: continue

                # --- 1. 基本データ ---
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                name = info.get('shortName', ticker)
                sector = info.get('sector', 'Unknown')
                
                # --- 2. 割安性 (Valuation) ---
                # PEGレシオなどを取得
                peg = info.get('pegRatio', np.nan)
                fwd_pe = info.get('forwardPE', np.nan)
                
                val_score = 0
                val_msg = "判断不能"
                if pd.notna(peg):
                    if peg < 1.0: 
                        val_score = 30
                        val_msg = "S (超割安)"
                    elif peg < 1.5: 
                        val_score = 20
                        val_msg = "A (割安)"
                    elif peg < 2.0: 
                        val_score = 10
                        val_msg = "B (適正)"
                    else: 
                        val_msg = "C (割高感)"
                
                # --- 3. トレンド (Trend) ---
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else price
                
                trend_score = 0
                trend_msg = "レンジ/下降"
                if price > sma50 > sma200:
                    trend_score = 30
                    trend_msg = "S (上昇トレンド)"
                elif price > sma50:
                    trend_score = 15
                    trend_msg = "A (短期上昇)"
                
                # --- 4. 機関投資家・コンセンサス (Consensus) ---
                target_mean = info.get('targetMeanPrice', 0)
                upside = (target_mean - price) / price if target_mean else 0
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                cons_score = 0
                if upside > 0.2: cons_score = 20
                elif upside > 0.1: cons_score = 10
                
                # --- 5. 売買目安 (Support/Resistance) ---
                # 押し目買いの目安としてSMA50を使用
                buy_zone_high = sma50 * 1.02
                buy_zone_low = sma50 * 0.98
                
                # RSI計算
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # 総合スコア
                total_score = val_score + trend_score + cons_score
                
                # RSIによる補正（過熱感があれば減点）
                if rsi > 75: total_score -= 10
                if rsi < 30: total_score += 10 # 売られすぎリバウンド狙い

                data_list.append({
                    "Ticker": ticker,
                    "Name": name,
                    "Sector": sector,
                    "Price": price,
                    "Total_Score": total_score,
                    # 内訳
                    "Val_Score": val_score,
                    "Val_Msg": val_msg,
                    "Trend_Score": trend_score,
                    "Trend_Msg": trend_msg,
                    "Upside": upside,
                    "Analysts": analysts,
                    "Target_Price": target_mean,
                    "Buy_Zone": sma50, # 目安
                    "RSI": rsi,
                    "PEG": peg,
                    "Fwd_PE": fwd_pe
                })
            except: continue
            
    return pd.DataFrame(data_list)

# --- 3. UI構築 ---

# サイドバー設定
mode = st.sidebar.radio("モード切替", ["📊 銘柄分析ダッシュボード", "⚙️ ログ・設定 (裏方)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "📊 銘柄分析ダッシュボード":
    st.title("🦅 Market Edge Pro")
    st.caption("「今、何が起きているか」を可視化し、あなたの投資判断をサポートします。")
    
    col1, col2 = st.columns([3, 1])
    with col1:
        st.info("💡 **使い方のヒント:** スコアが高い銘柄が良いとは限りません。「割安性」重視か「トレンド」重視か、ご自身の戦略に合わせてデータを見てください。")
    with col2:
        if st.button("🔄 最新データを取得"):
            st.rerun()

    # データ取得
    df = fetch_stock_data(TARGETS)
    
    if not df.empty:
        # スコア順に並べ替え
        df = df.sort_values('Total_Score', ascending=False)
        
        # --- メインリスト表示 ---
        st.subheader("🔍 銘柄分析リスト")
        
        for i, row in df.iterrows():
            # カード形式で表示
            with st.expander(f"**{row['Ticker']}** : {row['Name']} (${row['Price']:.2f}) - スコア: {row['Total_Score']}/80"):
                
                # 3カラムレイアウト
                c1, c2, c3 = st.columns(3)
                
                with c1:
                    st.markdown("#### 1. 基礎体力 (Score)")
                    st.progress(min(row['Total_Score'] / 80, 1.0))
                    st.write(f"💰 **割安性:** {row['Val_Msg']} (PEG: {row['PEG']:.2f})")
                    st.write(f"📈 **トレンド:** {row['Trend_Msg']}")
                    st.write(f"🐋 **期待値:** +{row['Upside']:.1%} (目標株価: ${row['Target_Price']:.2f})")
                
                with c2:
                    st.markdown("#### 2. 売買の目安 (Levels)")
                    
                    # 現在値とターゲットの距離
                    st.metric("現在株価", f"${row['Price']:.2f}")
                    
                    # 買い目安（SMA50付近）
                    dist_to_support = (row['Price'] - row['Buy_Zone']) / row['Price']
                    support_color = "off"
                    support_msg = "まだ高い (待ち)"
                    if -0.02 < dist_to_support < 0.05:
                        support_color = "normal"
                        support_msg = "🎯 押し目ゾーン"
                    
                    st.metric("買い目安 (SMA50)", f"${row['Buy_Zone']:.2f}", 
                              f"乖離 {dist_to_support:.1%}", delta_color="inverse")
                    st.caption(f"判定: **{support_msg}**")

                with c3:
                    st.markdown("#### 3. テクニカル (Timing)")
                    st.metric("RSI (過熱感)", f"{row['RSI']:.1f}")
                    if row['RSI'] > 70:
                        st.error("⚠️ 買われすぎ (高値掴み注意)")
                    elif row['RSI'] < 30:
                        st.success("✅ 売られすぎ (リバウンド好機)")
                    else:
                        st.info("➡️ 中立")
                        
                    st.markdown("---")
                    st.caption(f"アナリスト数: {row['Analysts']}名 / セクター: {row['Sector']}")

else:
    st.title("⚙️ 管理・ログ画面")
    st.write("ここは過去のデータログを確認する画面です。")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        st.dataframe(hist_df)
    else:
        st.write("履歴はありません。")
