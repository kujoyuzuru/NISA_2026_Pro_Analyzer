import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import hashlib
import uuid

# --- 1. 基本設定 (Layer B: Engine) ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

# ファイル・パラメータ定数
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v13.0_Layered_UX"
MIN_INTERVAL_DAYS = 7       # 頻度制限 (本番ログ用)
MAX_SPREAD_TOLERANCE = 0.8  # 安全弁 (Spread 80%以上は除外)
PORTFOLIO_SIZE = 5
MAX_SECTOR_ALLOCATION = 2

# --- 2. 裏方ロジック (Layer B & C: Logic & Audit) ---

def get_verification_code():
    """検証用コード(旧Anchor)の生成 - 監査モード用"""
    if not os.path.exists(HISTORY_FILE): return "NO_DATA"
    with open(HISTORY_FILE, "rb") as f:
        return hashlib.sha256(f.read()).hexdigest()[:12]

def get_last_hash():
    if not os.path.exists(HISTORY_FILE): return "GENESIS"
    try:
        df = pd.read_csv(HISTORY_FILE)
        return df.iloc[-1]['Record_Hash'] if not df.empty else "GENESIS"
    except:
        return "BROKEN"

def calculate_chain_hash(prev_hash, content):
    combined = f"{prev_hash}|{content}"
    return hashlib.sha256(combined.encode()).hexdigest()

def get_last_execution_time():
    if not os.path.exists(HISTORY_FILE): return None
    try:
        df = pd.read_csv(HISTORY_FILE)
        if df.empty: return None
        return pd.to_datetime(df.iloc[-1]['Scan_Time'])
    except:
        return None

def decay_function(spread):
    return 1.0 / (1.0 + spread)

# --- 3. 分析エンジン (Layer A: Intelligence) ---

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 市場データをスキャン中..."):
        for i, ticker in enumerate(tickers):
            try:
                stock = yf.Ticker(ticker)
                try: info = stock.info
                except: continue 

                hist = stock.history(period="6mo")
                if hist.empty: continue

                # --- Basic Data ---
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                name = info.get('shortName', ticker)
                sector = info.get('sector', 'Unknown')
                
                # --- Valuation (割安性) ---
                peg = info.get('pegRatio', np.nan)
                val_score = 0
                val_label = "ー"
                
                if pd.notna(peg):
                    if peg < 1.0:
                        val_score = 30
                        val_label = "S (割安)"
                    elif peg < 1.5:
                        val_score = 20
                        val_label = "A (良好)"
                    elif peg < 2.0:
                        val_score = 10
                        val_label = "B (適正)"
                    else:
                        val_label = "C (割高圏)"
                
                # --- Trend (トレンド) ---
                sma50 = hist['Close'].rolling(window=50).mean().iloc[-1]
                sma200 = hist['Close'].rolling(window=200).mean().iloc[-1] if len(hist) > 200 else price
                
                trend_score = 0
                trend_label = "下降/レンジ"
                
                if price > sma50 > sma200:
                    trend_score = 30
                    trend_label = "S (上昇トレンド)"
                elif price > sma50:
                    trend_score = 15
                    trend_label = "A (短期上昇)"
                
                # --- Upside & Risk (期待値とリスク) ---
                target_mean = info.get('targetMeanPrice', 0)
                upside = (target_mean - price) / price if target_mean else 0
                
                # Spread (不確実性)
                target_high = info.get('targetHighPrice', target_mean)
                target_low = info.get('targetLowPrice', target_mean)
                spread = (target_high - target_low) / target_mean if target_mean else 0.5
                
                analysts = info.get('numberOfAnalystOpinions', 0)
                conf_factor = min(1.0, analysts / 15.0) if analysts >= 3 else 0.0
                
                # ★安全弁 (Safety Valve)
                filter_status = "OK"
                if spread > MAX_SPREAD_TOLERANCE:
                    filter_status = "REJECT_RISK" # Spread過大は除外
                elif analysts < 3:
                    filter_status = "REJECT_DATA"
                
                cons_score = 0
                if upside > 0:
                    base = 20 if upside > 0.2 else (10 if upside > 0.1 else 0)
                    cons_score = int(base * decay_function(spread) * conf_factor)
                
                # Total
                total_score = val_score + trend_score + cons_score
                
                # --- Timing (RSI) ---
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                rsi_status = "中立"
                if rsi > 70: rsi_status = "⚠️ 加熱"
                elif rsi < 30: rsi_status = "✅ 底値圏"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Sector": sector,
                    "Price": price,
                    "Total_Score": total_score,
                    "Filter_Status": filter_status,
                    # Details
                    "Val_Label": val_label,
                    "Trend_Label": trend_label,
                    "Upside": upside,
                    "Spread": spread,
                    "Target": target_mean,
                    "Buy_Level": sma50, # SMA50を買い目安とする
                    "RSI": rsi,
                    "RSI_Status": rsi_status,
                    "PEG": peg
                })
            except: continue
            
    return pd.DataFrame(data_list)

