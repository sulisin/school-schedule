import streamlit as st
import pandas as pd
from sqlalchemy import create_engine, text
import datetime
import re
import time
import streamlit.components.v1 as components

# ==========================================
# 🔑 Supabase 雲端資料庫連線設定
# ==========================================
DATABASE_URL = "postgresql://postgres.vccvzbtgzkiyvoowxjlq:Tsshs-011329@aws-0-ap-northeast-1.pooler.supabase.com:6543/postgres"

if DATABASE_URL.startswith("postgresql://"):
    DATABASE_URL = DATABASE_URL.replace("postgresql://", "postgresql+psycopg2://", 1)

@st.cache_resource
def get_db_engine():
    return create_engine(DATABASE_URL, pool_pre_ping=True)

engine = get_db_engine()

def run_query(query, params=None):
    with engine.connect() as conn:
        return pd.read_sql(text(query), conn, params=params)

def run_action(query, params=None):
    with engine.begin() as conn:
        conn.execute(text(query), params or {})

# ========================================================
# ⚡ 記憶體極速快取
# ========================================================
def to_arabic_class(name):
    if not name: return ""
    num_map = {'一': '1', '二': '2', '三': '3', '四': '4', '五': '5', '六': '6'}
    match = re.search(r'([一二三四五六])年(\d+)班', name)
    return f"{num_map[match.group(1)]}{int(match.group(2)):02d}" if match else name

@st.cache_data(ttl=600)
def get_base_schedule_cached():
    return run_query("SELECT * FROM base_schedule")

@st.cache_data(ttl=600)
def get_user_credentials_cached():
    return run_query("SELECT emp_id, password, real_name, role FROM user_credentials")

base_schedule_df = get_base_schedule_cached()
all_classes = sorted(list(set(base_schedule_df['class_name'].dropna().tolist())), key=to_arabic_class)
all_teachers_in_db = sorted(list(set(base_schedule_df['teacher_name'].dropna().tolist())))

# ========================================================
# 網頁基本設定與樣式
# ========================================================
st.set_page_config(page_title="辭修中學調代課系統", layout="wide")
st.markdown("""
    <style>
    .stTabs [data-baseweb="tab-list"] { flex-wrap: wrap !important; gap: 5px; }
    .stTabs [data-baseweb="tab-list"] button [data-testid="stMarkdownContainer"] p { font-size: 16px; font-weight: bold; }
    </style>
""", unsafe_allow_html=True)
st.subheader("🏫 辭修中學調代課系統")

REAL_TODAY_STR = datetime.date.today().strftime('%Y-%m-%d')

def send_notification(target_user, message):
    if target_user and target_user != "教務處":
        run_action(
            "INSERT INTO notifications (target_user, message) VALUES (:t, :m)",
            {"t": target_user, "m": message}
        )

# ========================================================
# 🔑 原生網址記憶登入系統 (免套件、重整免重登、無殘影)
# ========================================================
if 'logged_in' not in st.session_state: st.session_state.logged_in = False
if 'user_name' not in st.session_state: st.session_state.user_name = ""
if 'user_id' not in st.session_state: st.session_state.user_id = ""

# 檢查網址列是否有登入憑證 (F5 重整時自動恢復登入)
if not st.session_state.logged_in:
    url_user_id = st.query_params.get("u", "")
    if url_user_id:
        users_df = get_user_credentials_cached()
        user_match = users_df[users_df['emp_id'].str.upper() == url_user_id.upper()]
        if not user_match.empty:
            st.session_state.logged_in = True
            st.session_state.user_id = url_user_id.upper()
            st.session_state.user_name = user_match.iloc[0]['real_name']

# 若未登入，只渲染登入頁面並徹底停止後續執行 (消滅所有殘影)
if not st.session_state.logged_in:
    st.markdown("### 🔐 歡迎使用，請輸入帳號密碼登入")
    col_l1, col_l2 = st.columns(2)
    with col_l1: 
        input_emp_id = st.text_input("👤 請輸入您的員工編號（帳號）：", placeholder="例如: T001 或 ADMIN").strip()
    with col_l2: 
        input_pwd = st.text_input("🔑 請輸入密碼：", type="password", placeholder="請輸入您的密碼")
    
    if st.button("🔓 驗證登入", type="primary"):
        if not input_emp_id or not input_pwd: 
            st.error("❌ 帳號與密碼皆不能為空白！")
        else:
            users_df = get_user_credentials_cached()
            user_match = users_df[users_df['emp_id'].str.upper() == input_emp_id.upper()]
            if not user_match.empty and str(user_match.iloc[0]['password']) == str(input_pwd):
                st.session_state.logged_in = True
                st.session_state.user_id = input_emp_id.upper()
                st.session_state.user_name = user_match.iloc[0]['real_name']
                
                # 寫入網址參數，確保 F5 重整免重新登入
                st.query_params["u"] = input_emp_id.upper()
                st.rerun()
            else: 
                st.error("❌ 登入失敗：員工編號或密碼錯誤。")
    st.stop()  # 強制中斷，確保絕不會跟主系統畫面疊加

# ========================================================
# 📅 核心邏輯區
# ========================================================
def get_week_day_zh(date_obj): return {0: '一', 1: '二', 2: '三', 3: '四', 4: '五', 5: '六', 6: '日'}[date_obj.weekday()]
def get_actual_date_of_weekday(base_date, target_weekday_zh):
    target_idx = {'一': 0, '二': 1, '三': 2, '四': 3, '五': 4}.get(target_weekday_zh, 0)
    return base_date + datetime.timedelta(days=target_idx - base_date.weekday())

def sort_lessons_dataframe(df):
    if not df.empty:
        df['w_sort'] = df['week_day'].map({'一': 1, '二': 2, '三': 3, '四': 4, '五': 5, '六': 6, '日': 7})
        df['p_sort'] = pd.to_numeric(df['period'], errors='coerce')
        df = df.sort_values(['w_sort', 'p_sort']).reset_index(drop=True)
    return df

def get_consecutive_block(teacher_name, date_val, new_period_str):
    date_str = date_val if isinstance(date_val, str) else date_val.strftime('%Y-%m-%d')
    date_obj = datetime.datetime.strptime(date_str, '%Y-%m-%d').date() if isinstance(date_val, str) else date_val
    week_day_zh = get_week_day_zh(date_obj)
    
    base_df = base_schedule_df[(base_schedule_df['teacher_name'] == teacher_name) & (base_schedule_df['week_day'] == week_day_zh)]
    base_periods = set(base_df['period'].astype(int).tolist()) if not base_df.empty else set()
    
    swapped_out = run_query(
        "SELECT period FROM temp_swaps WHERE swap_date=:d AND original_teacher=:t AND status IN ('approved', 'approved_sub', 'pending_admin')",
        {"d": date_str, "t": teacher_name}
    )
    swapped_in = run_query(
        "SELECT period FROM temp_swaps WHERE swap_date=:d AND new_teacher=:t AND status IN ('approved', 'approved_sub', 'pending_admin')",
        {"d": date_str, "t": teacher_name}
    )
    
    out_set = set(swapped_out['period'].astype(int).tolist()) if not swapped_out.empty else set()
    in_set = set(swapped_in['period'].astype(int).tolist()) if not swapped_in.empty else set()
    
    final_periods = (base_periods - out_set) | in_set
    new_p = int(new_period_str)
    final_periods.add(new_p)
    periods = sorted(list(final_periods))
    
    if new_p not in periods: return 0, 0, 0
    start_p = end_p = new_p
    while start_p - 1 in periods: start_p -= 1
    while end_p + 1 in periods: end_p += 1
    return (end_p - start_p + 1), start_p, end_p

# ========================================================
# 側邊欄控制與 🔔 站內通知中心
# ========================================================
st.sidebar.markdown(f"👤 **目前登入：{st.session_state.user_name}**")
st.sidebar.markdown(f"🪪 **員工編號：{st.session_state.user_id}**")

if st.session_state.user_id == "ADMIN":
    unread_df = run_query("SELECT COUNT(DISTINCT group_id) as cnt FROM temp_swaps WHERE status = 'pending_admin'")
    unread_count = unread_df.iloc[0]['cnt'] if not unread_df.empty else 0
    my_notifs = pd.DataFrame()
else:
    unread_df = run_query("SELECT COUNT(*) as cnt FROM notifications WHERE target_user = :t AND is_read = 0", {"t": st.session_state.user_name})
    unread_count = unread_df.iloc[0]['cnt'] if not unread_df.empty else 0
    my_notifs = run_query("SELECT id, message FROM notifications WHERE target_user = :t AND is_read = 0 ORDER BY id DESC", {"t": st.session_state.user_name})

st.sidebar.markdown("---")
with st.sidebar.expander(f"🔔通知 ({unread_count})", expanded=(unread_count > 0)):
    if st.session_state.user_id == "ADMIN":
        if unread_count > 0: st.warning(f"📝 尚有 **{unread_count}** 筆調課單等待審核！\n\n👉 請至【教務處後台】處理。")
        else: st.success("目前無待處理事項。")
    else:
        if my_notifs.empty: st.success("目前沒有新通知。")
        else:
            for _, n in my_notifs.iterrows(): st.info(n['message'])
            if st.button("🧹 全部標為已讀", use_container_width=True):
                run_action("UPDATE notifications SET is_read = 1 WHERE target_user = :t", {"t": st.session_state.user_name})
                st.rerun()

st.sidebar.markdown("---")
if st.sidebar.button("🚪 登出系統", use_container_width=True):
    st.session_state.logged_in, st.session_state.user_id, st.session_state.user_name = False, "", ""
    st.query_params.clear()  # 清空網址憑證
    st.rerun()

st.sidebar.markdown("---")
st.sidebar.header("📅 日期選擇")
min_allowed_date = datetime.date.today() - datetime.timedelta(days=14)
selected_date = st.sidebar.date_input("請選擇查詢日期：", value=datetime.date.today(), min_value=min_allowed_date)
current_weekday = get_week_day_zh(selected_date)
st.sidebar.info(f"💡 當前選定為：星期{current_weekday}")

