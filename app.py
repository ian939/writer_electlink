import streamlit as st
import pandas as pd
import json
import re
import datetime
import os
import glob
import requests
from google import genai
from google.genai import types
from streamlit_gsheets import GSheetsConnection

# ==========================================
# 1. 설정 및 초기화
# ==========================================
st.set_page_config(page_title="SKelectlink AI 회의록", page_icon="⚡", layout="wide")

# API 키 및 DB 연결
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("Secrets에 GEMINI_API_KEY 설정이 필요합니다.")
    st.stop()

client = genai.Client(api_key=api_key)
MODEL_NAME = "gemini-flash-latest"

# 구글 시트 연결 (DB)
conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# 2. DB 관련 함수 (Google Sheets)
# ==========================================
def get_users_db():
    """구글 시트에서 전체 유저 데이터를 가져옴 (캐시 없이 최신 데이터)"""
    # ttl=0으로 설정해 항상 최신 데이터를 불러옴
    return conn.read(worksheet="Sheet1", ttl=0)

def update_user_db(df):
    """변경된 데이터프레임을 구글 시트에 저장"""
    conn.update(worksheet="Sheet1", data=df)
    st.cache_data.clear() # 캐시 초기화

def check_login():
    """로그인 처리 로직"""
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.user_info = {}

    if st.session_state.logged_in:
        return True

    st.markdown("## 🔒 로그인 (SKelectlink)")
    
    with st.form("login_form"):
        username = st.text_input("아이디")
        password = st.text_input("비밀번호", type="password")
        submitted = st.form_submit_button("로그인")

        if submitted:
            try:
                df = get_users_db()
                # 아이디/비번 확인
                user_row = df[(df['username'] == username) & (df['password'].astype(str) == password)]
                
                if not user_row.empty:
                    st.session_state.logged_in = True
                    # 유저 정보를 세션에 저장 (Series -> Dict)
                    st.session_state.user_info = user_row.iloc[0].to_dict()
                    st.success("로그인 성공!")
                    st.rerun()
                else:
                    st.error("아이디 또는 비밀번호가 잘못되었습니다.")
            except Exception as e:
                st.error(f"DB 연결 오류: {e}")
    
    return False

# ==========================================
# 3. 비즈니스 로직 함수
# ==========================================
def load_rag_data(personal_files=None):
    rag_text = ""
    file_list = []
    
    # 1. 공용 폴더
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
    
    # 2. 개인 업로드 (세션)
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
    
    [SCRIPT]
    {script_text[:5000]}
    
    [OUTPUT JSON]
    {{"title": "주제", "date": "2024-01-01", "attendees": ["이름1", "참석자 2"]}}
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json")
        )
        return json.loads(response.text.strip())
    except:
        return {"title": "", "date": str(datetime.date.today()), "attendees": []}

def detect_speaker_count(script):
    patterns = re.findall(r'참석자\s?(\d+)', script)
    if patterns: return min(max(map(int, patterns)), 30)
    return 0

