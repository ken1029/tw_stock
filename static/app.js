// (全域變數)
let fetchInterval;
const UPDATE_INTERVAL = 5000;
let isFetching = false;
let backfillPollInterval = null;
const loadingSpinner = document.getElementById('loading-spinner');
let stockModal = null;
let currentPortfolioData = [];
let historyChart = null;
let previousStockData = {};
let previousTotals = {};
let historicalDailyData = {};
let currentSortKey = 'market_value';
let currentSortDirection = 'desc';
let currentRange = 'MTD';
let currentPerformanceType = 'total'; // 新增：績效類型 (total, tw, cn)
let currentCnyRate = 1.0;
let columnVisibility = {};
let stockCharts = {}; // 儲存個股圖表實例

// (格式化工具)
const currencyFormatter = new Intl.NumberFormat('zh-TW', {
    style: 'currency',
    currency: 'TWD',
    maximumFractionDigits: 0, 
    minimumFractionDigits: 0
});
const chartCurrencyFormatter = new Intl.NumberFormat('zh-TW', {
    style: 'currency',
    currency: 'TWD',
    maximumFractionDigits: 2, 
    minimumFractionDigits: 2
});
const numberFormatter = new Intl.NumberFormat('en-US', {
    maximumFractionDigits: 2,
    minimumFractionDigits: 2
});
const percentFormatter = new Intl.NumberFormat('zh-TW', {
    style: 'percent',
    minimumFractionDigits: 2,
    maximumFractionDigits: 2
});

// (新) 產生資料來源的標籤
function getSourceBadge(source) {
    if (source === 'MIS') return '<span class="badge bg-source-mis">MIS</span>';
    if (source === 'Sina') return '<span class="badge bg-source-sina">Sina</span>';
    if (source === 'yfinance') return '<span class="badge bg-source-yf">yfinance</span>';
    return '<span class="badge bg-source-na">N/A</span>';
}

function getPlClass(value) {
    if (value > 0) return 'text-danger'; 
    if (value < 0) return 'text-success'; 
    return 'text-dark';
}

function getChangeClass(newValue, oldValue) {
    if (typeof oldValue === 'undefined' || newValue === oldValue) {
        return '';
    }
    return newValue > oldValue ? 'flash-up' : 'flash-down'; 
}

function applyFlashEffect(element, newValue, oldValue) {
    if (typeof oldValue === 'undefined' || newValue === oldValue || !element) {
        return;
    }
    const changeClass = newValue > oldValue ? 'flash-up' : 'flash-down';
    element.classList.add(changeClass);
    setTimeout(() => element.classList.remove('flash-up', 'flash-down'), 1000);
}

function animateCountUp(element, endVal, previousVal, formatter) {
    if (!element) return;

    // 檢查 countUp 函式庫是否載入
    if (typeof countUp === 'undefined' || typeof countUp.CountUp === 'undefined') {
        console.warn('CountUp.js library not loaded. Skipping animation.');
        const formattedValue = (formatter === percentFormatter)
            ? formatter.format(endVal / 100)
            : formatter.format(endVal);
        element.textContent = formattedValue;
        return;
    }

    const startVal = previousVal || 0;
    
    // [修正] 自動偵測格式化器的小數位數設定
    let decimalPlaces = 0;
    if (formatter && formatter.resolvedOptions) {
        decimalPlaces = formatter.resolvedOptions().maximumFractionDigits || 0;
    }

    const options = {
        startVal: startVal,
        duration: 1.5,
        useEasing: true,
        separator: ',',
        decimal: '.',
        decimalPlaces: decimalPlaces, // [關鍵修正] 顯式指定小數位數，避免被取整為整數
        formattingFn: (n) => {
            // 對於百分比，CountUp 傳入的是乘過 100 的數值(例如 2.5)，
            // 但 formatter.format (percentFormatter) 期望的是 0.025
            if (formatter === percentFormatter) {
                return formatter.format(n / 100);
            }
            return formatter.format(n);
        }
    };

    // 實例化並執行
    const anim = new countUp.CountUp(element, endVal, options);
    if (!anim.error) {
        anim.start();
    } else {
        console.error(anim.error);
        // 發生錯誤時的備用顯示
        element.textContent = options.formattingFn(endVal);
    }
}


// 通用的帶重試機制的 fetch 函數
async function fetchWithRetry(url, options = {}, attempt = 0) {
    const MAX_RETRIES = 150;
    const RETRY_DELAY = 2000; // 2秒
    const FETCH_TIMEOUT = 10000; // 10秒超時
    
    // 獲取連線狀態元素
    const statusEl = document.getElementById('connection-status');
    const messageEl = document.getElementById('connection-message');
    const retryCountEl = document.getElementById('retry-count');
    
    // 創建帶有超時的 fetch 請求
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), FETCH_TIMEOUT);
    
    try {
        const response = await fetch(url, { ...options, signal: controller.signal });
        clearTimeout(timeoutId); // 清除超時
        
        if (!response.ok) {
            throw new Error(`Network response was not ok (${response.status})`);
        }
        
        // 隱藏連線狀態（成功時）
        if (statusEl) statusEl.style.display = 'none';
        return response;
    } catch (error) {
        clearTimeout(timeoutId); // 確保清除超時
        console.error(`Error fetching ${url}:`, error);
        
        // 檢查是否為超時錯誤
        if (error.name === 'AbortError') {
            // 如果還有重試機會，進行重試
            if (attempt < MAX_RETRIES) {
                // 顯示重試狀態
                if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.className = 'connection-status alert alert-warning';
                    messageEl.textContent = '連線超時，正在重新嘗試...';
                    retryCountEl.textContent = `${attempt + 1}/${MAX_RETRIES}`;
                }
                
                console.log(`Retrying fetch ${url} due to timeout... (${attempt + 1}/${MAX_RETRIES})`);
                
                // 設置延遲後重試
                await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
                return await fetchWithRetry(url, options, attempt + 1);
            } else {
                // 顯示最終錯誤狀態
                if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.className = 'connection-status alert alert-danger';
                    messageEl.textContent = '連線超時，請檢查網路連線';
                    retryCountEl.textContent = `${MAX_RETRIES}/${MAX_RETRIES}`;
                }
                
                console.error(`Max retries exceeded due to timeout for ${url}.`);
                
                throw new Error("請求超時，無法加載數據");
            }
        } else {
            // 其他錯誤
            // 如果還有重試機會，進行重試
            if (attempt < MAX_RETRIES) {
                // 顯示重試狀態
                if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.className = 'connection-status alert alert-warning';
                    messageEl.textContent = '連線失敗，正在重新嘗試...';
                    retryCountEl.textContent = `${attempt + 1}/${MAX_RETRIES}`;
                }
                
                console.log(`Retrying fetch ${url}... (${attempt + 1}/${MAX_RETRIES})`);
                
                // 設置延遲後重試
                await new Promise(resolve => setTimeout(resolve, RETRY_DELAY));
                return await fetchWithRetry(url, options, attempt + 1);
            } else {
                // 顯示最終錯誤狀態
                if (statusEl) {
                    statusEl.style.display = 'block';
                    statusEl.className = 'connection-status alert alert-danger';
                    
                    // 根據錯誤類型顯示不同的訊息
                    if (error.message.startsWith('Network response was not ok')) {
                        messageEl.textContent = '無法連接到後端服務，請檢查 API 是否正常';
                    } else {
                        messageEl.textContent = '連線失敗，請檢查網路連線';
                    }
                    
                    retryCountEl.textContent = `${MAX_RETRIES}/${MAX_RETRIES}`;
                }
                
                console.error(`Max retries exceeded for ${url}.`);
                
                // 如果是 HTTP 錯誤，嘗試獲取伺服器返回的錯誤訊息
                if (error.message.startsWith('Network response was not ok')) {
                    throw new Error("無法連接到後端服務，請檢查 API 是否正常");
                }
                
                throw error;
            }
        }
    }
}

// 新增重試機制的 fetchPortfolio 函數
async function fetchPortfolio() {
    if (isFetching) {
        return;
    }
    isFetching = true;
    
    // 顯示加載指示器
    if (loadingSpinner) loadingSpinner.style.display = 'block';
    
    try {
        const response = await fetchWithRetry('/api/portfolio');
        const data = await response.json();
        updateTotals(data.totals);
        updateTable(data.stocks);
    } catch (error) {
        console.error('Error fetching portfolio:', error);
        stopFetching();
        alert("抓取資料失敗，請檢查後端服務是否開啟，或 API 是否正常。");
    } finally {
        // 隱藏加載指示器
        if (loadingSpinner) loadingSpinner.style.display = 'none';
        
        isFetching = false;
        const lastUpdatedEl = document.getElementById('last-updated');
        lastUpdatedEl.textContent = `最後更新: ${new Date().toLocaleTimeString('zh-TW')}`;
        lastUpdatedEl.style.display = 'inline';
    }
}

// (updateTotals - 包含 "新卡片" 的邏輯)
function updateTotals(totals) {
    currentCnyRate = totals.cny_rate || 1.0;

    // --- (修改) 使用數字滾動動畫 ---
    animateCountUp(document.getElementById('total-market-value'), totals.market_value, previousTotals.market_value, currencyFormatter);
    animateCountUp(document.getElementById('total-cost-basis'), totals.cost_basis, previousTotals.cost_basis, currencyFormatter);
    animateCountUp(document.getElementById('total-pl'), totals.pl, previousTotals.pl, currencyFormatter);
    animateCountUp(document.getElementById('total-pl-percent'), totals.pl_percent, previousTotals.pl_percent, percentFormatter);
    animateCountUp(document.getElementById('tw-market-value'), totals.tw_value, previousTotals.tw_value, currencyFormatter);
    animateCountUp(document.getElementById('cn-market-value'), totals.cn_value, previousTotals.cn_value, currencyFormatter);
    
    // --- (新增) 更新人民幣匯率顯示 ---
    const cnyRate = totals.cny_rate || 4.4;
    animateCountUp(document.getElementById('cny-rate'), cnyRate, previousTotals.cny_rate, numberFormatter);
    
    const todayPlTotal = totals.daily_diff || 0;
    const todayPlPercent = totals.daily_diff_percent || 0;

    animateCountUp(document.getElementById('daily-summary-diff'), todayPlTotal, previousTotals.today_pl, currencyFormatter);
    animateCountUp(document.getElementById('daily-summary-percent'), todayPlPercent, previousTotals.today_pl_percent, percentFormatter);


    // --- (保留) 更新顏色和輔助文字 ---
    const totalPlEl = document.getElementById('total-pl');
    const totalPlClass = getPlClass(totals.pl);
    totalPlEl.className = `text-nowrap ${totalPlClass}`;
    
    const totalPlPercentEl = document.getElementById('total-pl-percent');
    totalPlPercentEl.className = totalPlClass;

    document.getElementById('last-close-value').textContent = `(${currencyFormatter.format(totals.last_close_value)})`;
    
    const dailyDiffEl = document.getElementById('daily-summary-diff');
    const dailyPercentEl = document.getElementById('daily-summary-percent');
    const dailyClass = getPlClass(todayPlTotal);
    dailyDiffEl.className = dailyClass;
    dailyPercentEl.className = dailyClass;
    
    // --- 更新 previousTotals ---
    previousTotals = {
        market_value: totals.market_value,
        cost_basis: totals.cost_basis,
        pl: totals.pl,
        pl_percent: totals.pl_percent,
        today_pl: totals.daily_diff,
        today_pl_percent: todayPlPercent,
        tw_value: totals.tw_value,
        cn_value: totals.cn_value,
        cny_rate: cnyRate
    };
    
    // --- 檢查是否觸發閃爍通知 ---
    checkAndTriggerNotification(totals.pl_percent, totals.pl);
    
    // --- 檢查市值閃爍通知 ---
    checkMarketValueNotification(totals.market_value, 'total');
    checkMarketValueNotification(totals.tw_value, 'tw');
    checkMarketValueNotification(totals.cn_value, 'cn');
}

