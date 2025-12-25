import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from datetime import datetime, timedelta
import os
import hashlib
import uuid

# --- 1. システム設定 ---
st.set_page_config(page_title="Market Edge Pro", page_icon="🦅", layout="wide")

# 定数・パラメータ
HISTORY_FILE = "master_execution_log.csv"
PROTOCOL_VER = "v21.0_Combat_Ready"
MIN_INTERVAL_DAYS = 7       

# ★ トレードルール定数 (画面上部にも表示)
SMA_PERIOD = 50                 # トレンド基準線
ATR_PERIOD = 14                 # 値動き計測期間
STOP_MULTIPLIER = 2.0           # 損切り幅 (ATR x N)
TARGET_MULTIPLIER = 4.0         # 短期利確目標 (ATR x N) -> R/R 2.0を狙う構成
MIN_RISK_REWARD = 2.0           # 許容R/R下限
DIP_TOLERANCE = 0.05            # 押し目許容範囲 (+5%以内)
MAX_VOLATILITY = 0.05           # 除外変動率 (5%以上は除外)

# --- 2. ユーティリティ (フォーマット・監査) ---

def fmt_pct(val):
    """率を%表記に整形"""
    return f"{val * 100:.1f}%"

def fmt_price(val):
    """価格をドル表記に整形"""
    return f"${val:.2f}"

def get_verification_code():
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

# --- 3. 分析エンジン (一貫性重視) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    atr = true_range.rolling(period).mean().iloc[-1]
    return atr

@st.cache_data(ttl=3600)
def fetch_market_data(tickers):
    data_list = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    with st.spinner("🦅 ルール適合チェック・短期目標算出中..."):
        for i, ticker in enumerate(tickers):
            try:
                stock = yf.Ticker(ticker)
                try: info = stock.info
                except: continue 

                hist = stock.history(period="6mo")
                if len(hist) < 60: continue

                # Basic Data
                price = info.get('currentPrice', hist['Close'].iloc[-1])
                name = info.get('shortName', ticker)
                
                # --- A. トレンド判定 (定義固定) ---
                # ルール: 価格 > SMA50 かつ SMA50が上昇中(5日前比)
                sma50 = hist['Close'].rolling(window=SMA_PERIOD).mean()
                sma50_now = sma50.iloc[-1]
                sma50_prev = sma50.iloc[-5]
                
                is_uptrend = (price > sma50_now) and (sma50_now > sma50_prev)
                trend_status = "上昇" if is_uptrend else "下降/調整"
                
                # --- B. リスク管理 (ATR) ---
                atr = calculate_atr(hist, ATR_PERIOD)
                vol_pct = atr / price
                
                # 損切りライン (現在値 - ATR * 2.0)
                stop_loss = price - (atr * STOP_MULTIPLIER)
                risk_amt = price - stop_loss
                
                # --- C. 期待値 (短期スイング用: ATRベース) ---
                # アナリスト目標は遠すぎるため、短期は「ATR * 4.0幅 (R/R 2.0相当)」を技術的目標とする
                target_technical = price + (atr * TARGET_MULTIPLIER)
                reward_amt = target_technical - price
                
                rr_ratio = reward_amt / risk_amt if risk_amt > 0 else 0
                
                # 参考: アナリスト目標
                target_analyst = info.get('targetMeanPrice', 0)
                
                # --- D. フィルタリング (Logic Gate) ---
                dist_sma = (price - sma50_now) / sma50_now
                
                # RSI
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # PEG check (参考)
                peg = info.get('pegRatio')
                val_msg = "データなし"
                if peg: val_msg = f"PEG {peg:.2f}"
                
                # --- 判定ロジック ---
                category = "待機" # デフォルト
                main_reason = "ー"
                
                # 1. 除外条件
                if vol_pct > MAX_VOLATILITY:
                    category = "除外"
                    main_reason = f"変動過大 (日率{fmt_pct(vol_pct)})"
                elif not is_uptrend:
                    category = "除外" # 待機ではなく除外（トレンド違い）
                    main_reason = "トレンド不適合 (SMA50割れ/下向き)"
                
                # 2. 候補条件
                elif category == "待機": # 除外でなければ
                    if rr_ratio < MIN_RISK_REWARD:
                        category = "待機"
                        main_reason = f"期待値不足 (R/R {rr_ratio:.1f}倍)"
                    elif dist_sma > DIP_TOLERANCE:
                        category = "監視"
                        main_reason = f"乖離過大 (SMA50+{fmt_pct(dist_sma)})"
                    elif rsi >= 70:
                        category = "監視"
                        main_reason = f"過熱感 (RSI {rsi:.0f})"
                    elif rsi < 70 and 0 < dist_sma <= DIP_TOLERANCE:
                        category = "候補"
                        main_reason = "好条件: トレンド・押し目・期待値OK"
                    else:
                        category = "待機"
                        main_reason = "条件不一致 (SMA50以下など)"

                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Price": price,
                    "Category": category, # 統一分類名
                    "Reason": main_reason,
                    "Trend": trend_status,
                    "R_R": rr_ratio,
                    "Stop": stop_loss,
                    "Target_Tech": target_technical,
                    "Target_Analyst": target_analyst,
                    "SMA50": sma50_now,
                    "Dist_SMA": dist_sma,
                    "RSI": rsi,
                    "ATR": atr,
                    "Val_Msg": val_msg,
                    "Vol_Pct": vol_pct
                })
            except: continue
            
    return pd.DataFrame(data_list)

