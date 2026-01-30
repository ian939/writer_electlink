import streamlit as st
import pandas as pd
import json
import re
import datetime
import os
import glob
import requests
import time
from google import genai
from google.genai import types
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. 디자인 및 설정 (Modern CSS Style)
# ==========================================
st.set_page_config(page_title="SKelectlink AI 회의록", page_icon="⚡", layout="wide")

# v0 느낌의 모던 스타일 CSS
modern_style = """
<style>
    @import url("https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/static/pretendard.min.css");
    
    html, body, [class*="css"] {
        font-family: 'Pretendard', -apple-system, BlinkMacSystemFont, system-ui, Roboto, sans-serif !important;
    }

    /* 전체 배경 */
    .stApp {
        background-color: #F8FAFC; 
    }

    /* 메인 타이틀 영역 스타일 */
    .main-header {
        background: linear-gradient(135deg, #3B82F6 0%, #2563EB 100%);
        padding: 40px 20px;
        border-radius: 16px;
        color: white;
        margin-bottom: 30px;
        text-align: center;
        box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1);
    }
    .main-header h1 {
        color: white !important;
        margin: 0;
        font-size: 2.2rem;
        font-weight: 800;
        letter-spacing: -0.02em;
    }
    .main-header p {
        color: rgba(255, 255, 255, 0.9) !important;
        margin-top: 10px;
        font-size: 1.1rem;
    }

    /* 카드형 컨테이너 (st.container(border=True)) 스타일 재정의 */
    div[data-testid="stVerticalBlockBorderWrapper"] > div {
        border: 1px solid #E2E8F0 !important;
        background-color: #FFFFFF;
        border-radius: 12px;
        padding: 24px;
        box-shadow: 0 1px 3px 0 rgba(0, 0, 0, 0.1), 0 1px 2px -1px rgba(0, 0, 0, 0.06);
    }

    /* 텍스트 입력 필드 스타일 (Shadcn UI 느낌) */
    .stTextInput input, .stTextArea textarea {
        border-radius: 8px !important;
        border: 1px solid #CBD5E1 !important;
        background-color: #FFFFFF !important;
        color: #1E293B !important;
        transition: all 0.2s;
        padding: 10px 12px;
    }
    .stTextInput input:focus, .stTextArea textarea:focus {
        border-color: #3B82F6 !important;
        box-shadow: 0 0 0 3px rgba(59, 130, 246, 0.15) !important;
    }

    /* 버튼 스타일 */
    div.stButton > button {
        border-radius: 8px;
        font-weight: 600;
        border: 1px solid #E2E8F0;
        background-color: white;
        color: #475569;
        height: 48px;
        transition: all 0.2s ease;
    }
    div.stButton > button:hover {
        border-color: #3B82F6;
        color: #3B82F6;
        background-color: #EFF6FF;
    }
    
    /* Primary 버튼 (강조) */
    div.stButton > button[kind="primary"] {
        background: linear-gradient(to bottom right, #3B82F6, #2563EB);
        border: none;
        color: white;
        box-shadow: 0 4px 6px -1px rgba(37, 99, 235, 0.3);
    }
    div.stButton > button[kind="primary"]:hover {
        background: linear-gradient(to bottom right, #2563EB, #1D4ED8);
        box-shadow: 0 6px 8px -1px rgba(37, 99, 235, 0.4);
        transform: translateY(-1px);
    }

    /* 탭 스타일 */
    .stTabs [data-baseweb="tab-list"] {
        gap: 8px;
        background-color: #F1F5F9;
        padding: 4px;
        border-radius: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 40px;
        border-radius: 6px;
        background-color: transparent;
        border: none;
        color: #64748B;
        font-weight: 600;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FFFFFF !important;
        color: #2563EB !important;
        box-shadow: 0 1px 3px rgba(0,0,0,0.1);
    }
    
    /* 헤더 텍스트 색상 */
    h2, h3 { color: #1E293B; font-weight: 700; }
    p, label { color: #475569; }
    
</style>
"""
st.markdown(modern_style, unsafe_allow_html=True)

# API 키 및 DB 연결
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("🚨 Secrets에 GEMINI_API_KEY 설정이 필요합니다.")
    st.stop()

