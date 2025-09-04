import sqlite3
import json
import os
import pandas as pd
import re
from datetime import datetime
from typing import List, Dict, Optional, Tuple

# Use data directory for Render persistent storage
DATA_DIR = os.environ.get("DATA_DIR", ".")
DATABASE_PATH = os.path.join(DATA_DIR, "sheets_calendar.db")

def init_database():
    """Initialize SQLite database with required tables"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Create sheets table
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sheets (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            url TEXT NOT NULL,
            color TEXT NOT NULL,
            sheet_id TEXT NOT NULL,
            gid TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            row_count INTEGER DEFAULT 0
        )
    """)
    
    # Create events table for caching
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sheet_id INTEGER,
            title TEXT NOT NULL,
            name TEXT NOT NULL,
            date TEXT NOT NULL,
            time TEXT NOT NULL,
            sheet_name TEXT NOT NULL,
            color TEXT NOT NULL,
            hospital TEXT,
            phone TEXT,
            details TEXT, -- JSON string
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (sheet_id) REFERENCES sheets (id) ON DELETE CASCADE
        )
    """)
    
    # Create excel_files table for local Excel file processing
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS excel_files (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            filename TEXT NOT NULL,
            file_path TEXT NOT NULL,
            hospital_name TEXT NOT NULL,
            color TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            last_processed TIMESTAMP,
            row_count INTEGER DEFAULT 0
        )
    """)
    
    # Create index for better performance
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_date ON events(date)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_events_sheet_id ON events(sheet_id)")
    
    conn.commit()
    conn.close()

def add_sheet(name: str, url: str, color: str, sheet_id: str, gid: str, row_count: int = 0) -> int:
    """Add a new sheet to the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        INSERT INTO sheets (name, url, color, sheet_id, gid, row_count)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (name, url, color, sheet_id, gid, row_count))
    
    sheet_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return sheet_db_id

def get_all_sheets() -> List[Dict]:
    """Get all sheets from database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, url, color, sheet_id, gid, created_at, row_count
        FROM sheets ORDER BY created_at DESC
    """)
    
    sheets = []
    for row in cursor.fetchall():
        sheets.append({
            "id": row[0],
            "name": row[1],
            "url": row[2],
            "color": row[3],
            "sheet_id": row[4],
            "gid": row[5],
            "created_at": row[6],
            "row_count": row[7]
        })
    
    conn.close()
    return sheets

def delete_sheet(sheet_id: int) -> bool:
    """Delete a sheet and its events from database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    # Check if sheet exists
    cursor.execute("SELECT id FROM sheets WHERE id = ?", (sheet_id,))
    if not cursor.fetchone():
        conn.close()
        return False
    
    # Delete events first (cascade should handle this, but being explicit)
    cursor.execute("DELETE FROM events WHERE sheet_id = ?", (sheet_id,))
    
    # Delete sheet
    cursor.execute("DELETE FROM sheets WHERE id = ?", (sheet_id,))
    
    conn.commit()
    conn.close()
    return True

