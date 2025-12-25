import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import uuid

# --- 1. システム設定 & 定数 ---
st.set_page_config(page_title="Market Edge Pro - Audit", page_icon="🦅", layout="wide")

MODEL_VERSION = "v3.0_Strict_Audit"
COST_ASSUMPTION = 0.005 # 往復手数料+スリッページ 0.5%
MIN_ANALYSTS_FULL_TRUST = 15 # 信頼度が1.0になるアナリスト数

# --- 2. ユーティリティ関数 ---
def calculate_confidence(analysts):
    """アナリスト数に基づく信頼度係数 (Sigmoid like or Linear)"""
    # 5人未満は0点、5人〜15人で徐々に信頼度アップ、15人でMAX
    if analysts < 5: return 0.0
    return min(1.0, analysts / MIN_ANALYSTS_FULL_TRUST)

def get_data_cutoff_time():
    """データの基準時間を取得（場中なら現在、閉場後なら直近終値）"""
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# --- 3. [Tab 1] スキャナー機能 ---
@st.cache_data(ttl=3600)
def fetch_market_context():
    try:
        bench = yf.Ticker("QQQ")
        hist = bench.history(period="1d")
        if not hist.empty:
            return hist['Close'].iloc[-1]
        return 0.0
    except:
        return 0.0

@st.cache_data(ttl=3600)
def fetch_stock_data(tickers, benchmark_price):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    cutoff_time = get_data_cutoff_time()
    
    with st.status("🦅 厳格データ取得 & 統計的スコアリング...", expanded=True) as status:
        total = len(tickers)
        for i, ticker in enumerate(tickers):
            status.update(label=f"Scanning... {ticker} ({i+1}/{total})")
            
            try:
                stock = yf.Ticker(ticker)
                try:
                    info = stock.info
                except:
                    continue 

                hist = stock.history(period="1y")
                if hist.empty: continue

                # --- A. Raw Data (Adjusted Close) ---
                # yfinanceのhistoryはデフォルトでAdjusted Close
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                sector = info.get('sector', 'Unknown')
                
                # 1. Valuation (Strict Mode)
                official_peg = info.get('pegRatio')
                # Proxyデータは取得するが、スコアには使わない
                fwd_pe = info.get('forwardPE')
                growth = info.get('earningsGrowth')
                
                peg_val = np.nan
                peg_type = "-" 
                
                if official_peg is not None:
                    peg_val = official_peg
                    peg_type = "Official"
                elif fwd_pe is not None and growth is not None and growth > 0:
                    peg_val = fwd_pe / (growth * 100)
                    peg_type = "Proxy(Ref)" # 参考扱い
                
                # 2. Consensus & Statistics
                target_mean = info.get('targetMeanPrice')
                target_high = info.get('targetHighPrice')
                target_low = info.get('targetLowPrice')
                analysts = info.get('numberOfAnalystOpinions', 0)
                
                upside_val = 0.0
                spread_val = 1.0 # Default High Risk
                
                if target_mean and target_mean > 0 and price > 0:
                    upside_val = (target_mean - price) / price
                    if target_high and target_low:
                        spread_val = (target_high - target_low) / target_mean
                
                # アナリスト数による信頼度係数
                conf_factor = calculate_confidence(analysts)

                # 3. Trend
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1]

                # --- B. Scoring Logic (Strict) ---
                score = 0
                breakdown = []

                # 1. Valuation (Official Only)
                # Proxyは時間軸不整合のリスクがあるためスコア除外
                if peg_type == "Official" and pd.notna(peg_val):
                    base_points = 0
                    if 0 < peg_val < 1.0: base_points = 30
                    elif peg_val < 1.5: base_points = 20
                    elif peg_val < 2.0: base_points = 10
                    
                    if base_points > 0:
                        score += base_points
                        breakdown.append(f"PEG {peg_val:.2f}: +{base_points}")
                elif peg_type == "Proxy(Ref)":
                    breakdown.append(f"PEG(Proxy) {peg_val:.2f}: No Score")
                else:
                    breakdown.append("No Official PEG")

                # 2. Trend
                trend_ok = False
                if price > sma50 > sma200:
                    score += 30
                    trend_ok = True
                    breakdown.append("Trend(P-Order): +30")
                elif price < sma50:
                    breakdown.append("Trend(Below SMA): 0")

                # 3. Upside (Multi-Factor Discount)
                # Score = Base * (1 - Spread) * Confidence(Analysts)
                if upside_val > 0:
                    base_upside = 0
                    if upside_val > 0.2: base_upside = 20
                    elif upside_val > 0.1: base_upside = 10
                    
                    if base_upside > 0:
                        spread_discount = max(0.0, 1.0 - spread_val)
                        # 最終係数 = Spread係数 * 人数信頼度
                        total_factor = spread_discount * conf_factor
                        final_upside = int(base_upside * total_factor)
                        
                        score += final_upside
                        if final_upside > 0:
                            breakdown.append(f"Upside(F:{total_factor:.2f}): +{final_upside}")
                        else:
                            breakdown.append("Upside(Low Conf/High Spread): 0")

                # 4. RSI
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                if 40 <= rsi <= 60 and trend_ok:
                    score += 20
                    breakdown.append("RSI Dip: +20")
                elif rsi > 75:
                    score -= 10
                    breakdown.append("RSI High: -10")

                # Grade
                grade = "C"
                if score >= 80: grade = "S"
                elif score >= 60: grade = "A"
                elif score >= 40: grade = "B"

                data_list.append({
                    "Run_ID": run_id,
                    "Data_Cutoff": cutoff_time, # データの基準時刻
                    "Ticker": ticker,
                    "Sector": sector,
                    "Score": int(score),
                    "Grade": grade,
                    "Price_At_Scan": price,
                    "Benchmark_Ref": benchmark_price,
                    # --- Snapshot ---
                    "PEG_Val": peg_val,
                    "PEG_Type": peg_type,
                    "Spread": spread_val,
                    "Analysts": analysts,
                    "Confidence": conf_factor,
                    "Upside": upside_val,
                    "Breakdown": " / ".join(breakdown),
                    "Model_Ver": MODEL_VERSION
                })
            
            except Exception:
                continue
        
        status.update(label="✅ Scan Complete", state="complete", expanded=False)
    
    return pd.DataFrame(data_list)


