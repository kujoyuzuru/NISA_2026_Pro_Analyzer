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
PROTOCOL_VER = "v22.0_Integrity_First"
MIN_INTERVAL_DAYS = 7       

# ★ トレードルール定数 (画面上部にも表示)
SMA_PERIOD = 50                 # トレンド基準線
ATR_PERIOD = 14                 # 値動き計測期間
STOP_MULTIPLIER = 2.0           # 損切り幅 (ATR x N)
TARGET_SHORT_MULT = 3.0         # 短期利確目標 (ATR x N)
MIN_RISK_REWARD = 2.0           # 許容R/R下限
DIP_TOLERANCE = 0.05            # 押し目許容範囲 (+5%以内)
MAX_VOLATILITY = 0.05           # 除外変動率 (5%以上は除外)

# --- 2. ユーティリティ (フォーマット・監査) ---

def fmt_pct(val):
    """率を%表記に整形 (例: 0.0264 -> 2.6%)"""
    return f"{val * 100:.1f}%" if pd.notnull(val) else "-"

def fmt_price(val):
    """価格をドル表記に整形"""
    return f"${val:.2f}" if pd.notnull(val) else "-"

def fmt_num(val, digit=1):
    """数値を整形"""
    return f"{val:.{digit}f}" if pd.notnull(val) else "-"

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

# --- 3. 分析エンジン (Single Source of Truth) ---

def calculate_atr(df, period=14):
    high_low = df['High'] - df['Low']
    high_close = np.abs(df['High'] - df['Close'].shift())
    low_close = np.abs(df['Low'] - df['Close'].shift())
    ranges = pd.concat([high_low, high_close, low_close], axis=1)
    true_range = np.max(ranges, axis=1)
    # 修正: Wilder's Smoothingではなく単純移動平均を使うケースもあるが、
    # ここでは計算安定性のため単純移動平均(Rolling Mean)を採用
    atr = true_range.rolling(period).mean().iloc[-1]
    return atr

def calculate_rsi(series, period=14):
    delta = series.diff()
    gain = (delta.where(delta > 0, 0)).fillna(0)
    loss = (-delta.where(delta < 0, 0)).fillna(0)
    
    # 修正: RSI計算の安定化 (EWMを使うのが一般的だが、ズレを防ぐため単純平均で実装)
    avg_gain = gain.rolling(window=period).mean()
    avg_loss = loss.rolling(window=period).mean()
    
    rs = avg_gain / avg_loss
    rsi = 100 - (100 / (1 + rs))
    
    # 健全性チェック: 0-100クリップ
    return rsi.clip(0, 100).iloc[-1]

@st.cache_data(ttl=3600)
def analyze_market(tickers, mode="Short"):
    results = []
    run_id = str(uuid.uuid4())[:8]
    fetch_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    
    for ticker in tickers:
        try:
            stock = yf.Ticker(ticker)
            try: info = stock.info
            except: continue 

            hist = stock.history(period="6mo")
            if len(hist) < 60: continue

            # --- A. 指標計算 (Calculation Phase) ---
            current_price = info.get('currentPrice', hist['Close'].iloc[-1])
            name = info.get('shortName', ticker)
            
            # トレンド (SMA50)
            sma50_series = hist['Close'].rolling(window=SMA_PERIOD).mean()
            sma50_now = sma50_series.iloc[-1]
            sma50_prev = sma50_series.iloc[-5] # 5日前
            
            # ボラティリティ (ATR)
            atr = calculate_atr(hist, ATR_PERIOD)
            vol_pct = atr / current_price if current_price else 0
            
            # RSI
            rsi = calculate_rsi(hist['Close'])
            
            # 乖離率
            dist_sma = (current_price - sma50_now) / sma50_now
            
            # --- B. 目標・損切り設定 (Mode Dependent) ---
            stop_loss = current_price - (atr * STOP_MULTIPLIER)
            risk_amt = current_price - stop_loss
            
            target_price = 0
            target_source = "不明"
            
            if mode == "Short":
                # 短期モード: ATRベース
                target_price = current_price + (atr * TARGET_SHORT_MULT)
                target_source = "ATR目標"
            else:
                # 中期モード: アナリスト平均 or 高値
                analyst_target = info.get('targetMeanPrice')
                if analyst_target and analyst_target > current_price:
                    target_price = analyst_target
                    target_source = "アナリスト平均"
                else:
                    target_price = current_price * 1.15 # データなしの仮定
                    target_source = "仮定(+15%)"

            reward_amt = target_price - current_price
            rr_ratio = reward_amt / risk_amt if risk_amt > 0 else 0
            
            # --- C. 判定ロジック (Logic Gate) ---
            
            # 1. 健全性チェック (Data Integrity Gate)
            if np.isnan(rsi) or np.isnan(sma50_now) or current_price == 0:
                status = "データ異常"
                reason = "計算不能な指標あり"
                action_type = "除外"
                
            # 2. ロジック判定
            else:
                # トレンド判定: 価格が上 & 向きが上
                is_uptrend = (current_price > sma50_now) and (sma50_now > sma50_prev)
                # 押し目判定: 乖離が許容範囲内(プラス圏)
                is_dip = (0 < dist_sma <= DIP_TOLERANCE)
                # 過熱判定
                is_overbought = (rsi >= 70)
                # 変動率判定
                is_volatile = (vol_pct > MAX_VOLATILITY)
                
                # ステータス決定
                if is_volatile:
                    action_type = "除外"
                    status = "変動過大"
                    reason = f"日率{fmt_pct(vol_pct)} > 許容{fmt_pct(MAX_VOLATILITY)}"
                elif not is_uptrend:
                    action_type = "除外" # 待機ではなく除外(トレンド不適合)
                    status = "トレンド不適合"
                    reason = "SMA50割れ または SMA50下向き"
                elif rr_ratio < MIN_RISK_REWARD:
                    action_type = "待機"
                    status = "期待値不足"
                    reason = f"R/R {rr_ratio:.1f}倍 < {MIN_RISK_REWARD}倍"
                elif is_overbought:
                    action_type = "監視"
                    status = "過熱感"
                    reason = f"RSI {rsi:.0f} (買われすぎ)"
                elif dist_sma > DIP_TOLERANCE:
                    action_type = "監視"
                    status = "乖離過大"
                    reason = f"SMA50から+{fmt_pct(dist_sma)} (高値圏)"
                elif is_dip and not is_overbought:
                    action_type = "候補"
                    status = "条件合致"
                    reason = "トレンド・押し目・R/R 全クリア"
                else:
                    action_type = "待機"
                    status = "条件不一致"
                    reason = "形状が不鮮明"

            # 結果格納
            results.append({
                "Run_ID": run_id,
                "Scan_Time": fetch_time,
                "Ticker": ticker,
                "Name": name,
                "Price": current_price,
                
                "Action": action_type,    # 候補/監視/待機/除外
                "Status": status,         # 詳細ステータス
                "Reason": reason,         # 人間用理由
                
                "Target": target_price,
                "Target_Src": target_source,
                "Stop": stop_loss,
                "RR": rr_ratio,
                
                "SMA50": sma50_now,
                "Dist_SMA": dist_sma,
                "RSI": rsi,
                "Vol_Pct": vol_pct,
                "Trend_Ok": is_uptrend if 'is_uptrend' in locals() else False
            })
            
        except Exception:
            continue
            
    return pd.DataFrame(results)