client = genai.Client(api_key=api_key)
MODEL_NAME = "gemini-flash-latest"

conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# 2. Helper 함수 (기존 로직 유지)
# ==========================================
def get_users_db():
    return conn.read(worksheet="Sheet1", ttl=0)

def update_user_db(df):
    conn.update(worksheet="Sheet1", data=df)
    st.cache_data.clear()

def check_login():
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.user_info = {}

    if st.session_state.logged_in:
        return True

    # 로그인 화면 디자인 개선
    c1, c2, c3 = st.columns([1, 1.2, 1])
    with c2:
        st.markdown("<br><br><br>", unsafe_allow_html=True)
        with st.container(border=True):
            st.markdown("""
                <div style='text-align: center; margin-bottom: 20px;'>
                    <h2 style='color: #2563EB; margin:0;'>SKelectlink</h2>
                    <p style='font-size: 14px; color: #64748B;'>스마트한 회의록 작성을 위한 AI 비서</p>
                </div>
            """, unsafe_allow_html=True)
            
            with st.form("login_form"):
                username = st.text_input("아이디", placeholder="ID를 입력하세요")
                password = st.text_input("비밀번호", type="password", placeholder="비밀번호를 입력하세요")
                st.markdown("<br>", unsafe_allow_html=True)
                submitted = st.form_submit_button("로그인", type="primary", use_container_width=True)

                if submitted:
                    try:
                        df = get_users_db()
                        user_row = df[
                            (df['username'].astype(str).str.strip() == username.strip()) & 
                            (df['password'].astype(str).str.strip() == password.strip())
                        ]
                        if not user_row.empty:
                            st.session_state.logged_in = True
                            st.session_state.user_info = user_row.iloc[0].to_dict()
                            st.success(f"환영합니다, {st.session_state.user_info.get('name')}님!")
                            time.sleep(0.5)
                            st.rerun()
                        else:
                            st.error("아이디 또는 비밀번호가 일치하지 않습니다.")
                    except Exception as e:
                        st.error(f"시스템 접속 오류: {e}")
    return False

def load_rag_data(personal_files=None):
    rag_text = ""
    file_list = []
    base_dir = os.path.dirname(os.path.abspath(__file__))
    rag_dir = os.path.join(base_dir, 'rag')
    if os.path.exists(rag_dir):
        txt_files = glob.glob(os.path.join(rag_dir, "*.txt"))
        for file_path in txt_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    rag_text += f"\n\n--- [공용: {os.path.basename(file_path)}] ---\n{content}"
                    file_list.append(f"[공용] {os.path.basename(file_path)}")
            except: pass
    if personal_files:
        for uploaded_file in personal_files:
            try:
                string_data = uploaded_file.getvalue().decode("utf-8")
                rag_text += f"\n\n--- [개인: {uploaded_file.name}] ---\n{string_data}"
                file_list.append(f"[개인] {uploaded_file.name}")
            except: pass
    return rag_text, file_list

def send_slack_webhook(url, message):
    try:
        requests.post(url, json={"text": message})
        return True
    except: return False

def analyze_script_metadata(script_text):
    prompt = f"""
    아래 회의 스크립트를 분석하여 JSON 형식으로 정보를 추출하세요.
    [추출 항목] title, date(YYYY-MM-DD), attendees(List[String])
    - attendees: 실명 위주, 없으면 '참석자 1' 형태 유지.
    [SCRIPT] {script_text[:5000]}
    [OUTPUT JSON] {{"title": "주제", "date": "2024-01-01", "attendees": ["이름1", "참석자 2"]}}
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text.strip())
    except: return {"title": "", "date": str(datetime.date.today()), "attendees": []}

def detect_speaker_count(script):
    patterns = re.findall(r'참석자\s?(\d+)', script)
    if patterns: return min(max(map(int, patterns)), 30)
    return 0

def generate_minutes(info, script, mapping, rag_data="", custom_prompt=""):
    today = datetime.date.today().strftime("%Y-%m-%d")
    attendees_str = ", ".join(info['attendees'])
    output_format = """