def generate_minutes(info, script, mapping, rag_data="", custom_prompt=""):
    today = datetime.date.today().strftime("%Y-%m-%d")
    attendees_str = ", ".join(info['attendees'])
    
    # 기본 포맷
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
    
    # 사용자 커스텀 포맷이 있으면 교체
    if custom_prompt and len(custom_prompt) > 20:
        output_format = custom_prompt

    full_prompt = f"""
# [ROLE]
전문 회의록 비서. RAG 지식 기반 작성.

# [RAG]
{rag_data}

# [INPUT]
1. 작성일: {today}
2. 정보: {info['title']} / {info['date']} / {attendees_str}
3. 매칭: {mapping}
4. 스크립트:
{script}

# [RULES]
1. Action Item 담당자 뒤에 팀명 추측 금지.
2. 할루시네이션 금지.

{output_format}
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=full_prompt,
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text
    except Exception as e:
        return f"Error: {e}"


# ==========================================
# 4. 메인 앱 실행
# ==========================================

# 1. 로그인 체크
if not check_login():
    st.stop()

# 2. 로그인 후 사용자 정보 로드
user_data = st.session_state.user_info
current_user = user_data['username']
user_name = user_data['name']
saved_webhook = str(user_data.get('webhook', '')) if pd.notna(user_data.get('webhook')) else ""
saved_prompt = str(user_data.get('prompt', '')) if pd.notna(user_data.get('prompt')) else ""

# ==========================================
# 5. UI 구성
# ==========================================

# [사이드바] 마이페이지
with st.sidebar:
    st.title(f"👤 {user_name}님")
    
    with st.expander("🔧 개인 설정 (프로필)", expanded=False):
        with st.form("profile_form"):
            st.caption("설정을 저장하면 서버(구글시트)에 반영됩니다.")
            new_webhook = st.text_input("Slack Webhook URL", value=saved_webhook)
            new_prompt = st.text_area("나만의 프롬프트 (Markdown)", value=saved_prompt, height=150)
            
            if st.form_submit_button("💾 설정 저장"):
                with st.spinner("저장 중..."):
                    # DB 업데이트 로직
                    df = get_users_db()
                    # 해당 유저 행 찾아서 업데이트
                    idx = df[df['username'] == current_user].index
                    if not idx.empty:
                        df.at[idx[0], 'webhook'] = new_webhook
                        df.at[idx[0], 'prompt'] = new_prompt
                        update_user_db(df)
                        
                        # 세션 정보도 업데이트
                        st.session_state.user_info['webhook'] = new_webhook
                        st.session_state.user_info['prompt'] = new_prompt
                        st.success("저장되었습니다! (새로고침 불필요)")
                        # 변수 즉시 반영
                        saved_webhook = new_webhook
                        saved_prompt = new_prompt
                    else:
                        st.error("유저 정보를 찾을 수 없습니다.")

    st.divider()
    
    # 개인 RAG 업로드 (세션용)
    st.markdown("📂 **참고 자료 (이번 접속용)**")
    personal_files = st.file_uploader("txt 파일 추가", type=["txt"], accept_multiple_files=True)
    rag_text, rag_file_names = load_rag_data(personal_files)
    
    if rag_file_names:
        st.caption(f"참고 중: {len(rag_file_names)}개")

    if st.button("로그아웃"):
        st.session_state.logged_in = False
        st.rerun()

# [메인]
st.title("⚡ SKelectlink 회의록 생성기")

# 화자 매칭 상태 관리
if 'speaker_rows' not in st.session_state:
    st.session_state.speaker_rows = [{'id': 0, 'manual_default': False}, {'id': 1, 'manual_default': False}]
    st.session_state.next_id = 2

def add_speaker_row():
    st.session_state.speaker_rows.append({'id': st.session_state.next_id, 'manual_default': True})
    st.session_state.next_id += 1

def remove_speaker_row(row_id):
    st.session_state.speaker_rows = [r for r in st.session_state.speaker_rows if r['id'] != row_id]

# ----------------------------
# STEP 1. 입력
# ----------------------------
st.subheader("1. 스크립트 입력")
script_text = st.text_area("회의 녹취", height=150, key="input_script")

if st.button("🔍 1차 분석", type="primary"):
    if script_text:
        with st.spinner("분석 중..."):
            meta = analyze_script_metadata(script_text)
            st.session_state['meta'] = meta
            cnt = len(meta.get('attendees', []))
            cnt = cnt if cnt > 0 else max(detect_speaker_count(script_text), 2)
            st.session_state.speaker_rows = [{'id': i, 'manual_default': False} for i in range(cnt)]
            st.session_state.next_id = cnt
            st.success("완료")

# ----------------------------
# STEP 2. 확인
# ----------------------------
if 'meta' in st.session_state:
    st.markdown("---")
    meta = st.session_state['meta']
    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        t = c1.text_input("주제", value=meta.get('title',''))
        d = c2.text_input("날짜", value=meta.get('date', str(datetime.date.today())))
        
        att_list = meta.get('attendees', [])
        if not att_list: att_list = [f"참석자 {i+1}" for i in range(len(st.session_state.speaker_rows))]
        att_str = st.text_input("참석자", value=", ".join(att_list))
        
        st.session_state['final_info'] = {"title": t, "date": d, "attendees": [x.strip() for x in att_str.split(',')]}

# ----------------------------
# STEP 3. 매칭
# ----------------------------
if 'final_info' in st.session_state:
    st.markdown("---")
    opts = st.session_state['final_info']['attendees'] + ["직접 입력"]
    mapping_list = []
    
    with st.container(height=300, border=True):
        for i, row in enumerate(st.session_state.speaker_rows):
            rid = row['id']
            cols = st.columns([1, 2, 2, 0.3])
            cols[0].markdown(f"**🗣️ 참석자 {i+1}**")
            d_idx = len(opts)-1 if row['manual_default'] else (i if i < len(opts)-1 else 0)
            sel = cols[1].selectbox("선택", opts, index=d_idx, label_visibility="collapsed", key=f"s_{rid}")
            real = sel
            if sel == "직접 입력": real = cols[2].text_input("입력", label_visibility="collapsed", key=f"t_{rid}")
            if real: mapping_list.append(f"- 참석자 {i+1} → {real}")
            if cols[3].button("❌", key=f"d_{rid}"):
                remove_speaker_row(rid)
                st.rerun()
                
    if st.button("➕ 화자 추가", on_click=add_speaker_row): pass

    # ----------------------------
    # STEP 4. 생성
    # ----------------------------
    st.markdown("---")
    if st.button("✨ 회의록 생성", type="primary", use_container_width=True):
        with st.spinner("생성 중..."):
            res = generate_minutes(
                st.session_state['final_info'], script_text, "\n".join(mapping_list), 
                rag_text, saved_prompt # 저장된 커스텀 프롬프트 사용
            )
            if "# [SLACK MESSAGE]" in res: d, s = res.split("# [SLACK MESSAGE]")
            else: d, s = res, "파싱 실패"
            st.session_state['res_doc'] = d.strip()
            st.session_state['res_slack'] = s.strip()

# ----------------------------
# STEP 5. 결과
# ----------------------------
if 'res_doc' in st.session_state:
    st.markdown("---")
    t1, t2 = st.tabs(["📄 문서", "💬 슬랙"])
    with t1: st.text_area("결과", value=st.session_state['res_doc'], height=500); st.markdown(st.session_state['res_doc'])
    with t2:
        st.text_area("메시지", value=st.session_state['res_slack'], height=200)
        if saved_webhook:
            if st.button("🚀 저장된 Webhook으로 전송"):
                if send_slack_webhook(saved_webhook, st.session_state['res_slack']): st.success("전송됨")
                else: st.error("실패")
        else: st.info("사이드바 설정에서 Webhook URL을 저장하면 바로 전송 가능합니다.")
