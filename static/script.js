// Global variables
let selectedColor = '#FF6B9D';
let currentDate = new Date();
let sheets = [];
let events = [];

// Initialize app
document.addEventListener('DOMContentLoaded', function() {
    setupColorPalette();
    checkAuthStatus();
    loadSheets();
    generateCalendar();
    loadEvents();
    loadMonthlyInfo(); // 초기 월별 정보 로드
});

// Authentication functions
function login() {
    window.location.href = '/auth/login';
}

function logout() {
    if (confirm('로그아웃 하시겠습니까?')) {
        window.location.href = '/auth/logout';
    }
}

// Check authentication status
function checkAuthStatus() {
    fetch('/auth/status')
        .then(response => response.json())
        .then(data => {
            const loginRequired = document.getElementById('login-required');
            const mainContent = document.getElementById('main-content');
            
            if (data.authenticated) {
                if (loginRequired) loginRequired.style.display = 'none';
                if (mainContent) mainContent.style.display = 'block';
            } else {
                if (loginRequired) loginRequired.style.display = 'block';
                if (mainContent) mainContent.style.display = 'none';
            }
        })
        .catch(error => {
            console.error('Auth status check failed:', error);
        });
}

// Color palette setup
function setupColorPalette() {
    const colorOptions = document.querySelectorAll('.color-option');
    
    // Select first color by default
    if (colorOptions.length > 0) {
        colorOptions[0].classList.add('selected');
        selectedColor = colorOptions[0].dataset.color;
    }
    
    colorOptions.forEach(option => {
        option.addEventListener('click', function() {
            // Remove previous selection
            colorOptions.forEach(opt => opt.classList.remove('selected'));
            
            // Add selection to clicked option
            this.classList.add('selected');
            selectedColor = this.dataset.color;
        });
    });
}

// Sheet management
async function addSheet() {
    const name = document.getElementById('sheet-name').value.trim();
    const url = document.getElementById('sheet-url').value.trim();
    
    if (!name || !url) {
        alert('시트 제목과 URL을 모두 입력해주세요.');
        return;
    }
    
    if (!url.includes('docs.google.com/spreadsheets')) {
        alert('유효한 Google Sheets URL을 입력해주세요.');
        return;
    }
    
    try {
        showLoading(true);
        
        const response = await fetch('/api/sheets', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({
                name: name,
                url: url,
                color: selectedColor
            })
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            // Clear form
            document.getElementById('sheet-name').value = '';
            document.getElementById('sheet-url').value = '';
            
            // Reload sheets and events
            await loadSheets();
            await loadEvents();
            
            alert(result.message || '시트가 성공적으로 추가되었습니다!');
        } else {
            throw new Error(result.detail || '시트 추가에 실패했습니다.');
        }
    } catch (error) {
        console.error('Error adding sheet:', error);
        if (error.message.includes('401')) {
            alert('Google 로그인이 필요합니다. 다시 로그인해주세요.');
            checkAuthStatus();
        } else {
            alert('시트 추가 중 오류가 발생했습니다: ' + error.message);
        }
    } finally {
        showLoading(false);
    }
}

async function deleteSheet(sheetId) {
    if (!confirm('이 시트를 삭제하시겠습니까?')) {
        return;
    }
    
    try {
        showLoading(true);
        
        const response = await fetch(`/api/sheets/${sheetId}`, {
            method: 'DELETE'
        });
        
        const result = await response.json();
        
        if (response.ok && result.success) {
            await loadSheets();
            await loadEvents();
        } else {
            throw new Error('시트 삭제에 실패했습니다.');
        }
    } catch (error) {
        console.error('Error deleting sheet:', error);
        alert('시트 삭제 중 오류가 발생했습니다: ' + error.message);
    } finally {
        showLoading(false);
    }
}

async function loadSheets() {
    try {
        const response = await fetch('/api/sheets');
        sheets = await response.json();
        renderSheetsList();
    } catch (error) {
        console.error('Error loading sheets:', error);
    }
}

