# 임시 파일 - 삭제 예정
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
from googleapiclient.discovery import build
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

# Function to get Google credentials from environment or file
# Function to clean JSON string from control characters
def clean_json_string(json_str: str) -> str:
    """Remove control characters from JSON string"""
    import re
    # Remove control characters except newline, carriage return, and tab
    cleaned = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f-\x9f]', '', json_str)
    return cleaned

# Function to get Google credentials from environment or file
def get_google_credentials_info():
    """Get Google OAuth credentials from environment variable or file"""
    print("=== Starting get_google_credentials_info ===")
    
    try:
        # Try environment variable first (for production)
        env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
        print(f"Environment variable exists: {env_creds is not None}")
        
        if env_creds:
            print(f"Environment variable length: {len(env_creds)}")
            print(f"First 50 characters: {env_creds[:50]}")
            
            # Clean the JSON string before parsing
            cleaned_creds = clean_json_string(env_creds)
            print(f"After cleaning length: {len(cleaned_creds)}")
            
            try:
                result = json.loads(cleaned_creds)
                print("JSON parsing successful")
                print(f"Keys in credentials: {list(result.keys())}")
                return result
            except json.JSONDecodeError as e:
                print(f"JSON decode error: {e}")
                print(f"Error at position: {e.pos}")
                # Show characters around the error position
                if hasattr(e, 'pos') and e.pos:
                    start = max(0, e.pos - 20)
                    end = min(len(cleaned_creds), e.pos + 20)
                    print(f"Context around error: '{cleaned_creds[start:end]}'")
                raise Exception(f"환경변수 JSON 파싱 실패: {str(e)}")
        
        # Fallback to file (for development)
        print("Checking for credentials.json file...")
        if os.path.exists("credentials.json"):
            print("File exists, reading...")
            with open("credentials.json", 'r', encoding='utf-8') as f:
                content = f.read()
                print(f"File content length: {len(content)}")
                cleaned_content = clean_json_string(content)
                try:
                    result = json.loads(cleaned_content)
                    print("File JSON parsing successful")
                    return result
                except json.JSONDecodeError as e:
                    print(f"File JSON decode error: {e}")
                    raise Exception(f"파일 JSON 파싱 실패: {str(e)}")
        else:
            print("credentials.json file not found")
        
        raise Exception("OAuth 설정이 없습니다. GOOGLE_CREDENTIALS_JSON 환경변수를 설정하거나 credentials.json 파일을 추가하세요.")
    
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/sheets")
async def get_sheets():
    """Get all sheet configurations"""
    sheets = db_get_sheets()
    return JSONResponse(sheets)

@app.delete("/api/sheets/{sheet_id}")
async def delete_sheet(sheet_id: int):
    """Delete a sheet configuration"""
    success = db_delete_sheet(sheet_id)
    if not success:
        raise HTTPException(status_code=404, detail="시트를 찾을 수 없습니다.")
    return JSONResponse({"success": True})

@app.get("/api/events")
async def get_events():
    """Get all events from all sheets"""
    if not user_credentials:
        return JSONResponse([])
    
    # Refresh events from all sheets
    await refresh_all_events()
    
    # Return events from database
    events = db_get_events()
    return JSONResponse(events)

async def refresh_all_events():
    """Refresh events for all sheets"""
    if not user_credentials:
        return
    
    sheets = db_get_sheets()
    for sheet in sheets:
        await refresh_events_for_sheet(sheet["id"])