# ========================================================
# 🎨 HTML 課表渲染引擎
# ========================================================
def render_styled_table_html(df):
    html_code = """<style>.schedule-table { width: 100%; border-collapse: collapse; font-family: 'PingFang TC', sans-serif; margin: 10px 0; background-color: #fff; box-shadow: 0 1px 3px rgba(0,0,0,0.1); } .schedule-table th { background-color: #f8f9fa; color: #495057; font-weight: bold; text-align: center; padding: 12px; border: 1px solid #dee2e6; width: 16%; } .schedule-table th:first-child { width: 10%; background-color: #f1f3f5; color: #495057; } .schedule-table td { padding: 12px; border: 1px solid #dee2e6; text-align: center; vertical-align: middle; font-size: 15px; height: 75px; line-height: 1.5; } .cell-normal { background-color: #ffffff; color: #212529; } .cell-out { background-color: #ffebee; color: #c62828; font-weight: 500; } .cell-in { background-color: #e3f2fd; color: #1565c0; font-weight: bold; } .sub-text { font-size: 13px; color: #6c757d; margin-top: 4px; font-weight: normal; }</style><table class="schedule-table"><thead><tr><th></th><th>一</th><th>二</th><th>三</th><th>四</th><th>五</th></tr></thead><tbody>"""
    for idx, row in df.iterrows():
        html_code += f"<tr><td style='font-weight: bold; background-color: #f1f3f5; color: #495057;'>{idx}</td>"
        for col in ['一', '二', '三', '四', '五']:
            cell_val = str(row[col]).strip()
            if not cell_val: html_code += "<td class='cell-normal'></td>"
            elif "❌" in cell_val: html_code += f"<td class='cell-out'>{cell_val.split('\n')[0]}<br><div class='sub-text'>{'<br>'.join(cell_val.split('\n')[1:])}</div></td>"
            elif "🔄" in cell_val: html_code += f"<td class='cell-in'>{cell_val.split('\n')[0]}<br>{cell_val.split('\n')[1] if len(cell_val.split('\n'))>1 else ''}<div class='sub-text'>{'<br>'.join(cell_val.split('\n')[2:])}</div></td>"
            elif "🔒" in cell_val: html_code += f"<td class='cell-normal' style='background-color: #f1f3f5; color: #868e96;'>{cell_val.split('\n')[0]}<div class='sub-text'>{'<br>'.join(cell_val.split('\n')[1:])}</div></td>"
            else: html_code += f"<td class='cell-normal'>{cell_val.split('\n')[0]}<div class='sub-text'>{'<br>'.join(cell_val.split('\n')[1:])}</div></td>"
        html_code += "</tr>"
    html_code += "</tbody></table>"
    st.markdown(html_code, unsafe_allow_html=True)

def load_merged_timetable(target_date, filter_value, filter_type="teacher"):
    start_of_week = target_date - datetime.timedelta(days=target_date.weekday())
    end_of_week = start_of_week + datetime.timedelta(days=6)
    
    field = "teacher_name" if filter_type == "teacher" else "class_name"
    df_base = base_schedule_df[base_schedule_df[field] == filter_value]
    
    df_swaps = run_query(
        "SELECT period, week_day, original_teacher, new_teacher, original_subject, new_subject, class_name, status FROM temp_swaps WHERE swap_date BETWEEN :s AND :e AND status IN ('approved', 'approved_sub')",
        {"s": start_of_week.strftime('%Y-%m-%d'), "e": end_of_week.strftime('%Y-%m-%d')}
    )
    
    df_locks = run_query(
        "SELECT period, lock_date, reason FROM locked_slots WHERE teacher_name = :t AND lock_date BETWEEN :s AND :e",
        {"t": filter_value, "s": start_of_week.strftime('%Y-%m-%d'), "e": end_of_week.strftime('%Y-%m-%d')}
    ) if filter_type == "teacher" else pd.DataFrame()
    
    timetable = pd.DataFrame("", index=[str(i) for i in range(1, 9)], columns=['一', '二', '三', '四', '五'])
    if not df_base.empty:
        for _, row in df_base.iterrows():
            p, w = str(row['period']), str(row['week_day'])
            if p in timetable.index and w in timetable.columns:
                timetable.loc[p, w] = f"{row['subject']}\n{to_arabic_class(row['class_name'])}" if filter_type == "teacher" else f"{row['subject']}\n{row['teacher_name']}"
                
    if not df_swaps.empty:
        for _, swap in df_swaps.iterrows():
            p, w = str(swap['period']), str(swap['week_day'])
            if p in timetable.index and w in timetable.columns:
                if swap['status'] == 'approved_sub':
                    if filter_type == "teacher":
                        if swap['original_teacher'] == filter_value: timetable.loc[p, w] = f"❌ {swap['new_teacher']}代\n{swap['original_subject']} ({to_arabic_class(swap['class_name'])})"
                        elif swap['new_teacher'] == filter_value: timetable.loc[p, w] = f"🔄 代{swap['original_teacher']}的{swap['original_subject']}課\n{to_arabic_class(swap['class_name'])}"
                    else:
                        if swap['class_name'] == filter_value: timetable.loc[p, w] = f"🔄 {swap['new_teacher']} 代課\n{swap['original_subject']}\n(原: {swap['original_teacher']})"
                else:
                    if filter_type == "teacher":
                        if swap['original_teacher'] == filter_value: timetable.loc[p, w] = "❌ 已調出\n"
                        elif swap['new_teacher'] == filter_value: timetable.loc[p, w] = f"🔄 [調入]\n{swap['new_subject']}\n{to_arabic_class(swap['class_name'])}"
                    else:
                        if swap['class_name'] == filter_value: timetable.loc[p, w] = f"🔄 [調課]\n{swap['new_subject']}\n{swap['new_teacher']}"
                        
    if filter_type == "teacher" and not df_locks.empty:
        for _, l_row in df_locks.iterrows():
            p, w = str(l_row['period']), get_week_day_zh(datetime.datetime.strptime(l_row['lock_date'], '%Y-%m-%d').date())
            if p in timetable.index and w in timetable.columns:
                timetable.loc[p, w] = timetable.loc[p, w] + f"\n🔒 [{l_row['reason']}]" if timetable.loc[p, w] else f"🔒 [{l_row['reason']}]"
                
    timetable.index = [f"第 {i} 節" for i in timetable.index]
    return timetable

# ========================================================
# 🖨️ 列印表單核心引擎
# ========================================================
def generate_slip_card_html(title_type, name, data):
    date_tds = ""
    for w in range(1, 6):
        dates_str = "<br>".join(sorted(list(data['dates'][w])))
        date_tds += f"<td>{dates_str}</td>"
        
    period_trs = ""
    for p in range(1, 9):
        period_trs += f"<tr class='period-cell'><td>第{p}節</td>"
        for w in range(1, 6):
            c_text = "<div style='border-top:1px dashed #ccc; margin:2px 0;'></div>".join(data['grid'][p][w])
            if "調出" in c_text: c_text = c_text.replace("調出", "<span style='font-weight:bold;'>調出</span>")
            elif c_text: c_text = f"<span style='font-weight:bold;'>{c_text}</span>"
            period_trs += f"<td><div class='cell-content'>{c_text}</div></td>"
        period_trs += "</tr>"
        
    if title_type == 'teacher':
        reasons = "、".join(data['reasons']) if data['reasons'] else "行政指派"
        t_type = "、".join(data['type'])
        cb_swap = "☑" if '調' in t_type else "☐"
        cb_sub = "☑" if '代' in t_type else "☐"
        header_html = f"""
        <div class="card-header">
            <div class="title">辭修中學<br>調代課單</div>
            <div class="info">類別：{cb_swap}調 {cb_sub}代<br>原因：{reasons}</div>
            <div class="teacher-name"><span class="name-text">{name}</span><br>老師</div>
        </div>"""
    else:
        header_html = f"""
        <div class="card-header">
            <div class="title" style="font-size: 20px;">辭修中學<br>課表異動單</div>
            <div class="info" style="visibility:hidden;">類別：☑調 ☐代<br>原因：無</div>
            <div class="teacher-name"><span class="name-text">{to_arabic_class(name)}</span><br>班</div>
        </div>"""

    footer_html = '<div style="text-align: right; margin-top: 5px; font-weight: bold; font-size: 14px;">教務處</div>'

    return f"""
    <div class="slip-card">
        {header_html}
        <table class="slip-table">
            <tr class="th-row"><th>時間</th><th>一</th><th>二</th><th>三</th><th>四</th><th>五</th></tr>
            <tr class="date-row"><td>日期</td>{date_tds}</tr>
            {period_trs}
        </table>
        {footer_html}
    </div>
    """

def build_print_html(gids):
    params = {f"g{i}": gid for i, gid in enumerate(gids)}
    param_keys = ",".join([f":g{i}" for i in range(len(gids))])
    df_swaps = run_query(f"SELECT * FROM temp_swaps WHERE group_id IN ({param_keys})", params)

    teacher_data, class_data = {}, {}

    def add_action(data_dict, name, date_str, period, action_text, reason=None, t_type=None):
        if name not in data_dict: 
            data_dict[name] = {'type': set(), 'reasons': set(), 'dates': {w: set() for w in range(1,6)}, 'grid': {p: {w: [] for w in range(1,6)} for p in range(1,9)}}
        dt = datetime.datetime.strptime(date_str, '%Y-%m-%d')
        w = dt.weekday() + 1
        if w > 5: return
        if reason: data_dict[name]['reasons'].add(reason)
        if t_type: data_dict[name]['type'].add(t_type)
        data_dict[name]['dates'][w].add(dt.strftime('%m/%d'))
        data_dict[name]['grid'][int(period)][w].append(action_text)

    for gid in gids:
        rows = df_swaps[df_swaps['group_id'] == gid]
        if rows.empty: continue
        status = rows.iloc[0]['status']
        if status == 'approved_sub':
            r = rows.iloc[0]
            add_action(teacher_data, r['original_teacher'], r['swap_date'], r['period'], "調出", r['reason'], "代")
            add_action(teacher_data, r['new_teacher'], r['swap_date'], r['period'], f"{to_arabic_class(r['class_name'])}<br>{r['original_subject']}", r['reason'], "代")
            add_action(class_data, r['class_name'], r['swap_date'], r['period'], f"{r['original_subject']}<br>代:{r['new_teacher']}")
        else:
            rA_rows = rows[rows['is_initiator']==1]
            rB_rows = rows[rows['is_initiator']==0]
            if rA_rows.empty or rB_rows.empty: continue
            rA, rB = rA_rows.iloc[0], rB_rows.iloc[0]
            
            add_action(teacher_data, rA['original_teacher'], rA['swap_date'], rA['period'], "調出", rA['reason'], "調")
            add_action(teacher_data, rA['original_teacher'], rB['swap_date'], rB['period'], f"{to_arabic_class(rB['class_name'])}<br>{rA['original_subject']}", rA['reason'], "調")
            add_action(teacher_data, rB['original_teacher'], rB['swap_date'], rB['period'], "調出", rB['reason'], "調")
            add_action(teacher_data, rB['original_teacher'], rA['swap_date'], rA['period'], f"{to_arabic_class(rA['class_name'])}<br>{rB['original_subject']}", rB['reason'], "調")
            add_action(class_data, rA['class_name'], rA['swap_date'], rA['period'], f"{rA['new_subject']}<br>{rA['new_teacher']}")
            add_action(class_data, rB['class_name'], rB['swap_date'], rB['period'], f"{rB['new_subject']}<br>{rB['new_teacher']}")

    html_blocks = []
    for t_name, data in teacher_data.items(): html_blocks.append(generate_slip_card_html('teacher', t_name, data))
    for c_name, data in class_data.items(): html_blocks.append(generate_slip_card_html('class', c_name, data))
    return html_blocks