def clear_events_for_sheet(sheet_id: int):
    """Clear all events for a specific sheet"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM events WHERE sheet_id = ?", (sheet_id,))
    
    conn.commit()
    conn.close()

def add_event(sheet_id: int, title: str, name: str, date: str, time: str, 
              sheet_name: str, color: str, hospital: str = "", phone: str = "", 
              details: Dict = None):
    """Add an event to the database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    details_json = json.dumps(details) if details else "{}"
    
    cursor.execute("""
        INSERT INTO events (sheet_id, title, name, date, time, sheet_name, color, hospital, phone, details)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (sheet_id, title, name, date, time, sheet_name, color, hospital, phone, details_json))
    
    conn.commit()
    conn.close()

def get_all_events() -> List[Dict]:
    """Get all events from database"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT title, name, date, time, sheet_name, color, hospital, phone, details
        FROM events ORDER BY date, time
    """)
    
    events = []
    for row in cursor.fetchall():
        try:
            details = json.loads(row[8]) if row[8] else {}
        except:
            details = {}
            
        events.append({
            "title": row[0],
            "name": row[1],
            "date": row[2],
            "time": row[3],
            "sheet_name": row[4],
            "color": row[5],
            "hospital": row[6],
            "phone": row[7],
            "details": details
        })
    
    conn.close()
    return events

def get_sheet_by_id(sheet_id: int) -> Optional[Dict]:
    """Get a specific sheet by ID"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, name, url, color, sheet_id, gid, created_at, row_count
        FROM sheets WHERE id = ?
    """, (sheet_id,))
    
    row = cursor.fetchone()
    conn.close()
    
    if row:
        return {
            "id": row[0],
            "name": row[1],
            "url": row[2],
            "color": row[3],
            "sheet_id": row[4],
            "gid": row[5],
            "created_at": row[6],
            "row_count": row[7]
        }
    return None

# Excel 파일 처리 기능들

def extract_hospital_name_from_filename(filename: str) -> str:
    """파일명에서 병원명 추출"""
    filename_lower = filename.lower()
    
    hospital_mapping = {
        '라비앙': '라비앙성형외과',
        '트랜드': '트랜드성형외과',
        '황금피부과': '황금피부과',
        '셀나인': '셀나인청담',
        '제네오엑스': '셀나인청담',
        '케이블린': '케이블린필러',
        '쥬브겔': '쥬브겔필러'
    }
    
    for key, hospital in hospital_mapping.items():
        if key in filename_lower:
            return hospital
    
    return "알 수 없는 병원"

def get_hospital_color(hospital_name: str) -> str:
    """병원별 색상 반환"""
    colors = {
        '라비앙성형외과': '#FF6B6B',
        '트랜드성형외과': '#4ECDC4',
        '황금피부과': '#45B7D1',
        '셀나인청담': '#96CEB4',
        '케이블린필러': '#FFEAA7',
        '쥬브겔필러': '#DDA0DD'
    }
    return colors.get(hospital_name, '#95A5A6')

def parse_date_time(date_str) -> Tuple[Optional[str], Optional[str]]:
    """날짜 문자열을 파싱해서 날짜와 시간으로 분리"""
    if pd.isna(date_str) or not str(date_str).strip():
        return None, None
    
    date_str = str(date_str).strip()
    
    # Excel에서 숫자로 저장된 날짜 처리
    try:
        if date_str.replace('.', '').replace('-', '').isdigit():
            excel_date = float(date_str)
            if excel_date > 40000:  # Excel의 날짜 시리얼 번호
                from datetime import timedelta
                excel_epoch = datetime(1900, 1, 1)
                actual_date = excel_epoch + timedelta(days=excel_date - 2)
                return actual_date.strftime("%Y-%m-%d"), "09:00"
    except:
        pass
    
    # 다양한 날짜 형식 처리
    patterns = [
        r'(\d{2})-(\d{2})-(\d{2})\((\w)\)\s*(\d{1,2}):(\d{2})',
        r'(\d{4})-(\d{1,2})-(\d{1,2})\s*(\d{1,2}):(\d{2})',
        r'(\d{2})\.(\d{1,2})\.(\d{1,2})\s*(\d{1,2}):(\d{2})',
        r'(\d{2})-(\d{1,2})-(\d{1,2})',
        r'(\d{4})-(\d{1,2})-(\d{1,2})',
    ]
    
    for pattern in patterns:
        match = re.search(pattern, date_str)
        if match:
            groups = match.groups()
            
            if len(groups) >= 3:
                year, month, day = groups[0], groups[1], groups[2]
                
                # 2자리 년도를 4자리로 변환
                if len(year) == 2:
                    year_int = int(year)
                    year = "20" + year if year_int < 50 else "19" + year
                
                try:
                    date_formatted = f"{year}-{month.zfill(2)}-{day.zfill(2)}"
                    datetime.strptime(date_formatted, "%Y-%m-%d")
                    
                    # 시간 정보가 있으면 추출
                    if len(groups) >= 6:
                        time_formatted = f"{groups[-2].zfill(2)}:{groups[-1]}"
                    else:
                        time_formatted = "09:00"
                    
                    return date_formatted, time_formatted
                except ValueError:
                    pass
    
    return None, None

def extract_phone_number(text) -> str:
    """텍스트에서 전화번호 추출"""
    if pd.isna(text):
        return ""
    
    text = str(text)
    phone_pattern = r'(\d{3})-(\d{3,4})-(\d{4})'
    match = re.search(phone_pattern, text)
    if match:
        return match.group()
    
    # 숫자만 있는 경우 포맷팅
    numbers = re.findall(r'\d+', text)
    if numbers:
        phone_str = ''.join(numbers)
        if len(phone_str) == 11 and phone_str.startswith('010'):
            return f"{phone_str[:3]}-{phone_str[3:7]}-{phone_str[7:]}"
        elif len(phone_str) == 10:
            return f"{phone_str[:3]}-{phone_str[3:6]}-{phone_str[6:]}"
    
    return text

def find_header_row(df: pd.DataFrame) -> Tuple[int, Dict[str, int]]:
    """헤더 행과 컬럼 매핑을 찾는 함수"""
    for idx, row in df.iterrows():
        if row.astype(str).str.contains('성함|이름', case=False, na=False).any():
            columns_mapping = {}
            for col_idx, cell_value in enumerate(row):
                if pd.isna(cell_value):
                    continue
                
                cell_str = str(cell_value).lower()
                if '성함' in cell_str or '이름' in cell_str:
                    columns_mapping['name'] = col_idx
                elif '연락처' in cell_str or '전화' in cell_str or '핸드폰' in cell_str:
                    columns_mapping['phone'] = col_idx
                elif '날짜' in cell_str or '일시' in cell_str or '예약' in cell_str:
                    if '확정' in cell_str or '일시' in cell_str or '수술일' in cell_str:
                        columns_mapping['date'] = col_idx
                elif '시술' in cell_str or '수술' in cell_str or '부위' in cell_str:
                    columns_mapping['procedure'] = col_idx
            
            return idx, columns_mapping
    
    return -1, {}

def add_excel_file(filename: str, file_path: str, hospital_name: str = None) -> int:
    """Excel 파일 정보를 데이터베이스에 추가"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    if not hospital_name:
        hospital_name = extract_hospital_name_from_filename(filename)
    
    color = get_hospital_color(hospital_name)
    
    cursor.execute("""
        INSERT INTO excel_files (filename, file_path, hospital_name, color)
        VALUES (?, ?, ?, ?)
    """, (filename, file_path, hospital_name, color))
    
    file_db_id = cursor.lastrowid
    conn.commit()
    conn.close()
    
    return file_db_id

def get_all_excel_files() -> List[Dict]:
    """모든 Excel 파일 목록 반환"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        SELECT id, filename, file_path, hospital_name, color, created_at, last_processed, row_count
        FROM excel_files ORDER BY created_at DESC
    """)
    
    files = []
    for row in cursor.fetchall():
        files.append({
            "id": row[0],
            "filename": row[1],
            "file_path": row[2],
            "hospital_name": row[3],
            "color": row[4],
            "created_at": row[5],
            "last_processed": row[6],
            "row_count": row[7]
        })
    
    conn.close()
    return files