def select_candidates(df):
    """ポートフォリオ候補の選定 (セクター分散ルール適用)"""
    df_valid = df[df['Filter_Status'] == "OK"].copy()
    df_sorted = df_valid.sort_values('Total_Score', ascending=False)
    
    candidates = []
    sector_counts = {}
    
    for _, row in df_sorted.iterrows():
        if len(candidates) >= PORTFOLIO_SIZE: break
        sec = row['Sector']
        cnt = sector_counts.get(sec, 0)
        
        if cnt < MAX_SECTOR_ALLOCATION:
            candidates.append(row)
            sector_counts[sec] = cnt + 1
            
    return pd.DataFrame(candidates)

def log_execution(df_candidates):
    """実行ログの保存 (Hash Chain & Frequency Check)"""
    prev_hash = get_last_hash()
    last_time = get_last_execution_time()
    current_time = pd.to_datetime(df_candidates['Scan_Time'].iloc[0])
    
    # 頻度制限チェック (練習モードか本番か)
    is_practice = False
    note = "Official Run"
    if last_time is not None:
        delta = current_time - last_time
        if delta.days < MIN_INTERVAL_DAYS:
            is_practice = True
            note = f"Practice (Too Soon: {delta.days} days)"
    
    df_save = df_candidates.copy()
    df_save["Prev_Hash"] = prev_hash
    df_save["Note"] = note
    
    # チェーンハッシュ生成
    content = df_save[['Run_ID', 'Ticker', 'Total_Score', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return is_practice

# --- 4. UI構築 (Layer A & C) ---

# サイドバー：普段は隠れている「裏の顔」
st.sidebar.header("🔧 システム設定")
mode = st.sidebar.radio("モード選択", ["📈 市場スキャナー (通常)", "🛡️ 管理・監査室 (検証)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

# === Layer A: 意思決定の補助 (表の顔) ===
if mode == "📈 市場スキャナー (通常)":
    st.title("🦅 Market Edge Pro")
    st.caption("客観データに基づく、本日の有望銘柄リスト")
    
    # シンプルなアクションボタン
    if st.button("🔍 市場を分析する", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            candidates = select_candidates(df)
            
            if not candidates.empty:
                # 裏側でログ保存 (ユーザーには意識させない)
                is_practice = log_execution(candidates)
                
                # ステータス表示
                if is_practice:
                    st.toast("⚠️ 練習モードで記録しました (頻度制限中)", icon="ℹ️")
                else:
                    st.toast("✅ 公式記録として保存しました", icon="💾")
                
                # --- メインリスト表示 (10秒で理解できるUI) ---
                st.markdown(f"### 📋 本日の候補リスト ({len(candidates)}銘柄)")
                
                for i, row in candidates.iterrows():
                    # 視覚的なヘッダー
                    score = row['Total_Score']
                    header_color = "🟢" if score >= 60 else ("🟡" if score >= 40 else "🔴")
                    
                    with st.expander(f"{header_color} **{row['Ticker']}** | {row['Name']} | ${row['Price']:.2f}", expanded=True):
                        
                        # 3つの重要指標を横並び
                        c1, c2, c3 = st.columns(3)
                        
                        # 1. ファンダメンタルズ
                        with c1:
                            st.caption("📊 基礎体力")
                            st.write(f"**スコア:** {score} / 80")
                            st.write(f"**割安度:** {row['Val_Label']}")
                            st.write(f"**トレンド:** {row['Trend_Label']}")
                        
                        # 2. 売買目安 (Actionable Info)
                        with c2:
                            st.caption("🎯 買い目安 (SMA50)")
                            dist = (row['Price'] - row['Buy_Level']) / row['Price']
                            
                            lvl_status = "様子見 (乖離大)"
                            lvl_color = "gray"
                            if -0.02 < dist < 0.05:
                                lvl_status = "★ 押し目ゾーン"
                                lvl_color = "green"
                            elif dist < -0.05:
                                lvl_status = "警戒 (トレンド割れ)"
                                lvl_color = "red"
                                
                            st.markdown(f":{lvl_color}[**{lvl_status}**]")
                            st.write(f"基準値: ${row['Buy_Level']:.2f}")
                            st.write(f"現在乖離: {dist:+.1%}")

                        # 3. タイミング
                        with c3:
                            st.caption("⏰ タイミング (RSI)")
                            st.write(f"**{row['RSI']:.1f}** ({row['RSI_Status']})")
                            
                            if row['RSI'] > 70:
                                st.warning("過熱気味。飛び乗り注意。")
                            elif row['RSI'] < 30:
                                st.success("リバウンドの好機。")
                            else:
                                st.info("中立水準。")

                st.divider()
                st.caption("※ 買い目安は50日移動平均線を基準としています。この価格に近づいたタイミングでのエントリーを検討してください。")
            
            else:
                st.error("⚠️ 本日は「安全基準（Spread/リスク）」を満たす銘柄がありませんでした。無理なエントリーは控えましょう。")
                st.write("除外された銘柄一覧:", df[['Ticker', 'Filter_Status']])
        else:
            st.error("データ取得に失敗しました。")

# === Layer C: 監査室 (裏の顔) ===
else:
    st.title("🛡️ 管理・監査室")
    st.info("ここは運用記録の検証と、データの健全性を確認するための管理画面です。")
    
    tab1, tab2 = st.tabs(["📜 実行ログ & 検証コード", "⚙️ プロトコル定義"])
    
    with tab1:
        st.subheader("検証用コード (Verification ID)")
        code = get_verification_code()
        
        col_a, col_b = st.columns([3, 1])
        with col_a:
            st.code(code, language="text")
        with col_b:
            st.caption("公開運用の際は、このコードをSNS等に記録してください。")
            
        st.divider()
        st.subheader("実行履歴 (Raw Log)")
        if os.path.exists(HISTORY_FILE):
            # 互換性処理付き読み込み
            hist_df = pd.read_csv(HISTORY_FILE)
            if 'Violation' in hist_df.columns: # 古い列名対応
                hist_df.rename(columns={'Violation': 'Note'}, inplace=True)
            if 'Note' not in hist_df.columns:
                hist_df['Note'] = "Legacy Data"
                
            st.dataframe(hist_df.sort_index(ascending=False))
        else:
            st.write("履歴データなし")

    with tab2:
        st.subheader("運用プロトコル")
        st.code(f"""
        Version: {PROTOCOL_VER}
        Min Interval: {MIN_INTERVAL_DAYS} days (Official Run)
        Max Risk (Spread): {MAX_SPREAD_TOLERANCE:.0%}
        Portfolio Size: {PORTFOLIO_SIZE}
        Max Sector Allocation: {MAX_SECTOR_ALLOCATION}
        """, language="yaml")
