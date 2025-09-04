import pandas as pd
import openpyxl
from datetime import datetime
import re
import os
import glob
from typing import List, Dict, Optional, Tuple
import sqlite3
import json

class ExcelHospitalProcessor:
    """Excel 파일에서 병원/의원/피부과 정보를 추출하는 클래스"""
    
    def __init__(self, excel_directory: str, database_path: str = "hospital_calendar.db"):
        self.excel_directory = excel_directory
        self.database_path = database_path
        self.hospital_keywords = ['병원', '의원', '피부과', '외과', '클리닉', '센터', '성형외과', '정형외과', '내과', '산부인과', '소아과', '치과', '한의원']
        self.init_database()
    
    def init_database(self):
        """데이터베이스 초기화"""
        conn = sqlite3.connect(self.database_path)
        cursor = conn.cursor()
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS hospital_appointments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                hospital_name TEXT NOT NULL,
                patient_name TEXT NOT NULL,
                phone_number TEXT,
                appointment_date DATE,
                appointment_time TIME,
                procedure_type TEXT,
                status TEXT,
                notes TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS file_processing_log (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                file_name TEXT NOT NULL,
                sheet_name TEXT NOT NULL,
                rows_processed INTEGER,
                appointments_found INTEGER,
                processing_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        conn.commit()
        conn.close()
    
    def extract_hospital_name_from_filename(self, filename: str) -> str:
        """파일명에서 병원명 추출"""
        filename_lower = filename.lower()
        
        # 파일명에서 병원명 매핑
        hospital_mapping = {
            '라비앙': '라비앙성형외과',
            '트랜드': '트랜드성형외과',
            '황금피부과': '황금피부과',
            '셀나인': '셀나인청담',
            '제네오엑스': '셀나인청담',
            '케이블린': '케이블린 체험단 병원들',
            '쥬브겔': '쥬브겔 체험단 병원들'
        }
        
        for key, hospital in hospital_mapping.items():
            if key in filename_lower:
                return hospital
        
        return "알 수 없는 병원"
    
    def find_header_row(self, df: pd.DataFrame) -> Tuple[int, Dict[str, int]]:
        """헤더 행과 컬럼 매핑을 찾는 함수"""
        for idx, row in df.iterrows():
            if row.astype(str).str.contains('성함|이름', case=False, na=False).any():
                # 헤더 행 찾음
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
                        if '확정' in cell_str or '일시' in cell_str:
                            columns_mapping['date'] = col_idx
                    elif '시술' in cell_str or '수술' in cell_str or '부위' in cell_str:
                        columns_mapping['procedure'] = col_idx
                
                return idx, columns_mapping
        
        return -1, {}
    
    def parse_date_time(self, date_str: str) -> Tuple[Optional[str], Optional[str]]:
        """날짜 문자열을 파싱해서 날짜와 시간으로 분리"""
        if pd.isna(date_str) or not str(date_str).strip():
            return None, None
        
        date_str = str(date_str).strip()
        
        # Excel에서 숫자로 저장된 날짜 처리
        try:
            if date_str.replace('.', '').isdigit():
                excel_date = float(date_str)
                if excel_date > 40000:  # Excel의 날짜 시리얼 번호
                    from datetime import datetime, timedelta
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
                    year, month, day = groups[0