# ========================================================
# 彈窗與簽核機制
# ========================================================
@st.dialog("確認發起調課", width="large")
def confirm_submit_dialog(initiator_name, my_lesson, swap_partner_data, date_1_str, date_2_str, reason_str, is_admin=False):
    if is_admin: st.error("🚨 【教務處行政最高權限】您即將強制為老師調課。送出後將「直接生效」，無需雙方確認！")
    st.markdown(f"**1. 【{initiator_name} 老師】移出**：`{date_1_str}` 第 `{my_lesson['period']}` 節 **【{my_lesson['subject']}】**")
    st.markdown(f"**2. 換入課堂**：`{date_2_str}` 第 `{swap_partner_data['period']}` 節 **【{swap_partner_data['subject']}】**")
    st.markdown(f"**3. 對象**：**【{swap_partner_data['teacher_name']} 老師】**")
    st.markdown(f"**4. 原因**：`{reason_str}`")
    
    if st.button("🚨 強制送出生效" if is_admin else "🔥 確定送出調課申請", type="primary"):
        g_id = f"GRP_{int(time.time())}"
        status_a, status_b = ('approved', 'approved') if is_admin else ('pending', 'pending_target')
        
        run_action(
            "INSERT INTO temp_swaps (swap_date, class_name, period, week_day, original_teacher, new_teacher, original_subject, new_subject, status, group_id, is_initiator, reason) VALUES (:d, :c, :p, :w, :ot, :nt, :os, :ns, :st, :gid, 1, :r)",
            {"d": date_1_str, "c": my_lesson['class_name'], "p": str(my_lesson['period']), "w": my_lesson['week_day'], "ot": initiator_name, "nt": swap_partner_data['teacher_name'], "os": my_lesson['subject'], "ns": swap_partner_data['subject'], "st": status_a, "gid": g_id, "r": reason_str}
        )
        run_action(
            "INSERT INTO temp_swaps (swap_date, class_name, period, week_day, original_teacher, new_teacher, original_subject, new_subject, status, group_id, is_initiator, reason) VALUES (:d, :c, :p, :w, :ot, :nt, :os, :ns, :st, :gid, 0, :r)",
            {"d": date_2_str, "c": my_lesson['class_name'], "p": str(swap_partner_data['period']), "w": swap_partner_data['week_day'], "ot": swap_partner_data['teacher_name'], "nt": initiator_name, "os": swap_partner_data['subject'], "ns": my_lesson['subject'], "st": status_b, "gid": g_id, "r": reason_str}
        )
        
        if is_admin:
            send_notification(initiator_name, f"👑 教務處已強制調動您的課堂：{date_1_str} 第 {my_lesson['period']} 節。")
            send_notification(swap_partner_data['teacher_name'], f"👑 教務處已強制調動您的課堂：{date_2_str} 第 {swap_partner_data['period']} 節。")
        else:
            send_notification(swap_partner_data['teacher_name'], f"📬 {initiator_name} 老師向您發起了調課邀請 ({date_1_str} 第{my_lesson['period']}節)，請至系統簽核。")
        st.success("✅ 操作成功！全校課表已即時更新。" if is_admin else "🚀 申請已成功送出，等待對方同意！")
        st.rerun()

@st.dialog("審查調課申請單", width="large")
def review_swap_dialog(group_id, sender_name, cls_name, date_a, per_a, sub_a, date_b, per_b, sub_b):
    st.markdown(f"### 📬 來自 **{sender_name} 老師** 的對調申請")
    st.write("👉 **您將去代上的課 (對方的原課堂)**：")
    st.markdown(f"- `{date_a}` 第 `{per_a}` 節 **【{sub_a}】**")
    st.write("👉 **對方會來上的課 (您的原課堂)**：")
    st.markdown(f"- `{date_b}` 第 `{per_b}` 節 **【{sub_b}】**")
    
    c_b, s_b, e_b = get_consecutive_block(st.session_state.user_name, date_a, per_a)
    c_a, s_a, e_a = get_consecutive_block(sender_name, date_b, per_b)
    if c_b >= 3: st.warning(f"⚠️ **連堂預警**：若同意此單，您於 {date_a} 將有 **{c_b} 堂連課 (第 {s_b}~{e_b} 節)**！")
    if c_a >= 3: st.warning(f"⚠️ **連堂預警**：若同意此單，【{sender_name} 老師】於 {date_b} 將有 **{c_a} 堂連課 (第 {s_a}~{e_a} 節)**！")
    st.caption("💡 點選同意後，此申請將送交「教務處」進行最終審核才能生效。")
    colA, colB = st.columns(2)
    with colA:
        if st.button("✅ 同意對調 (送交教務處)", type="primary", use_container_width=True):
            run_action("UPDATE temp_swaps SET status = 'pending_admin' WHERE group_id = :gid", {"gid": group_id})
            send_notification(sender_name, f"✅ {st.session_state.user_name} 老師已同意您的調課 ({date_a} 第{per_a}節)，待教務處審核。")
            st.success("已同意！單據已送往教務處等待核准。")
            st.rerun()
    with colB:
        if st.button("❌ 婉拒申請", type="secondary", use_container_width=True):
            run_action("UPDATE temp_swaps SET status = 'rejected' WHERE group_id = :gid", {"gid": group_id})
            send_notification(sender_name, f"❌ {st.session_state.user_name} 老師婉拒了您的調課申請 ({date_a} 第{per_a}節)。")
            st.error("已退回此調課申請。")
            st.rerun()

@st.dialog("⚠️ 行政最高權限：強制撤銷確認", width="large")
def force_cancel_dialog(group_id, info_str, notif_t1, notif_m1, notif_t2, notif_m2):
    st.error("您即將強制註銷/駁回以下調代課案：")
    st.markdown(info_str)
    st.warning("👉 撤銷後，紀錄將保留並標示為【教務處撤銷】，雙方課表恢復常態原狀。")
    if st.button("🚨 我已知悉，確定強制撤銷", type="primary"):
        run_action("UPDATE temp_swaps SET status = 'rejected_admin' WHERE group_id = :gid", {"gid": group_id})
        if notif_t1: send_notification(notif_t1, notif_m1)
        if notif_t2: send_notification(notif_t2, notif_m2)
        st.success("✅ 撤銷成功！單據已作廢並保留紀錄。")
        st.rerun()

@st.dialog("🖨️ 單筆表單預覽", width="large")
def print_single_dialog(group_id):
    html_blocks = build_print_html([group_id])
    pages_html = ""
    for i in range(0, len(html_blocks), 4):
        chunk = html_blocks[i:i+4]
        pages_html += f'<div class="page">{"".join(chunk)}</div>'

    final_page = f"""
    <html><head><style>
    html, body {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'PingFang TC', sans-serif; background: #e9ecef; }}
    @media screen {{
        .print-container {{ width: 210mm; margin: 80px auto 40px auto; display: flex; flex-direction: column; gap: 20px; }}
        .page {{ width: 210mm; height: 297mm; padding: 10mm; background: #fff; box-shadow: 0 4px 10px rgba(0,0,0,0.2); display: flex; flex-wrap: wrap; justify-content: space-between; align-content: space-between; box-sizing: border-box; }}
        .slip-card {{ width: calc(50% - 3mm); height: 135mm; border: 2px solid #000; padding: 8mm; box-sizing: border-box; display: flex; flex-direction: column; }}
        .fixed-btn {{ text-align: center; padding: 15px; background: #1e3a8a; position: fixed; top: 0; left: 0; width: 100%; z-index: 1000; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
    }}
    @media print {{
        @page {{ size: A4 portrait; margin: 0; }}
        .no-print, .fixed-btn {{ display: none !important; }}
        html, body {{ background: #fff !important; width: 210mm; height: 100%; margin: 0 !important; padding: 0 !important; }}
        .print-container {{ margin: 0 !important; padding: 0 !important; width: 210mm; display: block; }}
        .page {{ width: 210mm; height: 297mm; padding: 10mm; margin: 0 !important; border: none !important; box-shadow: none !important; box-sizing: border-box; page-break-after: always; page-break-inside: avoid; display: flex; flex-wrap: wrap; justify-content: space-between; align-content: space-between; }}
        .slip-card {{ width: calc(50% - 3mm); height: 135mm; margin: 0 !important; border: 2px solid #000; padding: 8mm; box-sizing: border-box; display: flex; flex-direction: column; }}
    }}
    .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 2px solid #000; padding-bottom: 8px; }}
    .title {{ font-size: 18px; font-weight: bold; text-align: center; line-height: 1.2; }}
    .info {{ font-size: 14px; font-weight: bold; line-height: 1.4; }}
    .teacher-name {{ font-size: 16px; font-weight: bold; text-align: center; }}
    .name-text {{ font-size: 22px; }}
    .slip-table {{ width: 100%; border-collapse: collapse; text-align: center; flex-grow: 1; table-layout: fixed; }}
    .slip-table td, .slip-table th {{ border: 1px solid #000; padding: 2px; }}
    .th-row th {{ background: #f0f0f0 !important; font-size: 14px; height: 24px; }}
    .date-row td {{ font-weight: bold; font-size: 12px; height: 20px; }}
    .period-cell {{ height: 10%; }}
    .cell-content {{ font-size: 12px; line-height: 1.1; max-height: 100%; overflow: hidden; display: flex; flex-direction: column; justify-content: center; align-items: center; word-wrap: break-word; word-break: break-all; }}
    </style></head>
    <body>
        <div class="fixed-btn no-print">
            <button onclick="window.print()" style="padding: 10px 30px; font-size: 20px; font-weight: bold; cursor: pointer; background: #fff; color: #1e3a8a; border: none; border-radius: 5px;">🖨️ 確認列印 (請設定為A4直印)</button>
        </div>
        <div class="print-container">{pages_html}</div>
    </body></html>
    """
    run_action("UPDATE temp_swaps SET is_printed = 1 WHERE group_id = :gid", {"gid": group_id})
    components.html(final_page, height=800, scrolling=True)

