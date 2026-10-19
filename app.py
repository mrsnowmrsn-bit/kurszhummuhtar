import csv
import datetime
import hashlib
import io
import sqlite3
import pandas as pd
import plotly.express as px
import streamlit as st

# =========================================================
# 1. PAGE CONFIG & MODERN DARK/LIGHT SYSTEM STYLES
# =========================================================
st.set_page_config(
    page_title="Университет: Электрондық Журнал АЖ",
    page_icon="🎓",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    /* Негізгі фон мен қаріптер */
    .stApp {
        background-color: #f8fafc;
        font-family: 'Inter', sans-serif;
    }
    
    /* Басқару панелінің стилі */
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, #0f172a 0%, #1e293b 100%);
        box-shadow: 4px 0 15px rgba(0,0,0,0.1);
    }
    [data-testid="stSidebar"] * {
        color: #f8fafc !important;
    }
    
    /* Карточкалар мен контейнерлер */
    .custom-card {
        background: #ffffff;
        padding: 24px;
        border-radius: 16px;
        border: 1px solid #e2e8f0;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -1px rgba(0, 0, 0, 0.03);
        margin-bottom: 20px;
    }
    
    /* Метрикалық карточкалар */
    .stat-card {
        background: linear-gradient(135deg, #ffffff 0%, #f1f5f9 100%);
        border-left: 5px solid #2563eb;
        padding: 18px 20px;
        border-radius: 12px;
        box-shadow: 0 2px 8px rgba(0,0,0,0.04);
    }
    .stat-title {
        font-size: 0.875rem;
        color: #64748b;
        font-weight: 600;
        text-transform: uppercase;
    }
    .stat-value {
        font-size: 1.875rem;
        color: #0f172a;
        font-weight: 800;
        margin-top: 4px;
    }
    
    /* Батырмалар стилі */
    .stButton>button {
        border-radius: 8px;
        font-weight: 600;
        transition: all 0.2s ease;
    }
    
    /* Кесте стилі */
    .styled-table {
        width: 100%;
        border-collapse: collapse;
        margin: 15px 0;
        font-size: 0.9em;
        border-radius: 8px 8px 0 0;
        overflow: hidden;
    }
</style>
""",
    unsafe_allow_html=True,
)

# =========================================================
# 2. DATABASE INITIALIZATION & TRANSACTIONS (1NF, 2NF, 3NF)
# =========================================================
DB_NAME = "university_portal.db"


def get_connection():
  conn = sqlite3.connect(DB_NAME, timeout=10)
  conn.execute("PRAGMA foreign_keys = ON;")
  return conn


def hash_password(password: str) -> str:
  return hashlib.sha256(password.encode("utf-8")).hexdigest()


def init_db():
  conn = get_connection()
  cursor = conn.cursor()

  # 1. Пайдаланушылар кестесі (Авторизация + Рөлдер)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT UNIQUE NOT NULL,
            password_hash TEXT NOT NULL,
            full_name TEXT NOT NULL,
            role TEXT CHECK(role IN ('ADMIN', 'TEACHER', 'STUDENT')) NOT NULL
        )
    """)

  # 2. Студенттер кестесі (3NF сақталған)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS students (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER UNIQUE,
            student_code TEXT UNIQUE NOT NULL,
            full_name TEXT NOT NULL,
            group_name TEXT NOT NULL,
            course_num INTEGER NOT NULL,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE SET NULL
        )
    """)

  # 3. Пәндер кестесі
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS subjects (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            subject_name TEXT UNIQUE NOT NULL,
            credits INTEGER DEFAULT 3
        )
    """)

  # 4. Бағалар мен қатысу журналы (Triggers/Indexes)
  cursor.execute("""
        CREATE TABLE IF NOT EXISTS grades (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            student_id INTEGER NOT NULL,
            subject_id INTEGER NOT NULL,
            grade INTEGER CHECK(grade >= 0 AND grade <= 100),
            attendance TEXT CHECK(attendance IN ('Қатысты', 'Қатыспады', 'Себепті')) NOT NULL,
            lesson_date TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (student_id) REFERENCES students(id) ON DELETE CASCADE,
            FOREIGN KEY (subject_id) REFERENCES subjects(id) ON DELETE CASCADE
        )
    """)

  # Индекстер құру (Өнімділікті арттыру)
  cursor.execute(
      "CREATE INDEX IF NOT EXISTS idx_grades_student ON grades(student_id);"
  )
  cursor.execute(
      "CREATE INDEX IF NOT EXISTS idx_grades_subject ON grades(subject_id);"
  )

  # Бастапқы әкімші аккаунтын құру (егер жоқ болса)
  cursor.execute("SELECT COUNT(*) FROM users WHERE role = 'ADMIN'")
  if cursor.fetchone()[0] == 0:
    admin_pass = hash_password("admin123")
    cursor.execute(
        "INSERT INTO users (username, password_hash, full_name, role) VALUES"
        " (?, ?, ?, ?)",
        ("admin", admin_pass, "Бас Администратор (Деканат)", "ADMIN"),
    )

    # Әдепкі пәндер
    default_subs = [
        ("C# және .NET Тұғырнамасы", 5),
        ("Microsoft SQL Server Деректер Қоры", 5),
        ("Веб-бағдарламалау (Python/Streamlit)", 4),
        ("Алгоритмдер мен деректер құрылымы", 4),
    ]
    cursor.executemany(
        "INSERT OR IGNORE INTO subjects (subject_name, credits) VALUES (?, ?)",
        default_subs,
    )

  conn.commit()
  conn.close()


