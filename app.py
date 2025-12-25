import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime
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
TARGET_SHORT_MULT = 3.0         # 短期利確目標 (ATR x N)
MIN_RISK_REWARD = 2.0           # 許容R/R下限
DIP_TOLERANCE = 0.05            # 押し目許容範囲 (+5%以内)
MAX_VOLATILITY = 0.05           # 除外変動率 (5%以上は除外)

# --- 2. ユーティリティ ---

def fmt_pct(val):
    return f"{val * 100:.1f}%" if pd.notnull(val) else "-"

def fmt_price(val):
    return f"${val:.2f}" if pd.notnull(val) else "-"

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

# --- 3. 分析エンジン (Single Source of Truth) ---

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
    
    with st.spinner("🦅 全銘柄を一括判定中 (トレンド・R/R・整合性チェック)..."):
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
                
                # --- A. 指標計算 (Calculation Phase) ---
                
                # 1. トレンド (SMA50)
                sma50_series = hist['Close'].rolling(window=SMA_PERIOD).mean()
                sma50_now = sma50_series.iloc[-1]
                sma50_prev = sma50_series.iloc[-5]
                slope_positive = sma50_now > sma50_prev
                
                # 2. ボラティリティ (ATR)
                atr = calculate_atr(hist, ATR_PERIOD)
                vol_pct = atr / price
                
                # 3. 乖離 & RSI
                dist_sma = (price - sma50_now) / sma50_now
                delta = hist['Close'].diff()
                gain = (delta.where(delta > 0, 0)).rolling(window=14).mean()
                loss = (-delta.where(delta < 0, 0)).rolling(window=14).mean()
                rs = gain / loss
                rsi = 100 - (100 / (1 + rs)).iloc[-1]
                
                # 4. 目標 & 損切り
                stop_loss = price - (atr * STOP_MULTIPLIER)
                risk_amt = price - stop_loss
                
                # 短期目標 (ATRベース)
                target_short = price + (atr * TARGET_SHORT_MULT)
                reward_short = target_short - price
                rr_short = reward_short / risk_amt if risk_amt > 0 else 0
                
                # 中期目標 (アナリスト or 高値)
                target_mid = info.get('targetMeanPrice')
                if not target_mid or target_mid <= price:
                    target_mid = price * 1.15 # データなしor到達済みなら仮定
                reward_mid = target_mid - price
                rr_mid = reward_mid / risk_amt if risk_amt > 0 else 0

                # PEG (参考)
                peg = info.get('pegRatio')
                
                # --- B. 状態判定 (Decision Phase) ---
                
                state = "待機" # Default
                reason = "-"
                
                # 判定1: 除外 (Exclude)
                if vol_pct > MAX_VOLATILITY:
                    state = "除外"
                    reason = f"値動き過大 (日率{fmt_pct(vol_pct)})"
                elif not (price > sma50_now and slope_positive):
                    state = "除外" # 上昇トレンド以外は即除外
                    reason = "トレンド不適合 (SMA50以下/下向き)"
                
                # 判定2: 候補 (Candidate)
                elif state != "除外":
                    # 押し目チェック (0% < 乖離 < 5%)
                    is_dip = (0 < dist_sma <= DIP_TOLERANCE)
                    # 過熱感チェック
                    is_safe_rsi = (rsi < 70)
                    # R/Rチェック (短期または中期で合格なら候補とする)
                    is_good_rr = (rr_short >= MIN_RISK_REWARD)
                    
                    if is_dip and is_safe_rsi and is_good_rr:
                        state = "買い候補"
                        reason = "好条件: トレンド+押し目+期待値"
                    elif dist_sma > DIP_TOLERANCE or not is_safe_rsi:
                        state = "監視"
                        reason = f"過熱/乖離 (RSI {rsi:.0f} / 乖離 {fmt_pct(dist_sma)})"
                    elif not is_good_rr:
                        state = "待機"
                        reason = f"期待値不足 (短期R/R {rr_short:.1f}倍)"
                    else:
                        state = "待機"
                        reason = "条件不一致 (SMA50割れ等)"

                # リスト格納
                data_list.append({
                    "Run_ID": run_id,
                    "Scan_Time": fetch_time,
                    "Ticker": ticker,
                    "Name": name,
                    "Price": price,
                    "State": state,       # 統一された状態
                    "Reason": reason,
                    
                    "Stop_Loss": stop_loss,
                    "Risk_Amt": risk_amt,
                    
                    "Target_Short": target_short,
                    "RR_Short": rr_short,
                    
                    "Target_Mid": target_mid,
                    "RR_Mid": rr_mid,
                    
                    "SMA50": sma50_now,
                    "Dist_SMA": dist_sma,
                    "RSI": rsi,
                    "Vol_Pct": vol_pct,
                    "PEG": peg
                })
            except: continue
            
    return pd.DataFrame(data_list)

def log_execution(df):
    prev_hash = get_last_hash()
    df_save = df.copy()
    df_save["Prev_Hash"] = prev_hash
    
    # ログ用ハッシュ
    content = df_save[['Run_ID', 'Ticker', 'State', 'Reason']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)

# --- 4. UI構築 (Action First) ---

st.sidebar.title("メニュー")
page = st.sidebar.radio("機能選択", ["🚀 市場スキャン", "⚙️ 記録・監査"])