# ========================================================
# 分頁控制動態生成
# ========================================================
tabs_list = ["🔍 教師課表", "🎓 班級課表", "🔄 線上調課"]
if st.session_state.user_id == "ADMIN": 
    tabs_list.extend(["🏢 教務處後台", "🖨️ 列印中心", "🔒 鎖定時段設定", "👥 群組管理", "⚙️ 帳號管理", "💰 第八節計費"])
tabs = st.tabs(tabs_list)

# --- TAB 1 & 2: 課表查閱 ---
with tabs[0]:
    try: default_idx = all_teachers_in_db.index(st.session_state.user_name)
    except: default_idx = 0
    selected_query_teacher = st.selectbox("請選擇要查詢的老師姓名：", all_teachers_in_db, index=default_idx)
    if selected_query_teacher:
        st.caption(f"📊 {selected_query_teacher} 老師 在 {selected_date} 所在週次的整週課表")
        render_styled_table_html(load_merged_timetable(selected_date, selected_query_teacher, "teacher"))

with tabs[1]:
    selected_cls = st.selectbox("請選擇要查詢的班級：", all_classes, format_func=to_arabic_class)
    if selected_cls:
        st.caption(f"📋 {to_arabic_class(selected_cls)} 班 在 {selected_date} 所在週次的整週課表")
        render_styled_table_html(load_merged_timetable(selected_date, selected_cls, "class"))