// --- 閃爍通知功能 ---
function checkAndTriggerNotification(plPercent, plValue) {
    const settings = loadSettings();
    
    // 檢查是否啟用了通知功能
    if (!settings.enableNotifications) {
        // 如果之前有閃爍效果，則移除
        const totalPlPercentElement = document.getElementById('total-pl-percent');
        const totalPlElement = document.getElementById('total-pl');
        if (totalPlPercentElement && totalPlPercentElement.classList.contains('flash-threshold-exceeded')) {
            totalPlPercentElement.classList.remove('flash-threshold-exceeded');
        }
        if (totalPlElement && totalPlElement.classList.contains('flash-threshold-exceeded')) {
            totalPlElement.classList.remove('flash-threshold-exceeded');
        }
        return;
    }
    
    // 檢查總報酬率通知設定
    const plPercentThreshold = settings.plPercentNotificationThreshold || 1.0;
    const totalPlPercentElement = document.getElementById('total-pl-percent');
    
    if (settings.enablePlPercentNotification && Math.abs(plPercent) >= plPercentThreshold) {
        // 添加閃爍效果到總報酬率元素
        if (totalPlPercentElement && !totalPlPercentElement.classList.contains('flash-threshold-exceeded')) {
            totalPlPercentElement.classList.add('flash-threshold-exceeded');
        }
    } else {
        // 移除總報酬率的閃爍效果
        if (totalPlPercentElement && totalPlPercentElement.classList.contains('flash-threshold-exceeded')) {
            totalPlPercentElement.classList.remove('flash-threshold-exceeded');
        }
    }
    
    // 檢查總損益通知設定
    const plThreshold = settings.plNotificationThreshold || 1000;
    const totalPlElement = document.getElementById('total-pl');
    
    if (settings.enablePlNotification && Math.abs(plValue) >= plThreshold) {
        // 添加閃爍效果到總損益元素
        if (totalPlElement && !totalPlElement.classList.contains('flash-threshold-exceeded')) {
            totalPlElement.classList.add('flash-threshold-exceeded');
        }
    } else {
        // 移除總損益的閃爍效果
        if (totalPlElement && totalPlElement.classList.contains('flash-threshold-exceeded')) {
            totalPlElement.classList.remove('flash-threshold-exceeded');
        }
    }
}

// --- 市值閃爍通知功能 ---
function checkMarketValueNotification(marketValue, type) {
    const settings = loadSettings();
    
    // 檢查是否啟用了通知功能
    if (!settings.enableNotifications) {
        // 如果之前有閃爍效果，則移除
        let element = null;
        if (type === 'total') {
            element = document.getElementById('total-market-value');
        } else if (type === 'tw') {
            element = document.getElementById('tw-market-value');
        } else if (type === 'cn') {
            element = document.getElementById('cn-market-value');
        }
        
        if (element && element.classList.contains('flash-threshold-exceeded')) {
            element.classList.remove('flash-threshold-exceeded');
        }
        return;
    }
    
    let threshold = 0;
    let isEnabled = false;
    let element = null;
    
    if (type === 'total') {
        threshold = settings.marketValueNotificationThreshold || 1000000;
        isEnabled = settings.enableMarketValueNotification;
        element = document.getElementById('total-market-value');
    } else if (type === 'tw') {
        threshold = settings.twMarketValueNotificationThreshold || 500000;
        isEnabled = settings.enableTwMarketValueNotification;
        element = document.getElementById('tw-market-value');
    } else if (type === 'cn') {
        threshold = settings.cnMarketValueNotificationThreshold || 500000;
        isEnabled = settings.enableCnMarketValueNotification;
        element = document.getElementById('cn-market-value');
    }
    
    // 檢查市值是否超過閾值
    if (isEnabled && marketValue >= threshold) {
        // 添加閃爍效果到對應的元素
        if (element && !element.classList.contains('flash-threshold-exceeded')) {
            element.classList.add('flash-threshold-exceeded');
        }
    } else {
        // 移除閃爍效果
        if (element && element.classList.contains('flash-threshold-exceeded')) {
            element.classList.remove('flash-threshold-exceeded');
        }
    }
}

// (updateTable - 包含 "試算" 邏輯)
function updateTable(stocks) {
    // 1. 排序資料陣列 (這是我們 "真實的順序")
    const sortedStocks = stocks.slice().sort((a, b) => {
        const valA = a[currentSortKey];
        const valB = b[currentSortKey];
        if (typeof valA === 'string') {
            return currentSortDirection === 'asc'
                ? valA.localeCompare(valB)
                : valB.localeCompare(valA);
        }
        return currentSortDirection === 'asc' ? valA - valB : valB - valA;
    });

    updateSortIndicators();
    
    currentPortfolioData = sortedStocks;
    const tableBody = document.getElementById('portfolio-table-body');
    const newStockData = {};

    // 2. 將所有 "現存" 的 DOM 列放入 Map 中，以便快速查找
    //    我們同時儲存 "資料列" 和 "圖表列"
    const existingRowsMap = new Map();
    tableBody.querySelectorAll('tr[data-ticker]').forEach(row => {
        const ticker = row.dataset.ticker;
        existingRowsMap.set(ticker, row);
    });

    // 3. 處理 "初始載入中" 或 "空狀態"
    const initialSpinnerRow = tableBody.querySelector('td > .spinner-border');
    if (initialSpinnerRow) {
        initialSpinnerRow.closest('tr').remove();
    }

    if (sortedStocks.length === 0 && existingRowsMap.size === 0) {
        if (!tableBody.querySelector('.empty-row')) {
            tableBody.innerHTML = `
                <tr class="empty-row">
                    <td colspan="15" class="text-center p-5">
                        <div class="empty-state-container">
                            <i class="bi bi-clipboard-data" style="font-size: 3rem; color: var(--muted-text);"></i>
                            <h4 class="mt-3">尚未新增任何持股</h4>
                            <p class="mb-4">點擊下方「新增持股」按鈕開始建立您的投資組合</p>
                            <button class="btn btn-primary" id="empty-state-add-btn">
                                <i class="bi bi-plus-circle-fill me-1"></i> 新增持股
                            </button>
                        </div>
                    </td>
                </tr>
            `;
            const emptyStateAddBtn = document.getElementById('empty-state-add-btn');
            if (emptyStateAddBtn) {
                emptyStateAddBtn.addEventListener('click', openModalForAdd);
            }
        }
        return;
    } else if (sortedStocks.length > 0 && tableBody.querySelector('.empty-row')) {
        tableBody.innerHTML = ''; // 移除"尚未新增"的訊息
    }

    // 4. --- 核心協調邏輯 ---
    //    我們遍歷 "已排序的資料"，並確保 DOM 順序與之一致
    
    let currentDomIndex = 0; // 追蹤我們期望的 DOM 位置 (每支股票佔 2 列)
    
    sortedStocks.forEach((stock, index) => {
        const oldStockData = previousStockData[stock.ticker] || {};
        const rowTicker = stock.ticker;
        const chartTicker = `${stock.ticker}-chart`;
        
        let row = existingRowsMap.get(rowTicker);
        let chartRow = existingRowsMap.get(chartTicker);

        // 取得 "目前" 在這個 DOM 位置上的元素
        // tableBody.children 是一個 "即時" 的 HTMLCollection
        const nodeAtCurrentIndex = tableBody.children[currentDomIndex];

        if (row && chartRow) {
            // --- A. 股票已存在 ---
            
            // 1. (智慧更新) 僅更新內容，並應用閃爍效果
            updateRowContent(row, stock, oldStockData);
            
            // 2. (智慧移動) 檢查 DOM 位置是否正確
            //    如果 "目前" 在這個位置的元素 (nodeAtCurrentIndex) 不是 "我們期望" 的元素 (row)，
            //    就代表順序錯了，我們需要 "移動" DOM。
            if (nodeAtCurrentIndex !== row) {
                // 使用 insertBefore 來移動 DOM
                tableBody.insertBefore(row, nodeAtCurrentIndex);
                // 緊接著移動它的圖表列，插入到 "資料列" 的 "下一個兄弟" 之前
                tableBody.insertBefore(chartRow, row.nextSibling);
            }
            
            // 3. 這兩列 (資料+圖表) 已處理完畢，標記為已使用
            currentDomIndex += 2;
            existingRowsMap.delete(rowTicker);
            existingRowsMap.delete(chartTicker);

        } else {
            // --- B. 這是新股票 ---
            
            // 1. 建立新的 DOM 元素
            const newRow = createRow(stock, oldStockData);
            const newChartRow = createStockChartContainer(stock.ticker);
            
            // 2. 將它們插入到 "目前" 的 DOM 位置
            //    (如果 nodeAtCurrentIndex 是 null (即末尾)，insertBefore 會自動變成 appendChild)
            tableBody.insertBefore(newRow, nodeAtCurrentIndex);
            tableBody.insertBefore(newChartRow, newRow.nextSibling);

            // 3. 這兩個新元素佔據了 DOM 位置
            currentDomIndex += 2;
        }
        
        // (儲存資料，供下次閃爍比對)
        newStockData[stock.ticker] = {
            current_price: stock.current_price,
            today_pl: stock.today_pl,
            market_value: stock.market_value
        };
    });

    // 5. --- 清理 ---
    //    在 Map 中 "剩下" 的所有列，都是在 sortedStocks 中不存在的 (即被刪除的股票)
    existingRowsMap.forEach((row, ticker) => {
        // 如果是圖表列，先銷毀圖表實例
        if (ticker.endsWith('-chart')) {
            const stockTicker = ticker.replace('-chart', '');
            if (stockCharts[stockTicker]) {
                stockCharts[stockTicker].destroy();
                delete stockCharts[stockTicker];
            }
        }
        // 從 DOM 中移除
        row.remove();
    });

    previousStockData = newStockData;
}

function createRow(stock, oldStockData) {
    const row = document.createElement('tr');
    row.dataset.ticker = stock.ticker;
    row.classList.add('fade-in-row');

    const trialContent = `
        <input type="number" step="0.01" class="form-control form-control-sm trial-input"
               data-ticker="${stock.ticker}"
               placeholder="目標價 (${stock.currency})">
        <div class="trial-result" id="trial-result-${stock.ticker}" style="display: none;"></div>
    `;
    const chartButtonContent = `
        <button class="btn btn-sm btn-outline-secondary chart-btn" data-ticker="${stock.ticker}" title="歷史價格圖表">
          <i class="bi bi-graph-up"></i>
        </button>
    `;
    const buttonsContent = `
        <button class="btn btn-sm btn-outline-primary edit-btn" data-ticker="${stock.ticker}" title="編輯">
          <i class="bi bi-pencil-fill"></i>
        </button>
        <button class="btn btn-sm btn-outline-danger delete-btn" data-ticker="${stock.ticker}" data-name="${stock.name}" title="刪除">
          <i class="bi bi-trash-fill"></i>
        </button>
    `;
    
    row.innerHTML = `
        <td data-key="data_source"></td>
        <td data-key="ticker"></td>
        <td data-key="name"></td>
        <td data-key="shares"></td>
        <td data-key="avg_cost"></td>
        <td data-key="current_price" class="price-cell"></td>
        <td data-key="previous_close"></td>
        <td data-key="change_percent"></td>
        <td data-key="market_value" class="market-value-cell"></td>
        <td data-key="today_pl" class="today-pl-cell"></td>
        <td data-key="pl"></td>
        <td data-key="pl_percent"></td>
        <td data-key="what_if">${trialContent}</td>
        <td data-key="chart" class="text-center">${chartButtonContent}</td>
        <td data-key="actions" class="text-nowrap">${buttonsContent}</td>
    `;
    
    updateRowContent(row, stock, oldStockData);
    return row;
}