def log_execution(df):
    prev_hash = get_last_hash()
    df_save = df.copy()
    df_save["Prev_Hash"] = prev_hash
    
    # ログ用ハッシュ
    content = df_save[['Run_ID', 'Ticker', 'Action', 'Reason']].to_string()
    new_hash = calculate_chain_hash(prev_hash, content)
    df_save["Record_Hash"] = new_hash
    
    if not os.path.exists(HISTORY_FILE):
        df_save.to_csv(HISTORY_FILE, index=False)
    else:
        df_save.to_csv(HISTORY_FILE, mode='a', header=False, index=False)

# --- 4. UI構築 ---

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
        df = analyze_market(TARGETS, mode=mode)
        
        if not df.empty:
            log_execution(df)
            
            # 2. 今日やることサマリー
            cnt_cand = len(df[df['Action']=="候補"])
            cnt_watch = len(df[df['Action']=="監視"])
            cnt_wait = len(df[df['Action']=="待機"])
            cnt_excl = len(df[df['Action']=="除外"])
            
            st.markdown(f"**本日の判定:** ✅候補 **{cnt_cand}** | 👀監視 **{cnt_watch}** | ⏳待機 **{cnt_wait}** | 🗑️除外 **{cnt_excl}**")
            st.divider()

            # 3. 候補リスト (Actionable Cards)
            if cnt_cand > 0:
                st.subheader(f"✅ 買い候補 ({cnt_cand})")
                cand_df = df[df['Action']=="候補"].sort_values('RR', ascending=False)
                
                for _, row in cand_df.iterrows():
                    with st.container():
                        # Header
                        c1, c2 = st.columns([3, 1])
                        c1.markdown(f"#### {row['Ticker']} {row['Name']}")
                        c2.caption(f"現在値: {fmt_price(row['Price'])}")
                        
                        # Action Block (Entry/Stop/Target/RR)
                        ac1, ac2, ac3, ac4 = st.columns(4)
                        ac1.info(f"🔵 **入る目安**\n\n{fmt_price(row['Price'])}")
                        ac2.error(f"🛑 **損切り**\n\n{fmt_price(row['Stop'])}")
                        ac3.success(f"🎯 **目標({row['Target_Src']})**\n\n{fmt_price(row['Target'])}")
                        ac4.metric("期待値 (R/R)", f"{row['RR']:.1f}倍")
                        
                        # Logic & Detail
                        st.write(f"**理由:** {row['Reason']}")
                        with st.expander("詳細データ・根拠"):
                            st.write(f"- トレンド: {'上昇 (OK)' if row['Trend_Ok'] else '不適合'}")
                            st.write(f"- 乖離率: {fmt_pct(row['Dist_SMA'])} (SMA50: {fmt_price(row['SMA50'])})")
                            st.write(f"- RSI: {row['RSI']:.0f}")
                            st.write(f"- 変動率: {fmt_pct(row['Vol_Pct'])}")
                        st.divider()
            
            # 4. 監視・待機・除外 (Simplified Lists)
            c_left, c_right = st.columns(2)
            
            with c_left:
                st.subheader("👀 監視 / 待機")
                watch_df = df[df['Action'].isin(["監視", "待機"])].sort_values('Dist_SMA')
                if not watch_df.empty:
                    for _, row in watch_df.iterrows():
                        with st.expander(f"{row['Ticker']}: {row['Reason']}"):
                            st.write(f"状態: {row['Status']}")
                            st.write(f"R/R: {row['RR']:.1f}倍 | RSI: {row['RSI']:.0f}")
                            st.write(f"待つ条件: SMA50({fmt_price(row['SMA50'])})付近まで調整、または過熱感解消")
                else:
                    st.write("なし")

            with c_right:
                st.subheader("🗑️ 除外 (対象外)")
                excl_df = df[df['Action']=="除外"]
                if not excl_df.empty:
                    st.dataframe(excl_df[['Ticker', 'Reason', 'Vol_Pct']], hide_index=True)
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