def log_execution(df_candidates):
    prev_hash = get_last_hash()
    last_time = get_last_execution_time()
    current_time = pd.to_datetime(df_candidates['Scan_Time'].iloc[0])
    
    note = "Official"
    if last_time is not None and (current_time - last_time).days < MIN_INTERVAL_DAYS:
        note = "Practice"
    
    df_save = df_candidates.copy()
    df_save["Prev_Hash"] = prev_hash
    df_save["Note"] = note
    
    content = df_save[['Run_ID', 'Ticker', 'Category', 'Scan_Time']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)
    
    return note == "Practice"

# --- 4. UI構築 (実戦仕様) ---

st.sidebar.title("メニュー")
mode = st.sidebar.radio("モード切替", ["🚀 市場スキャン (判断)", "⚙️ 記録・監査 (裏)"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if mode == "🚀 市場スキャン (判断)":
    # --- ヘッダー: ルール要約 (常時表示) ---
    st.title("🦅 Market Edge Pro")
    st.info(f"""
    📏 **判定ルール (Short-Swing Mode)**
    **トレンド:** 価格 > SMA50 かつ SMA50上向き | **押し目:** SMA50乖離 +{DIP_TOLERANCE:.0%}以内
    **損切り:** ATR×{STOP_MULTIPLIER} | **目標:** ATR×{TARGET_MULTIPLIER} | **R/R:** {MIN_RISK_REWARD}倍以上
    **除外:** 日次変動 > {MAX_VOLATILITY:.0%} | **更新:** {datetime.now().strftime('%H:%M')}
    """)
    
    if st.button("🔄 条件チェックを実行", type="primary"):
        df = fetch_market_data(TARGETS)
        
        if not df.empty:
            log_execution(df)
            
            # --- 1. 候補 (Candidates) ---
            # R/Rが高い順に表示
            entries = df[df['Category'] == "候補"].sort_values('R_R', ascending=False)
            
            st.header(f"✅ 候補リスト ({len(entries)}銘柄)")
            
            if not entries.empty:
                for _, row in entries.iterrows():
                    with st.container():
                        # --- 上段: 基本情報 ---
                        c_head1, c_head2, c_head3 = st.columns([2, 1, 1])
                        with c_head1:
                            st.subheader(f"{row['Ticker']} {row['Name']}")
                        with c_head2:
                            st.metric("現在値", fmt_price(row['Price']))
                        with c_head3:
                            st.caption(f"更新: {row['Scan_Time'][11:16]}")
                        
                        # --- 中段: 4大指標カード (横並び) ---
                        c1, c2, c3, c4 = st.columns(4)
                        with c1:
                            st.info("🔵 **入る目安**")
                            st.write(f"**{fmt_price(row['Price'])}**")
                            st.caption(f"SMA50: {fmt_price(row['SMA50'])}")
                        with c2:
                            st.error("🛑 **損切り**")
                            st.write(f"**{fmt_price(row['Stop'])}**")
                            st.caption(f"ATR×{STOP_MULTIPLIER}")
                        with c3:
                            st.success("🎯 **短期目標**")
                            st.write(f"**{fmt_price(row['Target_Tech'])}**")
                            st.caption(f"ATR×{TARGET_MULTIPLIER}")
                        with c4:
                            # R/R評価
                            rr = row['R_R']
                            rr_color = "green" if rr >= 2.5 else "off"
                            st.metric("期待値 (R/R)", f"{rr:.1f}倍", delta_color="normal")

                        # --- 下段: 理由と注意 ---
                        st.write(f"**判定:** {row['Reason']}")
                        
                        # 簡易警告 (ダミーロジック: 決算等は本来APIが必要だが枠を用意)
                        warns = []
                        if row['Vol_Pct'] > 0.04: warns.append("値動き激しい")
                        if row['RSI'] > 65: warns.append("RSI高め")
                        
                        if warns:
                            st.warning(f"⚠️ 注意: {', '.join(warns)}")

                        # --- 詳細展開 ---
                        with st.expander("詳細データと根拠"):
                            st.write(f"・トレンド: {row['Trend']}")
                            st.write(f"・SMA50乖離: {fmt_pct(row['Dist_SMA'])}")
                            st.write(f"・過熱感(RSI): {row['RSI']:.0f}")
                            st.write(f"・ボラティリティ(日): {fmt_pct(row['Vol_Pct'])}")
                            st.write(f"・割安度: {row['Val_Msg']}")
                            st.caption(f"※アナリスト目標平均: {fmt_price(row['Target_Analyst'])} (参考)")
                        
                        st.divider()
            else:
                st.info("現在、全条件（トレンド・押し目・R/R）を満たす候補はありません。")

            # --- 2. 監視 (Wait) ---
            watches = df[df['Category'] == "監視"].sort_values('Dist_SMA', ascending=True)
            st.header(f"👀 監視リスト ({len(watches)}銘柄)")
            if not watches.empty:
                for _, row in watches.iterrows():
                    with st.expander(f"{row['Ticker']} (${row['Price']:.2f}) : {row['Reason']}"):
                        st.warning(f"⏰ **待機:** 株価が **{fmt_price(row['SMA50'])}** 付近まで調整したら再確認")
                        st.write(f"RSI: {row['RSI']:.0f} / 乖離: {fmt_pct(row['Dist_SMA'])}")
            else:
                st.write("なし")

            # --- 3. 除外 (Excluded) ---
            excludes = df[df['Category'].isin(["除外", "待機"])]
            with st.expander(f"🗑️ 除外・待機 ({len(excludes)}銘柄)"):
                # シンプルな表
                disp_df = excludes[['Ticker', 'Category', 'Reason', 'Price']].copy()
                disp_df['Price'] = disp_df['Price'].apply(lambda x: f"${x:.2f}")
                st.dataframe(disp_df)
                
        else:
            st.error("データ取得エラー")

else:
    # --- 裏側 (監査) ---
    st.title("⚙️ 記録・監査室")
    
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        
        st.subheader("📊 実行サマリー")
        st.write(f"最終実行: {hist_df.iloc[-1]['Scan_Time']}")
        
        st.subheader("📜 実行ログ")
        if 'Violation' in hist_df.columns: hist_df.rename(columns={'Violation': 'Note'}, inplace=True)
        if 'Note' not in hist_df.columns: hist_df['Note'] = "-"
            
        st.dataframe(hist_df.sort_index(ascending=False))
        st.caption(f"Validation Code: {get_verification_code()}")
    else:
        st.write("履歴データなし")
