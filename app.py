import os
import ssl
import warnings
import time
import requests
import streamlit as st
import google.generativeai as genai
from urllib3.exceptions import InsecureRequestWarning

# ==========================================
# 0. 사내 보안망 및 SSL 설정 (최상단 배치)
# ==========================================
os.environ['PYTHONHTTPSVERIFY'] = '0'
os.environ['CURL_CA_BUNDLE'] = ''
os.environ['REQUESTS_CA_BUNDLE'] = ''
warnings.filterwarnings("ignore")
requests.packages.urllib3.disable_warnings(category=InsecureRequestWarning)

try:
    _create_unverified_https_context = ssl._create_unverified_context
except AttributeError:
    pass
else:
    ssl._create_default_https_context = _create_unverified_https_context

# ==========================================
# 1. API 설정 및 모델 초기화
# ==========================================
# Secrets 파일이 없으면 직접 입력한 키를 사용하도록 설정
GEMINI_API_KEY = st.secrets["GEMINI_API_KEY"]
LAW_API_KEY = st.secrets["LAW_API_KEY"]

genai.configure(api_key=GEMINI_API_KEY, transport='rest')
model = genai.GenerativeModel('gemini-3-flash-preview')

# ==========================================
# 2. 디자인 개선 (CSS)
# ==========================================
st.set_page_config(page_title="AI Legal Assistant", page_icon="⚖️", layout="wide")

st.markdown("""
    <style>
    .block-container { max-width: 1100px; padding-top: 2rem; }
    .stChatMessage { border-radius: 15px; margin-bottom: 1rem; }
    /* 답변 완료 후 상단으로 시선을 유도하기 위한 앵커 설정 */
    #output-header { padding-top: 10px; }
    </style>
    """, unsafe_allow_html=True)

st.markdown("""
    <style>
    .main {
        background-color: transparent;
    }
    .stChatMessage {
        border-radius: 15px;
        padding: 1rem;
        margin-bottom: 1rem;
    }
    .stButton>button {
        border-radius: 20px;
        width: 100%;
    }
    .status-box {
        padding: 10px;
        border-radius: 10px;
        background-color: #f0f2f6;
        margin-bottom: 10px;
        font-size: 0.9rem;
    }

    /* 하단 입력창(Chat Input) 너비를 결과창과 동일하게 강제 고정 */
    .stChatInputContainer {
        max-width: 400px;
        margin: 0 auto;
    }
    
    </style>
    """, unsafe_allow_html=True)

# ==========================================
# 3. 핵심 기능 함수
# ==========================================
def search_law_data(keyword, target="prec"):
    url = f"https://www.law.go.kr/DRF/lawSearch.do?OC={LAW_API_KEY}&target={target}&type=JSON&q={keyword}"
    try:
        res = requests.get(url, verify=False, timeout=15)
        if res.status_code == 200:
            return res.json()
    except:
        return None
    return None

def refine_legal_data(raw_json, target_type):
    refined_text = ""
    try:
        if target_type == "prec":
            items = raw_json.get('PrecSearch', {}).get('prec', [])
            for item in items[:2]:
                refined_text += f"\n[판례] {item.get('사건명')}\n- 요지: {item.get('판결요지', '내용없음')[:300]}...\n"
        else:
            items = raw_json.get('LawSearch', {}).get('law', [])
            for item in items[:2]:
                refined_text += f"\n[법령] {item.get('법령명명', '법령명없음')}\n- 조문: {item.get('법령본문', '내용없음')[:300]}...\n"
    except:
        return ""
    return refined_text

# ==========================================
# 4. UI 레이아웃
# ==========================================

# 사이드바 디자인
with st.sidebar:
    st.title("⚖️ Legal AI")
    st.markdown("---")
    st.markdown("### 서비스 안내")
    st.info("국가법령정보센터의 실시간 데이터와 Gemini의 추론 능력을 결합한 법률 어시스턴트입니다.")
    
    st.markdown("### 지원 범위")
    st.write("✔️ 신규 비즈니스 모델 기반")
    st.write("✔️ 행정규칙 및 판례 해석")
    st.write("✔️ 규제 리스크 분석")
    
    st.markdown("---")
    if st.button("새 대화 시작하기"):
        st.session_state.messages = []
        st.rerun()

# 메인 헤더
st.title("⚖️AI Legal Assistant")
st.markdown("복잡한 법률 상황이나 사업 아이디어를 입력하면 관련 법령을 분석합니다.")