init_db()

# Session state инициализациясы
if "logged_in" not in st.session_state:
  st.session_state.logged_in = False
if "user_info" not in st.session_state:
  st.session_state.user_info = None

# =========================================================
# 3. AUTHENTICATION (АВТОРИЗАЦИЯ ЖӘНЕ ТІРКЕЛУ)
# =========================================================
if not st.session_state.logged_in:
  col1, col2, col3 = st.columns([1, 2, 1])
  with col2:
    st.markdown("<br><br>", unsafe_allow_html=True)
    st.markdown(
        """
        <div class="custom-card" style="text-align: center;">
            <h1 style="color:#0f172a; margin-bottom: 5px;">🎓 Университет АЖ</h1>
            <p style="color:#64748b;">Электрондық журнал және үлгерім порталы</p>
        </div>
        """,
        unsafe_allow_html=True,
    )

    tab_login, tab_register = st.tabs(
        ["🔐 Жүйеге кіру", "📝 Пайдаланушыны тіркеу"]
    )

    with tab_login:
      with st.form("login_form"):
        username = st.text_input("Пайдаланушы аты (Username)")
        password = st.text_input("Пароль", type="password")
        submit_login = st.form_submit_button(
            "Кіру", use_container_width=True, type="primary"
        )

        if submit_login:
          conn = get_connection()
          cursor = conn.cursor()
          cursor.execute(
              "SELECT id, username, full_name, role FROM users WHERE username = ?"
              " AND password_hash = ?",
              (username, hash_password(password)),
          )
          user = cursor.fetchone()
          conn.close()

          if user:
            st.session_state.logged_in = True
            st.session_state.user_info = {
                "id": user[0],
                "username": user[1],
                "full_name": user[2],
                "role": user[3],
            }
            st.success(f"Қош келдіңіз, {user[2]}!")
            st.rerun()
          else:
            st.error("Пайдаланушы аты немесе пароль қате!")

    with tab_register:
      with st.form("register_form"):
        reg_username = st.text_input("Жаңа пайдаланушы аты")
        reg_fullname = st.text_input("Толық Аты-Жөні")
        reg_password = st.text_input("Пароль", type="password")
        reg_role = st.selectbox(
            "Рөлі",
            ["TEACHER", "STUDENT"],
            format_func=lambda x: (
                "Оқытушы" if x == "TEACHER" else "Студент"
            ),
        )

        # Студент болса қосымша өрістер
        reg_group = st.text_input("Топ (Студент үшін)", value="ИС-301")
        reg_course = st.number_input("Курс", min_value=1, max_value=5, value=3)

        submit_reg = st.form_submit_button(
            "Тіркелу", use_container_width=True
        )

        if submit_reg:
          if reg_username and reg_fullname and reg_password:
            try:
              conn = get_connection()
              cursor = conn.cursor()
              # Транзакция бастау
              cursor.execute("BEGIN TRANSACTION;")
              cursor.execute(
                  "INSERT INTO users (username, password_hash, full_name, role)"
                  " VALUES (?, ?, ?, ?)",
                  (
                      reg_username,
                      hash_password(reg_password),
                      reg_fullname,
                      reg_role,
                  ),
              )
              user_id = cursor.lastrowid

              if reg_role == "STUDENT":
                stud_code = f"ST-{user_id:04d}"
                cursor.execute(
                    "INSERT INTO students (user_id, student_code, full_name,"
                    " group_name, course_num) VALUES (?, ?, ?, ?, ?)",
                    (
                        user_id,
                        stud_code,
                        reg_fullname,
                        reg_group,
                        reg_course,
                    ),
                )

              conn.commit()
              conn.close()
              st.success("Тіркелу сәтті аяқталды! Енді жүйеге кіре аласыз.")
            except sqlite3.IntegrityError:
              st.error(
                  "Бұл пайдаланушы аты бос емес! Басқа аталды таңдаңыз."
              )
            except Exception as e:
              st.error(f"Қате орын алды: {e}")
          else:
            st.warning("Барлық өрістерді толтырыңыз!")
  st.stop()

