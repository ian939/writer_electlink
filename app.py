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
# 1. 설정 및 초기화
# ==========================================
st.set_page_config(page_title="SKelectlink AI 회의록", page_icon="⚡", layout="wide")

# API 키 확인
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    st.error("🚨 Secrets에 GEMINI_API_KEY 설정이 필요합니다.")
    st.stop()

client = genai.Client(api_key=api_key)
MODEL_NAME = "gemini-flash-latest"

# 구글 시트 연결
conn = st.connection("gsheets", type=GSheetsConnection)

# ==========================================
# 2. Helper 함수 (DB, RAG, API)
# ==========================================
def get_users_db():
    """구글 시트 데이터 로드 (캐시 없음)"""
    return conn.read(worksheet="시트1", ttl=0)

def update_user_db(df):
    """구글 시트 데이터 업데이트"""
    conn.update(worksheet="시트1", data=df)
    st.cache_data.clear()

def check_login():
    """로그인 UI 및 로직"""
    if "logged_in" not in st.session_state:
        st.session_state.logged_in = False
        st.session_state.user_info = {}

    if st.session_state.logged_in:
        return True

    # 로그인 화면 디자인
    c1, c2, c3 = st.columns([1, 2, 1])
    with c2:
        st.markdown("<h2 style='text-align: center;'>🔒 SKelectlink 회의록</h2>", unsafe_allow_html=True)
        with st.form("login_form"):
            username = st.text_input("아이디")
            password = st.text_input("비밀번호", type="password")
            submitted = st.form_submit_button("로그인", use_container_width=True)

            if submitted:
                try:
                    df = get_users_db()
                    # 문자열 변환 및 공백 제거 후 비교
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
                    st.error("시스템 접속 오류. 관리자에게 문의하세요.")
    return False

def load_rag_data(personal_files=None):
    rag_text = ""
    file_list = []
    
    # 공용 폴더
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
    
    # 개인 업로드
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
# 3. 앱 실행 로직
# ==========================================

# 1. 로그인 확인
if not check_login():
    st.stop()

# 2. 사용자 정보 로드 (세션 & DB)
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

# 화자 매칭용 세션 초기화
if 'speaker_rows' not in st.session_state:
    st.session_state.speaker_rows = [{'id': 0, 'manual_default': False}, {'id': 1, 'manual_default': False}]
    st.session_state.next_id = 2

def add_speaker_row():
    st.session_state.speaker_rows.append({'id': st.session_state.next_id, 'manual_default': True})
    st.session_state.next_id += 1

def remove_speaker_row(row_id):
    st.session_state.speaker_rows = [r for r in st.session_state.speaker_rows if r['id'] != row_id]

# ---------------------------------------------------------
# [사이드바] 마이페이지
# ---------------------------------------------------------
with st.sidebar:
    st.title(f"👤 {user_name}님")
    
    tab_setting, tab_pw = st.tabs(["⚙️ 설정", "🔒 비밀번호"])
    
    # [설정 탭]
    with tab_setting:
        st.caption("개인 설정을 관리합니다.")
        
        with st.expander("💬 Slack Webhook 설정"):
            new_webhook = st.text_input("Webhook URL", value=saved_webhook, type="password", help="슬랙 채널의 수신용 웹훅 주소")

        with st.expander("📝 프롬프트 관리 (커스텀)", expanded=True):
            if 'editor_prompt' not in st.session_state:
                st.session_state.editor_prompt = active_prompt

            # 슬롯 버튼 (가로 배치)
            c1, c2, c3 = st.columns(3)
            if c1.button("📂 불러1"):
                st.session_state.editor_prompt = slot1_val
                st.rerun()
            if c2.button("📂 불러2"):
                st.session_state.editor_prompt = slot2_val
                st.rerun()
            if c3.button("🔄 초기화"):
                st.session_state.editor_prompt = "" 
                st.rerun()

            new_prompt = st.text_area(
                "프롬프트 내용", 
                value=st.session_state.editor_prompt, 
                height=150,
                placeholder="시스템 기본 프롬프트를 덮어씌웁니다."
            )
            
            c1, c2 = st.columns(2)
            if c1.button("💾 슬롯1 저장"):
                df = get_users_db()
                idx = df[df['username'] == current_user].index
                if not idx.empty:
                    df.at[idx[0], 'prompt_slot1'] = new_prompt
                    update_user_db(df)
                    st.toast("슬롯 1에 저장됨")
                    time.sleep(1); st.rerun()
                    
            if c2.button("💾 슬롯2 저장"):
                df = get_users_db()
                idx = df[df['username'] == current_user].index
                if not idx.empty:
                    df.at[idx[0], 'prompt_slot2'] = new_prompt
                    update_user_db(df)
                    st.toast("슬롯 2에 저장됨")
                    time.sleep(1); st.rerun()

        st.markdown("---")
        if st.button("✅ 전체 설정 적용 (저장)", type="primary", use_container_width=True):
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
                    st.success("적용 완료!")

    # [비밀번호 탭]
    with tab_pw:
        curr_pw = st.text_input("현재 비밀번호", type="password")
        new_pw = st.text_input("새 비밀번호", type="password")
        confirm_pw = st.text_input("확인", type="password")
        
        if st.button("변경하기"):
            if new_pw != confirm_pw: st.error("새 비밀번호 불일치")
            elif not new_pw: st.error("비밀번호 입력 필요")
            else:
                df = get_users_db()
                user_row = df[(df['username'] == current_user) & (df['password'].astype(str) == curr_pw)]
                if not user_row.empty:
                    idx = user_row.index[0]
                    df.at[idx, 'password'] = f"'{new_pw}" 
                    update_user_db(df)
                    st.success("변경 완료. 다시 로그인해주세요.")
                    st.session_state.logged_in = False
                    time.sleep(1.5); st.rerun()
                else:
                    st.error("현재 비밀번호 틀림")

    st.divider()
    
    st.markdown("📂 **참고 자료 (휘발성)**")
    personal_files = st.file_uploader("txt 파일", type=["txt"], accept_multiple_files=True, label_visibility="collapsed")
    rag_text, rag_file_names = load_rag_data(personal_files)
    if rag_file_names:
        st.caption(f"📚 {len(rag_file_names)}개 파일 참조 중")

    st.markdown("")
    if st.button("로그아웃"):
        st.session_state.logged_in = False
        st.rerun()