// --- (新) 個股歷史價格圖表功能 --- 帶重試機制
async function fetchStockHistory(ticker) {
    try {
        const response = await fetchWithRetry(`/api/stock_history/${ticker}`);
        const data = await response.json();
        if (data.status !== "success") {
            throw new Error(data.message || "Failed to fetch stock history");
        }
        return data.history;
    } catch (error) {
        console.error(`Error fetching history for ${ticker}:`, error);
        throw error;
    }
}


function createStockChartContainer(ticker) {
    const container = document.createElement('tr');
    container.classList.add('stock-chart-row');
    container.dataset.ticker = `${ticker}-chart`;
    container.innerHTML = `
        <td colspan="15" class="p-0">
            <div class="collapse" id="chart-collapse-${ticker}">
                <div class="card card-body border-top-0 rounded-0">
                    <canvas id="stock-chart-${ticker}"></canvas>
                </div>
            </div>
        </td>
    `;
    return container;
}

async function toggleStockChart(event) {
    const button = event.target.closest('.chart-btn');
    const ticker = button.dataset.ticker;
    const chartCollapse = document.getElementById(`chart-collapse-${ticker}`);
    
    // 如果圖表已經展開，則收合
    if (chartCollapse.classList.contains('show')) {
        // 銷毀圖表實例以釋放資源
        if (stockCharts[ticker]) {
            stockCharts[ticker].destroy();
            delete stockCharts[ticker];
        }
        bootstrap.Collapse.getInstance(chartCollapse)?.hide();
        return;
    }
    
    // 如果圖表尚未加載，則加載數據並創建圖表
    try {
        // 獲取歷史數據（帶重試機制）
        const historyData = await fetchStockHistory(ticker);
        
        // 展開collapse容器
        const collapseInstance = new bootstrap.Collapse(chartCollapse, {
            toggle: true
        });
        
        // 等待容器展開完成後再創建圖表
        chartCollapse.addEventListener('shown.bs.collapse', function onShown() {
            chartCollapse.removeEventListener('shown.bs.collapse', onShown);
            // 添加一個小延遲確保容器完全渲染
            setTimeout(() => {
                renderStockChart(ticker, historyData);
            }, 10);
        }, { once: true });
    } catch (error) {
        console.error('Error toggling stock chart:', error);
        alert(`無法加載 ${ticker} 的歷史數據: ${error.message}`);
    }
}

function renderStockChart(ticker, historyData) {
    const canvas = document.getElementById(`stock-chart-${ticker}`);
    const ctx = canvas.getContext('2d');
    
    // 如果已有圖表實例，先銷毀
    if (stockCharts[ticker]) {
        stockCharts[ticker].destroy();
    }
    
    // 獲取持股數量和貨幣類型
    const stock = currentPortfolioData.find(s => s.ticker === ticker);
    const shares = stock ? stock.shares : 0;
    const currency = stock ? stock.currency : 'TWD';
    
    // 準備圖表數據
    const labels = historyData.map(item => item.date);
    const priceData = historyData.map(item => item.close);
    
    // 計算持有價值時考慮貨幣匯率
    let rate = 1.0;
    if (currency === 'CNY') {
        rate = currentCnyRate;
    }
    const valueData = historyData.map(item => item.close * shares * rate);
    
    // 獲取當前主題設定
    const settings = loadSettings();
    const isDarkTheme = settings.theme === 'dark';
    
    // 設定圖表顏色
    const textColor = isDarkTheme ? '#ffffff' : '#212529';
    const gridColor = isDarkTheme ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
    const tooltipBgColor = isDarkTheme ? 'rgba(255, 255, 255, 0.9)' : 'rgba(0, 0, 0, 0.8)';
    const tooltipTextColor = isDarkTheme ? '#000000' : '#ffffff';
    
    // 創建漸層背景
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, isDarkTheme ? 'rgba(0, 123, 255, 0.6)' : 'rgba(0, 123, 255, 0.4)');
    gradient.addColorStop(1, isDarkTheme ? 'rgba(0, 123, 255, 0.1)' : 'rgba(0, 123, 255, 0)');
    
    // 創建價值數據的漸層背景
    const valueGradient = ctx.createLinearGradient(0, 0, 0, 400);
    valueGradient.addColorStop(0, isDarkTheme ? 'rgba(255, 99, 132, 0.6)' : 'rgba(255, 99, 132, 0.4)');
    valueGradient.addColorStop(1, isDarkTheme ? 'rgba(255, 99, 132, 0.1)' : 'rgba(255, 99, 132, 0)');
    
    // 創建圖表
    stockCharts[ticker] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: [
                {
                    label: `${ticker} 歷史價格`,
                    data: priceData,
                    borderColor: isDarkTheme ? 'rgba(0, 123, 255, 0.8)' : 'rgba(0, 123, 255, 1)',
                    backgroundColor: gradient,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    pointBackgroundColor: isDarkTheme ? 'rgba(0, 123, 255, 0.8)' : 'rgba(0, 123, 255, 1)',
                    borderWidth: 2,
                    yAxisID: 'y-price'
                },
                {
                    label: `${ticker} 持有價值 (TWD)`,
                    data: valueData,
                    borderColor: isDarkTheme ? 'rgba(255, 99, 132, 0.8)' : 'rgba(255, 99, 132, 1)',
                    backgroundColor: valueGradient,
                    fill: true,
                    tension: 0.4,
                    pointRadius: 2,
                    pointHoverRadius: 5,
                    pointBackgroundColor: isDarkTheme ? 'rgba(255, 99, 132, 0.8)' : 'rgba(255, 99, 132, 1)',
                    borderWidth: 2,
                    yAxisID: 'y-value'
                }
            ]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            // 添加這個配置確保圖表在容器尺寸變化時自動調整
            onResize: function(chart, size) {
                chart.canvas.parentNode.style.width = '100%';
            },
            scales: {
                y: {
                    ticks: {
                        color: textColor,
                        callback: function(value) {
                            return numberFormatter.format(value);
                        }
                    },
                    grid: {
                        color: gridColor
                    }
                },
                x: {
                    ticks: {
                        color: textColor,
                        maxTicksLimit: 10
                    },
                    grid: {
                        color: gridColor
                    }
                },
                'y-price': {
                    type: 'linear',
                    display: true,
                    position: 'left',
                    ticks: {
                        color: textColor,
                        callback: function(value) {
                            return numberFormatter.format(value);
                        }
                    },
                    title: {
                        display: true,
                        text: '股價',
                        color: textColor
                    },
                    grid: {
                        color: gridColor
                    }
                },
                'y-value': {
                    type: 'linear',
                    display: true,
                    position: 'right',
                    ticks: {
                        color: textColor,
                        callback: function(value) {
                            return currencyFormatter.format(value);
                        }
                    },
                    title: {
                        display: true,
                        text: '持有價值 (TWD)',
                        color: textColor
                    },
                    grid: {
                        color: gridColor
                    }
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: textColor
                    },
                    display: true
                },
                tooltip: {
                    mode: 'index',
                    intersect: false,
                    backgroundColor: tooltipBgColor,
                    titleColor: tooltipTextColor,
                    bodyColor: tooltipTextColor,
                    titleFont: { size: 14, weight: 'bold' },
                    bodyFont: { size: 12 },
                    padding: 10,
                    cornerRadius: 4,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                if (context.datasetIndex === 0) {
                                    // 股價數據
                                    label += numberFormatter.format(context.parsed.y);
                                } else if (context.datasetIndex === 1) {
                                    // 價值數據
                                    label += currencyFormatter.format(context.parsed.y);
                                }
                            }
                            return label;
                        }
                    }
                }
            }
        }
    });
}

function updateRowContent(row, stock, oldStockData) {
    const priceChangeClass = getChangeClass(stock.current_price, oldStockData.current_price);
    const todayPlFlashClass = getChangeClass(stock.today_pl, oldStockData.today_pl);
    const sourceBadge = getSourceBadge(stock.data_source); // <--- (新) 加入這行
    const marketValueFlashClass = getChangeClass(stock.market_value, oldStockData.market_value);
    const todayPlClass = getPlClass(stock.today_pl);
    const totalPlClass = getPlClass(stock.pl);
    const changePercentClass = getPlClass(stock.change_percent);  // 漲幅顏色類別

    const tickerDisplay = `<strong>${stock.ticker}</strong> ${
            stock.currency !== 'TWD' ? `<span class="badge currency-badge ms-1" data-currency="${stock.currency}">${stock.currency}</span>` : ''
        }`;

    // --- 只更新有變動的內容 ---
    updateCell(row, 'data_source', sourceBadge); // <--- (新) 加入這行
    updateCell(row, 'ticker', tickerDisplay);
    updateCell(row, 'name', stock.name);
    updateCell(row, 'shares', stock.shares.toLocaleString());
    updateCell(row, 'avg_cost', numberFormatter.format(stock.avg_cost));
    updateCell(row, 'current_price', numberFormatter.format(stock.current_price), [priceChangeClass]);
    updateCell(row, 'previous_close', numberFormatter.format(stock.previous_close));
    updateCell(row, 'change_percent', percentFormatter.format(stock.change_percent / 100), [changePercentClass]);  // 新增漲幅顯示
    updateCell(row, 'market_value', currencyFormatter.format(stock.market_value), [marketValueFlashClass]);
    updateCell(row, 'today_pl', currencyFormatter.format(stock.today_pl), [todayPlClass, todayPlFlashClass]);
    updateCell(row, 'pl', currencyFormatter.format(stock.pl), [totalPlClass]);
    updateCell(row, 'pl_percent', percentFormatter.format(stock.pl_percent / 100), [totalPlClass]);
}

function updateCell(row, key, newContent, classes = []) {
    const cell = row.querySelector(`td[data-key="${key}"]`);
    if (!cell) return;

    // 只有在內容真正改變時才更新innerHTML
    if (cell.innerHTML !== newContent) {
        cell.innerHTML = newContent;
    }
    
    // 分離閃爍class和其他class
    const flashClasses = ['flash-up', 'flash-down'];
    const otherClasses = classes.filter(c => c && !flashClasses.includes(c));
    const flashClass = classes.find(c => flashClasses.includes(c));
    
    // 管理非閃爍的CSS class
    const classSet = new Set(cell.classList);
    const toRemove = ['text-danger', 'text-success', 'text-dark'];
    toRemove.forEach(c => classSet.delete(c));
    otherClasses.forEach(c => classSet.add(c));
    
    // 只有在需要時才添加閃爍class
    if (flashClass) {
        classSet.add(flashClass);
        // 設置計時器清除閃爍class
        setTimeout(() => {
            cell.classList.remove('flash-up', 'flash-down');
        }, 1000);
    }
    
    // 避免不必要的 classList 操作
    const newClassName = Array.from(classSet).join(' ');
    if (cell.className !== newClassName) {
       cell.className = newClassName;
    }
}

