import sqlite3
import json
import os
from datetime import datetime
from typing import List, Dict, Optional

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