# =========================================================
# 4. SIDEBAR NAVIGATION & USER ROLE CONTROL
# =========================================================
user = st.session_state.user_info

with st.sidebar:
  st.markdown(
      f"""
    <div style="text-align: center; padding: 10px 0;">
        <div style="font-size: 50px;">🎓</div>
        <h3 style="margin:0;">{user['full_name']}</h3>
        <span style="background: #2563eb; padding: 3px 10px; border-radius: 12px; font-size: 0.8em;">
            {user['role']}
        </span>
    </div>
    """,
      unsafe_allow_html=True,
  )
  st.markdown("---")

  if user["role"] == "ADMIN":
    menu = [
        "📊 Басқару Панелі",
        "👨‍🎓 Студенттерді Басқару",
        "📚 Пәндер Тізімі",
        "💾 Деректерді Резервтеу (Backup)",
    ]
  elif user["role"] == "TEACHER":
    menu = [
        "📝 Электрондық Журнал",
        "📊 Үлгерім Аналитикасы",
        "📥 Экспорттау (Excel/CSV)",
    ]
  else:  # STUDENT
    menu = ["📖 Мой Журнал (Үлгерім)", "📈 Статистика"]

  choice = st.sidebar.radio("Мәзір:", menu)

  st.markdown("---")
  if st.button("🚪 Жүйеден шығу", use_container_width=True):
    st.session_state.logged_in = False
    st.session_state.user_info = None
    st.rerun()