# --- 4. [Tab 2] 監査機能 (Audit) ---
def perform_audit(uploaded_file):
    """アップロードされたCSVをもとに予実を判定する"""
    try:
        df_past = pd.read_csv(uploaded_file)
        results = []
        
        # QQQの現状取得
        qqq = yf.Ticker("QQQ")
        qqq_hist = qqq.history(period="3mo") # 少し長めに
        qqq_current = qqq_hist['Close'].iloc[-1]
        
        progress = st.progress(0)
        
        for i, row in df_past.iterrows():
            ticker = row['Ticker']
            entry_price = row['Price_At_Scan'] # 本来は翌日始値だが、簡易検証のためスキャン時価格
            ref_qqq = row['Benchmark_Ref']
            
            # 現在価格の取得
            curr_stock = yf.Ticker(ticker).history(period="1d")
            if curr_stock.empty: continue
            curr_price = curr_stock['Close'].iloc[-1]
            
            # リターン計算
            stock_return = (curr_price - entry_price) / entry_price
            qqq_return = (qqq_current - ref_qqq) / ref_qqq
            
            # コスト控除後のAlpha
            net_return = stock_return - COST_ASSUMPTION
            alpha = net_return - qqq_return
            
            results.append({
                "Ticker": ticker,
                "Score_Then": row['Score'],
                "Entry_Price": entry_price,
                "Current_Price": curr_price,
                "Return": stock_return,
                "QQQ_Return": qqq_return,
                "Alpha (vs QQQ)": alpha,
                "Result": "WIN" if alpha > 0 else "LOSE"
            })
            progress.progress((i + 1) / len(df_past))
            
        return pd.DataFrame(results)
    except Exception as e:
        st.error(f"Audit Error: {e}")
        return pd.DataFrame()