// (fetchHistorySummary - 讀取 .total)
async function fetchHistorySummary() {
    try {
        const response = await fetchWithRetry('/api/history_summary');
        const data = await response.json();
        
        if (data.daily && Object.keys(data.daily).length > 0) {
            historicalDailyData = data.daily;
            renderHistoryChart(data.daily);
            calculateAndDisplayRange();
        }

    } catch (error) {
        console.error("Error fetching history summary:", error);
        // 顯示錯誤訊息
        const rangeQueryResultEl = document.getElementById('range-query-result');
        if (rangeQueryResultEl) {
            rangeQueryResultEl.textContent = `獲取歷史數據失敗: ${error.message}`;
            rangeQueryResultEl.className = 'alert alert-danger';
            rangeQueryResultEl.style.display = 'block';
        }
    }
}

// (renderHistoryChart - 讀取 .total, .tw_value, .cn_value)
function renderHistoryChart(dailyData) {
    const ctx = document.getElementById('history-chart').getContext('2d');
    
    // 獲取設定
    const settings = loadSettings();
    
    // 處理圖表時間範圍
    const sortedDates = Object.keys(dailyData).sort();
    let filteredDates = sortedDates;
    
    if (settings.chartTimeRange > 0) {
        // 只取最近 chartTimeRange 天的資料
        filteredDates = sortedDates.slice(-settings.chartTimeRange);
    }
    
    const labels = filteredDates;
    
    const totalData = [];
    const twData = [];
    const cnData = [];

    filteredDates.forEach(date => {
        const data = dailyData[date];
        if (typeof data === 'object' && data !== null) {
            totalData.push(data.total);
            twData.push(data.tw_value);
            cnData.push(data.cn_value);
        } else {
            totalData.push(data);
            twData.push(null);
            cnData.push(null);
        }
    });
    
    if (historyChart) {
        historyChart.destroy();
    }

    // 獲取當前主題設定
    const themeSettings = loadSettings();
    const isDarkTheme = themeSettings.theme === 'dark';
    
    // --- (新增) 漸層背景 ---
    const gradient = ctx.createLinearGradient(0, 0, 0, 400);
    gradient.addColorStop(0, isDarkTheme ? 'rgba(0, 123, 255, 0.6)' : 'rgba(0, 123, 255, 0.4)');
    gradient.addColorStop(1, isDarkTheme ? 'rgba(0, 123, 255, 0.1)' : 'rgba(0, 123, 255, 0)');
    
    // 設定圖表顏色
    const textColor = isDarkTheme ? '#ffffff' : '#212529';
    const gridColor = isDarkTheme ? 'rgba(255, 255, 255, 0.1)' : 'rgba(0, 0, 0, 0.1)';
    const tooltipBgColor = isDarkTheme ? 'rgba(255, 255, 255, 0.9)' : 'rgba(0, 0, 0, 0.8)';
    const tooltipTextColor = isDarkTheme ? '#000000' : '#ffffff';
    
    // 準備圖表數據集，根據設定決定是否顯示
    const datasets = [];
    
    // 總資產系列
    if (themeSettings.showTotalSeries !== false) {
        datasets.push({
            label: '總資產 (TWD)',
            data: totalData,
            borderColor: isDarkTheme ? 'rgba(0, 123, 255, 0.8)' : 'rgba(0, 123, 255, 1)',
            backgroundColor: gradient, // 使用漸層
            fill: true,
            tension: 0.4, // 更平滑的曲線
            pointRadius: 2,
            pointHoverRadius: 7,
            pointBackgroundColor: isDarkTheme ? 'rgba(0, 123, 255, 0.8)' : 'rgba(0, 123, 255, 1)',
            borderWidth: 2.5
        });
    }
    
    // 台灣股票系列
    if (themeSettings.showTwSeries !== false) {
        datasets.push({
            label: '台灣股票 (TWD)',
            data: twData,
            borderColor: isDarkTheme ? 'rgba(25, 135, 84, 0.8)' : 'rgba(25, 135, 84, 1)',
            backgroundColor: isDarkTheme ? 'rgba(25, 135, 84, 0.2)' : 'rgba(25, 135, 84, 0.1)',
            fill: false,
            tension: 0.4,
            pointRadius: 2,
            pointHoverRadius: 7,
            borderWidth: 1.5
        });
    }
    
    // 中國股票系列
    if (themeSettings.showCnSeries !== false) {
        datasets.push({
            label: '中國股票 (TWD)',
            data: cnData,
            borderColor: isDarkTheme ? 'rgba(220, 53, 69, 0.8)' : 'rgba(220, 53, 69, 1)',
            backgroundColor: isDarkTheme ? 'rgba(220, 53, 69, 0.2)' : 'rgba(220, 53, 69, 0.1)',
            fill: false,
            tension: 0.4,
            pointRadius: 2,
            pointHoverRadius: 7,
            borderWidth: 1.5
        });
    }
    
    historyChart = new Chart(ctx, {
        type: 'line',
        data: {
            labels: labels,
            datasets: datasets
        },
        options: {
            responsive: true,
            maintainAspectRatio: true,
            scales: {
                y: {
                    ticks: {
                        color: textColor,
                        callback: function(value, index, values) {
                            return currencyFormatter.format(value);
                        }
                    },
                    grid: {
                        color: gridColor
                    }
                },
                x: {
                    ticks: {
                        color: textColor,
                        maxTicksLimit: 10
                    },
                    grid: {
                        color: gridColor
                    }
                }
            },
            plugins: {
                legend: {
                    labels: {
                        color: textColor
                    },
                    // --- (新增) 讓圖例可以點擊 ---
                    onClick: (e, legendItem, legend) => {
                        const index = legendItem.datasetIndex;
                        const ci = legend.chart;
                        if (ci.isDatasetVisible(index)) {
                            ci.hide(index);
                            legendItem.hidden = true;
                        } else {
                            ci.show(index);
                            legendItem.hidden = false;
                        }
                    }
                },
                tooltip: {
                    // --- (新增) 美化提示框 ---
                    mode: 'index',
                    intersect: false,
                    backgroundColor: tooltipBgColor,
                    titleColor: tooltipTextColor,
                    bodyColor: tooltipTextColor,
                    titleFont: { size: 14, weight: 'bold' },
                    bodyFont: { size: 12 },
                    padding: 10,
                    cornerRadius: 4,
                    callbacks: {
                        label: function(context) {
                            let label = context.dataset.label || '';
                            if (label) {
                                label += ': ';
                            }
                            if (context.parsed.y !== null) {
                                label += currencyFormatter.format(context.parsed.y);
                            }
                            return label;
                        }
                    }
                }
            }
        }
    });
}

// (startFetching, stopFetching, CRUD 函式 ... 保持不變)
function startFetching() {
    fetchPortfolio(); 
    fetchInterval = setInterval(fetchPortfolio, UPDATE_INTERVAL);
}
function stopFetching() {
    clearInterval(fetchInterval);
}
function openModalForAdd() {
    document.getElementById('stock-form').reset();
    document.getElementById('stock-modal-label').textContent = '新增持股';
    document.getElementById('stock-modal-mode').value = 'add';
    document.getElementById('stock-modal-ticker').readOnly = false;
    document.getElementById('stock-modal-currency').value = 'TWD';
    stockModal.show();
}
function openModalForEdit(event) {
    const ticker = event.target.closest('button').dataset.ticker;
    const stock = currentPortfolioData.find(s => s.ticker === ticker);
    if (!stock) return;
    document.getElementById('stock-modal-label').textContent = `編輯持股: ${stock.name}`;
    document.getElementById('stock-modal-mode').value = 'edit';
    document.getElementById('stock-modal-ticker').value = stock.ticker;
    document.getElementById('stock-modal-ticker').readOnly = true;
    document.getElementById('stock-modal-shares').value = stock.shares;
    document.getElementById('stock-modal-avg-cost').value = stock.avg_cost;
    document.getElementById('stock-modal-currency').value = stock.currency;
    document.getElementById('stock-modal-name').value = stock.name;
    stockModal.show();
}
async function handleDelete(event) {
    const button = event.target.closest('button');
    const ticker = button.dataset.ticker;
    const name = button.dataset.name;
    if (!confirm(`您確定要刪除 [${name}] (${ticker}) 嗎？此操作無法復原。`)) {
        return;
    }
    
    // 嘗試刪除數據（帶重試機制）
    tryDeleteWithRetry(ticker);
}

// 帶重試機制的刪除函數
async function tryDeleteWithRetry(ticker) {
    try {
        const response = await fetchWithRetry(`/api/stock/${ticker}`, {
            method: 'DELETE'
        });
        
        if (!response.ok) {
            const errorResponse = await response.json();
            throw new Error(errorResponse.message || '刪除失敗');
        }
        console.log(`Deleted ${ticker}`);
        fetchPortfolio();
    } catch (error) {
        console.error('Error deleting stock:', error);
        alert(`刪除失敗: ${error.message}`);
    }
}
async function handleSave() {
    const mode = document.getElementById('stock-modal-mode').value;
    const ticker = document.getElementById('stock-modal-ticker').value;
    const data = {
        ticker: ticker,
        name: document.getElementById('stock-modal-name').value,
        shares: document.getElementById('stock-modal-shares').value,
        avg_cost: document.getElementById('stock-modal-avg-cost').value,
        currency: document.getElementById('stock-modal-currency').value,
    };
    if (!data.ticker || !data.shares || !data.avg_cost) {
        alert("Ticker, 股數, 和平均成本為必填欄位。");
        return;
    }
    let url = '/api/stock';
    let method = 'POST';
    if (mode === 'edit') {
        url = `/api/stock/${ticker}`;
        method = 'PUT';
    }
    
    // 嘗試保存數據（帶重試機制）
    trySaveWithRetry(url, method, data);
}

// 帶重試機制的保存函數
async function trySaveWithRetry(url, method, data) {
    try {
        const response = await fetchWithRetry(url, {
            method: method,
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify(data)
        });
        
        if (!response.ok) {
            const errorResponse = await response.json();
            throw new Error(errorResponse.message || '儲存失敗');
        }
        stockModal.hide();
        fetchPortfolio();
        fetchHistorySummary();
    } catch (error) {
        console.error('Error saving stock:', error);
        alert(`儲存失敗: ${error.message}`);
    }
}

// --- 日期驗證功能 ---
function validateDateInput(dateStr) {
    if (!dateStr) return false;
    
    const date = new Date(dateStr + 'T12:00:00Z');
    const today = new Date();
    today.setHours(0, 0, 0, 0);
    
    // 檢查日期是否有效
    if (isNaN(date.getTime())) return false;
    
    // 檢查日期是否在合理範圍內 (不能是未來日期)
    if (date > today) return false;
    
    return true;
}