function renderSheetsList() {
    const sheetsList = document.getElementById('sheets-list');
    
    if (sheets.length === 0) {
        sheetsList.innerHTML = '<p style="color: #666; text-align: center; padding: 20px;">등록된 시트가 없습니다.</p>';
        return;
    }
    
    sheetsList.innerHTML = sheets.map(sheet => `
        <div class="sheet-item slide-in" style="border-left-color: ${sheet.color}">
            <div class="sheet-info">
                <h4>${escapeHtml(sheet.name)}</h4>
                <p>${escapeHtml(sheet.url)}</p>
                <small style="color: #999;">${sheet.row_count || 0}개 행</small>
            </div>
            <button class="btn-delete" onclick="deleteSheet(${sheet.id})">삭제</button>
        </div>
    `).join('');
}

// Events management
async function loadEvents() {
    try {
        showLoading(true);
        const response = await fetch('/api/events');
        
        if (response.status === 401) {
            checkAuthStatus();
            return;
        }
        
        events = await response.json();
        generateCalendar();
        loadMonthlyInfo(); // 이벤트 로드 후 월별 정보도 로드
    } catch (error) {
        console.error('Error loading events:', error);
    } finally {
        showLoading(false);
    }
}

// Calendar generation
function generateCalendar() {
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth();
    
    // Update month header
    const monthNames = [
        '1월', '2월', '3월', '4월', '5월', '6월',
        '7월', '8월', '9월', '10월', '11월', '12월'
    ];
    document.getElementById('current-month').textContent = `${year}년 ${monthNames[month]}`;
    
    // Get first day of month and number of days
    const firstDay = new Date(year, month, 1);
    const lastDay = new Date(year, month + 1, 0);
    const daysInMonth = lastDay.getDate();
    const startingDayOfWeek = firstDay.getDay();
    
    // Get previous month's last days
    const prevMonth = new Date(year, month - 1, 0);
    const daysInPrevMonth = prevMonth.getDate();
    
    const calendarDays = document.getElementById('calendar-days');
    calendarDays.innerHTML = '';
    
    let dayCount = 1;
    let nextMonthDayCount = 1;
    
    // Generate 6 weeks (42 days)
    for (let week = 0; week < 6; week++) {
        for (let day = 0; day < 7; day++) {
            const dayIndex = week * 7 + day;
            const dayElement = document.createElement('div');
            dayElement.className = 'calendar-day';
            
            let displayDay, displayMonth, displayYear, isCurrentMonth;
            
            if (dayIndex < startingDayOfWeek) {
                // Previous month days
                displayDay = daysInPrevMonth - (startingDayOfWeek - dayIndex - 1);
                displayMonth = month - 1;
                displayYear = year;
                isCurrentMonth = false;
                dayElement.classList.add('other-month');
            } else if (dayCount <= daysInMonth) {
                // Current month days
                displayDay = dayCount;
                displayMonth = month;
                displayYear = year;
                isCurrentMonth = true;
                dayCount++;
            } else {
                // Next month days
                displayDay = nextMonthDayCount;
                displayMonth = month + 1;
                displayYear = year;
                isCurrentMonth = false;
                dayElement.classList.add('other-month');
                nextMonthDayCount++;
            }
            
            // Adjust year for previous/next month
            if (displayMonth < 0) {
                displayMonth = 11;
                displayYear--;
            } else if (displayMonth > 11) {
                displayMonth = 0;
                displayYear++;
            }
            
            // Check if it's today
            const today = new Date();
            if (displayYear === today.getFullYear() && 
                displayMonth === today.getMonth() && 
                displayDay === today.getDate()) {
                dayElement.classList.add('today');
            }
            
            // Create date string for event matching
            const dateString = `${displayYear}-${String(displayMonth + 1).padStart(2, '0')}-${String(displayDay).padStart(2, '0')}`;
            
            // Add day number
            const dayNumber = document.createElement('div');
            dayNumber.className = 'day-number';
            dayNumber.textContent = displayDay;
            dayElement.appendChild(dayNumber);
            
            // Add events for this day
            const dayEvents = events.filter(event => event.date === dateString);
            dayEvents.forEach(event => {
                const eventElement = document.createElement('div');
                eventElement.className = 'event';
                eventElement.style.backgroundColor = event.color;
                
                // 병원별 색상 도트 추가
                const hospitalColor = getHospitalColor(event.hospital);
                eventElement.innerHTML = `
                    <span class="hospital-dot" style="color: ${hospitalColor}; font-size: 8px; margin-right: 2px;">●</span>
                    ${event.time} ${event.name}
                `;
                
                // Create tooltip content
                let tooltipContent = `
                    <strong>${event.name}</strong><br>
                    <strong>시간:</strong> ${event.time}<br>
                `;
                
                if (event.hospital && event.hospital.trim()) {
                    tooltipContent += `<strong>병원:</strong> <span style="color: ${hospitalColor}">●</span> ${event.hospital}<br>`;
                }
                
                if (event.phone && event.phone.trim()) {
                    tooltipContent += `<strong>연락처:</strong> ${event.phone}<br>`;
                }
                
                // Add mouse events for tooltip
                eventElement.addEventListener('mouseenter', function(e) {
                    showTooltip(e, tooltipContent);
                });
                
                eventElement.addEventListener('mouseleave', function() {
                    hideTooltip();
                });
                
                eventElement.addEventListener('mousemove', function(e) {
                    updateTooltipPosition(e);
                });
                
                // Add click event to show details
                eventElement.addEventListener('click', function(e) {
                    e.stopPropagation();
                    hideTooltip(); // Hide tooltip when modal opens
                    showEventDetails(event);
                });
                
                dayElement.appendChild(eventElement);
            });
            
            calendarDays.appendChild(dayElement);
        }
    }
}

