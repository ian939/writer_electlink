import streamlit as st
import os
import glob
import json
import re
import datetime
import time
from google import genai
from google.genai import types

# ==========================================
# 1. 설정 및 초기화
# ==========================================
st.set_page_config(page_title="SKelectlink AI 회의록", page_icon="⚡", layout="wide")

# [보안] API 키 처리
if "GEMINI_API_KEY" in st.secrets:
    api_key = st.secrets["GEMINI_API_KEY"]
else:
    api_key = st.sidebar.text_input("Gemini API Key", type="password")

if not api_key:
    st.warning("👈 사이드바에 Gemini API 키를 입력하거나 Secrets를 설정해주세요.")
    st.stop()

# 클라이언트 초기화
client = genai.Client(api_key=api_key)

# -----------------------------------------------------------
# [모델 설정]
# 사용자가 검증한 최신 버전 ("latest") 사용
# 404 Not Found 에러 방지용
# -----------------------------------------------------------
MODEL_NAME = "gemini-flash-latest"

# ==========================================
# 2. 함수 정의
# ==========================================

def load_rag_data():
    """rag 폴더의 txt 파일들을 읽어옵니다."""
    rag_text = ""
    file_names = []
    
    base_dir = os.path.dirname(os.path.abspath(__file__))
    rag_dir = os.path.join(base_dir, 'rag')
    
    if os.path.exists(rag_dir):
        txt_files = glob.glob(os.path.join(rag_dir, "*.txt"))
        for file_path in txt_files:
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    content = f.read()
                    rag_text += f"\n\n--- [참고지식: {os.path.basename(file_path)}] ---\n{content}"
                    file_names.append(os.path.basename(file_path))
            except: pass
            
    return rag_text, file_names

def analyze_script_metadata(script_text):
    """스크립트 내용을 분석하여 제목, 날짜, 참석자 후보를 추출합니다."""
    prompt = f"""
    아래 회의 스크립트를 분석하여 JSON 형식으로 정보를 추출하세요.
    
    [추출 항목]
    1. title: 회의 주제나 제목 (내용을 요약해서 1줄로)
    2. date: 회의 날짜 (YYYY-MM-DD), 언급 없으면 오늘 날짜
    3. attendees: 대화에 참여한 사람들의 실제 이름 리스트 (직급 제외, 이름만 추출)

    [SCRIPT]
    {script_text[:5000]}
    
    [OUTPUT JSON FORMAT]
    {{"title": "주제", "date": "2024-01-01", "attendees": ["이름1", "이름2"]}}
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(response_mime_type="application/json") # JSON 모드 강제
        )
        text = response.text.strip()
        return json.loads(text)
    except Exception as e:
        st.error(f"분석 오류: {str(e)}")
        return {"title": "", "date": str(datetime.date.today()), "attendees": []}

def detect_speaker_count(script):
    """'참석자 N' 패턴을 찾아 최대 숫자를 반환합니다."""
    patterns = re.findall(r'참석자\s?(\d+)', script)
    if patterns:
        max_num = max(map(int, patterns))
        return min(max_num, 30) 
    return 0

def generate_minutes(info, script, mapping, rag_data=""):
    """최종 회의록을 생성합니다."""
    today = datetime.date.today().strftime("%Y-%m-%d")
    attendees_str = ", ".join(info['attendees'])
    
    prompt = f"""
# [ROLE]
당신은 SKelectlink의 전문 회의록 작성 비서입니다. 
제공된 스크립트와 RAG 지식을 바탕으로 팩트 기반의 회의록을 작성합니다.

# [REFERENCE (RAG Knowledge)]
이 섹션의 지식을 우선적으로 참고하여 사내 전문 용어, 프로젝트명, 맥락을 정확히 파악하십시오.
{rag_data}