// --- 區間查詢功能 --- 帶重試機制
async function showHistoricalDataRange() {
    const startDateStr = document.getElementById('date-range-start').value;
    const endDateStr = document.getElementById('date-range-end').value;
    const rangeQueryResultEl = document.getElementById('range-query-result');
    
    // 隱藏之前的查詢結果
    document.getElementById('lookup-result').style.display = 'none';
    
    if (!startDateStr || !endDateStr) {
        rangeQueryResultEl.style.display = 'none';
        return;
    }
    
    try {
        // 獲取最新的歷史數據（帶重試機制）
        const response = await fetchWithRetry('/api/history_summary');
        const data = await response.json();
        
        if (data.daily && Object.keys(data.daily).length > 0) {
            historicalDailyData = data.daily;
        } else {
            throw new Error('歷史資料為空');
        }
        
        // 驗證日期格式
        if (!validateDateInput(startDateStr) || !validateDateInput(endDateStr)) {
            rangeQueryResultEl.textContent = '請輸入有效的日期格式 (YYYY-MM-DD) 且日期不能為未來日期。';
            rangeQueryResultEl.className = 'alert alert-warning';
            rangeQueryResultEl.style.display = 'block';
            return;
        }
        
        if (Object.keys(historicalDailyData).length === 0) {
            rangeQueryResultEl.textContent = '歷史資料尚未載入。';
            rangeQueryResultEl.className = 'alert alert-warning';
            rangeQueryResultEl.style.display = 'block';
            return;
        }
        
        // 根據績效類型選擇數據
        let performanceLabel = '';
        let getDataValue = (data) => data.total; // 默認為總績效
        
        switch (currentPerformanceType) {
            case 'total':
                performanceLabel = '總績效';
                getDataValue = (data) => data.total;
                break;
            case 'tw':
                performanceLabel = '台灣績效';
                getDataValue = (data) => data.tw_value;
                break;
            case 'cn':
                performanceLabel = '中國績效';
                getDataValue = (data) => data.cn_value;
                break;
        }
        
        // 解析日期
        const startDate = new Date(startDateStr + 'T12:00:00Z');
        const endDate = new Date(endDateStr + 'T12:00:00Z');
        
        // 驗證日期順序
        if (startDate > endDate) {
            rangeQueryResultEl.textContent = '開始日期不能晚於結束日期。';
            rangeQueryResultEl.className = 'alert alert-warning';
            rangeQueryResultEl.style.display = 'block';
            return;
        }
        
        // 查找範圍內的數據
        const getSafeValue = (dateKey) => {
            if (!historicalDailyData[dateKey]) return null;
            const data = historicalDailyData[dateKey];
            if (typeof data === 'object' && data !== null) return getDataValue(data);
            return null;
        };
        
        // 查找開始日期的值（尋找最接近的可用日期）
        let startValue = null;
        let actualStartDateStr = '';
        let searchDate = new Date(startDate);
        for (let i = 0; i < 7; i++) {
            let dateKey = searchDate.toISOString().split('T')[0];
            startValue = getSafeValue(dateKey);
            if (startValue !== null) {
                actualStartDateStr = dateKey;
                break;
            }
            searchDate.setDate(searchDate.getDate() + 1);
        }
        
        // 查找結束日期的值（尋找最接近的可用日期）
        let endValue = null;
        let actualEndDateStr = '';
        searchDate = new Date(endDate);
        for (let i = 0; i < 7; i++) {
            let dateKey = searchDate.toISOString().split('T')[0];
            endValue = getSafeValue(dateKey);
            if (endValue !== null) {
                actualEndDateStr = dateKey;
                break;
            }
            searchDate.setDate(searchDate.getDate() - 1);
        }
        
        // 驗證是否找到數據
        if (startValue === null || endValue === null) {
            rangeQueryResultEl.textContent = '在指定日期範圍內找不到歷史資料。';
            rangeQueryResultEl.className = 'alert alert-warning';
            rangeQueryResultEl.style.display = 'block';
            return;
        }
        
        // 計算差異
        const diff = endValue - startValue;
        const percent = (startValue === 0) ? 0 : (diff / startValue);
        const plClass = getPlClass(diff);
        
        // 顯示結果
        const message = `查詢區間 <strong>${actualStartDateStr}</strong> 至 <strong>${actualEndDateStr}</strong> (${performanceLabel}):<br>
                       <h4 class="mb-0">${currencyFormatter.format(startValue)} → ${currencyFormatter.format(endValue)}</h4>`;
                          
        const diffHtml = `
            <hr class="my-2">
            <small class="mb-0">
                <strong class="${plClass}" style="font-size: 1.1rem;">
                    ${diff > 0 ? '+' : ''}${currencyFormatter.format(diff)} (${percentFormatter.format(percent)})
                </strong>
            </small>
        `;
        
        rangeQueryResultEl.innerHTML = message + diffHtml;
        rangeQueryResultEl.className = 'alert alert-info';
        rangeQueryResultEl.style.display = 'block';
        
        // 高亮圖表上的點
        highlightChartRange(actualStartDateStr, actualEndDateStr);
    } catch (error) {
        console.error("Error in showHistoricalDataRange:", error);
        rangeQueryResultEl.textContent = `查詢失敗: ${error.message}`;
        rangeQueryResultEl.className = 'alert alert-danger';
        rangeQueryResultEl.style.display = 'block';
    }
}

// (showHistoricalData - 讀取 .total) 帶重試機制
async function showHistoricalData(event) {
    const lookupDateStr = event.target.value;
    const lookupResultEl = document.getElementById('lookup-result');
    if (!lookupDateStr) {
        lookupResultEl.style.display = 'none';
        return;
    }
    
    try {
        // 獲取最新的歷史數據（帶重試機制）
        const response = await fetchWithRetry('/api/history_summary');
        const data = await response.json();
        
        if (data.daily && Object.keys(data.daily).length > 0) {
            historicalDailyData = data.daily;
        } else {
            throw new Error('歷史資料為空');
        }
        
        if (Object.keys(historicalDailyData).length === 0) {
            lookupResultEl.textContent = '歷史資料尚未載入 (或 history.json 為空)。';
            lookupResultEl.className = 'alert alert-warning';
            lookupResultEl.style.display = 'block';
            return;
        }
        
        // 根據績效類型選擇數據
        let performanceLabel = '';
        let getDataValue = (data) => data.total; // 默認為總績效
        
        switch (currentPerformanceType) {
            case 'total':
                performanceLabel = '總績效';
                getDataValue = (data) => data.total;
                break;
            case 'tw':
                performanceLabel = '台灣績效';
                getDataValue = (data) => data.tw_value;
                break;
            case 'cn':
                performanceLabel = '中國績效';
                getDataValue = (data) => data.cn_value;
                break;
        }
        
        const getSafeValue = (dateKey) => {
            if (!historicalDailyData[dateKey]) return null;
            const data = historicalDailyData[dateKey];
            if (typeof data === 'object' && data !== null) return getDataValue(data);
            if (typeof data === 'number') return data;
            return null;
        };
        let lookupDate = new Date(lookupDateStr + 'T12:00:00Z');
        let foundDateStr = '';
        let foundValue = null;
        for (let i = 0; i < 7; i++) {
            let dateKey = lookupDate.toISOString().split('T')[0];
            foundValue = getSafeValue(dateKey);
            if (foundValue !== null) {
                foundDateStr = dateKey;
                break;
            }
            lookupDate.setDate(lookupDate.getDate() - 1);
        }
        if (foundValue === null) {
            lookupResultEl.textContent = `在 ${lookupDateStr} 或之前找不到任何歷史資料。`;
            lookupResultEl.className = 'alert alert-warning';
            lookupResultEl.style.display = 'block';
            return;
        }
        const sortedDates = Object.keys(historicalDailyData).sort();
        const foundIndex = sortedDates.indexOf(foundDateStr);
        let previousValue = 0;
        let previousDateStr = '';
        let diffHtml = '';
        if (foundIndex > 0) {
            previousDateStr = sortedDates[foundIndex - 1];
            previousValue = getSafeValue(previousDateStr);
            const diff = foundValue - previousValue;
            const percent = (previousValue === 0) ? 0 : (diff / previousValue);
            const plClass = getPlClass(diff);
            diffHtml = `
                <hr class="my-2">
                <small class="mb-0">
                    與 ${previousDateStr} ( ${currencyFormatter.format(previousValue)} ) 相比:<br>
                    <strong class="${plClass}" style="font-size: 1.1rem;">
                       ${diff > 0 ? '+' : ''}${currencyFormatter.format(diff)} (${percentFormatter.format(percent)})
                   </strong>
                </small>
            `;
        } else {
            diffHtml = `<hr class="my-2"><small class="mb-0">這是資料中的第一天，無前期資料可比較。</small>`;
        }
        let message = `查詢日期 <strong>${lookupDateStr}</strong> (以 <strong>${foundDateStr}</strong> 收盤價為準) (${performanceLabel}):<br>
                       <h4 class="mb-0">${currencyFormatter.format(foundValue)}</h4>`;
        lookupResultEl.innerHTML = message + diffHtml;
        lookupResultEl.className = 'alert alert-info';
        lookupResultEl.style.display = 'block';
        highlightChartPoint(foundDateStr);
    } catch (error) {
        console.error("Error in showHistoricalData:", error);
        lookupResultEl.textContent = `查詢失敗: ${error.message}`;
        lookupResultEl.className = 'alert alert-danger';
        lookupResultEl.style.display = 'block';
    }
}
// (highlightChartPoint 不變)
function highlightChartPoint(dateStr) {
    if (!historyChart) return;
    const dataIndex = historyChart.data.labels.indexOf(dateStr);
    if (dataIndex === -1) {
        historyChart.tooltip.setActiveElements([], { x: 0, y: 0 });
        historyChart.update();
        return;
    }
    historyChart.tooltip.setActiveElements([
        { datasetIndex: 0, index: dataIndex }
    ]);
    historyChart.setActiveElements([
        { datasetIndex: 0, index: dataIndex }
    ]);
    historyChart.update();
}

// (排序輔助函式 ... 保持不變)
function handleSortClick(event) {
    const newKey = event.currentTarget.dataset.sortKey;
    if (currentSortKey === newKey) {
        currentSortDirection = (currentSortDirection === 'asc' ? 'desc' : 'asc');
    } else {
        currentSortKey = newKey;
        currentSortDirection = 'desc';
    }
    updateTable(currentPortfolioData);
}
function updateSortIndicators() {
    const headers = document.querySelectorAll('#sortable-table-head .sortable-header');
    headers.forEach(header => {
        if (header.dataset.sortKey === currentSortKey) {
            header.setAttribute('data-sort-direction', currentSortDirection);
        } else {
            header.removeAttribute('data-sort-direction');
        }
    });
}