TARGETS = ["NVDA", "MSFT", "AAPL", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "AMD", "PLTR", "ARM", "SMCI", "COIN", "CRWD", "LLY", "NVO", "COST", "NFLX", "INTC"]

if page == "🚀 市場スキャン":
    # 1. モード選択とルール表示
    st.title("🦅 Market Edge Pro")
    
    col_mode, col_rule = st.columns([1, 3])
    with col_mode:
        mode = st.radio("判定モード", ["Short", "Mid"], help="Short=ATR目標, Mid=アナリスト目標")
    with col_rule:
        if mode == "Short":
            st.info(f"**Short Mode ルール:** 目標=ATR×{TARGET_SHORT_MULT} | 損切=ATR×{STOP_MULTIPLIER} | R/R>{MIN_RISK_REWARD}")
        else:
            st.info(f"**Mid Mode ルール:** 目標=アナリスト平均 | 損切=ATR×{STOP_MULTIPLIER} | R/R>{MIN_RISK_REWARD}")

    if st.button("🔄 スキャン実行", type="primary"):
        df = analyze_market(TARGETS)
        
        if not df.empty:
            log_execution(df)
            
            # 2. 今日やることサマリー
            cnt_cand = len(df[df['State']=="買い候補"])
            cnt_watch = len(df[df['State']=="監視"])
            cnt_wait = len(df[df['State']=="待機"])
            cnt_excl = len(df[df['State']=="除外"])
            
            st.markdown(f"**本日の判定:** ✅候補 **{cnt_cand}** | 👀監視 **{cnt_watch}** | ⏳待機 **{cnt_wait}** | 🗑️除外 **{cnt_excl}**")
            st.divider()

            # 3. 候補リスト (Actionable Cards)
            if cnt_cand > 0:
                st.subheader(f"✅ 買い候補 ({cnt_cand})")
                cand_df = df[df['State']=="買い候補"].sort_values('RR_Short', ascending=False)
                
                for _, row in cand_df.iterrows():
                    with st.container():
                        # Header
                        c1, c2 = st.columns([3, 1])
                        c1.markdown(f"#### {row['Ticker']} {row['Name']}")
                        c2.caption(f"現在値: {fmt_price(row['Price'])}")
                        
                        # Action Block (Entry/Stop/Target/RR)
                        ac1, ac2, ac3, ac4 = st.columns(4)
                        ac1.info(f"🔵 **入る目安**\n\n{fmt_price(row['Price'])}")
                        ac2.error(f"🛑 **損切り**\n\n{fmt_price(row['Stop_Loss'])}")
                        
                        # モードに応じた目標表示
                        if mode == "Short":
                            ac3.success(f"🎯 **短期目標**\n\n{fmt_price(row['Target_Short'])}")
                            ac4.metric("期待値 (R/R)", f"{row['RR_Short']:.1f}倍")
                        else:
                            ac3.success(f"🏰 **中期目標**\n\n{fmt_price(row['Target_Mid'])}")
                            ac4.metric("期待値 (R/R)", f"{row['RR_Mid']:.1f}倍")

                        # Logic & Detail
                        st.write(f"**理由:** {row['Reason']}")
                        with st.expander("詳細データ・根拠"):
                            st.write(f"- トレンド: {'上昇 (OK)'}")
                            st.write(f"- 乖離率: {fmt_pct(row['Dist_SMA'])} (SMA50: {fmt_price(row['SMA50'])})")
                            st.write(f"- RSI: {row['RSI']:.0f}")
                            st.write(f"- 変動率: {fmt_pct(row['Vol_Pct'])}")
                            st.write(f"- 割安度(PEG): {row['PEG'] if row['PEG'] else 'N/A'}")
                        
                        st.divider()
            
            # 4. 監視・待機・除外 (Simplified Lists)
            c_left, c_right = st.columns(2)
            
            with c_left:
                st.subheader("👀 監視 / 待機")
                watch_df = df[df['State'].isin(["監視", "待機"])].sort_values('Dist_SMA')
                if not watch_df.empty:
                    for _, row in watch_df.iterrows():
                        with st.expander(f"{row['Ticker']}: {row['Reason']}"):
                            st.write(f"状態: {row['State']}")
                            st.write(f"待つ条件: SMA50({fmt_price(row['SMA50'])})付近まで調整、または過熱感解消")
                            st.write(f"RSI: {row['RSI']:.0f} / 乖離: {fmt_pct(row['Dist_SMA'])}")
                else:
                    st.write("なし")

            with c_right:
                st.subheader("🗑️ 除外 (対象外)")
                excl_df = df[df['State']=="除外"]
                if not excl_df.empty:
                    st.dataframe(excl_df[['Ticker', 'Reason']], hide_index=True)
                else:
                    st.write("なし")

        else:
            st.error("データ取得失敗")

else:
    # 監査モード
    st.title("⚙️ 記録・監査室")
    if os.path.exists(HISTORY_FILE):
        hist_df = pd.read_csv(HISTORY_FILE)
        st.subheader("最新の実行ログ")
        st.dataframe(hist_df.sort_index(ascending=False).head(50))
        st.caption(f"Verification Code: {get_verification_code()}")
    else:
        st.write("ログなし")