# --- 5. UI構築 ---
tab1, tab2 = st.tabs(["🚀 Live Scanner", "⚖️ Performance Audit"])

# --- Tab 1: スキャナー ---
with tab1:
    st.title("🦅 Market Edge Pro (Strict Scorer)")
    st.caption(f"Ver: {MODEL_VERSION} | Cutoff: Realtime/Close | PEG: Official Only")

    # ベンチマーク
    bench_price = fetch_market_context()
    st.metric("Reference: QQQ Price", f"${bench_price:.2f}")

    with st.expander("📊 Strict Logic (厳格化されたロジック)", expanded=False):
        st.markdown(f"""
        1.  **Strict PEG:** Proxy PEG (Forward/Past) は不整合のため**スコア除外**。Official PEGのみ評価。
        2.  **Analyst Confidence:** アナリスト数({MIN_ANALYSTS_FULL_TRUST}名基準)に応じて、予想の信頼度を連続的に調整。
        3.  **Spread Impact:** 意見のバラつき(Spread)に応じて上値余地を減額。
        """)

    TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

    if st.button("🔍 厳格スキャン実行", type="primary"):
        df = fetch_stock_data(TARGETS, bench_price)
        
        if not df.empty:
            df = df.sort_values('Score', ascending=False).reset_index(drop=True)
            
            # CSV保存
            csv = df.to_csv(index=False).encode('utf-8')
            filename = f'Audit_Data_{datetime.now().strftime("%Y%m%d_%H%M")}.csv'
            
            st.download_button(
                label="💾 監査用CSVを保存 (Save for Audit)",
                data=csv,
                file_name=filename,
                mime='text/csv',
                help="このCSVを保存しておき、後日「Performance Audit」タブで読み込むことで、AIの成績を検証できます。"
            )
            
            st.dataframe(
                df[['Ticker', 'Score', 'Grade', 'PEG_Val', 'PEG_Type', 'Confidence', 'Spread', 'Breakdown']]
                .style
                .format({
                    'Score': '{:.0f}',
                    'PEG_Val': '{:.2f}',
                    'Confidence': '{:.0%}',
                    'Spread': '{:.1%}'
                })
                .background_gradient(subset=['Score'], cmap='Greens', vmin=0, vmax=100)
                .background_gradient(subset=['Spread'], cmap='Reds', vmin=0.0, vmax=1.0)
                .highlight_null(color='gray'),
                use_container_width=True,
                height=600
            )

# --- Tab 2: 予実監査 ---
with tab2:
    st.header("⚖️ Performance Audit (予実管理)")
    st.info("過去に保存したCSVをアップロードしてください。AIの予測スコアと、その後の実際のパフォーマンス(Alpha)を照合します。")
    
    uploaded_file = st.file_uploader("Upload Past Scan CSV", type="csv")
    
    if uploaded_file is not None:
        if st.button("📊 監査実行 (Audit Now)"):
            audit_df = perform_audit(uploaded_file)
            
            if not audit_df.empty:
                # 集計
                win_rate = len(audit_df[audit_df['Result']=="WIN"]) / len(audit_df)
                avg_alpha = audit_df['Alpha (vs QQQ)'].mean()
                
                c1, c2, c3 = st.columns(3)
                c1.metric("Win Rate (vs QQQ)", f"{win_rate:.1%}")
                c2.metric("Avg Alpha", f"{avg_alpha:.2%}", delta_color="normal")
                c3.caption("※Alpha = (Stock Return - 0.5% Cost) - QQQ Return")
                
                # 詳細テーブル
                st.dataframe(
                    audit_df.style
                    .format({
                        'Return': '{:.2%}',
                        'QQQ_Return': '{:.2%}',
                        'Alpha (vs QQQ)': '{:.2%}'
                    })
                    .applymap(lambda x: 'color: green; font-weight: bold;' if x > 0 else 'color: red;', subset=['Alpha (vs QQQ)']),
                    use_container_width=True
                )
            else:
                st.warning("監査データの計算に失敗しました。")