# --- TAB 3: 線上調課面板 ---
with tabs[2]:
    is_admin_mode = (st.session_state.user_id == "ADMIN")
    admin_mode_select = "📝 調課"
    if is_admin_mode:
        admin_mode_select = st.radio("行政權限", ["📝 教務處調課", "⚡ 單向代課"], horizontal=True)
        st.markdown("---")
        if "代課" in admin_mode_select:
            col_ad1, col_ad2 = st.columns(2)
            with col_ad1: absent_teacher = st.selectbox("1. 選擇【請假/公差】的缺席老師：", all_teachers_in_db, key="abs_tea_box")
            if absent_teacher:
                abs_lessons = base_schedule_df[(base_schedule_df['teacher_name'] == absent_teacher) & (base_schedule_df['week_day'] == current_weekday)]
                locked_df = run_query(
                    "SELECT period FROM temp_swaps WHERE swap_date=:d AND original_teacher=:t AND status NOT IN ('rejected', 'rejected_admin')",
                    {"d": selected_date.strftime('%Y-%m-%d'), "t": absent_teacher}
                )
                locked_abs_lessons = locked_df['period'].astype(str).tolist() if not locked_df.empty else []
                
                if not abs_lessons.empty:
                    abs_lessons = abs_lessons.copy()
                    abs_lessons['period'] = abs_lessons['period'].astype(str)
                    abs_lessons = sort_lessons_dataframe(abs_lessons[~abs_lessons['period'].isin(locked_abs_lessons)])
                
                if abs_lessons.empty: st.warning(f"ℹ️ {absent_teacher} 老師在選定日期 ({selected_date}) 無排課，或已指派完畢。")
                else:
                    with col_ad1:
                        abs_options = [f"第{r['period']}節 ｜ {to_arabic_class(r['class_name'])} - {r['subject']}" for _, r in abs_lessons.iterrows()]
                        chosen_abs_les = abs_lessons.iloc[st.selectbox("2. 選擇需要找人代上的課堂：", range(len(abs_options)), format_func=lambda x: abs_options[x])]
                    with col_ad2:
                        b1 = base_schedule_df[(base_schedule_df['week_day'] == current_weekday) & (base_schedule_df['period'].astype(str) == str(chosen_abs_les['period']))]['teacher_name'].tolist()
                        f1 = run_query("SELECT DISTINCT original_teacher FROM temp_swaps WHERE swap_date=:d AND period=:p AND status IN ('approved', 'approved_sub', 'pending_admin') AND original_teacher IS NOT NULL", {"d": selected_date.strftime('%Y-%m-%d'), "p": str(chosen_abs_les['period'])})
                        b2 = run_query("SELECT DISTINCT new_teacher FROM temp_swaps WHERE swap_date=:d AND period=:p AND status NOT IN ('rejected', 'rejected_admin') AND new_teacher IS NOT NULL", {"d": selected_date.strftime('%Y-%m-%d'), "p": str(chosen_abs_les['period'])})
                        l1 = run_query("SELECT DISTINCT teacher_name FROM locked_slots WHERE lock_date=:d AND period=:p", {"d": selected_date.strftime('%Y-%m-%d'), "p": str(chosen_abs_les['period'])})
                        
                        busy_base = b1
                        freed_teachers = f1['original_teacher'].tolist() if not f1.empty else []
                        busy_swap = b2['new_teacher'].tolist() if not b2.empty else []
                        admin_locked_teachers = l1['teacher_name'].tolist() if not l1.empty else []
                        
                        actual_busy = [t for t in busy_base if t not in freed_teachers]
                        available_sub_teachers = sorted([t for t in all_teachers_in_db if t not in set(actual_busy + busy_swap + [absent_teacher, "教務處"])])
                        
                        if not available_sub_teachers: st.error(f"❌ 全校目前在【第{chosen_abs_les['period']}節】沒有空堂老師！")
                        else:
                            sub_teacher = st.selectbox("3. 選擇【指派去上課】的代課老師：", available_sub_teachers)
                            sub_reason = st.text_input("📝 請輸入代課原因 (將印於調課單)", placeholder="例：公假、事假...")
                            if sub_teacher in admin_locked_teachers: st.warning(f"⚠️ 注意：【{sub_teacher} 老師】此節已被設定為「🔒 鎖定時段」，但您擁有最高權限，仍可強制排入。")
                            st.markdown("---")
                            sub_consec, s_s, e_s = get_consecutive_block(sub_teacher, selected_date, chosen_abs_les['period'])
                            if sub_consec >= 3: st.warning(f"⚠️ **連堂預警**：若指派，【{sub_teacher} 老師】將會有 **{sub_consec} 堂連課 (第 {s_s}~{e_s} 節)**！")
                                
                            if st.button("🚀 確定指派，直接生效", type="primary", use_container_width=True):
                                if not sub_reason.strip(): sub_reason = "行政指派代課"
                                g_id, date_str = f"GRP_SUB_{int(time.time())}", selected_date.strftime('%Y-%m-%d')
                                
                                run_action(
                                    "INSERT INTO temp_swaps (swap_date, class_name, period, week_day, original_teacher, new_teacher, original_subject, new_subject, status, group_id, is_initiator, reason) VALUES (:d, :c, :p, :w, :ot, :nt, :os, :ns, 'approved_sub', :gid, 1, :r)",
                                    {"d": date_str, "c": chosen_abs_les['class_name'], "p": str(chosen_abs_les['period']), "w": current_weekday, "ot": absent_teacher, "nt": sub_teacher, "os": chosen_abs_les['subject'], "ns": chosen_abs_les['subject'], "gid": g_id, "r": sub_reason}
                                )
                                run_action(
                                    "INSERT INTO temp_swaps (swap_date, class_name, period, week_day, original_teacher, new_teacher, original_subject, new_subject, status, group_id, is_initiator, reason) VALUES (:d, :c, :p, :w, :ot, :nt, :os, :ns, 'approved_sub', :gid, 0, :r)",
                                    {"d": date_str, "c": chosen_abs_les['class_name'], "p": str(chosen_abs_les['period']), "w": current_weekday, "ot": sub_teacher, "nt": absent_teacher, "os": chosen_abs_les['subject'], "ns": chosen_abs_les['subject'], "gid": g_id, "r": sub_reason}
                                )
                                send_notification(sub_teacher, f"⚡ 教務處已指派您於 {date_str} 第 {chosen_abs_les['period']} 節進行代課。")
                                st.success(f"🎉 成功指派！{sub_teacher} 老師將前往 {to_arabic_class(chosen_abs_les['class_name'])} 班上課。")
                                st.rerun()
            st.stop() 

    if not is_admin_mode or (is_admin_mode and "調課" in admin_mode_select):
        col1, col2 = st.columns(2)
        with col1:
            initiator = st.selectbox("👤 選擇要代為調課的發起老師：", all_teachers_in_db, key="admin_init_tea") if is_admin_mode else st.session_state.user_name
            if not is_admin_mode: st.info(f"📅 目前鎖定操作日期：**{selected_date} (星期{current_weekday})**")

            if initiator:
                my_base_lessons = base_schedule_df[(base_schedule_df['teacher_name'] == initiator) & (base_schedule_df['week_day'] == current_weekday)]
                locked_my = run_query(
                    "SELECT period FROM temp_swaps WHERE swap_date=:d AND original_teacher=:t AND status NOT IN ('rejected', 'rejected_admin')",
                    {"d": selected_date.strftime('%Y-%m-%d'), "t": initiator}
                )
                locked_my_lessons = locked_my['period'].astype(str).tolist() if not locked_my.empty else []
                
                if not my_base_lessons.empty:
                    my_base_lessons = my_base_lessons.copy()
                    my_base_lessons['period'] = my_base_lessons['period'].astype(str)
                    my_base_lessons = sort_lessons_dataframe(my_base_lessons[~my_base_lessons['period'].isin(locked_my_lessons)])
                
                if my_base_lessons.empty: st.warning(f"ℹ️ {initiator} 老師今日無排課，或皆已在流程中。")
                else:
                    lesson_options = [f"第{r['period']}節 | {to_arabic_class(r['class_name'])} - {r['subject']}" for _, r in my_base_lessons.iterrows()]
                    target_lesson = my_base_lessons.iloc[st.selectbox("1. 選擇移開的課堂：", range(len(lesson_options)), format_func=lambda x: lesson_options[x])]
                    cls_name, w_day_1, per_1 = target_lesson['class_name'], target_lesson['week_day'], target_lesson['period']
                    
                    potential_partners = sort_lessons_dataframe(base_schedule_df[(base_schedule_df['class_name'] == cls_name) & (base_schedule_df['teacher_name'] != initiator)])
                    
                    valid_swaps = []
                    if not potential_partners.empty:
                        for _, partner in potential_partners.iterrows():
                            t_b, w_day_2, per_2 = partner['teacher_name'], partner['week_day'], partner['period']
                            check1 = base_schedule_df[(base_schedule_df['teacher_name'] == t_b) & (base_schedule_df['week_day'] == w_day_1) & (base_schedule_df['period'].astype(str) == str(per_1))]
                            check2 = base_schedule_df[(base_schedule_df['teacher_name'] == initiator) & (base_schedule_df['week_day'] == w_day_2) & (base_schedule_df['period'].astype(str) == str(per_2))]
                            if check1.empty and check2.empty:
                                valid_swaps.append(partner)
                    st.markdown("---")
                    
                    if not valid_swaps: st.error("❌ 無符合『只調不代』且無衝堂之組合。")
                    else:
                        swap_labels = [f"與 {p['teacher_name']} 老師對調 ➡️ (換至 星期{p['week_day']} 第{p['period']}節 【{p['subject']}】)" for p in valid_swaps]
                        chosen_partner = valid_swaps[st.selectbox("2. 選擇對調時間：", range(len(swap_labels)), format_func=lambda x: swap_labels[x])]
                        target_date = st.date_input("3. 選擇調課實際日期：", value=get_actual_date_of_weekday(selected_date, chosen_partner['week_day']), min_value=min_allowed_date)
                        swap_reason = st.text_input("📝 請輸入調課原因 (將印於調課單)", placeholder="例：公假、事假...")
                        actual_date_1, actual_date_2 = selected_date, target_date
                        
                        errors = []
                        t_lock = run_query("SELECT reason FROM locked_slots WHERE teacher_name=:t AND lock_date=:d AND period=:p", {"t": chosen_partner['teacher_name'], "d": actual_date_1.strftime('%Y-%m-%d'), "p": str(per_1)})
                        i_lock = run_query("SELECT reason FROM locked_slots WHERE teacher_name=:t AND lock_date=:d AND period=:p", {"t": initiator, "d": actual_date_2.strftime('%Y-%m-%d'), "p": str(chosen_partner['period'])})
                        
                        target_lock_reason = t_lock.iloc[0]['reason'] if not t_lock.empty else None
                        init_lock_reason = i_lock.iloc[0]['reason'] if not i_lock.empty else None
                        
                        if not is_admin_mode:
                            if target_lock_reason: errors.append(f"❌ 對方在 {actual_date_1.strftime('%m/%d')} 第{per_1}節 已被教務處設定為🔒鎖定時段 ({target_lock_reason})，無法調入！")
                            if init_lock_reason: errors.append(f"❌ 您在 {actual_date_2.strftime('%m/%d')} 第{chosen_partner['period']}節 已被教務處設定為🔒鎖定時段 ({init_lock_reason})，無法調入！")
                        else:
                            if target_lock_reason: st.warning(f"⚠️ 注意：【{chosen_partner['teacher_name']}】於 {actual_date_1.strftime('%m/%d')} 第{per_1}節 已被設定為「🔒 {target_lock_reason}」，您可強制調入。")
                            if init_lock_reason: st.warning(f"⚠️ 注意：【{initiator}】於 {actual_date_2.strftime('%m/%d')} 第{chosen_partner['period']}節 已被設定為「🔒 {init_lock_reason}」，您可強制調入。")

                        c_chk1 = run_query("SELECT 1 FROM temp_swaps WHERE swap_date=:d AND period=:p AND original_teacher=:t AND status NOT IN ('rejected', 'rejected_admin')", {"d": actual_date_2.strftime('%Y-%m-%d'), "p": str(chosen_partner['period']), "t": chosen_partner['teacher_name']})
                        c_chk2 = run_query("SELECT 1 FROM temp_swaps WHERE swap_date=:d AND period=:p AND new_teacher=:t AND status NOT IN ('rejected', 'rejected_admin')", {"d": actual_date_1.strftime('%Y-%m-%d'), "p": str(per_1), "t": chosen_partner['teacher_name']})
                        c_chk3 = run_query("SELECT 1 FROM temp_swaps WHERE swap_date=:d AND period=:p AND new_teacher=:t AND status NOT IN ('rejected', 'rejected_admin')", {"d": actual_date_2.strftime('%Y-%m-%d'), "p": str(chosen_partner['period']), "t": initiator})

                        if not c_chk1.empty: errors.append(f"❌ 對方 ({actual_date_2.strftime('%m/%d')} 第{chosen_partner['period']}節) 已在流程中或調出！")
                        if not c_chk2.empty: errors.append(f"❌ 對方在 {actual_date_1.strftime('%m/%d')} 第{per_1}節 已有代課！")
                        if not c_chk3.empty: errors.append(f"❌ 【{initiator} 老師】在 {actual_date_2.strftime('%m/%d')} 第{chosen_partner['period']}節 已有任務！")

                        if get_week_day_zh(target_date) != chosen_partner['week_day']: st.error(f"❌ 請選擇【星期{chosen_partner['week_day']}】的日期！")
                        elif errors:
                            for e in errors: st.error(e)
                        else:
                            c1, s1, e1 = get_consecutive_block(chosen_partner['teacher_name'], actual_date_1, per_1)
                            if c1 >= 3: st.warning(f"⚠️ **連堂預警**：調課後，【{chosen_partner['teacher_name']} 老師】於 {actual_date_1.strftime('%m/%d')} 將有 **{c1} 堂連課 (第 {s1}~{e1} 節)**！")
                            c2, s2, e2 = get_consecutive_block(initiator, actual_date_2, chosen_partner['period'])
                            if c2 >= 3: st.warning(f"⚠️ **連堂預警**：調課後，【{initiator} 老師】於 {actual_date_2.strftime('%m/%d')} 將有 **{c2} 堂連課 (第 {s2}~{e2} 節)**！")

                            if st.button("🚀 強制送出生效" if is_admin_mode else "🚀 送出調課申請", type="primary"):
                                r_str = swap_reason.strip() if swap_reason.strip() else "調課"
                                confirm_submit_dialog(initiator, target_lesson, chosen_partner, actual_date_1.strftime('%Y-%m-%d'), actual_date_2.strftime('%Y-%m-%d'), r_str, is_admin=is_admin_mode)

            if not is_admin_mode:
                st.markdown("---")
                st.markdown("#### 📤 調課追蹤")
                sent_df = run_query(
                    "SELECT A.group_id, A.status, A.class_name, A.swap_date as my_date, A.period as my_per, A.original_subject as my_sub, B.original_teacher as partner_name, B.swap_date as partner_date, B.period as partner_per, B.original_subject as partner_sub FROM temp_swaps A JOIN temp_swaps B ON A.group_id = B.group_id WHERE A.original_teacher = :t AND A.is_initiator = 1 AND B.is_initiator = 0 ORDER BY A.id DESC",
                    {"t": st.session_state.user_name}
                )
                if sent_df.empty: st.caption("尚無發起紀錄。")
                else:
                    for _, row in sent_df.iterrows():
                        status_icon = {'pending': '⏳ 等待對方回覆', 'pending_admin': '⏳ 待教務處審核', 'approved': '✅ 雙向調課', 'rejected': '❌ 對方已婉拒', 'rejected_admin': '❌ 教務處撤銷/駁回'}.get(row['status'], '')
                        with st.expander(f"對象：{row['partner_name']} 老師 ｜ 狀態：{status_icon}"):
                            st.markdown(f"🏫 **班級**：{to_arabic_class(row['class_name'])} 班")
                            st.markdown(f"👉 **我將要上的課**：`{row['partner_date']}` 第 `{row['partner_per']}` 節 (原{row['partner_sub']}課)")
                            st.markdown(f"👉 **對方要上的課**：`{row['my_date']}` 第 `{row['my_per']}` 節 (原{row['my_sub']}課)")
                            if row['status'] in ('pending', 'pending_admin'):
                                if st.button("🗑️ 撤回此申請", key=f"cancel_{row['group_id']}", type="secondary"):
                                    run_action("DELETE FROM temp_swaps WHERE group_id = :gid", {"gid": row['group_id']})
                                    st.warning("已成功撤回。")
                                    st.rerun()

        with col2:
            if not is_admin_mode:
                st.markdown("### 🔔 線上簽核")
                my_pending_df = run_query(
                    "SELECT A.group_id, A.original_teacher as sender_name, A.class_name as class_name, A.swap_date as date_a, A.period as per_a, A.original_subject as sub_a, B.swap_date as date_b, B.period as per_b, B.original_subject as sub_b FROM temp_swaps A JOIN temp_swaps B ON A.group_id = B.group_id WHERE A.status = 'pending' AND B.status = 'pending_target' AND A.new_teacher = :t AND A.is_initiator = 1 AND B.is_initiator = 0",
                    {"t": st.session_state.user_name}
                )
                if my_pending_df.empty: st.info("☕ 暫無待處理的申請單。")
                else:
                    for _, row in my_pending_df.iterrows():
                        with st.container(border=True):
                            st.write(f"**發起老師**：{row['sender_name']} 老師")
                            if st.button("📝 開啟審查面板", key=f"app_{row['group_id']}", use_container_width=True):
                                review_swap_dialog(row['group_id'], row['sender_name'], row['class_name'], row['date_a'], row['per_a'], row['sub_a'], row['date_b'], row['per_b'], row['sub_b'])

                st.markdown("---")
                st.markdown("#### 📥 審核紀錄")
                replied_df = run_query(
                    "SELECT B.group_id, B.status, B.class_name, A.original_teacher as sender_name, A.swap_date as sender_date, A.period as sender_per, A.original_subject as sender_sub, B.swap_date as my_date, B.period as my_per, B.original_subject as my_sub FROM temp_swaps B JOIN temp_swaps A ON B.group_id = A.group_id WHERE B.original_teacher = :t AND B.is_initiator = 0 AND A.is_initiator = 1 AND B.status IN ('approved', 'rejected', 'pending_admin', 'rejected_admin') ORDER BY B.id DESC",
                    {"t": st.session_state.user_name}
                )
                if replied_df.empty: st.caption("尚無審核紀錄。")
                else:
                    for _, row in replied_df.iterrows():
                        status_icon = {'pending_admin': '⏳ 待教務處審核', 'approved': '✅ 已同意', 'rejected': '❌ 已內退/婉拒', 'rejected_admin': '❌ 教務處撤銷/駁回'}.get(row['status'], '')
                        with st.expander(f"發起人：{row['sender_name']} 老師 ｜ 狀態：{status_icon}"):
                            st.markdown(f"🏫 **班級**：{to_arabic_class(row['class_name'])} 班")
                            st.markdown(f"👉 **我將要上的課**：`{row['sender_date']}` 第 `{row['sender_per']}` 節 (原{row['sender_sub']}課)")
                            st.markdown(f"👉 **對方要上的課**：`{row['my_date']}` 第 `{row['my_per']}` 節 (原{row['my_sub']}課)")