async def refresh_events_for_sheet(db_sheet_id: int):
    """Refresh events for a specific sheet"""
    if not user_credentials:
        return
    
    from database import get_sheet_by_id
    sheet = get_sheet_by_id(db_sheet_id)
    if not sheet:
        return
        
    try:
        print(f"Processing sheet: {sheet['name']}")
        
        # Clear existing events for this sheet
        clear_events_for_sheet(db_sheet_id)
        
        # Fetch fresh data
        data = fetch_sheet_data(sheet["sheet_id"], sheet["gid"])
        
        if not data:
            print(f"No data found in sheet {sheet['name']}")
            return
        
        # 동적으로 컬럼 매핑 찾기
        column_mappings = find_column_mappings(data)
        print(f"Found column mappings: {column_mappings}")
        
        # 시트명에서 병원명 추출
        sheet_hospital = extract_hospital_from_sheet_name_or_data(sheet['name'], data)
        
        events_count = 0
        
        for row_idx, row in enumerate(data):
            if not row:
                continue
            
            # 매핑된 컬럼을 기반으로 데이터 추출
            extracted_data = extract_meaningful_data(row, column_mappings)
            
            # 이름과 날짜가 있는 경우만 처리
            if extracted_data['name'] and extracted_data['date']:
                
                # 병원명 결정 (시트에서 추출한 병원명 또는 이름 주변에서 찾기)
                hospital_name = (
                    sheet_hospital or 
                    find_hospital_info_near_name(data, row_idx, extracted_data['name'], column_mappings) or 
                    sheet['name']
                )
                
                # Add to database
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
                
                # 처음 10개 이벤트는 디버깅을 위해 로그 출력
                if events_count <= 10:
                    print(f"  Event {events_count}: {extracted_data['name']} - {extracted_data['date']} {extracted_data['time']} at {hospital_name}")
        
        print(f"Sheet {sheet['name']} processed: {events_count} events found")
                        
    except Exception as e:
        print(f"Error processing sheet {sheet['name']}: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
        print(f"Exception in get_google_credentials_info: {e}")
        print(f"Exception type: {type(e)}")
        import traceback
        print(f"Full traceback: {traceback.format_exc()}")
        raise e  # Re-raise the original exception
    
def get_redirect_uri(request: Request):
    """Get the appropriate redirect URI based on the request"""
    base_url = str(request.base_url).rstrip('/')
    return f"{base_url}/auth/callback"

def get_google_client():
    """Initialize Google Sheets client with user credentials"""
    global user_credentials
    if not user_credentials:
        raise HTTPException(status_code=401, detail="Google 로그인이 필요합니다.")
    
    try:
        print(f"User credentials available: {user_credentials is not None}")
        print(f"Credentials type: {type(user_credentials)}")
        
        client = gspread.authorize(user_credentials)
        print("Google Sheets client created successfully")
        return client
    except Exception as e:
        print(f"Error creating Google client: {e}")
        print(f"Error type: {type(e)}")
        raise HTTPException(status_code=500, detail=f"Google 클라이언트 생성 실패: {str(e)}")

# Data models
class SheetConfig(BaseModel):
    name: str
    url: str
    color: str

class Event(BaseModel):
    title: str
    date: str
    time: str
    name: str
    sheet_name: str
    color: str
    details: Dict

# Database-backed storage (no more in-memory storage needed)

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
        print(f"Trying to fetch sheet data for ID: {sheet_id}, GID: {gid}")
        client = get_google_client()
        
        print("Opening spreadsheet by key...")
        spreadsheet = client.open_by_key(sheet_id)
        print(f"Spreadsheet opened: {spreadsheet.title}")
        
        # Get worksheet by GID
        worksheets = spreadsheet.worksheets()
        print(f"Found {len(worksheets)} worksheets")
        
        worksheet = None
        for ws in worksheets:
            print(f"Worksheet: {ws.title}, ID: {ws.id}")
            if str(ws.id) == gid:
                worksheet = ws
                break
        
        if not worksheet:
            worksheet = spreadsheet.sheet1
            print(f"Using default worksheet: {worksheet.title}")
        else:
            print(f"Using worksheet: {worksheet.title}")
        
        # Try to get all records, if it fails due to duplicate headers, use raw values
        print("Fetching all records...")
        try:
            records = worksheet.get_all_records()
            print(f"Got {len(records)} records")
        except Exception as header_error:
            print(f"Header error: {header_error}")
            print("Falling back to raw values due to duplicate headers...")
            records = []
        
        # If no records or header error, get raw values
        if not records:
            print("Using raw values approach...")
            all_values = worksheet.get_all_values()
            print(f"Got {len(all_values)} rows of raw data")
            
            if all_values:
                # Use column letters as headers (A, B, C, etc.)
                max_columns = max(len(row) for row in all_values) if all_values else 0
                headers = [chr(65 + i) if i < 26 else f"Column_{i+1}" for i in range(max_columns)]
                print(f"Using headers: {headers}")
                
                records = []
                for row_idx, row in enumerate(all_values):
                    record = {}
                    for i, value in enumerate(row):
                        if i < len(headers):
                            record[headers[i]] = value
                        else:
                            record[f"Column_{i+1}"] = value
                    records.append(record)
                print(f"Created {len(records)} records from raw data")
        
        return records
        
    except Exception as e:
        print(f"Error fetching sheet data: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"시트 데이터 가져오기 실패: {str(e)}")

def find_column_mappings(data: List[Dict]) -> Dict[str, str]:
    """데이터에서 동적으로 컬럼 매핑을 찾는 함수"""
    mappings = {'name': None, 'phone': None, 'date': None, 'hospital': None, 'procedure': None}
    
    # 처음 몇 행을 검사해서 헤더를 찾기
    for row_idx, row in enumerate(data[:10]):
        if not row:
            continue
            
        # 각 컬럼을 검사
        for key, value in row.items():
            if not value or not isinstance(value, str):
                continue
                
            value_lower = value.lower().strip()
            
            # 이름 컬럼 찾기
            if any(keyword in value_lower for keyword in ['성함', '이름', '신청자']):
                # 실제 데이터가 있는 컬럼인지 확인
                if check_column_has_data(data, key, row_idx + 1):
                    mappings['name'] = key
            
            # 전화번호 컬럼 찾기
            elif any(keyword in value_lower for keyword in ['연락처', '전화', '핸드폰', '휴대폰']):
                if check_column_has_data(data, keydef find_column_mappings(data: List[Dict]) -> Dict[str, str]:
    """데이터에서 동적으로 컬럼 매핑을 찾는 함수 (개선됨)"""
    mappings = {'name': None, 'phone': None, 'date': None, 'hospital': None, 'procedure': None}
    
    print(f"Analyzing {len(data)} rows of data for column mappings...")
    
    # 처음 15행을 검사해서 헤더를 찾기 (더 많이 검사)
    for row_idx, row in enumerate(data[:15]):
        if not row:
            continue
            
        # 각 컬럼을 검사
        for key, value in row.items():
            if not value or not isinstance(value, (str, int, float)):
                continue
                
            value_str = str(value).lower().strip()
            
            # 이름 컬럼 찾기 (더 다양한 키워드)
            if any(keyword in value_str for keyword in ['성함', '이름', '신청자', '고객명', '환자명', '담당자']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found name column: {key} (value: {value})")
                    mappings['name'] = key
            
            # 전화번호 컬럼 찾기 (더 다양한 키워드)
            elif any(keyword in value_str for keyword in ['연락처', '전화', '핸드폰', '휴대폰', '폰번호', '연락']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found phone column: {key} (value: {value})")
                    mappings['phone'] = key
            
            # 날짜 컬럼 찾기 (우선순위 및 더 다양한 키워드)
            elif any(keyword in value_str for keyword in ['확정일시', '예약확정일시']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found priority date column: {key} (value: {value})")
                    mappings['date'] = key
            elif not mappings['date'] and any(keyword in value_str for keyword in ['수술일', '시술일']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found surgery date column: {key} (value: {value})")
                    mappings['date'] = key
            elif not mappings['date'] and any(keyword in value_str for keyword in ['예약일시', '날짜', '일시', '예약날짜']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found general date column: {key} (value: {value})")
                    mappings['date'] = key
            
            # 시술/수술 정보 컬럼 찾기
            elif any(keyword in value_str for keyword in ['시술', '수술', '부위', '진행', '항목', '시술내용', '수술내용']):
                if check_column_has_data(data, key, row_idx + 1):
                    print(f"Found procedure column: {key} (value: {value})")
                    mappings['procedure'] = key
    
    print(f"Column mappings found: {mappings}")
    
    # 여전히 이름 컬럼을 못 찾았다면, 더 과감한 방법 사용
    if not mappings['name']:
        print("No name column found with keywords, trying pattern-based approach...")
        for row_idx, row in enumerate(data[:20]):
            if not row:
                continue
            for key, value in row.items():
                if not value:
                    continue
                # 한글 이름 패턴을 가진 데이터가 여러 개 있는 컬럼 찾기
                value_str = str(value).strip()
                if (len(value_str) >= 2 and len(value_str) <= 4 and 
                    all(ord('가') <= ord(c) <= ord('힣') for c in value_str)):
                    # 이 컬럼에 한글 이름이 여러 개 있는지 확인
                    name_count = 0
                    for check_row in data[row_idx:row_idx + 10]:
                        if key in check_row and check_row[key]:
                            check_value = str(check_row[key]).strip()
                            if (len(check_value) >= 2 and len(check_value) <= 4 and 
                                all(ord('가') <= ord(c) <= ord('힣') for c in check_value)):
                                name_count += 1
                    
                    if name_count >= 3:  # 3개 이상의 한글 이름
                        print(f"Found name column by pattern: {key} (sample: {value_str})")
                        mappings['name'] = key
                        break
            if mappings['name']:
                break
    
    return mappings

def check_column_has_data(data: List[Dict], column_key: str, start_row: int = 1) -> bool:
    """해당 컬럼에 실제 데이터가 있는지 확인"""
    data_count = 0
    check_limit = min(start_row + 20, len(data))  # 최대 20행까지만 확인
    
    for i in range(start_row, check_limit):
        if i >= len(data):
            break
        row = data[i]
        if column_key in row and row[column_key]:
            value = str(row[column_key]).strip()
            if len(value) > 0 and value not in ['', '-', 'N/A', 'null']:
                data_count += 1
                if data_count >= 3:  # 3개 이상의 유효한 데이터가 있으면 유효한 컬럼으로 판단
                    return True
    
    return data_count >= 1  # 최소 1개라도 있으면 유효

def extract_hospital_from_sheet_name_or_data(sheet_name: str, data: List[Dict]) -> str:
    """시트에서 병원명 추출 - 개인정보 바로 위에서 찾기"""
    
    # 1. 데이터에서 '개인정보' 바로 위에서 병원명 찾기
    for row_idx, row in enumerate(data):
        if not row:
            continue
        
        # 각 셀에서 '개인정보' 문자열 찾기
        for key, value in row.items():
            if value and isinstance(value, str) and '개인정보' in value:
                # '개인정보' 바로 위의 행에서 병원 정보 찾기
                if row_idx > 0:
                    prev_row = data[row_idx - 1]
                    for prev_key, prev_value in prev_row.items():
                        if prev_value and isinstance(prev_value, str):
                            prev_value = str(prev_value).strip()
                            # 병원 관련 키워드가 있거나 의미있는 정보인 경우
                            if (any(keyword in prev_value for keyword in ['병원', '의원', '피부과', '외과', '클리닉', '센터']) 
                                or ('-' in prev_value and len(prev_value) > 5)):
                                print(f"Found hospital info above '개인정보': {prev_value}")
                                return prev_value
    
    # 2. 시트명에서 병원명 추출 시도
    hospital_keywords = ['병원', '의원', '피부과', '외과', '클리닉', '센터']
    
    for keyword in hospital_keywords:
        if keyword in sheet_name:
            # 시트명에서 병원명 부분 추출
            parts = sheet_name.split()
            for part in parts:
                if keyword in part:
                    return part
    
    # 3. 시트명에서 특정 패턴 찾기 (라비앙, 제네오엑스 등)
    name_patterns = {
        '라비앙': '라비앙성형외과',
        '트랜드': '트랜드성형외과', 
        '황금': '황금피부과',
        '셀나인': '셀나인청담',
        '제네오엑스': '셀나인청담',
        '케이블린': '케이블린필러',
        '쥬브겔': '쥬브겔필러'
    }
    
    sheet_name_lower = sheet_name.lower()
    for pattern, hospital in name_patterns.items():
        if pattern in sheet_name_lower:
            return hospital
    
    # 4. 데이터 내에서 병원명 찾기 (백업 방법)
    for row in data[:30]:  # 처음 30행만 검사
        if not row:
            continue
        for value in row.values():
            if not value:
                continue
            value_str = str(value).strip()
            for keyword in hospital_keywords:
                if keyword in value_str and len(value_str) < 100:  # 너무 긴 텍스트는 제외
                    return value_str
    
    return ""

def find_phone_number_in_row(row_dict: Dict) -> str:
    """행에서 전화번호 패턴 찾기"""
    phone_patterns = [
        r'010-\d{4}-\d{4}',  # 010-1234-5678
        r'\d{3}-\d{3,4}-\d{4}',  # 일반적인 전화번호
        r'010\d{8}',  # 01012345678
        r'\d{11}'  # 11자리 숫자
    ]
    
    for key, value in row_dict.items():
        if value and isinstance(value, str):
            for pattern in phone_patterns:
                match = re.search(pattern, value)
                if match:
                    phone = match.group()
                    # 형식 정규화
                    if len(phone) == 11 and phone.startswith('010'):
                        return f"{phone[:3]}-{phone[3:7]}-{phone[7:]}"
                    elif '-' in phone:
                        return phone
    
    return ""

def extract_meaningful_data(row_dict: Dict, column_mappings: Dict[str, str]) -> Dict:
    """매핑된 컬럼을 기반으로 의미있는 데이터 추출"""
    result = {
        'name': '',
        'phone': '',
        'date': '',
        'time': '09:00',
        'procedure': '',
        'hospital': ''
    }
    
    # 이름 추출
    if column_mappings['name'] and column_mappings['name'] in row_dict:
        name_value = row_dict[column_mappings['name']]
        if name_value:
            result['name'] = str(name_value).strip()
    
    # 전화번호 추출 - 매핑된 컬럼에서 먼저 찾고, 없으면 전체 행에서 패턴 검색
    if column_mappings['phone'] and column_mappings['phone'] in row_dict:
        phone_value = row_dict[column_mappings['phone']]
        if phone_value:
            result['phone'] = str(phone_value).strip()
    
    if not result['phone']:
        result['phone'] = find_phone_number_in_row(row_dict)
    
    # 날짜/시간 추출
    if column_mappings['date'] and column_mappings['date'] in row_dict:
        date_value = row_dict[column_mappings['date']]
        if date_value:
            date_part, time_part = parse_date_time(str(date_value))
            result['date'] = date_part or ''
            result['time'] = time_part or '09:00'
    
    # 시술 정보 추출
    if column_mappings['procedure'] and column_mappings['procedure'] in row_dict:
        proc_value = row_dict[column_mappings['procedure']]
        if proc_value:
            result['procedure'] = str(proc_value).strip()
    
    return result

def find_hospital_info_near_name(all_data: List[Dict], current_row_idx: int, name_value: str, column_mappings: Dict[str, str]) -> str:
    """이름을 찾은 후 위로 20개 행을 보고 '개인정보' 바로 위에서 병원 정보 찾기"""
    
    # 이름을 찾은 행에서 위로 20개 행까지 검사
    start_row = max(0, current_row_idx - 20)
    
    for i in range(current_row_idx, start_row - 1, -1):  # 역순으로 검사
        if i >= len(all_data):
            continue
            
        row = all_data[i]
        if not row:
            continue
            
        # '개인정보' 문자열이 있는지 확인
        for key, value in row.items():
            if value and isinstance(value, str) and '개인정보' in value:
                # '개인정보' 바로 위의 행에서 병원 정보 찾기
                if i > 0:
                    prev_row = all_data[i - 1]
                    for prev_key, prev_value in prev_row.items():
                        if prev_value and isinstance(prev_value, str):
                            prev_value = str(prev_value).strip()
                            # 병원 정보로 보이는 데이터
                            if (
                                any(keyword in prev_value for keyword in ['병원', '의원', '피부과', '외과', '클리닉', '센터']) or
                                ('-' in prev_value and len(prev_value) > 5) or
                                len(prev_value.split()) >= 2  # 2단어 이상
                            ):
                                print(f"Found hospital info above '개인정보' for {name_value}: {prev_value}")
                                return prev_value
    
    # 백업: 이름 주변에서 병원 키워드 찾기
    for i in range(max(0, current_row_idx - 10), min(current_row_idx + 3, len(all_data))):
        row = all_data[i]
        if not row:
            continue
            
        for key, value in row.items():
            if not value:
                continue
            value_str = str(value).strip()
            
            # 병원 관련 키워드가 있고 너무 길지 않은 경우
            if (any(keyword in value_str for keyword in ['병원', '의원', '피부과', '외과', '클리닉', '센터']) 
                and len(value_str) < 100 and len(value_str) > 3):
                return value_str
    
    return ""

def parse_date_time(date_str: str) -> tuple:
    """날짜 문자열 파싱 (개선됨)"""
    if not date_str or str(date_str).strip() == "":
        return None, None
    
    try:
        date_str = str(date_str).strip()
        print(f"Parsing date: '{date_str}'")
        
        # 다양한 날짜 형식을 시도해보기
        formats_with_time = [
            "%y-%m-%d(%a) %H:%M",    # 25-08-05(화) 10:00
            "%Y-%m-%d(%a) %H:%M",    # 2025-08-05(화) 10:00
            "%y-%m-%d %H:%M",        # 25-08-05 10:00
            "%Y-%m-%d %H:%M",        # 2025-08-05 10:00
            "%m/%d/%Y %H:%M",        # 08/05/2025 10:00
            "%d/%m/%Y %H:%M",        # 05/08/2025 10:00
            "%Y/%m/%d %H:%M",        # 2025/08/05 10:00
            "%d-%m-%Y %H:%M",        # 05-08-2025 10:00
            "%Y.%m.%d %H:%M",        # 2025.08.05 10:00
            "%y.%m.%d %H:%M",        # 25.08.05 10:00
        ]
        
        formats_date_only = [
            "%y-%m-%d(%a)",           # 25-08-05(화)
            "%Y-%m-%d(%a)",           # 2025-08-05(화)
            "%y-%m-%d",               # 25-08-05
            "%Y-%m-%d",               # 2025-08-05
            "%m/%d/%Y",               # 08/05/2025
            "%d/%m/%Y",               # 05/08/2025
            "%Y/%m/%d",               # 2025/08/05
            "%d-%m-%Y",               # 05-08-2025
            "%Y.%m.%d",               # 2025.08.05
            "%y.%m.%d",               # 25.08.05
        ]
        
        # 시간이 포함된 형식 먼저 시도
        for fmt in formats_with_time:
            try:
                dt = datetime.strptime(date_str, fmt)
                result_date = dt.strftime("%Y-%m-%d")
                result_time = dt.strftime("%H:%M")
                print(f"Parsed with time format '{fmt}': {result_date} {result_time}")
                return result_date, result_time
            except ValueError:
                continue
        
        # 날짜만 있는 형식 시도
        for fmt in formats_date_only:
            try:
                dt = datetime.strptime(date_str, fmt)
                result_date = dt.strftime("%Y-%m-%d")
                print(f"Parsed with date-only format '{fmt}': {result_date}")
                return result_date, "09:00"
            except ValueError:
                continue
        
        # 정규 표현식을 사용한 파싱
        import re
        
        # 한글 요일이 포함된 경우 제거
        date_str_cleaned = re.sub(r'\([\uc6d4화수목금토일]\)', '', date_str).strip()
        
        # 다양한 패턴 시도
        patterns = [
            r'(\d{2,4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})\s*(\d{1,2}):(\d{2})',  # 날짜 + 시간
            r'(\d{2,4})[-/.]?(\d{1,2})[-/.]?(\d{1,2})',                        # 날짜만
        ]
        
        for pattern in patterns:
            match = re.search(pattern, date_str_cleaned)
            if match:
                groups = match.groups()
                
                if len(groups) >= 3:
                    year, month, day = groups[0], groups[1], groups[2]
                    
                    # 2자리 년도를 4자리로 변환
                    if len(year) == 2:
                        year_int = int(year)
                        year = "20" + year if year_int < 50 else "19" + year
                    
                    try:
                        # 날짜 유효성 검증
                        date_formatted = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                        datetime.strptime(date_formatted, "%Y-%m-%d")
                        
                        # 시간 정보 추출
                        if len(groups) >= 5 and groups[3] and groups[4]:
                            time_formatted = f"{groups[3].zfill(2)}:{groups[4]}"
                        else:
                            time_formatted = "09:00"
                        
                        print(f"Parsed with regex: {date_formatted} {time_formatted}")
                        return date_formatted, time_formatted
                        
                    except ValueError as e:
                        print(f"Invalid date: {e}")
                        continue
        
        print(f"Could not parse date: '{date_str}'")
        return None, None
        
    except Exception as e:
        print(f"Date parsing error for '{date_str}': {e}")
        return None, None

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    global user_credentials
    is_authenticated = user_credentials is not None
    
    # 로그인되어 있으면 기존 시트들 자동 갱신
    if is_authenticated:
        try:
            print("Auto-refreshing existing sheets on homepage access...")
            await refresh_all_events()
        except Exception as e:
            print(f"Error during auto-refresh: {e}")
    
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "is_authenticated": is_authenticated
    })

@app.get("/auth/login")
async def login(request: Request):
    """Start Google OAuth flow"""
    try:
        print("Starting OAuth login flow...")
        credentials_info = get_google_credentials_info()
        print("Credentials loaded successfully")
        
        redirect_uri = get_redirect_uri(request)
        print(f"Redirect URI: {redirect_uri}")
        
        flow = Flow.from_client_config(
            credentials_info,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        print("OAuth flow created successfully")
        
        authorization_url, state = flow.authorization_url(
            access_type='offline',
            include_granted_scopes='true'
        )
        print(f"Authorization URL generated: {authorization_url[:100]}...")
        
        return RedirectResponse(authorization_url)
        
    except Exception as e:
        print(f"Login error: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"로그인 시작 중 오류: {str(e)}")

@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, state: str = None):
    """Handle OAuth callback"""
    global user_credentials
    
    print(f"OAuth callback received - Code: {'Yes' if code else 'No'}, State: {state}")
    
    if not code:
        print("No authorization code received")
        raise HTTPException(status_code=400, detail="인증 코드가 없습니다.")
    
    try:
        print("Loading credentials for callback...")
        credentials_info = get_google_credentials_info()
        
        redirect_uri = get_redirect_uri(request)
        print(f"Using redirect URI: {redirect_uri}")
        
        flow = Flow.from_client_config(
            credentials_info,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
        print("Flow created for token exchange")
        
        print("Fetching token...")
        flow.fetch_token(code=code)
        user_credentials = flow.credentials
        
        print("Token obtained successfully")
        print(f"Credentials valid: {user_credentials.valid}")
        
        return RedirectResponse("/")
        
    except Exception as e:
        print(f"Callback error: {e}")
        print(f"Error type: {type(e)}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=400, detail=f"인증 실패: {str(e)}")
    
@app.get("/auth/callback")
async def auth_callback(request: Request, code: str = None, state: str = None):
    """Handle OAuth callback"""
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
        raise HTTPException(status_code=400, detail=f"인증 실패: {str(e)}")

@app.get("/auth/logout")
async def logout():
    """Logout user"""
    global user_credentials
    user_credentials = None
    return RedirectResponse("/")

@app.get("/auth/status")
async def auth_status():
    """Check authentication status"""
    global user_credentials
    return JSONResponse({
        "authenticated": user_credentials is not None
    })

@app.post("/api/sheets")
async def add_sheet(sheet_config: SheetConfig):
    """Add a new sheet configuration"""
    if not user_credentials:
        raise HTTPException(status_code=401, detail="Google 로그인이 필요합니다.")
    
    try:
        sheet_id, gid = extract_sheet_id_and_gid(sheet_config.url)
        test_data = fetch_sheet_data(sheet_id, gid)
        
        if not test_data:
            raise ValueError("시트에서 데이터를 찾을 수 없습니다.")
        
        # Add to database
        db_sheet_id = db_add_sheet(
            name=sheet_config.name,
            url=sheet_config.url, 
            color=sheet_config.color,
            sheet_id=sheet_id,
            gid=gid,
            row_count=len(test_data)
        )
        
        # Refresh events for this sheet
        await refresh_events_for_sheet(db_sheet_id)
        
        new_sheet = {
            "id": db_sheet_id,
            "name": sheet_config.name,
            "url": sheet_config.url,
            "color": sheet_config.color,
            "sheet_id": sheet_id,
            "gid": gid,
            "created_at": datetime.now().isoformat(),
            "row_count": len(test_data)
        }
        
        return JSONResponse({
            "success": True, 
            "sheet": new_sheet, 
            "message": f"시트가 추가되었습니다. ({len(test_data)}개 행)"
        })
    
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/sheets")
async def get_sheets():
    """Get all sheet configurations"""
    sheets = db_get_sheets()
    return JSONResponse(sheets)

@app.delete("/api/sheets/{sheet_id}")
async def delete_sheet(sheet_id: int):
    """Delete a sheet configuration"""
    success = db_delete_sheet(sheet_id)
    if not success:
        raise HTTPException(status_code=404, detail="시트를 찾을 수 없습니다.")
    return JSONResponse({"success": True})

@app.get("/api/events")
async def get_events():
    """Get all events from all sheets"""
    if not user_credentials:
        return JSONResponse([])
    
    # Refresh events from all sheets
    await refresh_all_events()
    
    # Return events from database
    events = db_get_events()
    return JSONResponse(events)

async def refresh_all_events():
    """Refresh events for all sheets"""
    if not user_credentials:
        return
    
    sheets = db_get_sheets()
    for sheet in sheets:
        await refresh_events_for_sheet(sheet["id"])

async def refresh_events_for_sheet(db_sheet_id: int):
    """Refresh events for a specific sheet"""
    if not user_credentials:
        return
    
    from database import get_sheet_by_id
    sheet = get_sheet_by_id(db_sheet_id)
    if not sheet:
        return
        
    try:
        print(f"Processing sheet: {sheet['name']}")
        
        # Clear existing events for this sheet
        clear_events_for_sheet(db_sheet_id)
        
        # Fetch fresh data
        data = fetch_sheet_data(sheet["sheet_id"], sheet["gid"])
        
        if not data:
            print(f"No data found in sheet {sheet['name']}")
            return
        
        # 동적으로 컬럼 매핑 찾기
        column_mappings = find_column_mappings(data)
        print(f"Found column mappings: {column_mappings}")
        
        # 시트명에서 병원명 추출
        sheet_hospital = extract_hospital_from_sheet_name_or_data(sheet['name'], data)
        
        events_count = 0
        
        for row_idx, row in enumerate(data):
            if not row:
                continue
            
            # 매핑된 컬럼을 기반으로 데이터 추출
            extracted_data = extract_meaningful_data(row, column_mappings)
            
            # 이름과 날짜가 있는 경우만 처리
            if extracted_data['name'] and extracted_data['date']:
                
                # 병원명 결정 (시트에서 추출한 병원명 또는 이름 주변에서 찾기)
                hospital_name = (
                    sheet_hospital or 
                    find_hospital_info_near_name(data, row_idx, extracted_data['name'], column_mappings) or 
                    sheet['name']
                )
                
                # Add to database
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
                
                # 처음 10개 이벤트는 디버깅을 위해 로그 출력
                if events_count <= 10:
                    print(f"  Event {events_count}: {extracted_data['name']} - {extracted_data['date']} {extracted_data['time']} at {hospital_name}")
        
        print(f"Sheet {sheet['name']} processed: {events_count} events found")
                        
    except Exception as e:
        print(f"Error processing sheet {sheet['name']}: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)ings)
            
            # 이름과 날짜가 있는 경우만 처리
            if extracted_data['name'] and extracted_data['date']:
                
                # 병원명 결정 (시트에서 추출한 병원명 또는 이름 주변에서 찾기)
                hospital_name = (
                    sheet_hospital or 
                    find_hospital_info_near_name(data, row_idx, extracted_data['name'], column_mappings) or 
                    sheet['name']
                )
                
                # Add to database
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
                
                # 처음 10개 이벤트는 디버깅을 위해 로그 출력
                if events_count <= 10:
                    print(f"  Event {events_count}: {extracted_data['name']} - {extracted_data['date']} {extracted_data['time']} at {hospital_name}")
        
        print(f"Sheet {sheet['name']} processed: {events_count} events found")
                        
    except Exception as e:
        print(f"Error processing sheet {sheet['name']}: {e}")
        import traceback
        print(f"Traceback: {traceback.format_exc()}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