// (calculateAndDisplayRange - 修改以支援 7D 選項和績效類型)
function calculateAndDisplayRange() {
    if (Object.keys(historicalDailyData).length === 0) {
        console.log("calculateAndDisplayRange: 歷史資料尚未載入");
        return;
    }
    const sortedDates = Object.keys(historicalDailyData).sort();
    if (sortedDates.length === 0) {
        console.log("calculateAndDisplayRange: 歷史資料為空");
        return;
    }
    
    // 根據績效類型選擇數據
    let performanceLabel = '';
    let getDataValue = (data) => data.total; // 默認為總績效
    
    switch (currentPerformanceType) {
        case 'total':
            performanceLabel = '總績效';
            getDataValue = (data) => data.total;
            break;
        case 'tw':
            performanceLabel = '台灣績效';
            getDataValue = (data) => data.tw_value;
            break;
        case 'cn':
            performanceLabel = '中國績效';
            getDataValue = (data) => data.cn_value;
            break;
    }
    
    const lastDateStr = sortedDates[sortedDates.length - 1];
    const endData = findClosestPastDataWithValue(lastDateStr, sortedDates, getDataValue);
    
    let startData = { date: null, value: 0 };
    let rangeLabel = '';
    const today = new Date();
    switch (currentRange) {
        case 'MTD':
            rangeLabel = '本月 (MTD)';
            const monthPrefix = today.toISOString().split('T')[0].substring(0, 7);
            startData = findFirstDateOfPeriodWithValue(monthPrefix, sortedDates, getDataValue);
            break;
        case 'YTD':
            rangeLabel = '本年 (YTD)';
            const yearPrefix = today.toISOString().split('T')[0].substring(0, 4);
            startData = findFirstDateOfPeriodWithValue(yearPrefix, sortedDates, getDataValue);
            break;
        case '30D':
            rangeLabel = '近30天';
            let date30D = new Date(today);
            date30D.setDate(date30D.getDate() - 30);
            startData = findClosestPastDataWithValue(date30D.toISOString().split('T')[0], sortedDates, getDataValue);
            break;
        case '7D':  // 新增 7D 選項
            rangeLabel = '近7天';
            let date7D = new Date(today);
            date7D.setDate(date7D.getDate() - 7);
            startData = findClosestPastDataWithValue(date7D.toISOString().split('T')[0], sortedDates, getDataValue);
            break;
        case '1Y':
            rangeLabel = '近一年';
            let date1Y = new Date(today);
            date1Y.setFullYear(date1Y.getFullYear() - 1);
            startData = findClosestPastDataWithValue(date1Y.toISOString().split('T')[0], sortedDates, getDataValue);
            break;
    }
    
    // (修改) 當找不到起始日期資料時，顯示適當的訊息
    const endValue = endData.value || 0;
    if ((currentRange === 'MTD' || currentRange === '7D') && !startData.date) {
        // 如果是本月或近7天但找不到起始資料，顯示適當訊息
        document.getElementById('range-label').textContent = rangeLabel;
        document.getElementById('range-start-value').textContent = '(無起始資料)';
        document.getElementById('range-end-value').textContent = `(${currencyFormatter.format(endValue)})`;
        const diffEl = document.getElementById('range-summary-diff');
        const percentEl = document.getElementById('range-summary-percent');
        diffEl.textContent = 'N/A';
        percentEl.textContent = 'N/A';
        diffEl.className = 'text-dark';
        percentEl.className = 'text-dark';
        return;
    }
    
    const startValue = startData.value || 0;
    const diff = endValue - startValue;
    const percent = (startValue === 0) ? 0 : (diff / startValue);
    const plClass = getPlClass(diff);
    document.getElementById('range-label').textContent = rangeLabel;
    document.getElementById('range-start-value').textContent = `(${currencyFormatter.format(startValue)})`;
    document.getElementById('range-end-value').textContent = `(${currencyFormatter.format(endValue)})`;
    const diffEl = document.getElementById('range-summary-diff');
    const percentEl = document.getElementById('range-summary-percent');
    diffEl.textContent = `${diff > 0 ? '+' : ''}${currencyFormatter.format(diff)}`;
    percentEl.textContent = percentFormatter.format(percent);
    diffEl.className = plClass;
    percentEl.className = plClass;
}

// 輔助函數：查找帶有指定值的最接近過去數據
function findClosestPastDataWithValue(targetDateStr, sortedDates, getValueFunction) {
    let targetDate = new Date(targetDateStr + 'T12:00:00Z');
    for (let i = 0; i < 7; i++) {
        let dateKey = targetDate.toISOString().split('T')[0];
        const data = historicalDailyData[dateKey];
        if (data) {
            return { date: dateKey, value: getValueFunction(data) };
        }
        targetDate.setDate(targetDate.getDate() - 1);
    }
    const firstDate = sortedDates[0];
    const data = historicalDailyData[firstDate];
    return firstDate ? { date: firstDate, value: getValueFunction(data) } : { date: null, value: 0 };
}

// 輔助函數：查找期間的第一個日期數據
function findFirstDateOfPeriodWithValue(prefix, sortedDates, getValueFunction) {
     const date = sortedDates.find(d => d.startsWith(prefix));
     const data = historicalDailyData[date];
     return date ? { date: date, value: getValueFunction(data) } : { date: null, value: 0 };
}
function handleRangeClick(event) {
    const button = event.target;
    currentRange = button.dataset.range;
    document.querySelectorAll('#range-selector button').forEach(btn => {
        btn.classList.remove('active');
    });
    button.classList.add('active');
    calculateAndDisplayRange();
}

function handlePerformanceTypeClick(event) {
    const button = event.target;
    currentPerformanceType = button.dataset.performanceType;
    document.querySelectorAll('#performance-type-selector button').forEach(btn => {
        btn.classList.remove('active');
    });
    button.classList.add('active');
    calculateAndDisplayRange();
}

// --- *** (修改) 試算函式 *** ---
function getTrialResultHTML(stock, targetPrice) {
    if (!targetPrice || targetPrice <= 0 || !stock) {
        return { html: '', display: 'none' };
    }
    
    const shares = stock.shares;
    const currency = stock.currency;
    const currentValueTWD = stock.market_value;
    
    let rate = 1.0;
    if (currency === 'CNY') {
        rate = currentCnyRate;
    } 
    // (未來可擴充: else if (currency === 'USD') ... )
    
    const targetValueTWD = (targetPrice * shares) * rate;
    const diffTWD = targetValueTWD - currentValueTWD;
    
    // (*** 新增 ***) 計算百分比
    const percent = (currentValueTWD === 0) ? 0 : (diffTWD / currentValueTWD);
    
    // (*** 修改 ***) 更新 HTML
    const html = `
        目標市值: <strong>${currencyFormatter.format(targetValueTWD)}</strong><br>
        與現價差: <strong class="${getPlClass(diffTWD)}">
                      ${diffTWD > 0 ? '+' : ''}${currencyFormatter.format(diffTWD)}
                      (${percentFormatter.format(percent)})
                   </strong>
    `;
    return { html: html, display: 'block' };
}
function handleTrialCalc(event) {
    const input = event.target;
    const ticker = input.dataset.ticker;
    const targetPrice = parseFloat(input.value);
    const resultEl = document.getElementById(`trial-result-${ticker}`);
    
    // (從 currentPortfolioData 取得 "目前" 的資料)
    const stock = currentPortfolioData.find(s => s.ticker === ticker);
    
    const { html, display } = getTrialResultHTML(stock, targetPrice);
    
    resultEl.innerHTML = html;
    resultEl.style.display = display;
}

// --- (新) 欄位顯示/隱藏 ---
function setupColumnToggler() {
    const dropdown = document.getElementById('column-toggle-dropdown');
    const table = document.getElementById('portfolio-table');
    const headers = document.querySelectorAll('#sortable-table-head th');
    const STORAGE_KEY = 'portfolio_column_visibility';

    // 預設隱藏的欄位
    const defaultHidden = ['previous_close', 'chart', 'data_source'];

    // 1. 從 localStorage 載入設定，若無則使用預設值
    const savedSettings = JSON.parse(localStorage.getItem(STORAGE_KEY));
    if (savedSettings) {
        columnVisibility = savedSettings;
    } else {
        columnVisibility = {};
        headers.forEach(th => {
            const key = th.dataset.sortKey;
            if (key) {
                columnVisibility[key] = !defaultHidden.includes(key);
            }
        });
    }

    // 2. 產生 CSS 規則
    const styleSheet = document.createElement('style');
    document.head.appendChild(styleSheet);

    function updateCssRules() {
        let css = '';
        for (const key in columnVisibility) {
            if (!columnVisibility[key]) {
                css += `
                    #portfolio-table.hide-${key} th[data-sort-key="${key}"],
                    #portfolio-table.hide-${key} td[data-key="${key}"] {
                        display: none;
                    }
                `;
            }
        }
        styleSheet.innerHTML = css;
    }

    // 3. 根據設定更新表格 class
    function applyVisibility() {
        for (const key in columnVisibility) {
            if (columnVisibility[key]) {
                table.classList.remove(`hide-${key}`);
            } else {
                table.classList.add(`hide-${key}`);
            }
        }
        updateCssRules();
    }

    // 4. 產生下拉選單的 checkboxes
    dropdown.innerHTML = ''; // 清空
    headers.forEach(th => {
        const key = th.dataset.sortKey;
        const name = th.dataset.columnName;
        // 排除沒有 key 或 name 的欄位
        if (!key || !name) return;
        // 允許 'actions' 欄位被切換
        // 允許 'chart' 欄位被切換
        
        const li = document.createElement('li');
        li.classList.add('px-2');
        const isChecked = columnVisibility[key];

        li.innerHTML = `
            <div class="form-check">
                <input class="form-check-input" type="checkbox" value="${key}" id="toggle-col-${key}" ${isChecked ? 'checked' : ''}>
                <label class="form-check-label" for="toggle-col-${key}">
                    ${name}
                </label>
            </div>
        `;
        dropdown.appendChild(li);
    });

    // 5. 加上事件監聽
    dropdown.addEventListener('change', (e) => {
        if (e.target.type === 'checkbox') {
            const key = e.target.value;
            const isChecked = e.target.checked;
            columnVisibility[key] = isChecked;

            // --- (修正) ---
            // 移除 "試算" (what_if) 欄位與 "操作" (actions) 欄位的綁定
            // 讓使用者可以獨立控制 "操作" 欄位的顯示
            
            localStorage.setItem(STORAGE_KEY, JSON.stringify(columnVisibility));
            applyVisibility();
        }
    });
    
    // 防止點擊下拉選單內部時關閉選單
    dropdown.addEventListener('click', (e) => {
        e.stopPropagation();
    });

    // 初始套用
    applyVisibility();
}


// (DOMContentLoaded 不變)
document.addEventListener('DOMContentLoaded', () => {
    setupColumnToggler(); // <-- (新) 呼叫
    
    // 設置日期輸入框的最大日期為今天
    const today = new Date().toISOString().split('T')[0];
    document.getElementById('date-lookup').max = today;
    document.getElementById('date-range-start').max = today;
    document.getElementById('date-range-end').max = today;
    
    // 為日期範圍輸入框添加自動查詢功能
    document.getElementById('date-range-start').addEventListener('change', function() {
        const startDate = this.value;
        const endDate = document.getElementById('date-range-end').value;
        if (startDate && endDate) {
            showHistoricalDataRange();
        }
    });
    
    document.getElementById('date-range-end').addEventListener('change', function() {
        const startDate = document.getElementById('date-range-start').value;
        const endDate = this.value;
        if (startDate && endDate) {
            showHistoricalDataRange();
        }
    });
    
    stockModal = new bootstrap.Modal(document.getElementById('stock-modal'));
    settingsModal = new bootstrap.Modal(document.getElementById('settings-modal'));
    
    document.getElementById('add-stock-btn').addEventListener('click', openModalForAdd);
    document.getElementById('settings-btn').addEventListener('click', openSettingsModal);
    document.getElementById('modal-save-btn').addEventListener('click', handleSave);
    document.getElementById('save-settings-btn').addEventListener('click', saveSettingsFromForm);
    
    document.getElementById('date-lookup').addEventListener('change', function(event) {
        showHistoricalData(event);
    });
    const tableBody = document.getElementById('portfolio-table-body');
    tableBody.addEventListener('click', (event) => {
        if (event.target.closest('.edit-btn')) {
            openModalForEdit(event);
        }
        if (event.target.closest('.delete-btn')) {
            handleDelete(event);
        }
        if (event.target.closest('.chart-btn')) {
            toggleStockChart(event);
        }
    });
    tableBody.addEventListener('input', (event) => {
        if (event.target.classList.contains('trial-input')) {
            handleTrialCalc(event);
        }
    });
    const sortableHeaders = document.querySelectorAll('#sortable-table-head .sortable-header');
    sortableHeaders.forEach(header => {
        header.addEventListener('click', handleSortClick);
    });
    document.querySelectorAll('#range-selector button').forEach(btn => {
        btn.addEventListener('click', handleRangeClick);
    });
    document.querySelectorAll('#performance-type-selector button').forEach(btn => {
        btn.addEventListener('click', handlePerformanceTypeClick);
    });
    
    // 添加清除日期範圍按鈕事件監聽器
    document.getElementById('clear-date-range').addEventListener('click', clearDateRange);
    
    // 初始化設定
    initSettings();

// (新) AI 聊天室邏
    const aiChatSendBtn = document.getElementById('ai-chat-send-btn');
    const aiChatInput = document.getElementById('ai-chat-input');

    if (aiChatSendBtn) {
        aiChatSendBtn.addEventListener('click', sendAiChatMessage);
    }

    if (aiChatInput) {
        aiChatInput.addEventListener('keypress', (e) => {
            if (e.key === 'Enter') {
                sendAiChatMessage();
            }
        });

    } 
    
    // 設置除錯模式按鈕事件監聽器
    document.getElementById('backfill-range-btn').addEventListener('click', handleRangeBackfill);
    document.getElementById('delete-btn').addEventListener('click', handleDeleteHistory);
    
    startFetching();
    fetchHistorySummary();
  });

