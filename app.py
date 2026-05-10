import json
import os
import sqlite3
import threading
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pandas as pd
import streamlit as st


DB_PATH = os.getenv("HEALTH_DB_PATH", "health_dashboard.db")
WEBHOOK_PORT = 8000
WEBHOOK_STARTED = False
WEBHOOK_LOCK = threading.Lock()


def get_connection() -> sqlite3.Connection:
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def init_db(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS records (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            record_type TEXT NOT NULL,
            value_num REAL,
            note TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS workouts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            workout_type TEXT NOT NULL,
            calories REAL NOT NULL,
            duration REAL NOT NULL
        )
        """
    )
    conn.commit()


def insert_record(
    conn: sqlite3.Connection, record_type: str, value_num: float | None, note: str | None
) -> None:
    conn.execute(
        """
        INSERT INTO records (created_at, record_type, value_num, note)
        VALUES (?, ?, ?, ?)
        """,
        (datetime.now().isoformat(timespec="seconds"), record_type, value_num, note),
    )
    conn.commit()


def insert_workout(conn: sqlite3.Connection, workout_type: str, calories: float, duration: float) -> None:
    created_at = datetime.now().isoformat(timespec="seconds")
    conn.execute(
        """
        INSERT INTO workouts (created_at, workout_type, calories, duration)
        VALUES (?, ?, ?, ?)
        """,
        (created_at, workout_type, calories, duration),
    )
    conn.execute(
        """
        INSERT INTO records (created_at, record_type, value_num, note)
        VALUES (?, 'calories_burned', ?, ?)
        """,
        (created_at, calories, f"Webhook: {workout_type} ({duration:g} 分鐘)"),
    )
    conn.commit()


def get_recent_workouts(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    query = """
        SELECT created_at, workout_type, calories, duration
        FROM workouts
        ORDER BY id DESC
        LIMIT ?
    """
    return pd.read_sql_query(query, conn, params=(limit,))


def get_today_metrics(conn: sqlite3.Connection) -> tuple[float, float]:
    today_prefix = datetime.now().date().isoformat() + "%"
    cursor = conn.execute(
        """
        SELECT
            COALESCE(SUM(CASE WHEN record_type = 'calories_burned' THEN value_num ELSE 0 END), 0),
            COALESCE(SUM(CASE WHEN record_type = 'water_ml' THEN value_num ELSE 0 END), 0)
        FROM records
        WHERE created_at LIKE ?
        """,
        (today_prefix,),
    )
    calories, water_ml = cursor.fetchone()
    return float(calories), float(water_ml)


class WebhookHandler(BaseHTTPRequestHandler):
    def _send_json(self, status_code: int, payload: dict) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self) -> None:
        if self.path != "/webhook":
            self._send_json(404, {"ok": False, "error": "Not found"})
            return

        content_length = int(self.headers.get("Content-Length", "0"))
        raw_body = self.rfile.read(content_length)

        try:
            payload = json.loads(raw_body.decode("utf-8"))
            workout_type = str(payload["workout_type"]).strip()
            calories = float(payload["calories"])
            duration = float(payload["duration"])
            if not workout_type:
                raise ValueError("workout_type is empty")
            if calories < 0 or duration < 0:
                raise ValueError("calories/duration must be >= 0")
        except (KeyError, ValueError, json.JSONDecodeError) as exc:
            self._send_json(400, {"ok": False, "error": f"Invalid payload: {exc}"})
            return

        conn = get_connection()
        init_db(conn)
        insert_workout(conn, workout_type, calories, duration)
        conn.close()
        self._send_json(200, {"ok": True})

    def log_message(self, format: str, *args) -> None:
        return


def start_webhook_server() -> None:
    global WEBHOOK_STARTED
    with WEBHOOK_LOCK:
        if WEBHOOK_STARTED:
            return

        def run_server() -> None:
            server = ThreadingHTTPServer(("0.0.0.0", WEBHOOK_PORT), WebhookHandler)
            server.serve_forever()

        server_thread = threading.Thread(target=run_server, daemon=True)
        server_thread.start()
        WEBHOOK_STARTED = True


def get_recent_records(conn: sqlite3.Connection, limit: int = 10) -> pd.DataFrame:
    query = """
        SELECT created_at, record_type, value_num, note
        FROM records
        ORDER BY id DESC
        LIMIT ?
    """
    df = pd.read_sql_query(query, conn, params=(limit,))
    if df.empty:
        return df

    type_label_map = {
        "water_ml": "飲水",
        "food_note": "飲食",
        "calories_burned": "運動",
    }
    df["record_type"] = df["record_type"].map(type_label_map).fillna(df["record_type"])
    df = df.rename(
        columns={
            "created_at": "時間",
            "record_type": "類型",
            "value_num": "數值",
            "note": "內容",
        }
    )
    return df


def main() -> None:
    st.set_page_config(page_title="MyHealthVibe 健康儀表板", page_icon="💪", layout="wide")
    st.title("💪 MyHealthVibe 健康儀表板")
    st.caption(f"Webhook Endpoint 已啟用：`http://localhost:{WEBHOOK_PORT}/webhook`")

    conn = get_connection()
    init_db(conn)
    conn.close()

    st.sidebar.header("紀錄功能")

    with st.sidebar.form("water_form", clear_on_submit=True):
        st.subheader("飲水紀錄")
        water_ml = st.number_input("飲水量 (ml)", min_value=0, step=50)
        water_submit = st.form_submit_button("新增飲水")
        if water_submit and water_ml > 0:
            conn = get_connection()
            insert_record(conn, "water_ml", float(water_ml), "手動輸入飲水")
            conn.close()
            st.sidebar.success("已新增飲水紀錄")

    with st.sidebar.form("food_form", clear_on_submit=True):
        st.subheader("飲食文字紀錄")
        food_note = st.text_area("今天吃了什麼？")
        food_submit = st.form_submit_button("新增飲食")
        if food_submit and food_note.strip():
            conn = get_connection()
            insert_record(conn, "food_note", None, food_note.strip())
            conn.close()
            st.sidebar.success("已新增飲食紀錄")

    with st.sidebar.form("exercise_form", clear_on_submit=True):
        st.subheader("手動運動紀錄")
        exercise_note = st.text_input("運動內容")
        calories_burned = st.number_input("消耗卡路里 (kcal)", min_value=0, step=10)
        exercise_submit = st.form_submit_button("新增運動")
        if exercise_submit and exercise_note.strip():
            conn = get_connection()
            insert_record(conn, "calories_burned", float(calories_burned), exercise_note.strip())
            conn.close()
            st.sidebar.success("已新增運動紀錄")

    # Auto refresh every 5s so webhook data appears without manual action.
    @st.fragment(run_every="5s")
    def live_dashboard() -> None:
        conn = get_connection()
        calories_today, water_today = get_today_metrics(conn)
        st.subheader("今日總結")
        metric_col1, metric_col2 = st.columns(2)
        metric_col1.metric("總消耗卡路里 (kcal)", f"{calories_today:.0f}")
        metric_col2.metric("總飲水量 (ml)", f"{water_today:.0f}")

        st.subheader("最近 10 筆歷史紀錄")
        recent_df = get_recent_records(conn, limit=10)
        if recent_df.empty:
            st.info("目前沒有紀錄，請先在側邊欄新增資料。")
        else:
            st.dataframe(recent_df, use_container_width=True, hide_index=True)

        st.subheader("最近 10 筆 Workout Webhook 紀錄")
        workout_df = get_recent_workouts(conn, limit=10)
        if workout_df.empty:
            st.info("目前沒有 webhook workout 紀錄。")
        else:
            st.dataframe(workout_df, use_container_width=True, hide_index=True)
        conn.close()

    live_dashboard()


# Start webhook as soon as module is loaded by Streamlit.
start_webhook_server()


if __name__ == "__main__":
    main()