# [OUTPUT FORMAT] (Markdown)
# 📑 {info['title']}
> **📅 일시:** {info['date']}    
> **👥 참석자:** {attendees_str}    
> **🏢 작성:** AI Assistant
---
### 1. 요약
* [내용]
### 2. 주요 결정사항
* [내용]
### 3. Action Item
| 담당 | 할일 | 기한 |
| :--- | :--- | :--- |
| [이름] | [내용] | [날짜] |
---
# [SLACK MESSAGE]
🚨 **[공유] {info['title']}**
> 요약: [내용]
**✅ 결정:** [내용]
    """
    if custom_prompt and len(custom_prompt) > 20: output_format = custom_prompt
    full_prompt = f"""
# [ROLE] 전문 회의록 비서. RAG 지식 기반 작성.
# [RAG] {rag_data}
# [INPUT] 1. 작성일: {today} / 2. 정보: {info['title']} / {info['date']} / {attendees_str} / 3. 매칭: {mapping} / 4. 스크립트: {script}
# [RULES] 1. Action Item 담당자 뒤에 팀명 추측 금지. 2. 할루시네이션 금지.
{output_format}
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, contents=full_prompt,
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text
    except Exception as e: return f"Error: {e}"

# ==========================================
# 3. 앱 실행 로직
# ==========================================
if not check_login(): st.stop()

# 사용자 정보 로드
user_data = st.session_state.user_info
current_user = user_data['username']
user_name = user_data['name']

try:
    df_fresh = get_users_db()
    my_row = df_fresh[df_fresh['username'] == current_user].iloc[0]
    saved_webhook = str(my_row.get('webhook', '')) if pd.notna(my_row.get('webhook')) else ""
    active_prompt = str(my_row.get('prompt', '')) if pd.notna(my_row.get('prompt')) else ""
    slot1_val = str(my_row.get('prompt_slot1', '')) if pd.notna(my_row.get('prompt_slot1')) else ""
    slot2_val = str(my_row.get('prompt_slot2', '')) if pd.notna(my_row.get('prompt_slot2')) else ""
except:
    saved_webhook, active_prompt, slot1_val, slot2_val = "", "", "", ""

if 'speaker_rows' not in st.session_state:
    st.session_state.speaker_rows = [{'id': 0, 'manual_default': False}, {'id': 1, 'manual_default': False}]
    st.session_state.next_id = 2

def add_speaker_row():
    st.session_state.speaker_rows.append({'id': st.session_state.next_id, 'manual_default': True})
    st.session_state.next_id += 1

def remove_speaker_row(row_id):
    st.session_state.speaker_rows = [r for r in st.session_state.speaker_rows if r['id'] != row_id]