# ---------------------------------------------------------
# [메인] 앱 UI
# ---------------------------------------------------------
st.title("⚡ SKelectlink 회의록 생성기")

# STEP 1. 입력
with st.container(border=True):
    st.subheader("1. 스크립트 입력")
    script_text = st.text_area("회의 녹취록을 붙여넣으세요.", height=200, key="input_script")
    
    if st.button("🔍 1차 분석 실행", type="primary", use_container_width=True):
        if not script_text.strip():
            st.warning("내용을 입력해주세요.")
        else:
            with st.spinner("분석 중..."):
                meta = analyze_script_metadata(script_text)
                st.session_state['meta'] = meta
                
                # 화자 수 자동 계산 및 초기화
                extracted = meta.get('attendees', [])
                cnt = len(extracted) if len(extracted) > 0 else max(detect_speaker_count(script_text), 2)
                
                # 기존 매칭 정보 초기화
                st.session_state.speaker_rows = [{'id': i, 'manual_default': False} for i in range(cnt)]
                st.session_state.next_id = cnt
                st.success("분석 완료! 아래 정보를 확인해주세요.")

# STEP 2 & 3. 정보 확인 및 매칭
if 'meta' in st.session_state:
    st.markdown("⬇️")
    
    # 2단 컬럼 레이아웃
    col_info, col_mapping = st.columns([1, 1.2])
    
    # [좌측] 기본 정보 확인
    with col_info:
        with st.container(border=True):
            st.subheader("2. 기본 정보")
            meta = st.session_state['meta']
            
            t = st.text_input("주제", value=meta.get('title',''))
            d = st.text_input("날짜", value=meta.get('date', str(datetime.date.today())))
            
            att_list = meta.get('attendees', [])
            if not att_list: 
                att_list = [f"참석자 {i+1}" for i in range(len(st.session_state.speaker_rows))]
            
            att_str = st.text_input("참석자 명단", value=", ".join(att_list))
            final_att = [x.strip() for x in att_str.split(',') if x.strip()]
            
            st.session_state['final_info'] = {"title": t, "date": d, "attendees": final_att}

    # [우측] 화자 매칭
    with col_mapping:
        with st.container(border=True):
            st.subheader("3. 화자 매칭")
            
            if 'final_info' in st.session_state:
                opts = st.session_state['final_info']['attendees'] + ["직접 입력"]
                mapping_list = []
                
                # 스크롤 가능한 영역 (높이 고정)
                with st.container(height=220):
                    for i, row in enumerate(st.session_state.speaker_rows):
                        rid = row['id']
                        c_label, c_sel, c_inp, c_del = st.columns([0.8, 1.2, 1.2, 0.4])
                        
                        c_label.markdown(f"**참석자 {i+1}**")
                        
                        # 디폴트 인덱스
                        d_idx = len(opts)-1 if row['manual_default'] else (i if i < len(opts)-1 else 0)
                        
                        sel = c_sel.selectbox("선택", opts, index=d_idx, label_visibility="collapsed", key=f"s_{rid}")
                        real = sel
                        if sel == "직접 입력":
                            real = c_inp.text_input("이름", label_visibility="collapsed", key=f"t_{rid}")
                        
                        if real: 
                            mapping_list.append(f"- 참석자 {i+1} → {real}")
                        
                        if c_del.button("❌", key=f"d_{rid}"):
                            remove_speaker_row(rid)
                            st.rerun()
                
                if st.button("➕ 화자 추가", on_click=add_speaker_row, use_container_width=True): pass

    # STEP 4. 생성 버튼
    st.markdown("⬇️")
    if st.button("✨ 회의록 생성 (Start)", type="primary", use_container_width=True):
        with st.spinner("최종 회의록 작성 중..."):
            res = generate_minutes(
                st.session_state['final_info'], script_text, "\n".join(mapping_list), 
                rag_text, saved_prompt
            )
            
            if "# [SLACK MESSAGE]" in res: d, s = res.split("# [SLACK MESSAGE]")
            else: d, s = res, "파싱 실패 (또는 슬랙 메시지 없음)"
            
            st.session_state['res_doc'] = d.strip()
            st.session_state['res_slack'] = s.strip()

# STEP 5. 결과 확인
if 'res_doc' in st.session_state:
    st.divider()
    st.subheader("📝 생성 결과")
    
    t1, t2 = st.tabs(["📄 회의록 문서", "💬 슬랙 메시지"])
    
    with t1:
        c_copy, c_view = st.columns(2)
        with c_copy:
            st.text_area("Markdown 복사", value=st.session_state['res_doc'], height=600)
        with c_view:
            st.markdown(st.session_state['res_doc'])
            
    with t2:
        st.text_area("슬랙용 텍스트", value=st.session_state['res_slack'], height=200)
        if saved_webhook:
            if st.button("🚀 저장된 Webhook으로 전송", type="primary"):
                if send_slack_webhook(saved_webhook, st.session_state['res_slack']):
                    st.success("전송되었습니다!")
                else:
                    st.error("전송 실패")
        else:
            st.info("👈 사이드바 설정에서 Webhook URL을 저장하면 바로 전송할 수 있습니다.")
