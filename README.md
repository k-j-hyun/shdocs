# Sheets Calendar Sync

Google Sheets를 캘린더로 동기화하여 예약 일정을 관리하는 웹 애플리케이션입니다.

## 주요 기능

- **Google OAuth 인증**: 개인 Google 계정으로 안전한 시트 접근
- **Google Sheets 연동**: 여러 시트 동시 관리 (시트별 색상 구분)
- **캘린더 뷰**: 직관적인 월별 캘린더로 예약 일정 확인
- **자동 정보 추출**: 병원 정보 및 연락처 자동 인식
- **SQLite 저장**: 데이터베이스 기반으로 안정적인 데이터 보관
- **툴팁**: 마우스 오버로 빠른 정보 확인
- **모바일 최적화**: 터치 스와이프 및 반응형 UI

## 설치 및 실행

1. **의존성 설치**
   ```bash
   pip install -r requirements.txt
   ```

2. **애플리케이션 실행**
   ```bash
   python main.py
   ```

3. **브라우저에서 접속**
   ```
   http://localhost:8000
   ```

## 사용법

### 1. Google Sheets 설정

Google Sheets를 공개로 설정하거나 링크를 통한 접근을 허용해야 합니다:

1. Google Sheets에서 "공유" 클릭
2. "링크가 있는 모든 사용자" 또는 "인터넷 사용자" 권한 설정
3. URL 복사

### 2. 시트 추가

1. 시트 제목 입력
2. Google Sheets URL 붙여넣기
3. 색상 선택 (12가지 색상 중 선택)
4. "시트 추가" 버튼 클릭

### 3. 데이터 형식

Excel/Google Sheets에서 다음 열을 사용합니다:
- **E열 (5번째 열)**: 이름/제목
- **O열 (15번째 열)**: 예약확정일시

지원하는 날짜 형식:
- `25-07-24(목) 11:00`
- `2025-07-24 11:00`
- `07/24/2025 11:00`
- `24-07-2025 11:00`

### 4. 캘린더 사용

- **월 변경**: 좌우 화살표 버튼 또는 키보드 화살표키
- **모바일**: 좌우 스와이프로 월 변경
- **이벤트 상세**: 이벤트 클릭시 상세정보 모달 표시
- **자동 새로고침**: 5분마다 자동으로 데이터 갱신

## 기술 스택

- **Backend**: FastAPI (Python)
- **Frontend**: HTML, CSS, JavaScript
- **UI/UX**: 반응형 디자인, Pink & White 테마
- **데이터**: Google Sheets CSV Export API

## API 엔드포인트

- `GET /`: 메인 페이지
- `GET /api/sheets`: 등록된 시트 목록
- `POST /api/sheets`: 새 시트 추가
- `DELETE /api/sheets/{id}`: 시트 삭제
- `GET /api/events`: 모든 이벤트 조회

## 디렉토리 구조

```
shdocs/
├── main.py              # FastAPI 애플리케이션
├── requirements.txt     # Python 의존성
├── templates/
│   └── index.html      # 메인 HTML 템플릿
└── static/
    ├── style.css       # CSS 스타일시트
    └── script.js       # JavaScript 로직
```

## Render 배포

1. **GitHub 리포지토리 생성** 후 코드 업로드
2. **Render 계정 생성** 후 새 Web Service 연결
3. **설정 값**:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `gunicorn main:app -c gunicorn.conf.py`
   - **Environment**: Python 3
4. **환경 변수**:
   - `DATA_DIR`: 데이터베이스 저장 경로 (Render Disk 사용 시)

## Google OAuth 설정

1. [Google Cloud Console](https://console.cloud.google.com/) 접속
2. 새 프로젝트 생성
3. **Google Sheets API**, **Google Drive API** 활성화
4. **OAuth 2.0 클라이언트 ID** 생성
5. **승인된 리디렉션 URI** 설정:
   - 로컬: `http://localhost:8000/auth/callback`
   - 배포: `https://your-app.onrender.com/auth/callback`
6. `credentials.json` 파일을 프로젝트 루트에 저장

## 시트 형식 요구사항

- **E열 (5번째)**: 환자/고객 이름
- **O열 (15번째)**: 예약 날짜 및 시간
- **전화번호**: `000-0000-0000` 형식으로 아무 컬럼
- **병원 정보**: 개인정보 위쪽 행에 키워드 포함 ('병원', '클리닉', '의원', '센터', '피부과', '외과' 등)

## 기술 스택

- **Backend**: FastAPI + SQLite + Gunicorn
- **Frontend**: Vanilla JavaScript + HTML/CSS  
- **Authentication**: Google OAuth 2.0
- **Deployment**: Render
- **Database**: SQLite (영구 저장)

## 문제해결

### "Failed to fetch sheet data" 오류
- Google Sheets 공유 설정을 확인하세요
- URL이 올바른지 확인하세요
- 네트워크 연결을 확인하세요

### 이벤트가 표시되지 않는 경우
- E열과 O열에 데이터가 올바르게 입력되었는지 확인하세요
- 날짜 형식이 지원되는 형식인지 확인하세요
- 브라우저 개발자 도구에서 에러 메시지를 확인하세요

### 개발문의
- spellrain@naver.com