# 대화 기록 관리
if "messages" not in st.session_state:
    st.session_state.messages = []

# 대화 기록 표시 (Streamlit 최신 채팅 UI)
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# 사용자 입력
if prompt := st.chat_input("사업 모델이나 상황, 요청사항을 입력하세요."):
    # 사용자 메시지 저장 및 표시
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    with st.chat_message("assistant"):
        # 분석 과정은 상태창에서 보여줌
        status = st.status("🔍 법률 데이터를 검색하고 분석하는 중...", expanded=True)
            
        try:
            # [Step 1] 정교한 키워드 추출
            st.write("🎯 핵심 법적 키워드 추출 중...")
            kw_prompt = f"""
            당신은 법률 전문 검색 쿼리 작성자입니다. 
            사용자 상황: {prompt}
            
            위 상황의 인허가 요건, 위법 여부를 확인하기 위해 국가법령정보센터에서 검색할 단어를 2개만 뽑아주세요.
            조건:
            1. '법인세', '증여세', '행정소송 절차'와 같은 무관한 판례가 나오지 않도록 비즈니스 핵심 법령 위주로 구성하세요.
            2. 검색어는 '법령명 + 핵심단어' 조합으로 만드세요. (예: 전자금융거래법 선불전자지급수단)
            3. 결과는 반드시 콤마(,)로만 구분해서 출력하세요.
            """
            kw_res = model.generate_content(kw_prompt)
            keywords = [k.strip() for k in kw_res.text.split(',')]
            
            # [Step 2] 데이터 수집 (법령 1건, 판례 1건씩 수집)
            all_legal_context = ""
            targets = ["law", "prec"]
            
            for idx, kw in enumerate(keywords):
                target_type = targets[idx] if idx < len(targets) else "prec"
                st.write(f"📁 '{kw}' 관련 {target_type} 데이터 수집 중...")
                raw_data = search_law_data(kw, target=target_type)
                if raw_data:
                    all_legal_context += refine_legal_data(raw_data, target_type)
                time.sleep(3.0)

            # [Step 3] 데이터 필터링 단계 추가
            st.write("🧹 관련성 낮은 데이터 필터링 중...")
            filter_prompt = f"""
            사용자 상황: {prompt}
            수집된 데이터: {all_legal_context}
            
            위 데이터 중 사용자 상황과 '직접적인' 관련이 없는 내용은 삭제하고, 
            실제 비즈니스 가이드에 필요한 핵심 법령/판례 내용만 남겨서 정리해줘.
            만약 모두 관련이 없다면 '검색된 관련 법령 정보가 부족함'이라고 적어줘.
            """
            filtered_context = model.generate_content(filter_prompt).text

            # [Step 4] 최종 심층 분석 보고서 작성
            st.write("📑 최종 분석 보고서 작성 중...")
            final_prompt = f"""
            당신은 숙련된 법률 컨설턴트입니다. 아래 필터링된 데이터를 바탕으로 분석 보고서를 작성하세요.
            
            사용자 상황: {prompt}
            참고 법률 데이터: {filtered_context}
            
            [지침]
            1. (대화형 도입) 처음에는 인사나 서론 없이 "이 사업(상황)의 핵심은 ~입니다"라고 짧게 핵심 요약부터 시작하세요.
            2. (BM 분석) 질문이 신규 아이디어라면 등록 요건(자본금/인력 등), 관련 법령, 법적 리스크를 순서대로 설명하세요.
            3. (법률 질문) 일반 질문이라면 관련 법률 조항과 판례 요지를 명확히 소개하세요.
            4. (정직성) 만약 확보된 데이터 중 일치하는 법률이나 판례가 없으면 지어내지 말고 "현재 데이터로는 정확한 근거를 찾기 어렵다"고 답하세요.
            5. (추가 질문 유도) 분석 후에는 반드시 "더 구체적으로 어떤 부분을 알아봐 드릴까요?" 같은 메시지로 대화를 이어가세요.
            6. 마지막에 면책 문구를 포함하세요.
            """
            
            time.sleep(1.5)
            final_res = model.generate_content(final_prompt)
            full_response = final_res.text
            
            # 상태 업데이트 완료
            status.update(label="분석 완료!", state="complete", expanded=False)
            
            # 최종 결과 마크다운 표시
            st.markdown(full_response)
            st.session_state.messages.append({"role": "assistant", "content": full_response})

        except Exception as e:
            status.update(label="오류 발생", state="error")

            st.error(f"오류가 발생했습니다: {str(e)}")