# =========================================================
# 5. ADMIN MODULE (ДЕКАНАТ)
# =========================================================
if user["role"] == "ADMIN":

  if choice == "📊 Басқару Панелі":
    st.title("📊 Деканат: Басқару Панелі")

    conn = get_connection()
    df_students = pd.read_sql_query("SELECT * FROM students", conn)
    df_subjects = pd.read_sql_query("SELECT * FROM subjects", conn)
    df_grades = pd.read_sql_query("SELECT * FROM grades", conn)
    conn.close()

    c1, c2, c3, c4 = st.columns(4)
    with c1:
      st.markdown(
          f'<div class="stat-card"><div'
          ' class="stat-title">Студенттер</div><div'
          f' class="stat-value">{len(df_students)}</div></div>',
          unsafe_allow_html=True,
      )
    with c2:
      st.markdown(
          f'<div class="stat-card"><div class="stat-title">Оқу'
          ' топтары</div><div'
          f' class="stat-value">{df_students["group_name"].nunique() if not df_students.empty else 0}</div></div>',
          unsafe_allow_html=True,
      )
    with c3:
      st.markdown(
          f'<div class="stat-card"><div class="stat-title">Пәндер</div><div'
          f' class="stat-value">{len(df_subjects)}</div></div>',
          unsafe_allow_html=True,
      )
    with c4:
      avg_g = (
          round(df_grades["grade"].mean(), 1) if not df_grades.empty else 0
      )
      st.markdown(
          f'<div class="stat-card"><div class="stat-title">Орташа'
          f' баға</div><div class="stat-value">{avg_g}</div></div>',
          unsafe_allow_html=True,
      )

    st.markdown("### 📈 Топтар бойынша студенттер саны")
    if not df_students.empty:
      fig = px.bar(
          df_students["group_name"].value_counts().reset_index(),
          x="group_name",
          y="count",
          labels={"group_name": "Топ Атауы", "count": "Студент Саны"},
          color="group_name",
          title="Топтардағы студенттер үлесі",
      )
      st.plotly_chart(fig, use_container_width=True)

  elif choice == "👨‍🎓 Студенттерді Басқару":
    st.title("👨‍🎓 Студенттерді Басқару (CRUD)")

    tab_list, tab_add = st.tabs(
        ["📋 Студенттер Тізімі (Өңдеу/Жою)", "➕ Жаңа Студент Қосу"]
    )

    with tab_list:
      conn = get_connection()
      df_s = pd.read_sql_query(
          "SELECT id, student_code, full_name, group_name, course_num FROM"
          " students",
          conn,
      )
      conn.close()

      # Іздеу және Сүзгілеу
      search = st.text_input(
          "🔍 Аты-жөні немесе Студенттік код бойынша іздеу:"
      )
      if search:
        df_s = df_s[
            df_s["full_name"].str.contains(search, case=False)
            | df_s["student_code"].str.contains(search, case=False)
        ]

      st.dataframe(df_s, use_container_width=True)

      st.markdown("---")
      st.subheader("🗑️ Студентті өшіру / Өңдеу")
      col_del1, col_del2 = st.columns(2)
      with col_del1:
        del_id = st.number_input("Жойылатын студенттің ID дубликаты:", min_value=1, step=1)
        if st.button("Студентті жою", type="primary"):
          conn = get_connection()
          cursor = conn.cursor()
          cursor.execute("DELETE FROM students WHERE id = ?", (del_id,))
          conn.commit()
          conn.close()
          st.success(f"ID {del_id} студенті сәтті жойылды!")
          st.rerun()

    with tab_add:
      with st.form("admin_add_student"):
        s_code = st.text_input("Студент коды (Мысалы: ST-1001)")
        s_name = st.text_input("Аты-Жөні")
        s_group = st.text_input("Тобы", value="ИС-301")
        s_course = st.number_input("Курс", min_value=1, max_value=5, value=3)
        submit = st.form_submit_button("Сақтау")

        if submit and s_code and s_name:
          conn = get_connection()
          cursor = conn.cursor()
          try:
            cursor.execute(
                "INSERT INTO students (student_code, full_name, group_name,"
                " course_num) VALUES (?, ?, ?, ?)",
                (s_code, s_name, s_group, s_course),
            )
            conn.commit()
            st.success("Студент сәтті қосылды!")
          except Exception as e:
            st.error(f"Қате: {e}")
          finally:
            conn.close()

  elif choice == "💾 Деректерді Резервтеу (Backup)":
    st.title("💾 Деректер қорын резервтеу және қалпына келтіру")
    st.info(
        "Бұл модуль Деректер қорының (ACID / Backup) қауіпсіздігін қамтамасыз"
        " етеді."
    )

    with open(DB_NAME, "rb") as f:
      st.download_button(
          label="📦 Базаның резервтік көшірмесін жүктеу (.db)",
          data=f,
          file_name=f"backup_university_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
          mime="application/x-sqlite3",
          use_container_width=True,
      )