// (新) 輪詢回補狀態的函式
async function pollBackfillStatus(gracePeriod = 0) {
    const debugResult = document.getElementById('debug-result');
    const messageEl = document.getElementById('debug-result-message');

    try {
        const response = await fetchWithRetry('/api/backfill_status');
        const data = await response.json();
        
        console.log('[DEBUG] Backfill status data:', data); // 保留調試日誌
        messageEl.textContent = data.message;
        
        if (data.running) {
            // 任務正在執行
            debugResult.className = 'alert alert-info'; // 顯示為藍色
            
            // 繼續輪詢
            backfillPollInterval = setTimeout(pollBackfillStatus, 1500); // 1.5秒後再問一次
        } else {
            // 任務已停止
            clearTimeout(backfillPollInterval);
            backfillPollInterval = null;
            
            // 檢查是否在寬限期內
            if (gracePeriod > 0) {
                // 寬限期內，再試一次
                messageEl.textContent = data.message + ` (等待啟動... ${gracePeriod})`;
                backfillPollInterval = setTimeout(() => pollBackfillStatus(gracePeriod - 1), 1500);
            } else {
                // 根據最終訊息決定顏色
                if (data.message.includes("錯誤") || data.message.includes("FATAL")) {
                    debugResult.className = 'alert alert-danger';
                } else {
                    debugResult.className = 'alert alert-success';
                    // 成功完成，自動重新整理歷史圖表
                    fetchHistorySummary();
                }
                
                // 讓按鈕可以再次點擊
                document.getElementById('backfill-range-btn').disabled = false;
            }
        }
    } catch (error) {
        console.error('Error polling backfill status:', error);
        messageEl.textContent = `輪詢狀態失敗: ${error.message}`;
        debugResult.className = 'alert alert-danger';
        // 停止輪詢並解鎖按鈕
        clearTimeout(backfillPollInterval);
        backfillPollInterval = null;
        document.getElementById('backfill-range-btn').disabled = false;
    }
}
// 處理歷史資料回補
// (修改) 處理歷史資料範圍回補
// (修改) 處理歷史資料範圍回補
async function handleRangeBackfill() {
    const startDate = document.getElementById('backfill-start-date').value;
    const endDate = document.getElementById('backfill-end-date').value;
    const debugResult = document.getElementById('debug-result');
    const messageEl = document.getElementById('debug-result-message');
    const button = document.getElementById('backfill-range-btn');

    // (新) 檢查是否已在執行
    if (backfillPollInterval) {
        alert("回補任務已在執行中，請稍候。");
        return;
    }

    if (!startDate || !endDate) {
        messageEl.textContent = '請選擇開始日期和結束日期';
        debugResult.className = 'alert alert-warning';
        debugResult.style.display = 'block';
        return;
    }

    if (startDate > endDate) {
        messageEl.textContent = '開始日期不能晚於結束日期';
        debugResult.className = 'alert alert-warning';
        debugResult.style.display = 'block';
        return;
    }

    if (!confirm(`您確定要回補從 ${startDate} 到 ${endDate} 的歷史資料嗎？`)) {
        return;
    }
    
    try {
        // (新) 鎖定按鈕
        button.disabled = true;
        
        // (新) 初始化 UI
        messageEl.textContent = '正在啟動回補任務...';
        debugResult.className = 'alert alert-info';
        debugResult.style.display = 'block';

        const response = await fetchWithRetry('/api/backfill_range', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({ start_date: startDate, end_date: endDate })
        });
        
        const data = await response.json();
        console.log('[DEBUG] Backfill range response:', data); // 保留調試日誌
        
        if (data.status === 'success') {
            // (新) 立即開始輪詢狀態
            pollBackfillStatus(3);
        } else {
            messageEl.textContent = `啟動失敗：${data.message}`;
            debugResult.className = 'alert alert-danger';
            button.disabled = false; // 解鎖按鈕
        }
    } catch (error) {
        console.error('Error in handleRangeBackfill:', error);
        messageEl.textContent = `啟動失敗：${error.message}`;
        debugResult.className = 'alert alert-danger';
        button.disabled = false; // 解鎖按鈕
    }
    // (移除) 'finally' 區塊中的 fetchHistorySummary()，改到 pollBackfillStatus() 成功時才觸發
}


// 處理歷史資料刪除
async function handleDeleteHistory() {
    const deleteDate = document.getElementById('delete-date').value;
    const debugResult = document.getElementById('debug-result');
    
    if (!deleteDate) {
        debugResult.textContent = '請選擇日期';
        debugResult.className = 'alert alert-warning';
        debugResult.style.display = 'block';
        return;
    }
    
    // 確認是否要刪除
    if (!confirm(`您確定要刪除 ${deleteDate} 的歷史資料嗎？此操作無法復原。`)) {
        return;
    }
    
    try {
        debugResult.style.display = 'none';
        const response = await fetchWithRetry('/api/delete_history', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ date: deleteDate })
        });
        
        const data = await response.json();
        
        if (data.status === 'success') {
            debugResult.textContent = `歷史資料刪除成功：${deleteDate}`;
            debugResult.className = 'alert alert-success';
        } else {
            debugResult.textContent = `刪除失敗：${data.message}`;
            debugResult.className = 'alert alert-danger';
        }
    } catch (error) {
        console.error('Error in handleDeleteHistory:', error);
        debugResult.textContent = `刪除失敗：${error.message}`;
        debugResult.className = 'alert alert-danger';
    } finally {
        debugResult.style.display = 'block';
        // 重新加載歷史數據以更新圖表
        fetchHistorySummary();
    }
}

// (新) 發送 AI 聊天訊息
async function sendAiChatMessage() {
    const input = document.getElementById('ai-chat-input');
    const messagesContainer = document.getElementById('ai-chat-messages');
    const question = input.value.trim();

    if (!question) return;

    // 1. 顯示使用者訊息
    const userMessageEl = document.createElement('div');
    userMessageEl.className = 'user-message';
    userMessageEl.textContent = question;
    messagesContainer.appendChild(userMessageEl);

    // 清空輸入框
    input.value = '';

    // 2. 顯示 AI 思考中...
    const aiTypingEl = document.createElement('div');
    aiTypingEl.className = 'ai-message';
    aiTypingEl.innerHTML = '<span class="spinner-border spinner-border-sm" role="status"></span> 思考中...';
    messagesContainer.appendChild(aiTypingEl);
    
    // 滾動到底部
    messagesContainer.scrollTop = messagesContainer.scrollHeight;

    try {
        // 3. 發送請求到後端
        const response = await fetchWithRetry('/api/ask_ai', { // (使用 fetchWithRetry)
            method: 'POST',
            headers: {
                'Content-Type': 'application/json',
            },
            body: JSON.stringify({ question: question })
        });

        if (!response.ok) {
            const errorData = await response.json();
            throw new Error(errorData.error || 'API 請求失敗');
        }

        const data = await response.json();
        
        // 4. 更新為 AI 回覆 (使用 textContent 避免 XSS)
        const unsafeHtml = marked.parse(data.response);
        // DOMPurify.sanitize() 會清除掉危險的標籤 (例如 <script>)
        const safeHtml = DOMPurify.sanitize(unsafeHtml);
        // 最後才安全地使用 innerHTML 
        aiTypingEl.innerHTML = safeHtml;

    } catch (error) {
        console.error('Error asking AI:', error);
        aiTypingEl.textContent = `抱歉，連線時發生錯誤: ${error.message}`;
        aiTypingEl.style.color = '#dc3545'; // (Bootstrap 警告色)
    } finally {
        // 再次滾動到底部
        messagesContainer.scrollTop = messagesContainer.scrollHeight;
    }
}

// (新增) 清除日期範圍輸入
function clearDateRange() {
    document.getElementById('date-range-start').value = '';
    document.getElementById('date-range-end').value = '';
    document.getElementById('range-query-result').style.display = 'none';
    // 清除圖表上的高亮
    if (historyChart) {
        historyChart.tooltip.setActiveElements([], { x: 0, y: 0 });
        historyChart.setActiveElements([]);
        historyChart.update();
    }
}

// (新增) 高亮圖表上的日期範圍
function highlightChartRange(startDateStr, endDateStr) {
    if (!historyChart) return;
    
    // 找到開始和結束日期的索引
    const labels = historyChart.data.labels;
    const startIndex = labels.indexOf(startDateStr);
    const endIndex = labels.indexOf(endDateStr);
    
    // 如果找不到日期，清除高亮
    if (startIndex === -1 || endIndex === -1) {
        historyChart.tooltip.setActiveElements([], { x: 0, y: 0 });
        historyChart.update();
        return;
    }
    
    // 設置工具提示高亮顯示結束日期點
    historyChart.tooltip.setActiveElements([
        { datasetIndex: 0, index: endIndex }
    ]);
    
    // 更新圖表
    historyChart.update();
}

// --- 設定功能 ---
let settingsModal = null;

// 設定的默認值
const defaultSettings = {
    updateInterval: 5000,
    chartTimeRange: 90,
    showTotalSeries: true,
    showTwSeries: true,
    showCnSeries: true,
    theme: 'light',
    enableNotifications: false,
    enableMarketValueNotification: false,  // 預設不啟用總市值通知
    marketValueNotificationThreshold: 1000000,
    enableTwMarketValueNotification: false,  // 預設不啟用台灣股票總市值通知
    twMarketValueNotificationThreshold: 500000,
    enableCnMarketValueNotification: false,  // 預設不啟用中國股票總市值通知
    cnMarketValueNotificationThreshold: 500000,
    enablePlPercentNotification: true,  // 預設啟用總報酬率通知
    plPercentNotificationThreshold: 1.0,
    enablePlNotification: false,       // 預設不啟用總損益通知
    plNotificationThreshold: 1000
};

// 除錯模式設定
defaultSettings.debugMode = false;

// 從 localStorage 載入設定
function loadSettings() {
    const savedSettings = JSON.parse(localStorage.getItem('portfolio_settings'));
    return savedSettings || defaultSettings;
}

// 儲存設定到 localStorage
function saveSettings(settings) {
    localStorage.setItem('portfolio_settings', JSON.stringify(settings));
}

