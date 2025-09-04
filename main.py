from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from datetime import datetime
import re
from typing import List, Dict, Optional
import uvicorn
import gspread
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
import os
import json
from database import (init_database, add_sheet as db_add_sheet, get_all_sheets as db_get_sheets, 
                      delete_sheet as db_delete_sheet, clear_events_for_sheet, add_event as db_add_event, 
                      get_all_events as db_get_events)

app = FastAPI()

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")

# Google OAuth settings
SCOPES = [
    'https://www.googleapis.com/auth/spreadsheets.readonly',
    'https://www.googleapis.com/auth/drive.readonly'
]

# Initialize database on startup
init_database()

# Global variable to store credentials
user_credentials = None

def clean_json_string(json_str: str) -> str:
    """Remove control characters from JSON string"""
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', json_str)
    return cleaned

def get_google_credentials_info():
    """Get Google OAuth credentials from environment variable or file"""
    try:
        env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
        
        if env_creds:
            cleaned_creds = clean_json_string(env_creds)
            return json.loads(cleaned_creds)
        
        if os.path.exists("credentials.json"):
            with open("credentials.json", 'r', encoding='utf-8') as f:
                content = f.read()
                cleaned_content = clean_json_string(content)
                return json.loads(cleaned_content)
        
        raise Exception("OAuth 설정이 없습니다.")
    except Exception as e:
        raise e

def get_redirect_uri(request: Request):
    """Get the appropriate redirect URI based on the request"""
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/auth/callback"

def get_google_client():
    """Initialize Google Sheets client with user credentials"""
    global user_credentials
    if not user_credentials:
        raise HTTPException(status_code=401, detail="Google 로그인이 필요합니다.")
    
    return gspread.authorize(user_credentials)

# Data models
class SheetConfig(BaseModel):
    name: str
    url: str
    color: str

def extract_sheet_id_and_gid(url: str) -> tuple:
    """Extract sheet ID and GID from Google Sheets URL"""
    sheet_id_match = re.search(r'/spreadsheets/d/([a-zA-Z0-9-_]+)', url)
    gid_match = re.search(r'[#&]gid=([0-9]+)', url)
    
    if not sheet_id_match:
        raise ValueError("유효하지 않은 Google Sheets URL입니다")
    
    sheet_id = sheet_id_match.group(1)
    gid = gid_match.group(1) if gid_match else "0"
    
    return sheet_id, gid

def fetch_sheet_data(sheet_id: str, gid: str = "0") -> List[Dict]:
    """Fetch data from Google Sheets using authenticated access"""
    try:
        print(f"Fetching sheet data for ID: {sheet_id}, GID: {gid}")
        client = get_google_client()
        
        spreadsheet = client.open_by_key(sheet_id)
        
        # Get worksheet by GID
        worksheets = spreadsheet.worksheets()
        worksheet = None
        for ws in worksheets:
            if str(ws.id) == gid:
                worksheet = ws
                break
        
        if not worksheet:
            worksheet = spreadsheet.sheet1
        
        # Try to get all records
        try:
            records = worksheet.get_all_records()
            print(f"Got {len(records)} records")
        except Exception:
            records = []
        
        # If no records, get raw values
        if not records:
            all_values = worksheet.get_all_values()
            if all_values:
                max_columns = max(len(row) for row in all_values) if all_values else 0
                headers = [chr(65 + i) if i < 26 else f"Column_{i+1}" for i in range(max_columns)]
                
                records = []
                for row in all_values:
                    record = {}
                    for i, value in enumerate(row):
                        if i < len(headers):
                            record[headers[i]] = value
                        else:
                            record[f"Column_{i+1}"] = value
                    records.append(record)
        
        return records
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"시트 데이터 가져오기 실패: {str(e)}")