# [INPUT DATA]
1. 작성일: {today}
2. 회의정보: {info['title']} / {info['date']}
3. 참석자 명단: {attendees_str}
4. **화자 매칭 정보 (필수 적용):** {mapping}
(스크립트의 '참석자 N'을 위 매칭 정보를 보고 반드시 실명으로 변경하여 작성할 것)

5. [SCRIPT]
{script}

# [OUTPUT FORMAT] (Markdown)
# 📑 {info['title']}
> **📅 일시:** {info['date']}   
> **👥 참석자:** {attendees_str}   
> **🏢 작성:** AI Assistant (SKelectlink)
---
### 1. 회의 개요
* **목적:** [회의 목적 요약]
* **핵심 요약:** [전체 내용 3줄 요약]

### 2. 주요 발언 및 결정 (Key Message)
> **💡 주요 결정사항**
* **[이름]:** [핵심 발언 및 지시 사항]

### 3. 상세 논의 안건
#### [주제 1]
* **논의 내용:** [상세 내용]
* **결론:** [결정된 사항]

### 4. Action Item (To-Do)
| 담당자 | 할 일 | 기한 |
| :--- | :--- | :--- |
| [이름] | [구체적 실행 과제] | [날짜/미정] |

### 5. 종합 결론
* [향후 계획 및 마무리 코멘트]

---
# [SLACK MESSAGE]
🚨 **[공유] {info['title']} 회의록**
> **3줄 요약**
> 1. [요약1]
> 2. [요약2]
> 3. [요약3]