def process_excel_file(file_path: str) -> List[Dict]:
    """Excel 파일을 처리해서 예약 정보 추출"""
    appointments = []
    filename = os.path.basename(file_path)
    hospital_name = extract_hospital_name_from_filename(filename)
    color = get_hospital_color(hospital_name)
    
    try:
        # Excel 파일의 모든 시트 읽기
        excel_file = pd.ExcelFile(file_path)
        
        for sheet_name in excel_file.sheet_names:
            try:
                # 시트 읽기 (헤더 없이)
                df = pd.read_excel(file_path, sheet_name=sheet_name, header=None)
                
                if df.empty:
                    continue
                
                # 헤더 행과 컬럼 매핑 찾기
                header_row, columns_mapping = find_header_row(df)
                
                if header_row == -1 or 'name' not in columns_mapping:
                    continue
                
                # 데이터 행 처리
                for idx in range(header_row + 1, len(df)):
                    row = df.iloc[idx]
                    
                    # 이름이 있는지 확인
                    name_value = row.iloc[columns_mapping['name']] if 'name' in columns_mapping else None
                    if pd.isna(name_value) or not str(name_value).strip():
                        continue
                    
                    name = str(name_value).strip()
                    
                    # 전화번호 추출
                    phone = ""
                    if 'phone' in columns_mapping:
                        phone_value = row.iloc[columns_mapping['phone']]
                        phone = extract_phone_number(phone_value)
                    
                    # 날짜/시간 추출
                    appointment_date, appointment_time = None, None
                    if 'date' in columns_mapping:
                        date_value = row.iloc[columns_mapping['date']]
                        appointment_date, appointment_time = parse_date_time(date_value)
                    
                    # 시술 정보
                    procedure = ""
                    if 'procedure' in columns_mapping:
                        proc_value = row.iloc[columns_mapping['procedure']]
                        if not pd.isna(proc_value):
                            procedure = str(proc_value).strip()
                    
                    if appointment_date:  # 날짜가 있는 경우만 추가
                        appointment = {
                            'title': f"{hospital_name}_{name}",
                            'name': name,
                            'date': appointment_date,
                            'time': appointment_time or "09:00",
                            'sheet_name': f"{filename}_{sheet_name}",
                            'color': color,
                            'hospital': hospital_name,
                            'phone': phone,
                            'details': {
                                'procedure': procedure,
                                'sheet_name': sheet_name,
                                'row_index': idx + 1,
                                'file_path': file_path
                            }
                        }
                        
                        appointments.append(appointment)
                        
            except Exception as e:
                print(f"Error processing sheet {sheet_name}: {str(e)}")
                continue
                
    except Exception as e:
        print(f"Error processing file {filename}: {str(e)}")
    
    return appointments

def clear_events_for_excel_file(filename: str):
    """Excel 파일에 해당하는 모든 이벤트 삭제"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("DELETE FROM events WHERE sheet_name LIKE ?", (f"{filename}_%",))
    
    conn.commit()
    conn.close()

def update_excel_file_processed(filename: str, row_count: int):
    """Excel 파일 처리 정보 업데이트"""
    conn = sqlite3.connect(DATABASE_PATH)
    cursor = conn.cursor()
    
    cursor.execute("""
        UPDATE excel_files 
        SET last_processed = CURRENT_TIMESTAMP, row_count = ?
        WHERE filename = ?
    """, (row_count, filename))
    
    conn.commit()
    conn.close()