# ---------------------------------------------------------
# [사이드바]
# ---------------------------------------------------------
with st.sidebar:
    st.markdown(f"### 👋 **{user_name}**님")
    
    tab_setting, tab_pw = st.tabs(["⚙️ 설정", "🔒 비밀번호"])
    
    with tab_setting:
        with st.expander("💬 Slack Webhook"):
            new_webhook = st.text_input("Webhook URL", value=saved_webhook, type="password")

        with st.expander("📝 프롬프트 (Custom)", expanded=True):
            if 'editor_prompt' not in st.session_state: st.session_state.editor_prompt = active_prompt
            
            c1, c2, c3 = st.columns(3)
            if c1.button("📂 1"):
                st.session_state.editor_prompt = slot1_val; st.rerun()
            if c2.button("📂 2"):
                st.session_state.editor_prompt = slot2_val; st.rerun()
            if c3.button("🔄 리셋"):
                st.session_state.editor_prompt = ""; st.rerun()

            new_prompt = st.text_area("내용", value=st.session_state.editor_prompt, height=120, placeholder="기본 프롬프트 사용")
            
            c1, c2 = st.columns(2)
            if c1.button("💾 1 저장"):
                df = get_users_db()
                idx = df[df['username'] == current_user].index
                if not idx.empty:
                    df.at[idx[0], 'prompt_slot1'] = new_prompt
                    update_user_db(df)
                    st.toast("저장완료 (슬롯1)"); time.sleep(1); st.rerun()
            if c2.button("💾 2 저장"):
                df = get_users_db()
                idx = df[df['username'] == current_user].index
                if not idx.empty:
                    df.at[idx[0], 'prompt_slot2'] = new_prompt
                    update_user_db(df)
                    st.toast("저장완료 (슬롯2)"); time.sleep(1); st.rerun()

        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✅ 전체 설정 저장", type="primary", use_container_width=True):
            with st.spinner("저장 중..."):
                df = get_users_db()
                idx = df[df['username'] == current_user].index
                if not idx.empty:
                    df.at[idx[0], 'webhook'] = new_webhook
                    df.at[idx[0], 'prompt'] = new_prompt
                    update_user_db(df)
                    st.session_state.editor_prompt = new_prompt
                    st.session_state.user_info['webhook'] = new_webhook
                    st.session_state.user_info['prompt'] = new_prompt
                    st.success("적용되었습니다!")

    with tab_pw:
        curr_pw = st.text_input("현재 PW", type="password")
        new_pw = st.text_input("새 PW (영문자로 시작)", type="password", placeholder="숫자로 시작 불가")
        confirm_pw = st.text_input("확인", type="password")
        
        if st.button("변경하기"):
            if new_pw != confirm_pw:
                st.error("새 비밀번호가 일치하지 않습니다.")
            elif not new_pw:
                st.error("비밀번호를 입력해주세요.")
            elif new_pw[0].isdigit():
                st.error("⚠️ 비밀번호는 숫자로 시작할 수 없습니다. (영문자로 시작해주세요)")
            else:
                df = get_users_db()
                user_row = df[(df['username'] == current_user) & (df['password'].astype(str) == curr_pw)]
                if not user_row.empty:
                    idx = user_row.index[0]
                    df.at[idx, 'password'] = new_pw 
                    update_user_db(df)
                    st.success("변경완료. 재로그인 필요."); st.session_state.logged_in = False; time.sleep(1); st.rerun()
                else: st.error("현재 비밀번호가 틀렸습니다.")

    st.markdown("---")
    st.markdown("**📂 참고 자료 (휘발성)**")
    personal_files = st.file_uploader("파일 업로드", type=["txt"], accept_multiple_files=True, label_visibility="collapsed")
    rag_text, rag_file_names = load_rag_data(personal_files)
    if rag_file_names: st.caption(f"{len(rag_file_names)}개 참조 중")

    if st.button("로그아웃"): st.session_state.logged_in = False; st.rerun()

# ---------------------------------------------------------
# [메인] 앱 UI
# ---------------------------------------------------------
# 기존 텍스트 타이틀 대신 HTML 헤더 사용
st.markdown("""
<div class="main-header">
    <h1>⚡ SKelectlink</h1>
    <p>AI 기반 스마트 회의록 생성 서비스</p>
</div>
""", unsafe_allow_html=True)

# STEP 1. 입력 (Card)
with st.container(border=True):
    st.subheader("1. 📝 스크립트 입력")
    script_text = st.text_area("회의 녹취록을 여기에 붙여넣으세요.", height=200, key="input_script", placeholder="참석자 1: 안녕하세요...\n참석자 2: 오늘 회의는...")
    
    col_empty, col_btn = st.columns([4, 1])
    with col_btn:
        if st.button("🔍 1차 분석", type="primary", use_container_width=True):
            if not script_text.strip():
                st.warning("내용을 입력해주세요.")
            else:
                with st.spinner("내용 분석 중..."):
                    meta = analyze_script_metadata(script_text)
                    st.session_state['meta'] = meta
                    extracted = meta.get('attendees', [])
                    cnt = len(extracted) if len(extracted) > 0 else max(detect_speaker_count(script_text), 2)
                    st.session_state.speaker_rows = [{'id': i, 'manual_default': False} for i in range(cnt)]
                    st.session_state.next_id = cnt
                    st.success("분석 완료")