**✅ 결정:** [핵심 결정사항]
**⚡ Action Item:**
- [담당]: [할일]
    """
    try:
        response = client.models.generate_content(
            model=MODEL_NAME, 
            contents=prompt,
            config=types.GenerateContentConfig(temperature=0.2)
        )
        return response.text
    except Exception as e:
        return f"회의록 생성 오류 (Quota 확인 필요): {e}"

# ==========================================
# 3. Streamlit UI 구성
# ==========================================
st.title("⚡ SKelectlink 회의록 생성기")
st.caption("RAG(사내지식) + Gemini Latest 기반")

# 사이드바: RAG 상태 표시
rag_text, rag_files = load_rag_data()
with st.sidebar:
    st.subheader("📚 RAG 지식 베이스")
    if rag_files:
        st.success(f"{len(rag_files)}개의 지식 파일 로드됨")
        with st.expander("파일 목록 보기"):
            for f in rag_files:
                st.caption(f"- {f}")
    else:
        st.info("repository의 'rag/' 폴더에 .txt 파일이 없습니다.")

if 'num_speakers' not in st.session_state:
    st.session_state.num_speakers = 2

# ------------------------------------------
# STEP 1. 스크립트 입력
# ------------------------------------------
st.subheader("1. 스크립트 입력")
# [수정] 컨트롤+엔터로 실행되지 않도록 form 사용 안함
script_text = st.text_area(
    "회의 녹취 스크립트를 붙여넣으세요", 
    height=200, 
    placeholder="참석자 1: 안녕하세요...\n참석자 2: 반갑습니다...",
    key="input_script"
)

# [수정] 분석 버튼을 명시적으로 눌러야만 진행
if st.button("🔍 1차 정보 분석 (클릭)", type="primary"):
    if not script_text.strip():
        st.warning("스크립트를 먼저 입력해주세요.")
    else:
        with st.spinner("AI가 내용을 분석 중입니다..."):
            # 1. 메타데이터 추출
            meta = analyze_script_metadata(script_text)
            st.session_state['meta'] = meta
            
            # 2. 화자 수 감지
            detected_count = detect_speaker_count(script_text)
            
            # 3. 화자 수 보정
            current_attendees_count = len(meta.get('attendees', []))
            st.session_state.num_speakers = max(current_attendees_count, detected_count)
            if st.session_state.num_speakers == 0: st.session_state.num_speakers = 2
            
            st.success("분석 완료! 아래 정보를 확인해주세요.")

# ------------------------------------------
# STEP 2. 정보 확인 및 수정
# ------------------------------------------
if 'meta' in st.session_state:
    st.markdown("---")
    st.subheader("2. 회의 정보 확인")
    
    meta = st.session_state['meta']
    
    with st.container(border=True):
        c1, c2 = st.columns([2, 1])
        input_title = c1.text_input("회의 주제", value=meta.get('title', ''))
        input_date = c2.text_input("회의 날짜", value=meta.get('date', str(datetime.date.today())))
        
        # 참석자 태그 관리
        current_attendees = meta.get('attendees', [])
        input_attendees_str = st.text_input("참석자 명단 (자동 추출됨, 수정 가능)", value=", ".join(current_attendees))
        
        final_attendees = [x.strip() for x in input_attendees_str.split(',') if x.strip()]
        
        st.session_state['final_info'] = {
            "title": input_title,
            "date": input_date,
            "attendees": final_attendees
        }

# ------------------------------------------
# STEP 3. 화자 매칭 (핵심 로직)
# ------------------------------------------
if 'final_info' in st.session_state:
    st.markdown("---")
    st.subheader("3. 화자 매칭 (Speaker Mapping)")
    st.info("스크립트의 '참석자 N'이 실제로 누구인지 연결해주세요.")

    attendee_options = st.session_state['final_info']['attendees'] + ["직접 입력"]
    mapping_list = []

    # [수정] 스크롤 가능한 컨테이너 적용 (참석자 많을 때 화면 보호)
    with st.container(height=300, border=True):
        for i in range(st.session_state.num_speakers):
            cols = st.columns([1, 2, 2])
            cols[0].markdown(f"**🗣️ 참석자 {i+1}**")
            
            # 기본 선택값 로직
            default_idx = i if i < len(attendee_options) - 1 else 0
            
            selected_name = cols[1].selectbox(
                f"대상 선택 ({i})", 
                attendee_options, 
                index=default_idx, 
                label_visibility="collapsed",
                key=f"speaker_sel_{i}"
            )
            
            real_name = selected_name
            if selected_name == "직접 입력":
                real_name = cols[2].text_input(f"이름 입력 ({i})", label_visibility="collapsed", key=f"speaker_txt_{i}")
            
            if real_name:
                mapping_list.append(f"- 참석자 {i+1} → {real_name}")

    # 화자 추가 버튼
    if st.button("➕ 화자 추가"):
        st.session_state.num_speakers += 1
        st.rerun()

    # ------------------------------------------
    # STEP 4. 회의록 생성
    # ------------------------------------------
    st.markdown("---")
    if st.button("✨ 회의록 생성 시작", type="primary", use_container_width=True):
        if not script_text:
            st.error("스크립트가 없습니다.")
        else:
            with st.spinner("최종 회의록 작성 중... (약 10~20초 소요)"):
                mapping_str = "\n".join(mapping_list)
                result_text = generate_minutes(
                    st.session_state['final_info'], 
                    script_text, 
                    mapping_str, 
                    rag_text
                )
                
                # 결과 분리
                if "# [SLACK MESSAGE]" in result_text:
                    doc_part, slack_part = result_text.split("# [SLACK MESSAGE]")
                else:
                    doc_part, slack_part = result_text, "슬랙 메시지 생성 실패"
                
                st.session_state['result_doc'] = doc_part.strip()
                st.session_state['result_slack'] = slack_part.strip()

# ------------------------------------------
# STEP 5. 결과 확인
# ------------------------------------------
if 'result_doc' in st.session_state:
    st.markdown("---")
    st.subheader("📝 생성 결과")
    
    tab1, tab2 = st.tabs(["📄 회의록 (Markdown)", "💬 슬랙 메시지"])
    
    with tab1:
        st.text_area("복사하여 사용하세요", value=st.session_state['result_doc'], height=500)
        st.markdown(st.session_state['result_doc']) 
        
    with tab2:
        st.text_area("슬랙/메신저용", value=st.session_state['result_slack'], height=300)