# ========================================================
# 🏢 教務處後台分頁
# ========================================================
def render_admin_cards(df, is_pending_approval=False):
    for _, row in df.iterrows():
        gid, raw_status = row['group_id'], row['raw_status']
        if raw_status == 'approved_sub':
            txt_status, txt_col2 = "⚡ 單向代課", f"請假：**{row['申請老師']}** 老師\n\n`{row['申請方日期']}` 第 {row['申請方節次']} 節"
            txt_col3 = f"代課：**{row['對調老師']}** 老師\n\n科目：【{row['申請方科目']}】"
            info_for_del = f"**【單向代課案】** 班級：{row['班級']} 班\n- **請假**：{row['申請老師']} 老師 (`{row['申請方日期']}` 第 {row['申請方節次']} 節)\n- **代課**：{row['對調老師']} 老師"
        else:
            status_map = {'pending': '⏳ 等待對方回覆', 'pending_admin': '⏳ 待教務處審核', 'approved': '✅ 雙向調課', 'rejected': '❌ 老師婉拒', 'rejected_admin': '❌ 教務處撤銷/駁回'}
            txt_status = status_map.get(raw_status, '')
            txt_col2 = f"發起：**{row['申請老師']}** 老師\n\n`{row['申請方日期']}` 第 {row['申請方節次']} 節 ({row['申請方科目']})"
            txt_col3 = f"對調：**{row['對調老師']}** 老師\n\n`{row['對調方日期']}` 第 {row['對調方節次']} 節 ({row['對調方科目']})"
            info_for_del = f"**【雙向調課案】** 班級：{row['班級']} 班\n- **{row['申請老師']}** 老師 (`{row['申請方日期']}` 第 {row['申請方節次']} 節)\n- **{row['對調老師']}** 老師 (`{row['對調方日期']}` 第 {row['對調方節次']} 節)"

        with st.container(border=True):
            if is_pending_approval:
                c1, s1, e1 = get_consecutive_block(row['對調老師'], row['申請方日期'], row['申請方節次'])
                c2, s2, e2 = get_consecutive_block(row['申請老師'], row['對調方日期'], row['對調方節次'])
                if c1 >= 3: st.warning(f"⚠️ 注意：核准後，【{row['對調老師']} 老師】於 {row['申請方日期']} 將有 **{c1} 堂連課 (第 {s1}~{e1} 節)**！")
                if c2 >= 3: st.warning(f"⚠️ 注意：核准後，【{row['申請老師']} 老師】於 {row['對調方日期']} 將有 **{c2} 堂連課 (第 {s2}~{e2} 節)**！")

            col1, col2, col3, col4 = st.columns([1.5, 3.5, 3.5, 1.5])
            with col1:
                st.markdown(f"**{txt_status}**")
                st.caption(f"🏫 **{row['班級']} 班**")
            with col2: st.markdown(txt_col2)
            with col3: st.markdown(txt_col3)
            with col4:
                if is_pending_approval:
                    if st.button("✅ 核准生效", key=f"app_{gid}", type="primary", use_container_width=True):
                        run_action("UPDATE temp_swaps SET status = 'approved' WHERE group_id = :gid", {"gid": gid})
                        send_notification(row['申請老師'], f"✅ 教務處已核准您與 {row['對調老師']} 老師的調課單 ({row['申請方日期']} 第{row['申請方節次']}節)！")
                        send_notification(row['對調老師'], f"✅ 教務處已核准您與 {row['申請老師']} 老師的調課單 ({row['對調方日期']} 第{row['對調方節次']}節)！")
                        st.success("✅ 已核准！課表即時生效。")
                        st.rerun()
                    if st.button("❌ 駁回申請", key=f"rej_{gid}", type="secondary", use_container_width=True):
                        run_action("UPDATE temp_swaps SET status = 'rejected_admin' WHERE group_id = :gid", {"gid": gid})
                        st.error("❌ 已駁回退單。")
                        st.rerun()
                elif raw_status in ('approved', 'approved_sub'):
                    if st.button("🖨️ 列印表單", key=f"prt_{gid}", type="primary", use_container_width=True):
                        print_single_dialog(gid)
                    if st.button("🗑️ 強制撤銷", key=f"del_{gid}", use_container_width=True):
                        force_cancel_dialog(gid, info_for_del, row['申請老師'], f"👑 教務處已強制撤銷您發起的調課申請 ({row['申請方日期']} 第{row['申請方節次']}節)", row['對調老師'], f"👑 教務處已強制撤銷與您相關的調課邀請")
                elif raw_status == 'pending':
                    if st.button("🗑️ 強制撤銷", key=f"del_{gid}", use_container_width=True):
                        force_cancel_dialog(gid, info_for_del, row['申請老師'], f"👑 教務處已強制撤銷您發起的調課申請 ({row['申請方日期']} 第{row['申請方節次']}節)", row['對調老師'], f"👑 教務處已強制撤銷與您相關的調課邀請")

if st.session_state.user_id == "ADMIN":
    with tabs[3]:
        st.markdown("### 🏢 教務處行政全知管理後台")
        st.caption("此處列出全校所有的調代課紀錄。所有雙方同意的調課單，皆需在此「待審核專區」由教務處點選核准後，方可正式寫入課表生效。")
        search_kw = st.text_input("🔍 輸入關鍵字快速過濾（例如輸入：老師姓名、或班級數字 102）：").strip()
        
        raw_admin_df = run_query("""
            SELECT A.group_id, A.status as raw_status, A.class_name, A.is_printed, A.reason,
                   A.original_teacher as 申請老師, A.swap_date as 申請方日期, A.period as 申請方節次, A.original_subject as 申請方科目,
                   B.original_teacher as 對調老師, B.swap_date as 對調方日期, B.period as 對調方節次, B.original_subject as 對調方科目
            FROM temp_swaps A JOIN temp_swaps B ON A.group_id = B.group_id
            WHERE A.is_initiator = 1 AND B.is_initiator = 0 AND A.status IN ('pending', 'pending_admin', 'approved', 'rejected', 'rejected_admin')
            UNION ALL
            SELECT group_id, status as raw_status, class_name, is_printed, reason,
                   original_teacher as 申請老師, swap_date as 申請方日期, period as 申請方節次, original_subject as 申請方科目,
                   new_teacher as 對調老師, swap_date as 對調方日期, period as 對調方節次, new_subject as 對調方科目
            FROM temp_swaps WHERE status = 'approved_sub' AND is_initiator = 1
            ORDER BY group_id DESC
        """)
        
        if raw_admin_df.empty: st.info("☕ 目前全校資料庫中暫無任何調課申請紀錄。")
        else:
            display_df = raw_admin_df.copy()
            display_df['班級'] = display_df['class_name'].apply(to_arabic_class)
            if search_kw: display_df = display_df[display_df.astype(str).apply(lambda x: x.str.contains(search_kw, case=False)).any(axis=1)]
            if display_df.empty: st.warning(f"找不到包含『{search_kw}』的調課紀錄，請嘗試其他關鍵字。")
            else:
                def get_max_date(row):
                    d1, d2 = str(row['申請方日期']), str(row['對調方日期'])
                    if row['raw_status'] == 'approved_sub': return d1
                    if pd.isna(d1) or d1 == 'None': return d2
                    if pd.isna(d2) or d2 == 'None': return d1
                    return max(d1, d2)

                def get_min_date(row):
                    d1, d2 = str(row['申請方日期']), str(row['對調方日期'])
                    if row['raw_status'] == 'approved_sub': return d1
                    if pd.isna(d1) or d1 == 'None': return d2
                    if pd.isna(d2) or d2 == 'None': return d1
                    return min(d1, d2)

                display_df['max_date'] = display_df.apply(get_max_date, axis=1).fillna('1900-01-01')
                display_df['min_date'] = display_df.apply(get_min_date, axis=1).fillna('2099-12-31')
                display_df['申請方節次'] = pd.to_numeric(display_df['申請方節次'], errors='coerce').fillna(0)

                pending_admin_df = display_df[display_df['raw_status'] == 'pending_admin']
                other_df = display_df[display_df['raw_status'] != 'pending_admin']
                upcoming_df = other_df[other_df['max_date'] >= REAL_TODAY_STR].sort_values(['min_date', '申請方節次'], ascending=[True, True])
                past_df = other_df[other_df['max_date'] < REAL_TODAY_STR].sort_values(['max_date', '申請方節次'], ascending=[False, True])
                
                st.markdown(f"📊 目前符合條件的紀錄共 **{len(display_df)}** 筆。")
                admin_tabs = st.tabs([f"📝 待教務處審核 ({len(pending_admin_df)})", "📅 即將到來 / 進行中", "🕰️ 歷史 / 已過期單據"])
                with admin_tabs[0]:
                    if pending_admin_df.empty: st.success("🎉 目前沒有需要教務處審核的單子，太棒了！")
                    else: render_admin_cards(pending_admin_df, is_pending_approval=True)
                with admin_tabs[1]:
                    if upcoming_df.empty: st.caption("目前沒有即將到來的調代課紀錄。")
                    else: render_admin_cards(upcoming_df)
                with admin_tabs[2]:
                    if past_df.empty: st.caption("目前沒有歷史紀錄。")
                    else: render_admin_cards(past_df)