function changeMonth(direction) {
    currentDate.setMonth(currentDate.getMonth() + direction);
    generateCalendar();
    loadMonthlyInfo(); // 월별 정보 로드
}

// 월별 마크다운 정보 로드
async function loadMonthlyInfo() {
    if (!currentDate) return;
    
    const year = currentDate.getFullYear();
    const month = currentDate.getMonth() + 1;
    
    try {
        const response = await fetch(`/api/events/monthly/${year}/${month}`);
        const data = await response.json();
        
        const monthlyMarkdown = document.getElementById('monthly-markdown');
        const monthlyInfoTitle = document.getElementById('monthly-info-title');
        
        if (data.markdown) {
            // 마크다운을 HTML로 변환
            monthlyMarkdown.innerHTML = markdownToHtml(data.markdown);
            monthlyInfoTitle.textContent = `${year}년 ${month}월 예약 현황`;
        } else {
            monthlyMarkdown.innerHTML = '<p>예약 정보가 없습니다.</p>';
            monthlyInfoTitle.textContent = '월별 예약 현황';
        }
    } catch (error) {
        console.error('Error loading monthly info:', error);
        document.getElementById('monthly-markdown').innerHTML = '<p>월별 정보를 불러오는 중 오류가 발생했습니다.</p>';
    }
}