# =========================================================
# 6. TEACHER MODULE (ОҚЫТУШЫ)
# =========================================================
elif user["role"] == "TEACHER":

  if choice == "📝 Электрондық Журнал":
    st.title("📝 Электрондық Журнал Толтыру")

    conn = get_connection()
    students_df = pd.read_sql_query(
        "SELECT id, full_name, group_name FROM students", conn
    )
    subjects_df = pd.read_sql_query("SELECT id, subject_name FROM subjects", conn)
    conn.close()

    if students_df.empty:
      st.warning(
          "⚠️ Жүйеде бірде-бір студент тіркелмеген! Алдымен Деканат модулі"
          " арқылы немесе Тіркелу арқылы студент қосыңыз."
      )
    elif subjects_df.empty:
      st.warning(
          "⚠️ Деректер қорында пәндер жоқ! Базаны тексеріңіз немесе пән қосыңыз."
      )
    else:
      col_form1, col_form2 = st.columns([1, 1])

      with col_form1:
        st.markdown('<div class="custom-card">', unsafe_allow_html=True)
        st.subheader("📌 Баға және қатысу енгізу")
        with st.form("mark_form"):
          subject_sel = st.selectbox(
              "Пәнді таңдаңыз:",
              subjects_df["subject_name"].tolist(),
          )
          group_sel = st.selectbox(
              "Топты таңдаңыз:",
              students_df["group_name"].unique().tolist(),
          )

          filtered_students = students_df[
              students_df["group_name"] == group_sel
          ]

          if filtered_students.empty:
            st.error("Бұл топта студенттер жоқ!")
            student_sel = None
          else:
            student_sel = st.selectbox(
                "Студентті таңдаңыз:",
                filtered_students["full_name"].tolist(),
            )

          grade_val = st.slider(
              "Бағасы (0 - 100):", min_value=0, max_value=100, value=85
          )
          att_val = st.radio(
              "Қатысуы:",
              ["Қатысты", "Қатыспады", "Себепті"],
              horizontal=True,
          )
          date_val = st.date_input("Күні:", datetime.date.today())

          btn_save = st.form_submit_button(
              "💾 Журналға Жаппай Сақтау", use_container_width=True
          )

          if btn_save and student_sel:
            s_id = int(
                filtered_students[
                    filtered_students["full_name"] == student_sel
                ]["id"].values[0]
            )
            sub_id = int(
                subjects_df[
                    subjects_df["subject_name"] == subject_sel
                ]["id"].values[0]
            )

            conn = get_connection()
            cursor = conn.cursor()
            try:
              cursor.execute(
                  """
                                INSERT INTO grades (student_id, subject_id, grade, attendance, lesson_date)
                                VALUES (?, ?, ?, ?, ?)
                            """,
                  (s_id, sub_id, grade_val, att_val, str(date_val)),
              )
              conn.commit()
              st.success("Жазба сәтті сақталды!")
              st.rerun()
            except Exception as e:
              st.error(f"ДҚ қатесі: {e}")
            finally:
              conn.close()
        st.markdown("</div>", unsafe_allow_html=True)

      with col_form2:
        st.subheader("📋 Соңғы енгізілген бағалар")
        conn = get_connection()
        query = """
                SELECT g.id, s.full_name, sub.subject_name, g.grade, g.attendance, g.lesson_date 
                FROM grades g
                JOIN students s ON g.student_id = s.id
                JOIN subjects sub ON g.subject_id = sub.id
                ORDER BY g.id DESC LIMIT 10
            """
        recent_df = pd.read_sql_query(query, conn)
        conn.close()
        st.dataframe(recent_df, use_container_width=True)

  elif choice == "📊 Үлгерім Аналитикасы":
    st.title("📊 Үлгерім Аналитикасы мен Графиктер")
    conn = get_connection()
    query = """
            SELECT s.full_name, s.group_name, sub.subject_name, g.grade, g.attendance, g.lesson_date 
            FROM grades g
            JOIN students s ON g.student_id = s.id
            JOIN subjects sub ON g.subject_id = sub.id
        """
    df_all = pd.read_sql_query(query, conn)
    conn.close()

    if not df_all.empty:
      col_g1, col_g2 = st.columns(2)
      with col_g1:
        fig1 = px.histogram(
            df_all,
            x="grade",
            nbins=20,
            title="Бағалардың таралу гистограммасы",
            color_discrete_sequence=["#2563eb"],
        )
        st.plotly_chart(fig1, use_container_width=True)
      with col_g2:
        fig2 = px.pie(
            df_all,
            names="attendance",
            title="Қатысым статистикасы (Пайызбен)",
            color_discrete_sequence=px.colors.sequential.RdBu,
        )
        st.plotly_chart(fig2, use_container_width=True)
    else:
      st.info("Аналитика үшін әлі деректер енгізілмеген.")

  elif choice == "📥 Экспорттау (Excel/CSV)":
    st.title("📥 Журналды Экспорттау")
    conn = get_connection()
    query = """
            SELECT s.student_code, s.full_name, s.group_name, sub.subject_name, g.grade, g.attendance, g.lesson_date 
            FROM grades g
            JOIN students s ON g.student_id = s.id
            JOIN subjects sub ON g.subject_id = sub.id
        """
    df_exp = pd.read_sql_query(query, conn)
    conn.close()

    if not df_exp.empty:
      st.dataframe(df_exp, use_container_width=True)

      col_ex1, col_ex2 = st.columns(2)
      with col_ex1:
        csv_data = df_exp.to_csv(index=False).encode("utf-8-sig")
        st.download_button(
            "📄 CSV форматында жүктеу",
            data=csv_data,
            file_name="journal_export.csv",
            mime="text/csv",
            use_container_width=True,
        )
      with col_ex2:
        output = io.BytesIO()
        with pd.ExcelWriter(output, engine="openpyxl") as writer:
          df_exp.to_excel(writer, index=False, sheet_name="Журнал")
        excel_data = output.getvalue()
        st.download_button(
            "📊 Excel (.xlsx) форматында жүктеу",
            data=excel_data,
            file_name="journal_export.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            use_container_width=True,
        )
    else:
      st.info("Экспорттауға келетін деректер жоқ.")