# ========================================================
# 🖨️ 第五分頁：列印中心 (ADMIN Only) 
# ========================================================
    with tabs[4]:
        st.markdown("### 🖨️ 批次列印中心")
        st.caption("勾選多筆已核准的單據，系統將自動將同一個老師或班級的異動「合併在同一張課表網格」中，最大化節省紙張並保持清晰。")
        
        if raw_admin_df.empty: st.info("目前無任何紀錄可供列印。")
        else:
            print_df = raw_admin_df[raw_admin_df['raw_status'].isin(['approved', 'approved_sub'])].copy()
            if print_df.empty: st.info("目前尚無「已核准」的單據可供列印。")
            else:
                filter_printed = st.radio("顯示範圍", ["📄 僅顯示尚未列印", "📂 顯示全部已核准單據"], horizontal=True)
                if "尚未" in filter_printed: print_df = print_df[print_df['is_printed'] == 0]
                
                if print_df.empty: st.success("太棒了！所有已核准的單據都列印完畢囉！")
                else:
                    def get_print_max_date(row):
                        d1, d2 = str(row['申請方日期']), str(row['對調方日期'])
                        if row['raw_status'] == 'approved_sub': return d1
                        if pd.isna(d1) or d1 == 'None': return d2
                        if pd.isna(d2) or d2 == 'None': return d1
                        return max(d1, d2)

                    def get_print_min_date(row):
                        d1, d2 = str(row['申請方日期']), str(row['對調方日期'])
                        if row['raw_status'] == 'approved_sub': return d1
                        if pd.isna(d1) or d1 == 'None': return d2
                        if pd.isna(d2) or d2 == 'None': return d1
                        return min(d1, d2)
                    
                    print_df['max_date'] = print_df.apply(get_print_max_date, axis=1).fillna('1900-01-01')
                    print_df['min_date'] = print_df.apply(get_print_min_date, axis=1).fillna('2099-12-31')
                    
                    print_df['類型'] = print_df['raw_status'].map({'approved': '🔄 雙向調課', 'approved_sub': '⚡ 單向代課'})
                    print_df['摘要'] = print_df.apply(lambda r: f"{r['申請老師']} ({r['申請方日期']} 第{r['申請方節次']}節) ➡️ {r['對調老師']}", axis=1)
                    print_df['列印狀態'] = print_df['is_printed'].map({1: '✅ 已印', 0: '❌ 未印'})
                    
                    upcoming_print_df = print_df[print_df['max_date'] >= REAL_TODAY_STR].sort_values('min_date', ascending=True)
                    past_print_df = print_df[print_df['max_date'] < REAL_TODAY_STR].sort_values('max_date', ascending=False)
                    
                    print_tabs = st.tabs([f"📅 待列印 / 進行中 ({len(upcoming_print_df)})", f"🕰️ 歷史單據 ({len(past_print_df)})"])
                    
                    def render_print_tab(df, tab_key):
                        if df.empty:
                            st.info("此區間無資料。")
                            return
                        show_df = df[['group_id', '列印狀態', '類型', 'class_name', '摘要']].copy()
                        show_df.rename(columns={'class_name': '班級'}, inplace=True)
                        show_df.insert(0, "選取", False)
                        
                        edited_df = st.data_editor(show_df, hide_index=True, column_config={"選取": st.column_config.CheckboxColumn(required=True)}, disabled=["group_id", "列印狀態", "類型", "班級", "摘要"], use_container_width=True, key=f"editor_{tab_key}")
                        selected_gids = edited_df[edited_df["選取"]]['group_id'].tolist()
                        
                        if st.button("🖨️ 產生合併列印報表 (並標記為已列印)", key=f"btn_{tab_key}", type="primary"):
                            if not selected_gids: st.error("❌ 請至少勾選一筆單據！")
                            else:
                                html_blocks = build_print_html(selected_gids)
                                pages_html = ""
                                for i in range(0, len(html_blocks), 4):
                                    chunk = html_blocks[i:i+4]
                                    pages_html += f'<div class="page">{"".join(chunk)}</div>'

                                final_page = f"""
                                <html><head><style>
                                html, body {{ margin: 0; padding: 0; box-sizing: border-box; font-family: 'PingFang TC', sans-serif; background: #e9ecef; }}
                                @media screen {{
                                    .print-container {{ width: 210mm; margin: 80px auto 40px auto; display: flex; flex-direction: column; gap: 20px; }}
                                    .page {{ width: 210mm; height: 297mm; padding: 10mm; background: #fff; box-shadow: 0 4px 10px rgba(0,0,0,0.2); display: flex; flex-wrap: wrap; justify-content: space-between; align-content: space-between; box-sizing: border-box; }}
                                    .slip-card {{ width: calc(50% - 3mm); height: 135mm; border: 2px solid #000; padding: 8mm; box-sizing: border-box; display: flex; flex-direction: column; }}
                                    .fixed-btn {{ text-align: center; padding: 15px; background: #1e3a8a; position: fixed; top: 0; left: 0; width: 100%; z-index: 1000; box-shadow: 0 4px 6px rgba(0,0,0,0.1); }}
                                }}
                                @media print {{
                                    @page {{ size: A4 portrait; margin: 0; }}
                                    .no-print, .fixed-btn {{ display: none !important; }}
                                    html, body {{ background: #fff !important; width: 210mm; height: 100%; margin: 0 !important; padding: 0 !important; }}
                                    .print-container {{ margin: 0 !important; padding: 0 !important; width: 210mm; display: block; }}
                                    .page {{ width: 210mm; height: 297mm; padding: 10mm; margin: 0 !important; border: none !important; box-shadow: none !important; box-sizing: border-box; page-break-after: always; page-break-inside: avoid; display: flex; flex-wrap: wrap; justify-content: space-between; align-content: space-between; }}
                                    .slip-card {{ width: calc(50% - 3mm); height: 135mm; margin: 0 !important; border: 2px solid #000; padding: 8mm; box-sizing: border-box; display: flex; flex-direction: column; }}
                                }}
                                .card-header {{ display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; border-bottom: 2px solid #000; padding-bottom: 8px; }}
                                .title {{ font-size: 18px; font-weight: bold; text-align: center; line-height: 1.2; }}
                                .info {{ font-size: 14px; font-weight: bold; line-height: 1.4; }}
                                .teacher-name {{ font-size: 16px; font-weight: bold; text-align: center; }}
                                .name-text {{ font-size: 22px; }}
                                .slip-table {{ width: 100%; border-collapse: collapse; text-align: center; flex-grow: 1; table-layout: fixed; }}
                                .slip-table td, .slip-table th {{ border: 1px solid #000; padding: 2px; }}
                                .th-row th {{ background: #f0f0f0 !important; font-size: 14px; height: 24px; }}
                                .date-row td {{ font-weight: bold; font-size: 12px; height: 20px; }}
                                .period-cell {{ height: 10%; }}
                                .cell-content {{ font-size: 12px; line-height: 1.1; max-height: 100%; overflow: hidden; display: flex; flex-direction: column; justify-content: center; align-items: center; word-wrap: break-word; word-break: break-all; }}
                                </style></head>
                                <body>
                                    <div class="fixed-btn no-print">
                                        <button onclick="window.print()" style="padding: 10px 30px; font-size: 20px; font-weight: bold; cursor: pointer; background: #fff; color: #1e3a8a; border: none; border-radius: 5px;">🖨️ 確認列印 (請設定為A4直印)</button>
                                    </div>
                                    <div class="print-container">{pages_html}</div>
                                </body></html>
                                """
                                params = {f"g{i}": gid for i, gid in enumerate(selected_gids)}
                                param_keys = ",".join([f":g{i}" for i in range(len(selected_gids))])
                                run_action(f"UPDATE temp_swaps SET is_printed = 1 WHERE group_id IN ({param_keys})", params)
                                components.html(final_page, height=800, scrolling=True)

                    with print_tabs[0]: render_print_tab(upcoming_print_df, "upcoming")
                    with print_tabs[1]: render_print_tab(past_print_df, "past")