# STEP 2 & 3. 정보 확인 및 매칭
if 'meta' in st.session_state:
    st.markdown("<br>", unsafe_allow_html=True)
    
    col_info, col_mapping = st.columns([1, 1.2], gap="medium")
    
    # [좌측] 기본 정보 확인 (Card)
    with col_info:
        with st.container(border=True):
            st.subheader("2. 📅 기본 정보")
            meta = st.session_state['meta']
            
            t = st.text_input("회의 주제", value=meta.get('title',''), placeholder="주제를 입력하세요")
            d = st.text_input("회의 날짜", value=meta.get('date', str(datetime.date.today())))
            
            att_list = meta.get('attendees', [])
            if not att_list: 
                att_list = [f"참석자 {i+1}" for i in range(len(st.session_state.speaker_rows))]
            
            att_str = st.text_input("참석자 명단", value=", ".join(att_list))
            final_att = [x.strip() for x in att_str.split(',') if x.strip()]
            
            st.session_state['final_info'] = {"title": t, "date": d, "attendees": final_att}

    # [우측] 화자 매칭 (Card)
    with col_mapping:
        with st.container(border=True):
            st.subheader("3. 🗣️ 화자 매칭")
            
            if 'final_info' in st.session_state:
                opts = st.session_state['final_info']['attendees'] + ["직접 입력"]
                mapping_list = []
                
                # 스크롤 영역
                with st.container(height=260):
                    for i, row in enumerate(st.session_state.speaker_rows):
                        rid = row['id']
                        c_label, c_sel, c_inp, c_del = st.columns([0.8, 1.3, 1.3, 0.4])
                        
                        c_label.markdown(f"<div style='padding-top:12px; font-weight:600; font-size:14px; color:#475569;'>참석자 {i+1}</div>", unsafe_allow_html=True)
                        
                        d_idx = len(opts)-1 if row['manual_default'] else (i if i < len(opts)-1 else 0)
                        
                        sel = c_sel.selectbox("label", opts, index=d_idx, label_visibility="collapsed", key=f"s_{rid}")
                        real = sel
                        if sel == "직접 입력":
                            real = c_inp.text_input("label", label_visibility="collapsed", key=f"t_{rid}", placeholder="이름 입력")
                        
                        if real: mapping_list.append(f"- 참석자 {i+1} → {real}")
                        
                        if c_del.button("✕", key=f"d_{rid}"):
                            remove_speaker_row(rid)
                            st.rerun()
                
                st.markdown("<div style='height:10px;'></div>", unsafe_allow_html=True)
                if st.button("➕ 화자 추가 (직접 입력)", on_click=add_speaker_row, use_container_width=True): pass

    # STEP 4. 생성 버튼
    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("✨ AI 회의록 생성 시작", type="primary", use_container_width=True):
        with st.spinner("AI가 회의록을 작성하고 있습니다..."):
            res = generate_minutes(
                st.session_state['final_info'], script_text, "\n".join(mapping_list), 
                rag_text, saved_prompt
            )
            
            if "# [SLACK MESSAGE]" in res: d, s = res.split("# [SLACK MESSAGE]")
            else: d, s = res, "파싱 실패 (또는 슬랙 메시지 없음)"
            
            st.session_state['res_doc'] = d.strip()
            st.session_state['res_slack'] = s.strip()

# STEP 5. 결과 확인 (Card)
if 'res_doc' in st.session_state:
    st.markdown("<br>", unsafe_allow_html=True)
    with st.container(border=True):
        st.subheader("4. ✅ 생성 결과")
        
        t1, t2 = st.tabs(["📄 회의록 문서", "💬 슬랙 메시지"])
        
        with t1:
            c_copy, c_view = st.columns([1, 1])
            with c_copy:
                st.info("👇 Markdown 텍스트 (복사해서 노션 등에 붙여넣기)")
                st.text_area("raw_md", value=st.session_state['res_doc'], height=500, label_visibility="collapsed")
            with c_view:
                st.success("👇 미리보기")
                st.markdown(st.session_state['res_doc'])
                
        with t2:
            st.text_area("slack_msg", value=st.session_state['res_slack'], height=200, label_visibility="collapsed")
            if saved_webhook:
                if st.button("🚀 저장된 Webhook으로 전송", type="primary"):
                    if send_slack_webhook(saved_webhook, st.session_state['res_slack']):
                        st.success("전송되었습니다!")
                    else: st.error("전송 실패")
            else:
                st.warning("설정 탭에서 Webhook URL을 저장하면 바로 전송 가능합니다.")
