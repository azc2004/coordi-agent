# 👗 AI 맞춤 코디 추천 및 다단계 가상 착장(VTON) 프로토타입 서비스

본 프로젝트는 기준 상품 정보를 바탕으로 AI가 최적의 코디 아이템을 분석·추천하고, 이를 활용해 **다단계 누적 가상 착장(Layered Try-on)** 및 **스타일링 코디 룩북**을 연동해주는 프로토타입 서비스입니다.

---

## 🛠️ 기술 스택 (Technology Stack)

- **Frontend / UI**: [Streamlit](https://streamlit.io/) (Python Web App Framework)
- **AI Engine (LLM & Vision)**: [Google GenAI SDK](https://github.com/googleapis/python-genai) (`gemini-2.5-flash`, `gemini-3.1-flash-image`)
- **Image Processing**: [Pillow (PIL)](https://python-pillow.org/)
- **Data & APIs**: Halfclub OpenAPI (Elasticsearch 기반 검색 및 필터 연동)
- **Runtime**: Python 3.14+

---

## 🌟 핵심 기능 (Key Features)

1. **정교한 맞춤 코디 추천**:
   - 기준 상품의 성별, 시즌, 상세 속성(재질, 태그, 색상) 및 카테고리를 활용해 어울리는 조합 제안
   - 추천 이유(Reason)를 친절한 한국어 어조로 출력

2. **Elasticsearch 기반 하이브리드 필터 검색**:
   - AI 추천 아이템 정보에서 성별 코드(`gndCd`), 카테고리(`dpCtgrNo`), 브랜드 코드(`brandCd`)를 파라미터 필터로 정밀 추출
   - 필터 처리가 불가능한 세부 속성(예: '린넨 와이드', '스트라이프')만 `search_keyword`로 추출해 결합 검색함으로써 검색 신뢰도 극대화
   - 검색 필터 정보는 아코디언(`st.expander`) 형태로 펼쳐보기 지원
   - 남성/여성/남녀공용 중복 매칭형 기획 상품 제거 필터링

3. **다단계 누적 가상 착장 (Layered VTON)**:
   - `gemini-3.1-flash-image` 멀티모달 모델을 통해, 이전 가상 착장이 완료된 결과물 위에 다른 아이템(예: 상의 -> 하의 -> 신발)을 **차례로 누적해서 입어보는 레이어드 피팅** 지원
   - 이전 단계에 추가된 의상이 훼손되거나 원래대로 초기화되지 않도록 모델 아이덴티티 및 상태 보존 제어

4. **하반신 연장 생성 (Outpainting / Zoom-out)**:
   - 피팅 모델 샷이 허벅지 등 상반신 위주로 잘려 있더라도, '신발'류 가상 착장 시 자동으로 하단 구도를 확장 연장하여 다리와 발을 생성하고 신발을 피팅 노출

5. **0% 환각 스타일링 코디 룩북 (Fallback)**:
   - 생성 모델 에러나 이미지 깨짐 발생 시, 원본 이미지 데이터를 1:1로 매거진 화보 구도로 깔끔하게 이어 붙이는 자체 룩북 캔버스 보드(`create_coordination_board`)로 안전하게 대체 작동

6. **네트워크 예외 처리 및 백오프 재시도**:
   - Gemini API 통신 중 `503 UNAVAILABLE` 혹은 `429 RESOURCE_EXHAUSTED` 에러 발생 시, **지수 백오프 대기 시간(2s, 4s, 8s, 16s)**을 적용하여 최대 4회 재시도함으로써 인프라 안정성 확보

---

## 📂 프로젝트 구조 (Project Structure)

```bash
dev/coordi-agent/
├── app.py                # Streamlit 메인 프론트엔드 앱 로직 및 레이아웃 제어
├── llm_service.py        # Gemini API 연동, 한글화 프롬프트 제어, 이미지 생성/편집 및 룩북 생성
├── api_service.py        # 하프클럽 OpenAPI 연동 (기본 리스트 조회, 상세 정보 조회, 검색 연동)
├── requirements.txt      # 프로젝트 패키지 종속성 정의
└── .streamlit/
    └── secrets.toml      # Gemini API Key 등 로컬 개발 보안 토큰 보관
```

---

## 🚀 시작하기 (How to Run)

### 1. 가상환경 구성 및 패키지 설치
```bash
# 가상환경 활성화
source venv/bin/activate

# 종속성 라이브러리 설치
pip install -r requirements.txt
```

### 2. 환경 변수 설정
`.streamlit/secrets.toml` 파일을 생성하거나 수정하여 다음과 같이 Google Gemini API Key를 등록합니다.
```toml
GEMINI_API_KEY = "your_actual_gemini_api_key_here"
```

### 3. Streamlit 로컬 앱 실행
```bash
streamlit run app.py
```
실행이 완료되면 브라우저에서 자동으로 **`http://localhost:8501`** 주소로 접속되어 앱 프론트페이지가 열립니다.

---

## 🖼️ 화면 구성 가이드
- **좌측 영역**: 기준 상품 그리드 목록 (각 상품 아래 `선택` 버튼을 통해 코디 추천 트리거 및 상세페이지 새창 이동)
- **우측 영역**: 
  - **상단**: 선택된 기준 상품 메타 데이터
  - **중단**: AI가 제시한 카테고리별 매칭 탭 (추천 이유, 필터 정보, 실시간 추천 상품 그리드 노출)
  - **하단**: 실시간 **`✨ 가상 착장`** 결과 뷰 및 착장 결과를 비울 수 있는 **`🔄 가상 착장 초기화 (리셋)`** 버튼