# ========================================================
# 🔒 第六分頁：鎖定時段設定 (ADMIN Only) 
# ========================================================
    with tabs[5]:
        st.markdown("### 🔒 鎖定時段設定")
        st.caption("教務處可在此批次鎖定特定老師的特定節次。您可以直接選擇個人，或利用『群組』快速選取大量老師。")
        
        groups_df = run_query("SELECT DISTINCT group_name FROM teacher_groups")
        all_groups = groups_df['group_name'].tolist() if not groups_df.empty else []

        with st.form("add_lock_form"):
            st.markdown("##### 1. 選擇套用的對象 (可單選老師，也可直接選群組，自動聯集)")
            col_t1, col_t2 = st.columns(2)
            with col_t1: lock_groups = st.multiselect("📁 選擇群組 (選填)", all_groups)
            with col_t2: lock_teachers = st.multiselect("👤 選擇個別老師 (選填)", all_teachers_in_db)
            
            st.markdown("##### 2. 設定鎖定條件")
            col1, col2, col3 = st.columns([1, 2, 2])
            with col1: lock_d = st.date_input("📅 鎖定日期", value=selected_date)
            with col2: lock_periods = st.multiselect("⏰ 鎖定節次 (可多選)", [str(i) for i in range(1, 9)])
            with col3: lock_r = st.text_input("📝 鎖定原因", placeholder="例：處室會議、社團")
            
            if st.form_submit_button("批次新增鎖定", type="primary"):
                if not lock_teachers and not lock_groups: st.error("❌ 請至少選擇一個群組或一位老師！")
                elif not lock_periods: st.error("❌ 請至少選擇一堂節次！")
                else:
                    if lock_r.strip() == "": lock_r = "行政鎖定"
                    target_teachers = set(lock_teachers)
                    if lock_groups:
                        params = {f"g{i}": g for i, g in enumerate(lock_groups)}
                        param_keys = ",".join([f":g{i}" for i in range(len(lock_groups))])
                        g_teachers_df = run_query(f"SELECT teacher_name FROM teacher_groups WHERE group_name IN ({param_keys})", params)
                        if not g_teachers_df.empty:
                            target_teachers.update(g_teachers_df['teacher_name'].tolist())
                    
                    added_count = 0
                    for t in target_teachers:
                        for p in lock_periods:
                            chk = run_query("SELECT 1 FROM locked_slots WHERE teacher_name=:t AND lock_date=:d AND period=:p", {"t": t, "d": lock_d.strftime('%Y-%m-%d'), "p": str(p)})
                            if chk.empty:
                                run_action("INSERT INTO locked_slots (teacher_name, lock_date, period, reason) VALUES (:t, :d, :p, :r)", {"t": t, "d": lock_d.strftime('%Y-%m-%d'), "p": str(p), "r": lock_r.strip()})
                                added_count += 1
                    st.success(f"✅ 批次鎖定成功！共新增了 {added_count} 筆鎖定紀錄。")
                    st.rerun()
        
        st.markdown("---")
        st.markdown("#### 📋 目前已鎖定的時段")
        locks_df = run_query("SELECT id, teacher_name, lock_date, period, reason FROM locked_slots ORDER BY lock_date DESC, period ASC")
        
        if locks_df.empty: st.info("目前沒有任何鎖定的時段。")
        else:
            def format_periods(periods):
                if not periods: return ""
                periods = sorted(list(set([int(p) for p in periods])))
                ranges, start, prev = [], periods[0], periods[0]
                for p in periods[1:]:
                    if p == prev + 1: prev = p
                    else:
                        ranges.append(str(start) if start == prev else f"{start}~{prev}")
                        start = prev = p
                ranges.append(str(start) if start == prev else f"{start}~{prev}")
                return ", ".join(ranges)

            locks_df['period_int'] = pd.to_numeric(locks_df['period'], errors='coerce')
            locks_df = locks_df.sort_values(by=['lock_date', 'teacher_name', 'period_int'])

            grouped_locks = []
            for (t_name, l_date, reason), group in locks_df.groupby(['teacher_name', 'lock_date', 'reason']):
                p_list = group['period_int'].dropna().astype(int).tolist()
                id_list = group['id'].tolist()
                grouped_locks.append({
                    'teacher_name': t_name, 'lock_date': l_date, 'sort_date': l_date,
                    'reason': reason, 'periods': p_list, 'period_str': format_periods(p_list), 'ids': id_list
                })
            
            grouped_df = pd.DataFrame(grouped_locks)
            upcoming_locks = grouped_df[grouped_df['sort_date'] >= REAL_TODAY_STR].sort_values(['sort_date', 'teacher_name'], ascending=[True, True])
            past_locks = grouped_df[grouped_df['sort_date'] < REAL_TODAY_STR].sort_values(['sort_date', 'teacher_name'], ascending=[False, True])

            def render_lock_cards(df):
                for idx, row in df.iterrows():
                    with st.container(border=True):
                        c1, c2, c3 = st.columns([2, 5, 2])
                        with c1: st.markdown(f"**{row['teacher_name']}** 老師")
                        with c2: st.markdown(f"`{row['lock_date']}` 第 **{row['period_str']}** 節 ｜ 原因：{row['reason']}")
                        with c3:
                            if st.button("解鎖", key=f"unlock_grp_{row['lock_date']}_{row['teacher_name']}_{idx}"):
                                ids_tuple = tuple(row['ids'])
                                params = {f"id{i}": id_val for i, id_val in enumerate(ids_tuple)}
                                param_keys = ",".join([f":id{i}" for i in range(len(ids_tuple))])
                                run_action(f"DELETE FROM locked_slots WHERE id IN ({param_keys})", params)
                                st.success("✅ 已批次解除鎖定！")
                                st.rerun()

            st.markdown("##### 📅 即將到來 / 進行中")
            if upcoming_locks.empty: st.success("目前沒有即將到來的鎖定時段。")
            else: render_lock_cards(upcoming_locks)
                
            st.markdown("---")
            st.markdown("##### 🕰️ 歷史 / 已過期鎖定")
            if past_locks.empty: st.caption("目前沒有歷史紀錄。")
            else: render_lock_cards(past_locks)

# ========================================================
# 👥 第七分頁：群組管理 (ADMIN Only) 
# ========================================================
    with tabs[6]:
        st.markdown("### 👥 教師群組管理")
        st.caption("建立「自然科」、「處室主任」等群組，方便在『鎖定時段』或其他批次功能中快速套用。一名老師可同時存在於多個群組中。")
        
        with st.form("create_group_form"):
            new_group_name = st.text_input("📁 新群組名稱", placeholder="例如：自然科教師")
            group_members = st.multiselect("👤 選擇群組成員 (可多選並支援搜尋)", all_teachers_in_db)
            if st.form_submit_button("建立 / 更新群組", type="primary"):
                if not new_group_name.strip() or not group_members:
                    st.error("❌ 請輸入群組名稱並至少選擇一位老師！")
                else:
                    g_name = new_group_name.strip()
                    run_action("DELETE FROM teacher_groups WHERE group_name=:g", {"g": g_name})
                    for t in group_members:
                        run_action("INSERT INTO teacher_groups (group_name, teacher_name) VALUES (:g, :t)", {"g": g_name, "t": t})
                    st.success(f"✅ 群組【{g_name}】已成功建立/更新！")
                    st.rerun()

        st.markdown("---")
        st.markdown("#### 📋 目前已建立的群組")
        groups_df = run_query("SELECT group_name, string_agg(teacher_name, ', ') as members FROM teacher_groups GROUP BY group_name")
        
        if groups_df.empty:
            st.info("目前沒有建立任何群組。")
        else:
            for _, row in groups_df.iterrows():
                with st.container(border=True):
                    c1, c2, c3 = st.columns([2, 6, 2])
                    with c1: st.markdown(f"**📁 {row['group_name']}**")
                    with c2: st.caption(f"成員：{row['members']}")
                    with c3:
                        if st.button("刪除群組", key=f"del_grp_{row['group_name']}"):
                            run_action("DELETE FROM teacher_groups WHERE group_name=:g", {"g": row['group_name']})
                            st.warning(f"已刪除群組：{row['group_name']}")
                            st.rerun()

# ========================================================
# ⚙️ 第八分頁：全校帳號管理 (ADMIN Only) 
# ========================================================
    with tabs[7]:
        st.markdown("### ⚙️ 全校教職員帳號管理")
        st.caption("此處列出系統自動建立的全校帳號。您可以先下載清單，於 Excel 中修改「密碼(password)」後，再將檔案上傳回來覆蓋更新。")
        
        users_df = get_user_credentials_cached()
        users_df = users_df[users_df['role'] != 'admin'].sort_values('emp_id')
        st.dataframe(users_df, use_container_width=True)
        
        col_dl, col_ul = st.columns(2)
        with col_dl:
            st.download_button("📥 1. 下載目前帳號清單 (CSV)", data=users_df.to_csv(index=False).encode('utf-8-sig'), file_name="teacher_accounts.csv", mime="text/csv", type="primary")
            
        with col_ul:
            uploaded_file = st.file_uploader("📤 2. 上傳更新後的帳號清單 (CSV)", type=['csv'])
            if uploaded_file is not None:
                try:
                    new_df = pd.read_csv(uploaded_file)
                    req_cols = {'emp_id', 'password', 'real_name', 'role'}
                    if not req_cols.issubset(new_df.columns): st.error(f"❌ 上傳失敗！檔案必須包含這四個欄位：{req_cols}")
                    else:
                        run_action("DELETE FROM user_credentials WHERE role != 'admin'")
                        new_df.to_sql('user_credentials', engine, if_exists='append', index=False)
                        st.cache_data.clear()
                        st.success("✅ 帳號資料已成功整批更新！請重新整理頁面。")
                        st.rerun()
                except Exception as e: st.error(f"上傳發生錯誤：{e}")

# ========================================================
# 💰 第九分頁：第八節計費追蹤 (ADMIN Only)
# ========================================================
    with tabs[8]:
        st.markdown("### 💰 第八節計費結算追蹤")
        st.caption("此處專門列出涉及「第八節輔導課」的已核准調代課紀錄，協助教務處於月底快速結算鐘點費。")
        
        col_d1, col_d2 = st.columns(2)
        with col_d1: start_date = st.date_input("🔍 結算起始日期", value=datetime.date.today().replace(day=1))
        with col_d2: end_date = st.date_input("🔍 結算結束日期", value=datetime.date.today())
        
        if start_date > end_date:
            st.error("❌ 結束日期不能早於起始日期！")
        else:
            df_8th = run_query("""
                SELECT swap_date as 日期, class_name as 班級, 
                       original_teacher as 給出老師, new_teacher as 代上老師, 
                       status, original_subject as 科目
                FROM temp_swaps
                WHERE period = '8'
                  AND status IN ('approved', 'approved_sub')
                  AND (status = 'approved' OR (status = 'approved_sub' AND is_initiator = 1))
                  AND swap_date BETWEEN :s AND :e
                ORDER BY swap_date ASC
            """, {"s": start_date.strftime('%Y-%m-%d'), "e": end_date.strftime('%Y-%m-%d')})
            
            st.markdown("---")
            
            if df_8th.empty:
                st.info(f"☕ 於 {start_date.strftime('%Y/%m/%d')} 至 {end_date.strftime('%Y/%m/%d')} 期間內，沒有任何「第八節」的異動紀錄。")
            else:
                summary = {}
                for _, row in df_8th.iterrows():
                    orig, new_t = row['給出老師'], row['代上老師']
                    if orig not in summary: summary[orig] = {'給出/請假 (減堂)': 0, '代上/調入 (加堂)': 0}
                    if new_t not in summary: summary[new_t] = {'給出/請假 (減堂)': 0, '代上/調入 (加堂)': 0}
                    summary[orig]['給出/請假 (減堂)'] += 1
                    summary[new_t]['代上/調入 (加堂)'] += 1
                
                sum_df = pd.DataFrame.from_dict(summary, orient='index').reset_index()
                sum_df.rename(columns={'index': '老師姓名'}, inplace=True)
                sum_df['淨異動節數'] = sum_df['代上/調入 (加堂)'] - sum_df['給出/請假 (減堂)']
                sum_df = sum_df.sort_values('老師姓名').reset_index(drop=True)
                
                st.markdown("#### 📊 老師第八節淨異動結算表")
                st.dataframe(sum_df, use_container_width=True)
                
                st.markdown("---")
                st.markdown("#### 📜 異動明細紀錄")
                df_8th['班級'] = df_8th['班級'].apply(to_arabic_class)
                df_8th['異動類型'] = df_8th['status'].map({'approved': '雙向調課', 'approved_sub': '單向代課'})
                df_8th = df_8th[['日期', '異動類型', '班級', '科目', '給出老師', '代上老師']]
                st.dataframe(df_8th, use_container_width=True)