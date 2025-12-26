import sqlite3
import os

DB_PATH = "trading_journal.db"

def init_db():
    # 既存のDBがあっても安全に再利用する
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()

    # 1. 監視リスト
    c.execute('''
        CREATE TABLE IF NOT EXISTS watchlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            symbols TEXT NOT NULL
        )
    ''')
    # データが空なら初期値を入れる
    c.execute("SELECT count(*) FROM watchlists")
    if c.fetchone()[0] == 0:
        c.execute("INSERT INTO watchlists (name, symbols) VALUES (?, ?)", 
                  ("Default Watchlist", "AAPL,MSFT,TSLA,NVDA,GOOGL,AMZN,META,AMD"))

    # 2. ルール定義
    c.execute('''
        CREATE TABLE IF NOT EXISTS rule_sets (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            json_body TEXT NOT NULL
        )
    ''')

    # 3. スキャン結果
    c.execute('''
        CREATE TABLE IF NOT EXISTS scan_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            scanned_at DATETIME DEFAULT CURRENT_TIMESTAMP,
            rule_set_id TEXT,
            symbol TEXT,
            is_match BOOLEAN,
            match_details JSON,
            market_data_snapshot JSON
        )
    ''')

    # 4. 取引日誌
    c.execute('''
        CREATE TABLE IF NOT EXISTS journal_entries (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            symbol TEXT NOT NULL,
            entry_date DATE,
            pnl_value REAL,
            tags TEXT,
            original_note TEXT,
            formatted_note TEXT,
            created_at DATETIME DEFAULT CURRENT_TIMESTAMP
        )
    ''')

    conn.commit()
    conn.close()
    print(f"Database {DB_PATH} is ready.")

if __name__ == "__main__":
    init_db()