def find_column_mappings(data: List[Dict]) -> Dict[str, str]:
    """데이터에서 동적으로 컬럼 매핑을 찾는 함수"""
    mappings = {'name': None, 'phone': None, 'date': None, 'procedure': None}
    
    print(f"Analyzing {len(data)} rows for column mappings...")
    
    for row_idx, row in enumerate(data[:15]):
        if not row:
            continue
            
        for key, value in row.items():
            if not value:
                continue
                
            value_str = str(value).lower().strip()
            
            # 이름 컬럼 찾기
            if any(keyword in value_str for keyword in ['성함', '이름', '신청자', '고객명', '환자명']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found name column: {key}")
                    mappings['name'] = key
            
            # 전화번호 컬럼 찾기
            elif any(keyword in value_str for keyword in ['연락처', '전화', '핸드폰', '휴대폰']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found phone column: {key}")
                    mappings['phone'] = key
            
            # 날짜 컬럼 찾기
            elif any(keyword in value_str for keyword in ['확정일시', '예약확정일시', '수술일', '시술일']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found date column: {key}")
                    mappings['date'] = key
            elif not mappings['date'] and any(keyword in value_str for keyword in ['예약일시', '날짜', '일시']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found general date column: {key}")
                    mappings['date'] = key
            
            # 시술 정보 컬럼 찾기
            elif any(keyword in value_str for keyword in ['시술', '수술', '부위', '진행', '항목']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found procedure column: {key}")
                    mappings['procedure'] = key
    
    # 패턴 기반 이름 찾기
    if not mappings['name']:
        print("Trying pattern-based name detection...")
        for row_idx, row in enumerate(data[:20]):
            for key, value in row.items():
                if not value:
                    continue
                value_str = str(value).strip()
                if (len(value_str) >= 2 and len(value_str) <= 4 and 
                    all('가' <= c <= '힣' for c in value_str)):
                    name_count = 0
                    for check_row in data[row_idx:row_idx + 10]:
                        if key in check_row and check_row[key]:
                            check_value = str(check_row[key]).strip()
                            if (len(check_value) >= 2 and len(check_value) <= 4 and 
                                all('가' <= c <= '힣' for c in check_value)):
                                name_count += 1
                    
                    if name_count >= 3:
                        print(f"Found name column by pattern: {key}")
                        mappings['name'] = key
                        break
            if mappings['name']:
                break
    
    return mappings

def check_column_has_data(data: List[Dict], column_key: str, start_row: int = 1) -> bool:
    """해당 컬럼에 실제 데이터가 있는지 확인"""
    data_count = 0
    check_limit = min(start_row + 20, len(data))
    
    for i in range(start_row, check_limit):
        if i >= len(data):
            break
        row = data[i]
        if column_key in row and row[column_key]:
            value = str(row[column_key]).strip()
            if value and value not in ['', '-', 'N/A']:
                data_count += 1
                if data_count >= 3:
                    return True
    
    return data_count >= 1

def extract_hospital_from_data(sheet_name: str, data: List[Dict]) -> str:
    """시트에서 병원명 추출"""
    
    # '개인정보' 바로 위에서 병원는 찾기
    for row_idx, row in enumerate(data):
        for key, value in row.items():
            if value and isinstance(value, str) and '개인정보' in value and row_idx > 0:
                prev_row = data[row_idx - 1]
                for prev_key, prev_value in prev_row.items():
                    if prev_value and isinstance(prev_value, str):
                        prev_value = str(prev_value).strip()
                        prev_value_lower = prev_value.lower()
                        
                        print(f"Found hospital candidate from 개인정보: '{prev_value}'")
                        
                        # 스텔라/뉴브 관련 패턴 검사
                        if any(pattern in prev_value_lower for pattern in ['스텔라엠투투', '스텔라', '뉴브', '엠투투', 'm2m']):
                            print(f"Matched Stella/Newb pattern in sheet header: '{prev_value}' -> '뉴브의원'")
                            return '뉴브의원'
                        
                        # 제네오엑스/셀나인 관련 패턴 검사
                        elif any(pattern in prev_value_lower for pattern in ['제네오엑스', '셀나인']):
                            print(f"Matched GeneoX/Cellnine pattern in sheet header: '{prev_value}' -> '셀나인청담'")
                            return '셀나인청담'
                        
                        # 일반 병원 키워드
                        elif (any(keyword in prev_value_lower for keyword in ['병원', '의원', '피부과', '외과']) 
                              or ('-' in prev_value and len(prev_value) > 5)):
                            print(f"Found hospital from '개인정보': {prev_value}")
                            return prev_value
    
    # 시트명에서 병원명 추출 (더 상세한 매핑)
    sheet_name_lower = sheet_name.lower()
    print(f"Checking sheet name: '{sheet_name}'")
    
    patterns = {
        '라비앙': '라비앙성형외과',
        '트랜드': '트랜드성형외과', 
        '황금': '황금피부과',
        '셀나인': '셀나인청담',
        '제네오엑스': '뉴브의원',
        '스텔라': '뉴브의원',
        '케이블린': '케이블린필러',
        '쥬브겔': '쥬브겔필러'
    }
    
    for pattern, hospital in patterns.items():
        if pattern in sheet_name_lower:
            print(f"Matched sheet name pattern '{pattern}' -> '{hospital}'")
            return hospital
    
    return ""

def extract_phone_number(text) -> str:
    """전화번호 추출"""
    if not text:
        return ""
    
    text = str(text)
    patterns = [r'010-\d{4}-\d{4}', r'\d{3}-\d{3,4}-\d{4}']
    
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return match.group()
    
    return ""

def find_phone_in_row(row_dict: Dict) -> str:
    """행에서 전화번호 찾기"""
    for key, value in row_dict.items():
        if value:
            phone = extract_phone_number(value)
            if phone:
                return phone
    return ""

def parse_date_time(date_str: str) -> tuple:
    """날짜 문자열 파싱"""
    if not date_str:
        return None, None
    
    date_str = str(date_str).strip()
    
    formats = [
        "%y-%m-%d(%a) %H:%M", "%Y-%m-%d(%a) %H:%M",
        "%y-%m-%d %H:%M", "%Y-%m-%d %H:%M",
        "%y-%m-%d", "%Y-%m-%d"
    ]
    
    for fmt in formats:
        try:
            dt = datetime.strptime(date_str, fmt)
            time_part = dt.strftime("%H:%M") if "%H" in fmt else "09:00"
            return dt.strftime("%Y-%m-%d"), time_part
        except ValueError:
            continue
    
    # 정규표현식 파싱
    match = re.search(r'(\d{2,4})[-/.](\d{1,2})[-/.](\d{1,2})(?:\s*(\d{1,2}):(\d{2}))?', date_str)
    if match:
        year, month, day, hour, minute = match.groups()
        
        if len(year) == 2:
            year = "20" + year if int(year) < 50 else "19" + year
        
        try:
            date_formatted = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
            datetime.strptime(date_formatted, "%Y-%m-%d")
            time_formatted = f"{hour.zfill(2)}:{minute}" if hour and minute else "09:00"
            return date_formatted, time_formatted
        except ValueError:
            pass
    
    return None, None

def extract_meaningful_data(row_dict: Dict, column_mappings: Dict[str, str]) -> Dict:
    """의미있는 데이터 추출"""
    result = {'name': '', 'phone': '', 'date': '', 'time': '09:00', 'procedure': ''}
    
    # 이름 추출
    if column_mappings['name'] and column_mappings['name'] in row_dict:
        name_value = row_dict[column_mappings['name']]
        if name_value:
            result['name'] = str(name_value).strip()
    
    # 전화번호 추출
    if column_mappings['phone'] and column_mappings['phone'] in row_dict:
        phone_value = row_dict[column_mappings['phone']]
        if phone_value:
            result['phone'] = extract_phone_number(phone_value)
    
    if not result['phone']:
        result['phone'] = find_phone_in_row(row_dict)
    
    # 날짜 추출
    if column_mappings['date'] and column_mappings['date'] in row_dict:
        date_value = row_dict[column_mappings['date']]
        if date_value:
            date_part, time_part = parse_date_time(str(date_value))
            result['date'] = date_part or ''
            result['time'] = time_part or '09:00'
    
    # 시술 정보
    if column_mappings['procedure'] and column_mappings['procedure'] in row_dict:
        proc_value = row_dict[column_mappings['procedure']]
        if proc_value:
            result['procedure'] = str(proc_value).strip()
    
    return result

def find_hospital_near_name(all_data: List[Dict], current_row_idx: int, name_value: str) -> str:
    """이름 주변에서 가장 가까운 '개인정보' 바로 위에서 병원 정보 찾기"""
    print(f"Looking for hospital info near {name_value} at row {current_row_idx}")
    
    # 이름이 있는 행에서 위로 50개 행까지 검사
    start_row = max(0, current_row_idx - 50)
    
    # 가장 가까운 '개인정보' 찾기
    closest_info_row = None
    closest_distance = float('inf')
    
    for i in range(current_row_idx, start_row - 1, -1):
        if i >= len(all_data):
            continue
            
        row = all_data[i]
        if not row:
            continue
            
        for key, value in row.items():
            if value and isinstance(value, str) and '개인정보' in value:
                distance = current_row_idx - i
                if distance < closest_distance:
                    closest_distance = distance
                    closest_info_row = i
                    print(f"Found '개인정보' at row {i}, distance: {distance}")
                break
    
    # 가장 가까운 '개인정보' 바로 위에서 병원 정보 찾기
    if closest_info_row is not None and closest_info_row > 0:
        prev_row = all_data[closest_info_row - 1]
        print(f"Checking row {closest_info_row - 1} above '개인정보'")
        
        for prev_key, prev_value in prev_row.items():
            if prev_value and isinstance(prev_value, str):
                prev_value = str(prev_value).strip()
                print(f"Checking hospital value: '{prev_value}'")
                
                # 더 정확한 병원명 매핑 (대소문자 구분 없이)
                prev_value_lower = prev_value.lower()
                
                # 스텔라엠투투_뉴브의원 관련 패턴들
                stella_patterns = ['스텔라엠투투_뉴브의원', '스텔라엠투투', '스텔라', '뉴브의원', '뉴브', '엠투투', 'm2m']
                
                for pattern in stella_patterns:
                    if pattern in prev_value_lower:
                        print(f"Found Stella/Newb pattern '{pattern}' for {name_value}: '뉴브의원'")
                        return '뉴브의원'
                
                # 제네오엑스_셀나인청담 관련 패턴들
                geneoex_patterns = ['제네오엑스_셀나인청담', '제네오엑스', '셀나인청담', '셀나인']
                
                for pattern in geneoex_patterns:
                    if pattern in prev_value_lower:
                        print(f"Found GeneoX/Cellnine pattern '{pattern}' for {name_value}: '셀나인청담'")
                        return '셀나인청담'
                
                # 일반 병원 키워드
                if any(keyword in prev_value_lower for keyword in ['병원', '의원', '피부과', '외과', '클리닉', '센터']):
                    print(f"Found general hospital keyword for {name_value}: '{prev_value}'")
                    return prev_value
                elif '-' in prev_value and len(prev_value) > 10:
                    print(f"Found dash-separated hospital info for {name_value}: '{prev_value}'")
                    return prev_value
    
    # 백업: 이름 주변에서 병원 키워드 찾기
    print(f"Backup search around row {current_row_idx}")
    for i in range(max(0, current_row_idx - 10), min(current_row_idx + 3, len(all_data))):
        row = all_data[i]
        if not row:
            continue
            
        for key, value in row.items():
            if not value:
                continue
            value_str = str(value).strip().lower()
            
            # 더 많은 패턴 검사
            if any(pattern in value_str for pattern in ['스텔라', '뉴브', '엠투투', 'm2m']):
                print(f"Found Stella/Newb in backup search: '{value}'")
                return '뉴브의원'
            elif any(pattern in value_str for pattern in ['제네오엑스', '셀나인']):
                print(f"Found GeneoX/Cellnine in backup search: '{value}'")
                return '셀나인청담'
            elif (any(keyword in value_str for keyword in ['병원', '의원', '피부과', '외과', '클리닉', '센터']) 
                  and len(value_str) < 100 and len(value_str) > 5):
                print(f"Found hospital info in backup search: '{value}'")
                return str(value).strip()
    
    print(f"No hospital info found for {name_value}")
    return ""

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    global user_credentials
    is_authenticated = user_credentials is not None
    
    if is_authenticated:
        try:
            print("Auto-refreshing sheets...")
            await refresh_all_events()
        except Exception as e:
            print(f"Auto-refresh error: {e}")
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "is_authenticated": is_authenticated
    })

@app.get("/auth/login")
async def login(request: Request):
    try:
        credentials_info = get_google_credentials_info()
        redirect_uri = get_redirect_uri(request)
        
        flow = Flow.from_client_config(
            credentials_info,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        
        return RedirectResponse(authorization_url)
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, state: str = None):
    global user_credentials
    
    if not code:
        raise HTTPException(status_code=400, detail="인증 코드가 없습니다.")
    
    try:
        credentials_info = get_google_credentials_info()
        redirect_uri = get_redirect_uri(request)
        
        flow = Flow.from_client_config(
            credentials_info,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        
        flow.fetch_token(code=code)
        user_credentials = flow.credentials
        
        return RedirectResponse("/")
        
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/auth/logout")
async def logout():
    global user_credentials
    user_credentials = None
    return RedirectResponse("/")

@app.get("/auth/status")
async def auth_status():
    global user_credentials
    return JSONResponse({"authenticated": user_credentials is not None})

@app.post("/api/sheets")
async def add_sheet(sheet_config: SheetConfig):
    if not user_credentials:
        raise HTTPException(status_code=401, detail="Google 로그인이 필요합니다.")
    
    try:
        sheet_id, gid = extract_sheet_id_and_gid(sheet_config.url)
        test_data = fetch_sheet_data(sheet_id, gid)
        
        if not test_data:
            raise ValueError("시트에서 데이터를 찾을 수 없습니다.")
        
        db_sheet_id = db_add_sheet(
            name=sheet_config.name,
            url=sheet_config.url, 
            color=sheet_config.color,
            sheet_id=sheet_id,
            gid=gid,
            row_count=len(test_data)
        )
        
        await refresh_events_for_sheet(db_sheet_id)
        
        return JSONResponse({
            "success": True, 
            "sheet": {
                "id": db_sheet_id,
                "name": sheet_config.name,
                "url": sheet_config.url,
                "color": sheet_config.color,
                "created_at": datetime.now().isoformat(),
                "row_count": len(test_data)
            }, 
            "message": f"시트가 추가되었습니다. ({len(test_data)}개 행)"
        })
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/sheets")
async def get_sheets():
    sheets = db_get_sheets()
    return JSONResponse(sheets)

@app.delete("/api/sheets/{sheet_id}")
async def delete_sheet(sheet_id: int):
    success = db_delete_sheet(sheet_id)
    if not success:
        raise HTTPException(status_code=404, detail="시트를 찾을 수 없습니다.")
    return JSONResponse({"success": True})

@app.get("/api/events")
async def get_events():
    if not user_credentials:
        return JSONResponse([])
    
    await refresh_all_events()
    events = db_get_events()
    return JSONResponse(events)

@app.get("/api/events/monthly/{year}/{month}")
async def get_monthly_events(year: int, month: int):
    """특정 월의 이벤트를 마크다운 형식으로 반환"""
    if not user_credentials:
        return JSONResponse({"markdown": ""})
    
    await refresh_all_events()
    events = db_get_events()
    
    # 해당 월의 이벤트만 필터링
    monthly_events = []
    for event in events:
        try:
            event_date = datetime.strptime(event['date'], '%Y-%m-%d')
            if event_date.year == year and event_date.month == month:
                monthly_events.append(event)
        except ValueError:
            continue
    
    # 날짜순으로 정렬
    monthly_events.sort(key=lambda x: x['date'])
    
    # 마크다운 형식으로 변환
    markdown_content = f"# {year}년 {month}월 예약 현황\n\n"
    
    if not monthly_events:
        markdown_content += "해당 월에 예약이 없습니다.\n"
    else:
        # 병원별로 그룹핑
        hospitals = {}
        for event in monthly_events:
            hospital = event.get('hospital', '기타')
            if hospital not in hospitals:
                hospitals[hospital] = []
            hospitals[hospital].append(event)
        
        for hospital, events in hospitals.items():
            markdown_content += f"## {hospital}\n\n"
            markdown_content += "| 날짜 | 시간 | 이름 | 연락처 | 시술내용 |\n"
            markdown_content += "|------|------|------|---------|----------|\n"
            
            for event in events:
                date = event['date']
                time = event['time']
                name = event['name']
                phone = event.get('phone', '-')
                procedure = event.get('details', {}).get('procedure', '-') if event.get('details') else '-'
                markdown_content += f"| {date} | {time} | {name} | {phone} | {procedure} |\n"
            
            markdown_content += "\n"
    
    return JSONResponse({"markdown": markdown_content})

async def refresh_all_events():
    if not user_credentials:
        return
    
    sheets = db_get_sheets()
    for sheet in sheets:
        await refresh_events_for_sheet(sheet["id"])

async def refresh_events_for_sheet(db_sheet_id: int):
    if not user_credentials:
        return
    
    from database import get_sheet_by_id
    sheet = get_sheet_by_id(db_sheet_id)
    if not sheet:
        return
        
    try:
        print(f"\n=== Processing sheet: {sheet['name']} ===")
        
        clear_events_for_sheet(db_sheet_id)
        data = fetch_sheet_data(sheet["sheet_id"], sheet["gid"])
        
        if not data:
            print(f"No data found in sheet {sheet['name']}")
            return
        
        print(f"Data rows: {len(data)}")
        column_mappings = find_column_mappings(data)
        print(f"Column mappings: {column_mappings}")
        
        sheet_hospital = extract_hospital_from_data(sheet['name'], data)
        print(f"Sheet-level hospital: '{sheet_hospital}'")
        
        events_count = 0
        
        for row_idx, row in enumerate(data):
            if not row:
                continue
            
            extracted_data = extract_meaningful_data(row, column_mappings)
            
            if extracted_data['name'] and extracted_data['date']:
                print(f"\n--- Processing {extracted_data['name']} at row {row_idx} ---")
                
                # 병원명 결정 과정 상세 로깅
                hospital_from_near = find_hospital_near_name(data, row_idx, extracted_data['name'])
                print(f"Hospital from near name: '{hospital_from_near}'")
                
                hospital_name = (
                    sheet_hospital or 
                    hospital_from_near or 
                    sheet['name']
                )
                
                print(f"Final hospital for {extracted_data['name']}: '{hospital_name}'")
                
                db_add_event(
                    sheet_id=db_sheet_id,
                    title=f"{hospital_name}_{extracted_data['name']}",
                    name=extracted_data['name'],
                    date=extracted_data['date'],
                    time=extracted_data['time'],
                    sheet_name=sheet["name"],
                    color=sheet["color"],
                    hospital=hospital_name,
                    phone=extracted_data['phone'],
                    details={
                        'procedure': extracted_data['procedure'],
                        'row_index': row_idx + 1,
                        'original_data': dict(row)
                    }
                )
                events_count += 1
                
                if events_count <= 10:  # 더 많은 예제 보기
                    print(f"  Event {events_count}: {extracted_data['name']} - {extracted_data['date']} at {hospital_name}")
        
        print(f"\nSheet {sheet['name']} processed: {events_count} events found\n")
                        
    except Exception as e:
        print(f"Error processing sheet {sheet['name']}: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
