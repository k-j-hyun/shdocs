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
from googleapiclient.discovery import build
import os
import json
from database import init_database, add_sheet as db_add_sheet, get_all_sheets as db_get_sheets, delete_sheet as db_delete_sheet, clear_events_for_sheet, add_event as db_add_event, get_all_events as db_get_events

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
def get_google_credentials_info():
    """Get Google OAuth credentials from environment variable or file"""
    # Try environment variable first (for production)
    env_creds = os.getenv('GOOGLE_CREDENTIALS_JSON')
    if env_creds:
        return json.loads(env_creds)
    
    # Fallback to file (for development)
    if os.path.exists("credentials.json"):
        with open("credentials.json", 'r', encoding='utf-8') as f:
            return json.load(f)
    
    raise HTTPException(status_code=500, detail="OAuth 설정이 없습니다. GOOGLE_CREDENTIALS_JSON 환경변수를 설정하거나 credentials.json 파일을 추가하세요.")

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

def get_column_value_by_letter(row_dict: Dict, column_letter: str) -> str:
    """Get value from row by column letter (A, B, C, etc.)"""
    if column_letter in row_dict:
        return str(row_dict[column_letter]).strip()
    
    column_index = ord(column_letter.upper()) - ord('A')
    keys = list(row_dict.keys())
    
    if 0 <= column_index < len(keys):
        key = keys[column_index]
        return str(row_dict[key]).strip()
    
    return ""

def find_phone_number_in_row(row_dict: Dict) -> str:
    """Find phone number pattern (000-0000-0000 or similar) in any column of the row"""
    import re
    phone_pattern = r'\d{2,3}-\d{3,4}-\d{4}'
    
    for key, value in row_dict.items():
        if value and isinstance(value, str):
            match = re.search(phone_pattern, value)
            if match:
                return match.group()
    return ""

def find_hospital_info(all_data: List[Dict], current_row_idx: int, name_value: str) -> str:
    """Find hospital info by looking at rows above the current person's info"""
    # Look for hospital info in previous rows
    for i in range(max(0, current_row_idx - 10), current_row_idx):
        row = all_data[i]
        for col_letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G']:
            value = get_column_value_by_letter(row, col_letter)
            if value and any(keyword in value for keyword in ['병원', '클리닉', '의원', '센터', '스텔라', '엠투투', '피부과', '외과', '내과', '정형외과', '산부인과', '소아과', '치과', '한의원']):
                return value
    return ""

def parse_date_time(date_str: str) -> tuple:
    """Parse date string and return date and time"""
    if not date_str or date_str.strip() == "":
        return None, None
    
    try:
        date_str = date_str.strip()
        
        formats = [
            "%y-%m-%d(%a) %H:%M",
            "%Y-%m-%d(%a) %H:%M",
            "%y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M",
            "%m/%d/%Y %H:%M",
            "%d/%m/%Y %H:%M",
            "%Y/%m/%d %H:%M",
            "%d-%m-%Y %H:%M",
            "%Y.%m.%d %H:%M",
            "%y.%m.%d %H:%M",
        ]
        
        for fmt in formats:
            try:
                dt = datetime.strptime(date_str, fmt)
                return dt.strftime("%Y-%m-%d"), dt.strftime("%H:%M")
            except ValueError:
                continue
        
        date_match = re.search(r'(\d{2,4})[-/.년](\d{1,2})[-/.월](\d{1,2})[일]?', date_str)
        time_match = re.search(r'(\d{1,2}):(\d{2})', date_str)
        
        if date_match:
            year, month, day = date_match.groups()
            
            if len(year) == 2:
                year_int = int(year)
                if year_int > 50:
                    year = "19" + year
                else:
                    year = "20" + year
            
            try:
                date_formatted = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                datetime.strptime(date_formatted, "%Y-%m-%d")
                
                time_formatted = "00:00"
                if time_match:
                    hour, minute = time_match.groups()
                    time_formatted = f"{hour.zfill(2)}:{minute}"
                
                return date_formatted, time_formatted
            except ValueError:
                pass
        
        return None, None
        
    except Exception as e:
        print(f"Date parsing error for '{date_str}': {e}")
        return None, None

@app.get("/", response_class=HTMLResponse)
async def read_root(request: Request):
    global user_credentials
    is_authenticated = user_credentials is not None
    return templates.TemplateResponse("index.html", {
        "request": request, 
        "is_authenticated": is_authenticated
    })

@app.get("/auth/login")
async def login(request: Request):
    """Start Google OAuth flow"""
    try:
        credentials_info = get_google_credentials_info()
        redirect_uri = get_redirect_uri(request)
        
        flow = Flow.from_client_config(
            credentials_info,
            scopes=SCOPES,
            redirect_uri=redirect_uri
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    authorization_url, state = flow.authorization_url(
        access_type='offline',
        include_granted_scopes='true'
    )
    
    return RedirectResponse(authorization_url)

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
        
        for row_idx, row in enumerate(data):
            if not row:
                continue
            
            name_value = get_column_value_by_letter(row, 'E')
            date_value = get_column_value_by_letter(row, 'O')
            
            if row_idx < 10:
                print(f"Row {row_idx + 1}: Name='{name_value}', Date='{date_value}'")
                # Print all column values for first 10 rows to understand structure
                for col_letter in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'I', 'J']:
                    col_value = get_column_value_by_letter(row, col_letter)
                    if col_value:
                        print(f"  {col_letter}: '{col_value}'")
            
            if name_value and date_value and len(name_value) > 0 and len(date_value) > 0:
                date_part, time_part = parse_date_time(date_value)
                
                if date_part:
                    # Find phone number pattern in any column
                    phone_info = find_phone_number_in_row(row)
                    
                    # Find hospital info by looking at previous rows
                    hospital_info = find_hospital_info(data, row_idx, name_value)
                    
                    # Add to database
                    db_add_event(
                        sheet_id=db_sheet_id,
                        title=f"{sheet['name']}_{name_value}",
                        name=name_value,
                        date=date_part,
                        time=time_part or "00:00",
                        sheet_name=sheet["name"],
                        color=sheet["color"],
                        hospital=hospital_info,
                        phone=phone_info,
                        details=dict(row)
                    )
        
        # Count events for this sheet
        events = db_get_events()
        sheet_events = [e for e in events if e["sheet_name"] == sheet["name"]]
        print(f"Sheet {sheet['name']} processed: {len(sheet_events)} events found")
                        
    except Exception as e:
        print(f"Error processing sheet {sheet['name']}: {e}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