// 應用設定
function applySettings(settings) {
    // 更新資料獲取間隔
    if (settings.updateInterval !== UPDATE_INTERVAL) {
        stopFetching();
        if (settings.updateInterval > 0) {
            fetchInterval = setInterval(fetchPortfolio, settings.updateInterval);
        }
    }
    
    // 應用主題
    if (settings.theme === 'dark') {
        document.documentElement.setAttribute('data-theme', 'dark');
    } else {
        document.documentElement.removeAttribute('data-theme');
    }
    
    // 應用圖表主題
    if (historyChart) {
        // 重新渲染圖表以應用主題
        const dailyData = historicalDailyData;
        if (dailyData && Object.keys(dailyData).length > 0) {
            renderHistoryChart(dailyData);
        }
    }
    
    // 這裡可以添加更多設定應用邏輯
    // 例如圖表時間範圍、通知設定等
    
    // 應用除錯模式設定
    applyDebugMode(settings.debugMode);
    
    // 應用閃爍通知設定
    const totalPlPercentElement = document.getElementById('total-pl-percent');
    if (totalPlPercentElement) {
        // 獲取當前的總報酬率
        const plPercentText = totalPlPercentElement.textContent;
        // 移除百分比符號並解析數值
        const plPercent = parseFloat(plPercentText.replace('%', '')) || 0;
        // 獲取當前的總損益值
        const plValueText = document.getElementById('total-pl').textContent;
        const plValue = parseFloat(plValueText.replace(/[^0-9.-]/g, '')) || 0;
        
        checkAndTriggerNotification(plPercent, plValue);
    }
  }

// 應用除錯模式設定
// (修改) 應用除錯模式設定
function applyDebugMode(isEnabled) {
    const debugSection = document.getElementById('debug-section');
    if (debugSection) {
        debugSection.style.display = isEnabled ? 'block' : 'none';
    }
    
    // (新) 改為在 <html> 標籤上切換 CSS Class，
    // 這樣無論 <td> 何時被建立，都能正確顯示。
    document.documentElement.classList.toggle('debug-mode-enabled', isEnabled);
}

// 打開設定模態框
function openSettingsModal() {
    const settings = loadSettings();
    
    // 填充表單
    document.getElementById('update-interval').value = settings.updateInterval;
    document.getElementById('chart-time-range').value = settings.chartTimeRange;
    document.getElementById('show-total-series').checked = settings.showTotalSeries;
    document.getElementById('show-tw-series').checked = settings.showTwSeries;
    document.getElementById('show-cn-series').checked = settings.showCnSeries;
    document.getElementById('theme-selector').value = settings.theme;
    document.getElementById('enable-notifications').checked = settings.enableNotifications;
    document.getElementById('enable-market-value-notification').checked = settings.enableMarketValueNotification;
    document.getElementById('market-value-notification-threshold').value = settings.marketValueNotificationThreshold;
    document.getElementById('enable-tw-market-value-notification').checked = settings.enableTwMarketValueNotification;
    document.getElementById('tw-market-value-notification-threshold').value = settings.twMarketValueNotificationThreshold;
    document.getElementById('enable-cn-market-value-notification').checked = settings.enableCnMarketValueNotification;
    document.getElementById('cn-market-value-notification-threshold').value = settings.cnMarketValueNotificationThreshold;
    document.getElementById('enable-pl-percent-notification').checked = settings.enablePlPercentNotification;
    document.getElementById('pl-percent-notification-threshold').value = settings.plPercentNotificationThreshold;
    document.getElementById('enable-pl-notification').checked = settings.enablePlNotification;
    document.getElementById('pl-notification-threshold').value = settings.plNotificationThreshold;
    document.getElementById('debug-mode').checked = settings.debugMode || false;
    
    settingsModal.show();
  }

// 儲存設定
function saveSettingsFromForm() {
  const settings = {
      updateInterval: parseInt(document.getElementById('update-interval').value),
      chartTimeRange: parseInt(document.getElementById('chart-time-range').value),
      showTotalSeries: document.getElementById('show-total-series').checked,
      showTwSeries: document.getElementById('show-tw-series').checked,
      showCnSeries: document.getElementById('show-cn-series').checked,
      theme: document.getElementById('theme-selector').value,
      enableNotifications: document.getElementById('enable-notifications').checked,
      enableMarketValueNotification: document.getElementById('enable-market-value-notification').checked,
      marketValueNotificationThreshold: parseFloat(document.getElementById('market-value-notification-threshold').value),
      enableTwMarketValueNotification: document.getElementById('enable-tw-market-value-notification').checked,
      twMarketValueNotificationThreshold: parseFloat(document.getElementById('tw-market-value-notification-threshold').value),
      enableCnMarketValueNotification: document.getElementById('enable-cn-market-value-notification').checked,
      cnMarketValueNotificationThreshold: parseFloat(document.getElementById('cn-market-value-notification-threshold').value),
      enablePlPercentNotification: document.getElementById('enable-pl-percent-notification').checked,
      plPercentNotificationThreshold: parseFloat(document.getElementById('pl-percent-notification-threshold').value),
      enablePlNotification: document.getElementById('enable-pl-notification').checked,
      plNotificationThreshold: parseFloat(document.getElementById('pl-notification-threshold').value),
      debugMode: document.getElementById('debug-mode').checked
  };
    
    saveSettings(settings);
    applySettings(settings);
    settingsModal.hide();
    
    // 重新加載歷史數據以應用圖表設定
    fetchHistorySummary();
    
    // 應用閃爍通知設定
    const totalPlPercentElement = document.getElementById('total-pl-percent');
    const totalPlElement = document.getElementById('total-pl');
    const totalMarketValueElement = document.getElementById('total-market-value');
    const twMarketValueElement = document.getElementById('tw-market-value');
    const cnMarketValueElement = document.getElementById('cn-market-value');
    
    if (totalPlPercentElement && totalPlElement) {
        // 獲取當前的總報酬率
        const plPercentText = totalPlPercentElement.textContent;
        // 移除百分比符號並解析數值
        const plPercent = parseFloat(plPercentText.replace('%', '')) || 0;
        // 獲取當前的總損益值
        const plValueText = totalPlElement.textContent;
        const plValue = parseFloat(plValueText.replace(/[^0-9.-]/g, '')) || 0;
        
        checkAndTriggerNotification(plPercent, plValue);
    }
    
    // 應用市值閃爍通知設定
    if (totalMarketValueElement) {
        // 獲取當前的總市值
        const marketValueText = totalMarketValueElement.textContent;
        const marketValue = parseFloat(marketValueText.replace(/[^0-9.-]/g, '')) || 0;
        checkMarketValueNotification(marketValue, 'total');
    }
    
    if (twMarketValueElement) {
        // 獲取當前的台灣股票總市值
        const twMarketValueText = twMarketValueElement.textContent;
        const twMarketValue = parseFloat(twMarketValueText.replace(/[^0-9.-]/g, '')) || 0;
        checkMarketValueNotification(twMarketValue, 'tw');
    }
    
    if (cnMarketValueElement) {
        // 獲取當前的中國股票總市值
        const cnMarketValueText = cnMarketValueElement.textContent;
        const cnMarketValue = parseFloat(cnMarketValueText.replace(/[^0-9.-]/g, '')) || 0;
        checkMarketValueNotification(cnMarketValue, 'cn');
    }
}

// 在 initSettings 函數中新增除錯模式初始化
function initSettings() {
    const settings = loadSettings();
    applySettings(settings);
    applyDebugMode(settings.debugMode);
    
    // 應用閃爍通知設定
    if (settings.enableNotifications) {
        // 確保在初始化時檢查一次通知條件
        setTimeout(() => {
            const totalPlPercentElement = document.getElementById('total-pl-percent');
            const totalPlElement = document.getElementById('total-pl');
            if (totalPlPercentElement && totalPlElement) {
                // 獲取當前的總報酬率
                const plPercentText = totalPlPercentElement.textContent;
                // 移除百分比符號並解析數值
                const plPercent = parseFloat(plPercentText.replace('%', '')) || 0;
                // 獲取當前的總損益值
                const plValueText = totalPlElement.textContent;
                const plValue = parseFloat(plValueText.replace(/[^0-9.-]/g, '')) || 0;
                
                checkAndTriggerNotification(plPercent, plValue);
            }
            
            // 應用市值閃爍通知設定
            const totalMarketValueElement = document.getElementById('total-market-value');
            if (totalMarketValueElement) {
                // 獲取當前的總市值
                const marketValueText = totalMarketValueElement.textContent;
                const marketValue = parseFloat(marketValueText.replace(/[^0-9.-]/g, '')) || 0;
                checkMarketValueNotification(marketValue, 'total');
            }
            
            const twMarketValueElement = document.getElementById('tw-market-value');
            if (twMarketValueElement) {
                // 獲取當前的台灣股票總市值
                const twMarketValueText = twMarketValueElement.textContent;
                const twMarketValue = parseFloat(twMarketValueText.replace(/[^0-9.-]/g, '')) || 0;
                checkMarketValueNotification(twMarketValue, 'tw');
            }
            
            const cnMarketValueElement = document.getElementById('cn-market-value');
            if (cnMarketValueElement) {
                // 獲取當前的中國股票總市值
                const cnMarketValueText = cnMarketValueElement.textContent;
                const cnMarketValue = parseFloat(cnMarketValueText.replace(/[^0-9.-]/g, '')) || 0;
                checkMarketValueNotification(cnMarketValue, 'cn');
            }
        }, 1000);
    }
}

// --- 除錯訊息功能 ---
let debugMessagesInterval = null;

// 開始輪詢除錯訊息
function startDebugMessagesPolling() {
    // 先立即獲取一次除錯訊息
    fetchDebugMessages();
    
    // 每2秒輪詢一次除錯訊息
    debugMessagesInterval = setInterval(fetchDebugMessages, 2000);
}

// 停止輪詢除錯訊息
function stopDebugMessagesPolling() {
    if (debugMessagesInterval) {
        clearInterval(debugMessagesInterval);
        debugMessagesInterval = null;
    }
}

// 獲取除錯訊息
async function fetchDebugMessages() {
    try {
        const response = await fetch('/api/debug_messages');
        const data = await response.json();
        
        if (data.status === 'success') {
            updateDebugConsole(data.messages);
        }
    } catch (error) {
        console.error('Error fetching debug messages:', error);
    }
}

// 更新除錯控制台
function updateDebugConsole(messages) {
    const debugConsole = document.getElementById('debug-console');
    if (!debugConsole) return;
    
    // 清空控制台
    debugConsole.innerHTML = '';
    
    // 添加每條訊息
    messages.forEach(message => {
        const messageElement = document.createElement('div');
        messageElement.className = 'debug-message';
        messageElement.textContent = message;
        debugConsole.appendChild(messageElement);
    });
    
    // 滾動到底部
    debugConsole.scrollTop = debugConsole.scrollHeight;
}

// (修改) 應用除錯模式設定
function applyDebugMode(isEnabled) {
    const debugSection = document.getElementById('debug-section');
    if (debugSection) {
        debugSection.style.display = isEnabled ? 'block' : 'none';
    }
    
    // 控制除錯訊息控制台的顯示
    const debugConsoleContainer = document.getElementById('debug-console-container');
    if (debugConsoleContainer) {
        debugConsoleContainer.style.display = isEnabled ? 'block' : 'none';
    }
    
    // 如果啟用除錯模式，開始輪詢除錯訊息
    if (isEnabled) {
        startDebugMessagesPolling();
    } else {
        // 如果停用除錯模式，停止輪詢除錯訊息
        stopDebugMessagesPolling();
    }
    
    // (新) 改為在 <html> 標籤上切換 CSS Class，
    // 這樣無論 <td> 何時被建立，都能正確顯示。
    document.documentElement.classList.toggle('debug-mode-enabled', isEnabled);
}