# =========================================================
# 7. STUDENT MODULE (СТУДЕНТ)
# =========================================================
else:
  st.title(f"📖 Жеке Кабинет: {user['full_name']}")

  conn = get_connection()
  # Студент ID-сін табу
  cursor = conn.cursor()
  cursor.execute(
      "SELECT id, student_code, group_name FROM students WHERE user_id = ?",
      (user["id"],),
  )
  stud_data = cursor.fetchone()

  if stud_data:
    stud_id, stud_code, group_name = stud_data
    st.info(f"Студент Коды: **{stud_code}** | Топ: **{group_name}**")

    query = """
            SELECT sub.subject_name AS 'Пән', g.grade AS 'Баға', g.attendance AS 'Қатысуы', g.lesson_date AS 'Күні'
            FROM grades g
            JOIN subjects sub ON g.subject_id = sub.id
            WHERE g.student_id = ?
            ORDER BY g.lesson_date DESC
        """
    my_grades = pd.read_sql_query(query, conn, params=(stud_id,))
    conn.close()

    if choice == "📖 Мой Журнал (Үлгерім)":
      st.subheader("📝 Меңгерілген бағалар тізімі")
      if not my_grades.empty:
        st.dataframe(my_grades, use_container_width=True)
      else:
        st.warning("Сізге әлі баға қойылмаған.")

    elif choice == "📈 Статистика":
      st.subheader("📈 Жеке үлгерім динамикасы")
      if not my_grades.empty:
        avg_student_grade = my_grades["Баға"].mean()
        st.metric("Сіздің орташа балыңыз:", f"{avg_student_grade:.1f} / 100")

        fig = px.line(
            my_grades,
            x="Күні",
            y="Баға",
            color="Пән",
            title="Пәндер бойынша бағалар өзгерісі",
            markers=True,
        )
        st.plotly_chart(fig, use_container_width=True)
  else:
    st.warning("Сіздің аккаунтыңыз студенттер базасымен байланыстырылмаған.")
    conn.close()