// 간단한 마크다운 to HTML 변환 함수
function markdownToHtml(markdown) {
    let html = markdown;
    
    // 헤더 변환
    html = html.replace(/^# (.+)$/gm, '<h1>$1</h1>');
    html = html.replace(/^## (.+)$/gm, '<h2>$1</h2>');
    html = html.replace(/^### (.+)$/gm, '<h3>$1</h3>');
    
    // 테이블 변환 (간단한 방식)
    const lines = html.split('\n');
    let inTable = false;
    let processedLines = [];
    
    for (let i = 0; i < lines.length; i++) {
        const line = lines[i];
        
        if (line.startsWith('|') && line.endsWith('|')) {
            if (!inTable) {
                processedLines.push('<table class="monthly-table">');
                inTable = true;
            }
            
            // 헤더 라인 건너뛰기 (|------|)
            if (line.includes('---')) {
                continue;
            }
            
            const cells = line.split('|').slice(1, -1); // 첫 번째와 마지막 빈 엘리먼트 제거
            const isHeader = i === 0 || processedLines[processedLines.length - 1] === '<table class="monthly-table">';
            
            if (isHeader) {
                processedLines.push('<thead><tr>');
                cells.forEach(cell => {
                    processedLines.push(`<th>${cell.trim()}</th>`);
                });
                processedLines.push('</tr></thead><tbody>');
            } else {
                processedLines.push('<tr>');
                cells.forEach(cell => {
                    processedLines.push(`<td>${cell.trim()}</td>`);
                });
                processedLines.push('</tr>');
            }
        } else {
            if (inTable) {
                processedLines.push('</tbody></table>');
                inTable = false;
            }
            processedLines.push(line);
        }
    }
    
    if (inTable) {
        processedLines.push('</tbody></table>');
    }
    
    html = processedLines.join('\n');
    
    // 단락 변환
    html = html.replace(/\n\n/g, '</p><p>');
    html = '<p>' + html + '</p>';
    html = html.replace(/<p><\/p>/g, '');
    html = html.replace(/<p>(<h[1-6]>)/g, '$1');
    html = html.replace(/(<\/h[1-6]>)<\/p>/g, '$1');
    html = html.replace(/<p>(<table)/g, '$1');
    html = html.replace(/(<\/table>)<\/p>/g, '$1');
    
    return html;
}

// Event details modal
function showEventDetails(event) {
    const modal = document.getElementById('event-modal');
    const modalTitle = document.getElementById('modal-title');
    const modalBody = document.getElementById('modal-body');
    
    modalTitle.textContent = event.title;
    
    let detailsHtml = `
        <div class="detail-item">
            <strong>이름:</strong> ${escapeHtml(event.name)}
        </div>
        <div class="detail-item">
            <strong>날짜:</strong> ${event.date}
        </div>
        <div class="detail-item">
            <strong>시간:</strong> ${event.time}
        </div>
        <div class="detail-item">
            <strong>시트:</strong> ${escapeHtml(event.sheet_name)}
        </div>
    `;
    
    // Add all available details from the sheet
    if (event.details) {
        for (const [key, value] of Object.entries(event.details)) {
            if (value && value.toString().trim()) {
                detailsHtml += `
                    <div class="detail-item">
                        <strong>${escapeHtml(key)}:</strong> ${escapeHtml(value.toString())}
                    </div>
                `;
            }
        }
    }
    
    modalBody.innerHTML = detailsHtml;
    modal.classList.add('show');
}

function closeModal() {
    const modal = document.getElementById('event-modal');
    modal.classList.remove('show');
}

// Close modal when clicking outside
document.getElementById('event-modal').addEventListener('click', function(e) {
    if (e.target === this) {
        closeModal();
    }
});

// Loading indicator
function showLoading(show) {
    const loading = document.getElementById('calendar-loading');
    const calendar = document.getElementById('calendar');
    
    if (show) {
        loading.classList.add('show');
        calendar.style.display = 'none';
    } else {
        loading.classList.remove('show');
        calendar.style.display = 'block';
    }
}

// 병원별 색상 반환 함수
function getHospitalColor(hospitalName) {
    if (!hospitalName) return '#999999';
    
    const hospitalColors = {
        '라비앙성형외과': '#FF4757',
        '트랜드성형외과': '#2ED573',
        '황금피부과': '#FFA502',
        '셀나인청담': '#3742FA',
        '스텔라': '#FF6B9D',
        '뉴브의원': '#5F27CD',
        '엘투투': '#FF3838',
        '케이블린필러': '#FFDD59',
        '쥬브겔필러': '#C44569'
    };
    
    // 병원명에서 키워드 찾기
    for (const [keyword, color] of Object.entries(hospitalColors)) {
        if (hospitalName.includes(keyword.replace('성형외과', '')) || 
            hospitalName.includes(keyword.replace('피부과', '')) ||
            hospitalName.includes(keyword.replace('청담', '')) ||
            hospitalName.includes(keyword)) {
            return color;
        }
    }
    
    // 특별 키워드들
    if (hospitalName.includes('라비앙')) return '#FF4757';
    if (hospitalName.includes('트랜드')) return '#2ED573';
    if (hospitalName.includes('황금')) return '#FFA502';
    if (hospitalName.includes('셀나인') || hospitalName.includes('제네오엑스')) return '#3742FA';
    if (hospitalName.includes('스텔라')) return '#FF6B9D';
    if (hospitalName.includes('뉴브')) return '#5F27CD';
    if (hospitalName.includes('엘투투') || hospitalName.includes('M2M')) return '#FF3838';
    if (hospitalName.includes('케이블린')) return '#FFDD59';
    if (hospitalName.includes('쥬브겔')) return '#C44569';
    
    // 기본 색상
    return '#999999';
}

// Utility functions
function escapeHtml(text) {
    const map = {
        '&': '&amp;',
        '<': '&lt;',
        '>': '&gt;',
        '"': '&quot;',
        "'": '&#039;'
    };
    return text.replace(/[&<>"']/g, function(m) { return map[m]; });
}

// Touch events for mobile
let touchStartX = 0;
let touchEndX = 0;

document.addEventListener('touchstart', function(e) {
    touchStartX = e.changedTouches[0].screenX;
});

document.addEventListener('touchend', function(e) {
    touchEndX = e.changedTouches[0].screenX;
    handleSwipe();
});

function handleSwipe() {
    const swipeThreshold = 50;
    const diff = touchStartX - touchEndX;
    
    if (Math.abs(diff) > swipeThreshold) {
        if (diff > 0) {
            // Swipe left - next month
            changeMonth(1);
        } else {
            // Swipe right - previous month
            changeMonth(-1);
        }
    }
}

// Keyboard navigation
document.addEventListener('keydown', function(e) {
    if (e.key === 'ArrowLeft') {
        changeMonth(-1);
    } else if (e.key === 'ArrowRight') {
        changeMonth(1);
    } else if (e.key === 'Escape') {
        closeModal();
    }
});

// Auto refresh events every 5 minutes
setInterval(loadEvents, 5 * 60 * 1000);

// Check auth status every 30 seconds
setInterval(checkAuthStatus, 30 * 1000);

// Tooltip functionality
let tooltipElement = null;

function createTooltip() {
    if (!tooltipElement) {
        tooltipElement = document.createElement('div');
        tooltipElement.className = 'event-tooltip';
        document.body.appendChild(tooltipElement);
    }
    return tooltipElement;
}

function showTooltip(event, content) {
    const tooltip = createTooltip();
    tooltip.innerHTML = content;
    tooltip.style.display = 'block';
    tooltip.style.opacity = '0';
    
    // Position tooltip
    updateTooltipPosition(event);
    
    // Fade in
    setTimeout(() => {
        tooltip.style.opacity = '1';
    }, 10);
}

function hideTooltip() {
    if (tooltipElement) {
        tooltipElement.style.opacity = '0';
        setTimeout(() => {
            tooltipElement.style.display = 'none';
        }, 200);
    }
}

function updateTooltipPosition(event) {
    if (!tooltipElement || tooltipElement.style.display === 'none') return;
    
    const tooltip = tooltipElement;
    const rect = tooltip.getBoundingClientRect();
    const viewportWidth = window.innerWidth;
    const viewportHeight = window.innerHeight;
    
    let x = event.pageX + 10;
    let y = event.pageY + 10;
    
    // Adjust if tooltip would go off screen
    if (x + rect.width > viewportWidth) {
        x = event.pageX - rect.width - 10;
    }
    
    if (y + rect.height > viewportHeight) {
        y = event.pageY - rect.height - 10;
    }
    
    tooltip.style.left = x + 'px';
    tooltip.style.top = y + 'px';
}
