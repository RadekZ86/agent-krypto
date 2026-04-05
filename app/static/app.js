const percentFormatter = new Intl.NumberFormat("pl-PL", {
    maximumFractionDigits: 2,
});

const numberFormatter = new Intl.NumberFormat("pl-PL", {
    maximumFractionDigits: 4,
});

let dashboardState = null;
let selectedSymbol = null;
let selectedSector = "ALL";
let selectedChartTab = "overview";
let selectedHistoryMode = "recent";
let selectedLifecycleInterval = "auto";
let chartHistoryCache = {};
let chartPackageCache = {};
let chartHoverState = null;
let chartHoverHandlersBound = false;
let dashboardRefreshTimerId = null;

// ==================== AUTH STATE ====================
let currentUser = null;
let userApiKeys = [];

// ==================== AUTH FUNCTIONS ====================

async function checkAuthStatus() {
    try {
        const response = await fetch('/api/auth/me');
        const data = await response.json();
        if (data.authenticated && data.user) {
            currentUser = data.user;
            showApp();
            updateUserMenu();
            loadUserApiKeys();
        } else {
            currentUser = null;
            // Demo mode - skip login screen, allow app usage without auth
            showApp();
            updateUserMenu();
        }
    } catch (error) {
        console.error('Auth check failed:', error);
        // Demo mode - show app even if auth check fails
        showApp();
    }
}

function showLoginScreen() {
    const loginScreen = document.getElementById('login-screen');
    if (loginScreen) {
        loginScreen.classList.remove('hidden');
    }
}

function hideLoginScreen() {
    const loginScreen = document.getElementById('login-screen');
    if (loginScreen) {
        loginScreen.classList.add('hidden');
    }
}

function showApp() {
    hideLoginScreen();
}

function updateUserMenu() {
    const userMenuName = document.getElementById('user-menu-name');
    const userEmail = document.querySelector('.user-email');
    const userDropdown = document.getElementById('user-dropdown');
    
    if (currentUser) {
        if (userMenuName) userMenuName.textContent = currentUser.username || 'Konto';
        if (userEmail) userEmail.textContent = currentUser.email || '';
        if (userDropdown) {
            userDropdown.innerHTML = `
                <div class="dropdown-header">
                    <span class="user-email">${currentUser.email || ''}</span>
                </div>
                <div class="dropdown-divider"></div>
                <button class="dropdown-item" data-action="toggle-trading-mode">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="M2 12h20"/><path d="M12 2a15.3 15.3 0 0 1 4 10 15.3 15.3 0 0 1-4 10 15.3 15.3 0 0 1-4-10 15.3 15.3 0 0 1 4-10z"/></svg>
                    <span id="trading-mode-label">${currentUser.trading_mode === "LIVE" ? "Przelacz na PAPER" : "Przelacz na LIVE"}</span>
                </button>
                <button class="dropdown-item" data-action="api-keys">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M21 2l-2 2m-7.61 7.61a5.5 5.5 0 1 1-7.778 7.778 5.5 5.5 0 0 1 7.777-7.777zm0 0L15.5 7.5m0 0l3 3L22 7l-3-3m-3.5 3.5L19 4"/></svg>
                    Klucze API
                </button>
                <button class="dropdown-item" data-action="logout">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M9 21H5a2 2 0 0 1-2-2V5a2 2 0 0 1 2-2h4"/><polyline points="16 17 21 12 16 7"/><line x1="21" y1="12" x2="9" y2="12"/></svg>
                    Wyloguj
                </button>
            `;
            rebindDropdownHandlers();
        }
    } else {
        if (userMenuName) userMenuName.textContent = 'Demo';
        if (userEmail) userEmail.textContent = 'Tryb demonstracyjny';
        if (userDropdown) {
            userDropdown.innerHTML = `
                <div class="dropdown-header">
                    <span class="user-email">Tryb demonstracyjny</span>
                </div>
                <div class="dropdown-divider"></div>
                <button class="dropdown-item" data-action="login">
                    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 3h4a2 2 0 0 1 2 2v14a2 2 0 0 1-2 2h-4"/><polyline points="10 17 15 12 10 7"/><line x1="15" y1="12" x2="3" y2="12"/></svg>
                    Zaloguj się
                </button>
            `;
            rebindDropdownHandlers();
        }
    }
}

function rebindDropdownHandlers() {
    const userDropdown = document.getElementById('user-dropdown');
    if (!userDropdown) return;
    
    userDropdown.querySelectorAll('.dropdown-item').forEach(item => {
        item.addEventListener('click', () => {
            const action = item.dataset.action;
            if (action === 'logout') {
                handleLogout();
            } else if (action === 'api-keys') {
                switchView('settings');
            } else if (action === 'login') {
                showLoginScreen();
            } else if (action === 'toggle-trading-mode') {
                handleToggleTradingMode();
            }
            userDropdown.classList.add('hidden');
        });
    });
}

async function handleLogin(email, password) {
    try {
        const response = await fetch('/api/auth/login', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ email, password })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Błąd logowania');
        }
        
        currentUser = data.user;
        showApp();
        updateUserMenu();
        loadUserApiKeys();
        return { success: true };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

async function handleRegister(username, email, password) {
    try {
        const response = await fetch('/api/auth/register', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ username, email, password })
        });
        
        const data = await response.json();
        
        if (!response.ok) {
            throw new Error(data.detail || 'Błąd rejestracji');
        }
        
        currentUser = data.user;
        showApp();
        updateUserMenu();
        loadUserApiKeys();
        return { success: true };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

async function handleLogout() {
    try {
        await fetch('/api/auth/logout', { method: 'POST' });
    } catch (error) {
        console.error('Logout error:', error);
    }
    currentUser = null;
    userApiKeys = [];
    updateUserMenu();
    showLoginScreen();
}

async function handleToggleTradingMode() {
    if (!currentUser) return;
    const newMode = currentUser.trading_mode === "LIVE" ? "PAPER" : "LIVE";
    const confirmMsg = newMode === "LIVE"
        ? "UWAGA: Przelaczasz na tryb LIVE. Agent bedzie skladal PRAWDZIWE zlecenia na Twoim koncie Binance. Kontynuowac?"
        : "Przelaczasz na tryb PAPER. Agent bedzie handlowal tylko wirtualnie.";
    if (!confirm(confirmMsg)) return;
    try {
        const response = await fetch('/api/user/trading-mode', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ mode: newMode }),
        });
        const data = await response.json();
        if (data.ok) {
            currentUser.trading_mode = data.trading_mode;
            updateUserMenu();
            renderDashboard();
            setStatus(`Tryb zmieniony na ${data.trading_mode}`);
        } else {
            alert(data.error || "Blad zmiany trybu");
        }
    } catch (error) {
        alert("Blad polaczenia: " + error.message);
    }
}

// ==================== API KEYS FUNCTIONS ====================

async function loadUserApiKeys() {
    if (!currentUser) {
        userApiKeys = [];
        renderApiKeysList();
        return;
    }
    
    try {
        const response = await fetch('/api/keys');
        if (response.ok) {
            const data = await response.json();
            userApiKeys = data.keys || [];
            renderApiKeysList();
            updateBinanceKeySelector();
        }
    } catch (error) {
        console.error('Failed to load API keys:', error);
    }
}

function renderApiKeysList() {
    const container = document.getElementById('api-keys-list');
    if (!container) return;
    
    if (!currentUser) {
        container.innerHTML = '<p class="empty-state">Zaloguj się aby zarządzać kluczami API</p>';
        return;
    }
    
    if (userApiKeys.length === 0) {
        container.innerHTML = '<p class="empty-state">Brak kluczy API. Dodaj klucz aby połączyć z Binance.</p>';
        return;
    }
    
    container.innerHTML = userApiKeys.map(key => `
        <div class="api-key-item" data-key-id="${key.id}">
            <div class="api-key-info">
                <span class="api-key-name">${key.label || key.exchange.toUpperCase()}</span>
                <span class="api-key-meta">
                    <span>${key.api_key}</span>
                    <span>${key.is_testnet ? '🧪 Testnet' : '🌐 Mainnet'}</span>
                    <span>${key.permissions}</span>
                </span>
            </div>
            <div class="api-key-actions">
                <button class="btn-test" onclick="testApiKey(${key.id})">Test</button>
                <button class="btn-delete" onclick="deleteApiKey(${key.id})">Usuń</button>
            </div>
        </div>
    `).join('');
}

function updateBinanceKeySelector() {
    const selector = document.getElementById('binance-key-selector');
    if (!selector) return;
    
    selector.innerHTML = '<option value="">Wybierz klucz API</option>' + 
        userApiKeys.map(key => `
            <option value="${key.id}">${key.label || key.exchange.toUpperCase()} - ${key.api_key} ${key.is_testnet ? '(Testnet)' : ''}</option>
        `).join('');
}

async function addApiKey(apiKey, apiSecret, isTestnet, permissions) {
    try {
        const response = await fetch('/api/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                exchange: 'binance',
                api_key: apiKey,
                api_secret: apiSecret,
                is_testnet: isTestnet,
                permissions: permissions
            })
        });
        
        const text = await response.text();
        let data;
        try { data = JSON.parse(text); } catch { data = { detail: text || `Błąd serwera (${response.status})` }; }
        
        if (!response.ok) {
            throw new Error(data.detail || 'Błąd dodawania klucza');
        }
        
        await loadUserApiKeys();
        return { success: true };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

async function deleteApiKey(keyId) {
    if (!confirm('Czy na pewno chcesz usunąć ten klucz API?')) return;
    
    try {
        const response = await fetch(`/api/keys/${keyId}`, { method: 'DELETE' });
        if (response.ok) {
            await loadUserApiKeys();
        } else {
            const data = await response.json();
            alert('Błąd: ' + (data.detail || 'Nie udało się usunąć klucza'));
        }
    } catch (error) {
        alert('Błąd: ' + error.message);
    }
}

async function testApiKey(keyId) {
    try {
        setStatus('Testowanie połączenia z Binance...');
        const response = await fetch(`/api/binance/test?key_id=${keyId}`);
        const text = await response.text();
        let data;
        try { data = JSON.parse(text); } catch { data = { detail: text || `Błąd serwera (${response.status})` }; }
        
        if (data.success) {
            alert('✅ Połączenie z Binance działa poprawnie!\n' + (data.message || 'OK'));
            setStatus('Test połączenia: OK');
        } else {
            alert('❌ Błąd połączenia: ' + (data.detail || data.message || 'Nieznany błąd'));
            setStatus('Test połączenia: BŁĄD');
        }
    } catch (error) {
        alert('❌ Błąd: ' + error.message);
        setStatus('Test połączenia: BŁĄD');
    }
}

async function loadBinanceBalances(keyId) {
    const balancesContainer = document.getElementById('binance-balances');
    const portfolioDisplay = document.getElementById('binance-portfolio-value');
    
    if (!keyId) {
        if (balancesContainer) balancesContainer.innerHTML = '<p class="empty-state">Wybierz klucz API aby zobaczyć balans</p>';
        if (portfolioDisplay) portfolioDisplay.classList.add('hidden');
        return;
    }
    
    try {
        if (balancesContainer) balancesContainer.innerHTML = '<p class="empty-state">Ładowanie...</p>';
        
        const [balancesRes, portfolioRes] = await Promise.all([
            fetch(`/api/binance/balances?key_id=${keyId}`),
            fetch(`/api/binance/portfolio?key_id=${keyId}`)
        ]);
        
        const balText = await balancesRes.text();
        const portText = await portfolioRes.text();
        let balancesData, portfolioData;
        try { balancesData = JSON.parse(balText); } catch { balancesData = { detail: balText || `Błąd (${balancesRes.status})` }; }
        try { portfolioData = JSON.parse(portText); } catch { portfolioData = { detail: portText || `Błąd (${portfolioRes.status})` }; }

        if (!balancesRes.ok) {
            throw new Error(balancesData.detail || 'Nie udało się pobrać balansów Binance');
        }
        if (!portfolioRes.ok) {
            throw new Error(portfolioData.detail || 'Nie udało się pobrać portfela Binance');
        }
        
        if (balancesContainer && balancesData.balances) {
            if (balancesData.balances.length === 0) {
                balancesContainer.innerHTML = '<p class="empty-state">Brak środków na koncie</p>';
            } else {
                balancesContainer.innerHTML = balancesData.balances.map(b => `
                    <div class="balance-item">
                        <span class="balance-asset">${b.asset}</span>
                        <span class="balance-amount">${parseFloat(b.free).toFixed(8)}</span>
                    </div>
                `).join('');
            }
        }
        
        if (portfolioDisplay && portfolioData.total_value_usdt !== undefined) {
            portfolioDisplay.classList.remove('hidden');
            portfolioDisplay.querySelector('.value').textContent = 
                `$${parseFloat(portfolioData.total_value_usdt).toFixed(2)} USDT`;
        }
    } catch (error) {
        if (balancesContainer) balancesContainer.innerHTML = `<p class="empty-state">Błąd: ${error.message}</p>`;
    }
}

// Initialize auth UI handlers
function initAuthUI() {
    // Login form
    const loginForm = document.getElementById('login-form');
    const registerForm = document.getElementById('register-form');
    const showRegisterLink = document.getElementById('show-register');
    const showLoginLink = document.getElementById('show-login');
    const skipLoginBtn = document.getElementById('skip-login');
    const authError = document.getElementById('auth-error');
    
    function showError(message) {
        if (authError) {
            authError.textContent = message;
            authError.classList.remove('hidden');
        }
    }
    
    function hideError() {
        if (authError) authError.classList.add('hidden');
    }
    
    if (loginForm) {
        loginForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            hideError();
            const email = document.getElementById('login-email').value;
            const password = document.getElementById('login-password').value;
            
            const result = await handleLogin(email, password);
            if (!result.success) {
                showError(result.error);
            }
        });
    }
    
    if (registerForm) {
        registerForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            hideError();
            const username = document.getElementById('register-username').value;
            const email = document.getElementById('register-email').value;
            const password = document.getElementById('register-password').value;
            
            const result = await handleRegister(username, email, password);
            if (!result.success) {
                showError(result.error);
            }
        });
    }
    
    if (showRegisterLink) {
        showRegisterLink.addEventListener('click', (e) => {
            e.preventDefault();
            hideError();
            loginForm?.classList.add('hidden');
            registerForm?.classList.remove('hidden');
        });
    }
    
    if (showLoginLink) {
        showLoginLink.addEventListener('click', (e) => {
            e.preventDefault();
            hideError();
            registerForm?.classList.add('hidden');
            loginForm?.classList.remove('hidden');
        });
    }
    
    if (skipLoginBtn) {
        skipLoginBtn.addEventListener('click', () => {
            hideLoginScreen();
        });
    }
    
    // User menu dropdown
    const userMenuBtn = document.getElementById('user-menu-btn');
    const userDropdown = document.getElementById('user-dropdown');
    
    if (userMenuBtn && userDropdown) {
        userMenuBtn.addEventListener('click', (e) => {
            e.stopPropagation();
            userDropdown.classList.toggle('hidden');
        });
        
        document.addEventListener('click', () => {
            userDropdown.classList.add('hidden');
        });
    }
    
    // API Key form
    const addApiKeyBtn = document.getElementById('add-api-key-btn');
    const addApiKeyForm = document.getElementById('add-api-key-form');
    const cancelApiKeyBtn = document.getElementById('cancel-api-key');
    
    if (addApiKeyBtn && addApiKeyForm) {
        addApiKeyBtn.addEventListener('click', () => {
            addApiKeyForm.classList.toggle('hidden');
        });
    }
    
    if (cancelApiKeyBtn && addApiKeyForm) {
        cancelApiKeyBtn.addEventListener('click', () => {
            addApiKeyForm.classList.add('hidden');
            addApiKeyForm.reset();
        });
    }
    
    if (addApiKeyForm) {
        addApiKeyForm.addEventListener('submit', async (e) => {
            e.preventDefault();
            const apiKey = document.getElementById('api-key-input').value;
            const apiSecret = document.getElementById('api-secret-input').value;
            const isTestnet = document.getElementById('api-testnet').checked;
            const permissions = document.getElementById('api-permissions').value;
            
            const result = await addApiKey(apiKey, apiSecret, isTestnet, permissions);
            if (result.success) {
                addApiKeyForm.classList.add('hidden');
                addApiKeyForm.reset();
            } else {
                alert('Błąd: ' + result.error);
            }
        });
    }
    
    // Binance key selector
    const binanceKeySelector = document.getElementById('binance-key-selector');
    if (binanceKeySelector) {
        binanceKeySelector.addEventListener('change', (e) => {
            loadBinanceBalances(e.target.value);
        });
    }

    // Live allocation settings
    const allocRadios = document.querySelectorAll('input[name="alloc-mode"]');
    const allocValueRow = document.getElementById('alloc-value-row');
    const allocValueInput = document.getElementById('alloc-value-input');
    const allocValueLabel = document.getElementById('alloc-value-label');
    const saveAllocBtn = document.getElementById('save-alloc-btn');
    const allocStatus = document.getElementById('alloc-status');

    function updateAllocUI() {
        const mode = document.querySelector('input[name="alloc-mode"]:checked')?.value || 'percent';
        if (mode === 'max') {
            allocValueRow.style.display = 'none';
        } else {
            allocValueRow.style.display = '';
            if (mode === 'percent') {
                allocValueLabel.textContent = 'Procent (%)';
                allocValueInput.min = '1';
                allocValueInput.max = '100';
                allocValueInput.step = '1';
            } else {
                allocValueLabel.textContent = 'Kwota (PLN)';
                allocValueInput.min = '1';
                allocValueInput.max = '999999';
                allocValueInput.step = '1';
            }
        }
    }

    allocRadios.forEach(r => r.addEventListener('change', updateAllocUI));

    if (saveAllocBtn) {
        saveAllocBtn.addEventListener('click', async () => {
            const mode = document.querySelector('input[name="alloc-mode"]:checked')?.value || 'percent';
            const value = parseFloat(allocValueInput.value) || 10;
            try {
                const res = await fetch('/api/user/live-allocation', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ mode, value }),
                });
                const data = await res.json();
                if (data.ok) {
                    allocStatus.textContent = '✓ Zapisano';
                    allocStatus.className = 'alloc-status success';
                } else {
                    allocStatus.textContent = data.error || 'Błąd';
                    allocStatus.className = 'alloc-status error';
                }
            } catch {
                allocStatus.textContent = 'Błąd połączenia';
                allocStatus.className = 'alloc-status error';
            }
            setTimeout(() => { allocStatus.textContent = ''; }, 3000);
        });
    }
}

const chartTabs = [
    { id: "overview", label: "Wszystko" },
    { id: "price", label: "Cena" },
    { id: "volume", label: "Wolumen" },
    { id: "rsi", label: "RSI" },
    { id: "macd", label: "MACD" },
];

const historyModes = [
    { id: "recent", label: "Ostatnie 60" },
    { id: "max", label: "Cala historia" },
];

const lifecycleIntervals = [
    { id: "auto", label: "Auto" },
    { id: "1d", label: "1D" },
    { id: "1w", label: "1W" },
    { id: "1m", label: "1M" },
];

const INITIAL_RENDER_RETRY_ATTEMPTS = 6;
const INITIAL_RENDER_RETRY_DELAY_MS = 1500;

async function fetchDashboard() {
    const response = await fetch("/api/dashboard");
    if (!response.ok) {
        throw new Error("Nie udalo sie pobrac dashboardu.");
    }
    return response.json();
}

async function renderDashboard() {
    setStatus("Odswiezanie danych...");
    const payload = await fetchDashboard();
    await applyDashboardPayload(payload, true);
    setStatus(`Ostatnie odswiezenie: ${new Date().toLocaleTimeString("pl-PL")}`);
}

function sleep(ms) {
    return new Promise((resolve) => window.setTimeout(resolve, ms));
}

async function renderDashboardWithRetry(attempts = INITIAL_RENDER_RETRY_ATTEMPTS, delayMs = INITIAL_RENDER_RETRY_DELAY_MS) {
    let lastError = null;
    for (let attempt = 1; attempt <= attempts; attempt += 1) {
        try {
            await renderDashboard();
            return;
        } catch (error) {
            lastError = error;
            if (attempt === attempts) {
                break;
            }
            setStatus(`Ladowanie danych nie powiodlo sie. Ponawiam (${attempt + 1}/${attempts})...`);
            await sleep(delayMs);
        }
    }
    throw lastError;
}

function syncSelectedSymbol(payload) {
    const symbols = (payload.market || []).map((row) => row.symbol);
    if (!symbols.length) {
        selectedSymbol = null;
        return;
    }
    if (!selectedSymbol || !symbols.includes(selectedSymbol)) {
        selectedSymbol = payload.chart_focus_symbol || symbols[0];
    }
}

async function applyDashboardPayload(payload, resetChartCache = true) {
    dashboardState = payload;
    if (resetChartCache) {
        chartPackageCache = {};
    }
    syncSelectedSymbol(payload);
    const isLive = (payload.config?.trading_mode || payload.system_status?.trading_mode) === "LIVE";
    const bw = isLive && payload.binance_wallet ? payload.binance_wallet : null;
    paintWallet(payload.wallet, bw);
    paintModeStrip(payload.system_status, payload.config, payload.wallet);
    paintAgentMode(payload.system_status, payload.config);
    paintCapitalSummary(payload.wallet, bw);
    paintApiUsage(payload.api_usage);
    paintBoughtCoins(bw ? (bw.holdings || []).filter(h => h.value > 1).map(h => ({symbol: h.asset, buy_value: h.value, quantity: h.total, buy_price: h.value / (h.total || 1)})) : payload.wallet.positions);
    paintWatchlist(payload.market);
    paintPrivateLearning(payload.private_learning);
    paintTradeRanking(payload.trade_ranking);
    paintTradeBuckets(payload.recent_trades);
    paintSectorFilters(payload.config);
    paintMarket(payload.market);
    paintPositions(payload.wallet.positions);
    paintDecisions(payload.recent_decisions);
    paintTrades(payload.recent_trades);
    paintLiveOrders(payload.live_orders || []);
    paintChartSelector();
    paintChartTabs();
    paintChartRangeSwitcher();
    paintLifecycleIntervalSwitcher();
    scheduleDashboardAutoRefresh();
    try {
        await renderSelectedChart();
    } catch (error) {
        paintChartError(error.message || "Nie udalo sie zaladowac wykresu.");
    }
    paintLearning(payload.learning);
    paintArticles(payload.articles);
    paintSystemStatus(payload.system_status);
    paintBacktest(payload.backtest);
    syncAllocUI(payload.system_status);
}

function paintChartError(message) {
    document.getElementById("price-chart").innerHTML = "";
    document.getElementById("chart-summary").innerHTML = `<div class="empty-state">${message}</div>`;
    document.getElementById("chart-insights").innerHTML = "";
    setChartHoverState(null);
}

function paintWallet(wallet, binanceWallet) {
    // Update metric labels based on mode
    const metricLabels = {
        "cash-balance": binanceWallet ? `Wolne ${binanceWallet.quote_currency || "USDT"}` : "Gotowka",
        "gross-profit": binanceWallet ? "W krypto" : "Zysk",
        "gross-loss": binanceWallet ? "" : "Strata",
        "realized-profit": binanceWallet ? "Portfel Binance" : "Bilans",
        "buy-count": binanceWallet ? "" : "Kupione",
        "sell-count": binanceWallet ? "" : "Sprzedane",
        "win-rate": binanceWallet ? "" : "Win rate",
    };
    for (const [id, label] of Object.entries(metricLabels)) {
        const el = document.getElementById(id);
        if (el) {
            const labelEl = el.closest(".metric-tile")?.querySelector(".metric-label");
            if (labelEl) labelEl.textContent = label;
            const tile = el.closest(".metric-tile");
            if (tile) tile.style.display = label === "" ? "none" : "";
        }
    }
    if (binanceWallet) {
        const totalValue = binanceWallet.total_value || 0;
        const walletQuote = binanceWallet.quote_currency || "USDT";
        const stableAssets = ["USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"];
        const cashHolding = (binanceWallet.holdings || []).find(h => h.asset === walletQuote) || (binanceWallet.holdings || []).find(h => stableAssets.includes(h.asset));
        const cashValue = cashHolding ? cashHolding.free || 0 : 0;
        const lockedValue = totalValue - cashValue;
        const holdingsCount = (binanceWallet.holdings || []).filter(h => h.value > 1 && !stableAssets.includes(h.asset)).length;
        document.getElementById("cash-balance").textContent = formatQuote(cashValue, walletQuote);
        document.getElementById("equity").textContent = formatQuote(totalValue, walletQuote);
        document.getElementById("open-positions-count").textContent = String(holdingsCount);
        document.getElementById("buy-count").textContent = "–";
        document.getElementById("sell-count").textContent = "–";
        document.getElementById("gross-profit").textContent = formatQuote(lockedValue, walletQuote);
        document.getElementById("gross-loss").textContent = "–";
        document.getElementById("realized-profit").textContent = formatQuote(totalValue, walletQuote);
        document.getElementById("win-rate").textContent = "–";
    } else {
        document.getElementById("cash-balance").textContent = formatQuote(wallet.cash_balance);
        document.getElementById("equity").textContent = formatQuote(wallet.equity);
        document.getElementById("buy-count").textContent = String(wallet.buy_count);
        document.getElementById("sell-count").textContent = String(wallet.sell_count);
        document.getElementById("open-positions-count").textContent = String(wallet.open_positions_count);
        document.getElementById("gross-profit").textContent = formatQuote(wallet.gross_profit);
        document.getElementById("gross-loss").textContent = formatQuote(wallet.gross_loss);
        document.getElementById("realized-profit").textContent = formatQuote(wallet.realized_profit);
        document.getElementById("win-rate").textContent = `${percentFormatter.format(wallet.win_rate)}%`;
    }
    paintQuickSummary(wallet, binanceWallet);
    
    // Mobile hero card update
    const heroBalance = document.getElementById("mobile-hero-balance");
    const heroProfit = document.getElementById("mobile-hero-profit");
    const heroLoss = document.getElementById("mobile-hero-loss");
    const heroWinrate = document.getElementById("mobile-hero-winrate");

    if (binanceWallet) {
        const walletQuote = binanceWallet.quote_currency || "USDT";
        const holdings = binanceWallet.holdings || [];
        const quoteAsset = holdings.find(h => h.asset === walletQuote);
        const cashValue = quoteAsset ? quoteAsset.free : 0;
        const cryptoValue = (binanceWallet.total_value || 0) - cashValue;

        if (heroBalance) {
            heroBalance.textContent = formatQuote(binanceWallet.total_value || 0, walletQuote);
            heroBalance.style.color = "var(--positive)";
        }

        // Relabel mobile hero stats for LIVE
        const heroBalanceLabel = document.querySelector(".mobile-hero-main .mobile-hero-label");
        if (heroBalanceLabel) heroBalanceLabel.textContent = "Portfel Binance";

        const heroStatDivs = document.querySelectorAll(".mobile-hero-stat");
        if (heroStatDivs[0]) heroStatDivs[0].querySelector("span").textContent = `Wolne ${walletQuote}`;
        if (heroStatDivs[1]) heroStatDivs[1].querySelector("span").textContent = "W krypto";
        if (heroStatDivs[2]) heroStatDivs[2].querySelector("span").textContent = "Aktywow";

        if (heroProfit) {
            heroProfit.textContent = formatQuote(cashValue, walletQuote);
            heroProfit.style.color = "var(--positive)";
        }
        if (heroLoss) {
            heroLoss.textContent = formatQuote(cryptoValue, walletQuote);
            heroLoss.style.color = "var(--positive)";
            heroLoss.closest(".mobile-hero-stat")?.classList.remove("negative");
            heroLoss.closest(".mobile-hero-stat")?.classList.add("positive");
        }
        if (heroWinrate) heroWinrate.textContent = holdings.filter(h => h.asset !== walletQuote).length.toString();
    } else {
        if (heroBalance) {
            heroBalance.textContent = formatQuote(wallet.realized_profit);
            heroBalance.style.color = wallet.realized_profit >= 0 ? "var(--positive)" : "var(--negative)";
        }
        if (heroProfit) heroProfit.textContent = formatQuote(wallet.gross_profit);
        if (heroLoss) heroLoss.textContent = formatQuote(wallet.gross_loss);
        if (heroWinrate) heroWinrate.textContent = `${percentFormatter.format(wallet.win_rate)}%`;
    }
}

function paintModeStrip(systemStatus, config, wallet) {
    const container = document.getElementById("mode-strip");
    const scheduler = systemStatus?.scheduler || {};
    const schedulerActive = Boolean(scheduler.active);
    const schedulerHealth = scheduler.health || (schedulerActive ? "active" : scheduler.enabled ? "stale" : "stopped");
    const schedulerLabel = schedulerHealth === "active" ? "DZIALA CALY CZAS" : schedulerHealth === "stale" ? "SCHEDULER UTKNAL" : "AUTO OFF";
    const schedulerTone = schedulerHealth === "active" ? "buy" : schedulerHealth === "stale" ? "sell" : "sell";
    const paperMode = (config?.trading_mode || systemStatus?.trading_mode || "PAPER") === "PAPER";
    const dataSources = (systemStatus?.data_sources || []).join(", ");
    const preferredQuotes = (systemStatus?.preferred_trade_quotes || []).join(" / ");
    const lastClosed = wallet?.last_closed_trade;
    const lastClosedMarkup = lastClosed
        ? `${lastClosed.symbol}: ${formatQuote(lastClosed.profit)} o ${new Date(lastClosed.closed_at).toLocaleTimeString("pl-PL")}`
        : "brak zamknietych transakcji";

    container.innerHTML = `
        <div class="mode-chip-group">
            <span class="status-pill ${paperMode ? "hold" : "sell"}">${paperMode ? "TRYB PAPER" : "TRYB LIVE"}</span>
            <span class="status-pill ${schedulerTone}">${schedulerLabel}</span>
            <span class="status-pill neutral">DANE: ${dataSources || "brak"}</span>
        </div>
        <div class="mode-strip-copy">
            <strong>${paperMode ? "To juz dziala na zywych danych rynkowych, ale handluje tylko wirtualnym kapitalem." : "System jest gotowy do realnych zlecen."}</strong>
            <span>Ostatni zamkniety trade: ${lastClosedMarkup}</span>
            <span>Agent pracuje na parach o najlepszej plynnosci: ${preferredQuotes || "USDT"}. Głowna sciezka to ${config?.quote_currency || "USD"}/${config?.display_currency || config?.quote_currency} w widoku. W trybie LIVE agent automatycznie wykrywa dostepne pary na koncie.</span>
            <div class="mode-live-metrics">
                <span id="cycle-running-counter" class="status-pill neutral">Cykl teraz: -</span>
                <span id="last-cycle-counter" class="status-pill neutral">Ostatni cykl: -</span>
                <span id="next-cycle-counter" class="status-pill neutral">Nastepny cykl: -</span>
                <span id="live-quote-age-counter" class="status-pill neutral">Live quote: -</span>
                <span id="last-decision-counter" class="status-pill neutral">Decyzja: -</span>
                <span class="status-pill neutral">Analiza: ${systemStatus?.market_interval || config?.market_interval || "-"}</span>
                <span class="status-pill neutral">UI refresh: ${config?.dashboard_refresh_seconds || 10}s</span>
            </div>
        </div>
    `;
    updateAgentPulseStrip();
}

function scheduleDashboardAutoRefresh() {
    const refreshSeconds = Math.max(5, Number(dashboardState?.config?.dashboard_refresh_seconds || 10));
    if (dashboardRefreshTimerId !== null) {
        window.clearInterval(dashboardRefreshTimerId);
    }
    dashboardRefreshTimerId = window.setInterval(() => {
        renderDashboard().catch((error) => setStatus(error.message));
    }, refreshSeconds * 1000);
}

function updateAgentPulseStrip() {
    const scheduler = dashboardState?.system_status?.scheduler;
    const marketRows = dashboardState?.market || [];
    const focusRow = marketRows.find((row) => row.symbol === selectedSymbol) || marketRows[0] || null;
    const recentDecisions = dashboardState?.recent_decisions || [];
    const focusDecision = recentDecisions.find((row) => row.symbol === focusRow?.symbol)
        || (focusRow ? {
            symbol: focusRow.symbol,
            decision: focusRow.decision,
            confidence: focusRow.confidence,
            timestamp: focusRow.decision_timestamp,
        } : null);
    const cycleRunningElement = document.getElementById("cycle-running-counter");
    const lastCycleElement = document.getElementById("last-cycle-counter");
    const nextCycleElement = document.getElementById("next-cycle-counter");
    const liveQuoteElement = document.getElementById("live-quote-age-counter");
    const lastDecisionElement = document.getElementById("last-decision-counter");

    if (cycleRunningElement) {
        if (scheduler?.is_running) {
            cycleRunningElement.className = "status-pill hold live-pulse";
            cycleRunningElement.textContent = `Cykl teraz: trwa od ${formatElapsedTime(scheduler?.current_run_started_at)}`;
        } else if (scheduler?.active) {
            cycleRunningElement.className = "status-pill neutral";
            cycleRunningElement.textContent = "Cykl teraz: czeka";
        } else {
            cycleRunningElement.className = "status-pill sell";
            cycleRunningElement.textContent = "Cykl teraz: off";
        }
    }

    if (lastCycleElement) {
        lastCycleElement.textContent = `Ostatni cykl: ${formatRelativeTime(scheduler?.last_run_completed_at)}`;
    }
    if (nextCycleElement) {
        nextCycleElement.textContent = `Nastepny cykl: ${formatNextCycle(scheduler)}`;
    }
    if (liveQuoteElement) {
        const symbolLabel = focusRow?.symbol || "quote";
        liveQuoteElement.textContent = `Live quote ${symbolLabel}: ${formatRelativeTime(focusRow?.timestamp)}`;
    }
    if (lastDecisionElement) {
        const symbolLabel = focusDecision?.symbol || focusRow?.symbol || "coin";
        const decisionLabel = focusDecision?.decision || "-";
        const confidenceLabel = Number.isFinite(Number(focusDecision?.confidence))
            ? ` ${percentFormatter.format(Number(focusDecision.confidence))}%`
            : "";
        lastDecisionElement.className = `status-pill ${decisionToneClass(decisionLabel)}`;
        lastDecisionElement.textContent = `Decyzja ${symbolLabel}: ${decisionLabel}${confidenceLabel} | ${formatRelativeTime(focusDecision?.timestamp)}`;
    }
}

function decisionToneClass(decision) {
    const normalized = String(decision || "").toUpperCase();
    if (normalized === "BUY") {
        return "buy";
    }
    if (normalized === "SELL") {
        return "sell";
    }
    if (normalized === "HOLD") {
        return "hold";
    }
    return "neutral";
}

function formatRelativeTime(timestamp) {
    if (!timestamp) {
        return "-";
    }
    const value = new Date(timestamp);
    if (Number.isNaN(value.getTime())) {
        return "-";
    }
    const deltaSeconds = Math.max(0, Math.floor((Date.now() - value.getTime()) / 1000));
    if (deltaSeconds < 5) {
        return "teraz";
    }
    if (deltaSeconds < 60) {
        return `${deltaSeconds}s temu`;
    }
    const minutes = Math.floor(deltaSeconds / 60);
    if (minutes < 60) {
        return `${minutes} min temu`;
    }
    const hours = Math.floor(minutes / 60);
    return `${hours} h temu`;
}

function formatElapsedTime(timestamp) {
    if (!timestamp) {
        return "-";
    }
    const value = new Date(timestamp);
    if (Number.isNaN(value.getTime())) {
        return "-";
    }
    const deltaSeconds = Math.max(0, Math.floor((Date.now() - value.getTime()) / 1000));
    if (deltaSeconds < 5) {
        return "kilka sekund";
    }
    if (deltaSeconds < 60) {
        return `${deltaSeconds}s`;
    }
    const minutes = Math.floor(deltaSeconds / 60);
    if (minutes < 60) {
        return `${minutes} min`;
    }
    const hours = Math.floor(minutes / 60);
    return `${hours} h`;
}

function formatNextCycle(scheduler) {
    if (!scheduler?.active || !scheduler?.interval_seconds) {
        return "-";
    }
    if (scheduler?.is_running) {
        return "po tym przebiegu";
    }
    const anchor = scheduler.last_run_completed_at || scheduler.last_run_started_at;
    if (!anchor) {
        return "trwa inicjalizacja";
    }
    const anchorTime = new Date(anchor);
    if (Number.isNaN(anchorTime.getTime())) {
        return "-";
    }
    const nextRunMs = anchorTime.getTime() + Number(scheduler.interval_seconds) * 1000;
    const deltaSeconds = Math.ceil((nextRunMs - Date.now()) / 1000);
    if (deltaSeconds <= 0) {
        return "teraz";
    }
    if (deltaSeconds < 60) {
        return `za ${deltaSeconds}s`;
    }
    const minutes = Math.ceil(deltaSeconds / 60);
    return `za ${minutes} min`;
}

function paintAgentMode(systemStatus, config) {
    const container = document.getElementById("agent-mode-switcher");
    const description = document.getElementById("agent-mode-description");
    const profiles = config?.agent_mode_profiles || {};
    const activeMode = systemStatus?.agent_mode || "normal";

    container.innerHTML = Object.entries(profiles).map(([mode, profile]) => `
        <button class="switcher-button ${mode === activeMode ? "active" : ""}" data-mode="${mode}">${profile.label}</button>
    `).join("");

    container.querySelectorAll(".switcher-button").forEach((button) => {
        button.addEventListener("click", async () => {
            await switchAgentMode(button.dataset.mode);
        });
    });

    const profile = profiles[activeMode] || profiles.normal;
    description.innerHTML = profile ? `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>${profile.label}</span>
                <span class="badge neutral">AKTYWNY</span>
            </div>
            <div class="stack-item-meta">
                ${profile.description}<br>
                Limit wejsc dziennie: ${systemStatus.max_trades_per_day}<br>
                Max otwartych pozycji: ${systemStatus.max_open_positions}<br>
                Exploration: ${percentFormatter.format((systemStatus.exploration_rate || 0) * 100)}%
            </div>
        </div>
    ` : "";
}

function paintCapitalSummary(wallet, binanceWallet) {
    const container = document.getElementById("capital-summary");
    if (binanceWallet) {
        const totalValue = binanceWallet.total_value || 0;
        const walletQuote = binanceWallet.quote_currency || "USDT";
        const stableAssets = ["USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"];
        const cashHolding = (binanceWallet.holdings || []).find(h => h.asset === walletQuote) || (binanceWallet.holdings || []).find(h => stableAssets.includes(h.asset));
        const cashValue = cashHolding ? cashHolding.free || 0 : 0;
        const lockedValue = totalValue - cashValue;
        const cryptoHoldings = (binanceWallet.holdings || []).filter(h => h.total > 0 && !stableAssets.includes(h.asset));
        const cashLabel = `Wolne ${walletQuote}`;
        let holdingsHtml = cryptoHoldings.map(h =>
            buildQuickCard(h.asset, formatQuote(h.value, walletQuote), `${h.total.toFixed(6)} szt.`)
        ).join("");
        container.innerHTML = `
            ${buildQuickCard("Portfel Binance", formatQuote(totalValue, walletQuote), "Lacznie wszystkie aktywa na Binance")}
            ${buildQuickCard(cashLabel, formatQuote(cashValue, walletQuote), "Gotowka dostepna do handlu")}
            ${buildQuickCard("W pozycjach", formatQuote(lockedValue, walletQuote), `${cryptoHoldings.length} aktywow w portfelu`)}
            ${holdingsHtml}
        `;
    } else {
        const displayStartPln = dashboardState?.config?.start_balance_display_pln || 1000;
        container.innerHTML = `
            ${buildQuickCard("Start", formatQuote(wallet.starting_balance), `Kapital poczatkowy agenta. Reset przywraca bazowe ${percentFormatter.format(displayStartPln)} PLN.`)}
            ${buildQuickCard("Wydal na zakupy", formatQuote(wallet.spent_on_buys), "Laczna wartosc wejsc BUY")}
            ${buildQuickCard("Wrocilo ze sprzedazy", formatQuote(wallet.capital_returned), "Kapital odzyskany po SELL")}
            ${buildQuickCard("Fee lacznie", formatQuote(wallet.fees_paid), "Prowizje kupna i sprzedazy")}
            ${buildQuickCard("Zostalo gotowki", formatQuote(wallet.cash_balance), "To moze jeszcze wydac agent")}
            ${buildQuickCard("Zablokowane", formatQuote(wallet.capital_locked_cost), "Kapital siedzi w otwartych pozycjach")}
        `;
    }
}

function paintApiUsage(apiUsage) {
    const container = document.getElementById("api-usage-summary");
    if (!apiUsage) {
        container.innerHTML = `<div class="empty-state">Brak danych o zuzyciu API.</div>`;
        return;
    }

    container.innerHTML = `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>OpenAI</span>
                <span class="badge neutral">TOKENY</span>
            </div>
            <div class="stack-item-meta">
                Wywolania: ${apiUsage.calls}<br>
                Input tokens: ${compactNumber(apiUsage.input_tokens)}<br>
                Output tokens: ${compactNumber(apiUsage.output_tokens)}<br>
                Wszystkie tokeny: ${compactNumber(apiUsage.total_tokens)}<br>
                Szacunkowy koszt: ${formatQuote(apiUsage.estimated_cost_usd, "USD")}
            </div>
        </div>
    `;
}

function paintQuickSummary(wallet, binanceWallet) {
    const container = document.getElementById("quick-summary");
    if (!container) {
        return;
    }
    if (binanceWallet) {
        const walletQuote = binanceWallet.quote_currency || "USDT";
        const totalValue = binanceWallet.total_value || 0;
        const stableAssets = ["USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"];
        const cryptoHoldings = (binanceWallet.holdings || []).filter(h => h.total > 0 && !stableAssets.includes(h.asset));
        const cashHolding = (binanceWallet.holdings || []).find(h => h.asset === walletQuote);
        const cashValue = cashHolding ? cashHolding.free || 0 : 0;
        container.innerHTML = `
            ${buildQuickCard("Portfel Binance", formatQuote(totalValue, walletQuote), "Wartosc wszystkich aktywow")}
            ${buildQuickCard(`Wolne ${walletQuote}`, formatQuote(cashValue, walletQuote), "Gotowka do handlu")}
            ${cryptoHoldings.map(h => buildQuickCard(h.asset, `${h.total.toFixed(6)}`, formatQuote(h.value, walletQuote))).join("")}
        `;
        return;
    }
    const lastClosed = wallet.last_closed_trade;
    container.innerHTML = `
        ${buildQuickCard("Co kupil", `${wallet.buy_count} wejsc`, "Kazde BUY otwiera pozycje na wirtualnym kapitalie.")}
        ${buildQuickCard("Co sprzedal", `${wallet.sell_count} wyjsc`, "SELL zamyka pozycje i zapisuje wynik.")}
        ${buildQuickCard("Zysk symulowany", formatQuote(wallet.gross_profit), `${wallet.winning_trades_count} zyskownych transakcji paper trading`) }
        ${buildQuickCard("Strata symulowana", formatQuote(wallet.gross_loss), `${wallet.losing_trades_count} stratnych transakcji paper trading`) }
        ${buildQuickCard("Bilans symulowany", formatQuote(wallet.realized_profit), `Niezrealizowane paper PnL: ${formatQuote(wallet.unrealized_profit)}`) }
        ${buildQuickCard("Ostatni wynik symulowany", lastClosed ? `${lastClosed.symbol} ${formatQuote(lastClosed.profit)}` : "Brak", lastClosed ? new Date(lastClosed.closed_at).toLocaleString("pl-PL") : "Czeka na pierwsze zamkniecie") }
    `;
}

function paintWatchlist(rows) {
    const container = document.getElementById("watchlist-panel");
    if (!container) {
        return;
    }

    const watchRows = [...(rows || [])]
        .sort((left, right) => Math.abs(Number(right.change_24h || 0)) - Math.abs(Number(left.change_24h || 0)))
        .slice(0, 8);

    if (!watchRows.length) {
        container.innerHTML = `<div class="empty-state">Brak danych do watchlisty.</div>`;
        return;
    }

    container.innerHTML = watchRows.map((row) => {
        const change = Number(row.change_24h || 0);
        const toneClass = change >= 0 ? "positive" : "negative";
        const sign = change >= 0 ? "+" : "";
        const isActive = row.symbol === selectedSymbol;
        return `
            <button class="watchlist-row ${isActive ? "active" : ""}" data-symbol="${row.symbol}">
                <span class="watchlist-symbol">${row.symbol}</span>
                <span class="watchlist-price">${formatQuote(row.price)}</span>
                <span class="watchlist-change ${toneClass}">${sign}${percentFormatter.format(change)}%</span>
            </button>
        `;
    }).join("");

    container.querySelectorAll(".watchlist-row").forEach((element) => {
        element.addEventListener("click", async () => {
            selectedSymbol = element.dataset.symbol;
            switchView("charts");
            paintWatchlist(dashboardState?.market || []);
            try {
                await renderSelectedChart();
            } catch (error) {
                setStatus(error.message || "Nie udalo sie przelaczyc wykresu.");
            }
        });
    });
}

function paintPrivateLearning(privateLearning) {
    const container = document.getElementById("private-learning-panel");
    if (!container) {
        return;
    }

    if (!currentUser) {
        container.innerHTML = `<div class="empty-state">Zaloguj sie i dodaj klucz Binance, aby agent uczyl sie tez z Twojego realnego portfela i aktywnosci.</div>`;
        return;
    }

    if (!privateLearning || !privateLearning.enabled) {
        container.innerHTML = `<div class="empty-state">Brak prywatnych danych Binance do nauki. Dodaj aktywny klucz API z uprawnieniem odczytu.</div>`;
        return;
    }

    const holdingsMarkup = (privateLearning.top_holdings || []).slice(0, 4).map((holding) => `
        <div class="stack-item-meta">
            ${holding.asset}: ${formatQuote(holding.value, privateLearning.quote_currency)} | ${percentFormatter.format(holding.weight)}%
        </div>
    `).join("");

    const findingsMarkup = (privateLearning.findings || []).map((finding) => `
        <div class="stack-item-meta">${finding}</div>
    `).join("");

    const nextStepsMarkup = (privateLearning.next_steps || []).map((step) => `
        <div class="stack-item-meta">${step}</div>
    `).join("");

    container.innerHTML = `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Realny portfel</span>
                <span class="badge neutral">${formatQuote(privateLearning.total_value, privateLearning.quote_currency)}</span>
            </div>
            ${holdingsMarkup || '<div class="stack-item-meta">Brak istotnych holdingow.</div>'}
        </div>
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Wnioski dla agenta</span>
                <span class="badge hold">${privateLearning.open_orders_count} open orders</span>
            </div>
            ${findingsMarkup || '<div class="stack-item-meta">Brak dodatkowych wnioskow.</div>'}
        </div>
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Nastepne kroki nauki</span>
                <span class="badge buy">BINANCE</span>
            </div>
            ${nextStepsMarkup}
        </div>
    `;
}

function paintTradeRanking(tradeRanking) {
    const container = document.getElementById("trade-ranking-panel");
    if (!container) {
        return;
    }

    if (!currentUser) {
        container.innerHTML = `<div class="empty-state">Zaloguj sie, aby zobaczyc ranking trade'ow z Binance.</div>`;
        return;
    }

    if (!tradeRanking || !tradeRanking.enabled) {
        container.innerHTML = `<div class="empty-state">Brak historii trade'ow. Dodaj klucz API Binance z uprawnieniem odczytu.</div>`;
        return;
    }

    const summaryMarkup = `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Podsumowanie</span>
                <span class="badge ${tradeRanking.total_realized_pnl >= 0 ? "buy" : "sell"}">${formatQuote(tradeRanking.total_realized_pnl, tradeRanking.quote_currency)}</span>
            </div>
            <div class="stack-item-meta">
                Trade'ow: ${tradeRanking.total_trades} | Zyskowne pary: ${tradeRanking.profitable_pairs} | Stratne: ${tradeRanking.losing_pairs}
            </div>
        </div>
    `;

    const rankingMarkup = (tradeRanking.ranking || []).map((entry, index) => {
        const pnlClass = entry.realized_pnl >= 0 ? "positive" : "negative";
        const sign = entry.realized_pnl >= 0 ? "+" : "";
        return `
            <div class="trade-ranking-row">
                <span class="trade-ranking-rank">#${index + 1}</span>
                <span class="trade-ranking-symbol">${entry.symbol}</span>
                <span class="trade-ranking-count">${entry.trade_count} trades</span>
                <span class="trade-ranking-pnl ${pnlClass}">${sign}${formatQuote(entry.realized_pnl)}</span>
            </div>
        `;
    }).join("");

    const insightsMarkup = (tradeRanking.insights || []).map((insight) => `
        <div class="stack-item-meta">${insight}</div>
    `).join("");

    container.innerHTML = `
        ${summaryMarkup}
        ${rankingMarkup}
        ${insightsMarkup ? `<div class="stack-item"><div class="stack-item-title"><span>Wnioski</span><span class="badge hold">AI</span></div>${insightsMarkup}</div>` : ""}
    `;
}

function paintBoughtCoins(positions) {
    const container = document.getElementById("bought-coins-menu");
    if (!positions.length) {
        container.innerHTML = `<div class="empty-state">Agent nie trzyma teraz zadnego coina.</div>`;
        return;
    }

    container.innerHTML = positions.map((position) => {
        const pnlClass = position.pnl_value >= 0 ? "positive" : "negative";
        return `
            <div class="coin-menu-item">
                <div class="coin-menu-top">
                    <strong>${position.symbol}</strong>
                    <span class="badge buy">KUPIONE</span>
                </div>
                <div class="coin-menu-meta">
                    Ilosc: ${numberFormatter.format(position.quantity)}
                </div>
                <div class="coin-menu-meta">
                    Wejscie: ${formatQuote(position.buy_price)}
                </div>
                <div class="coin-menu-meta">
                    Teraz: ${formatQuote(position.current_price)}
                </div>
                <div class="coin-menu-meta ${pnlClass}">
                    PnL: ${formatQuote(position.pnl_value)}
                </div>
            </div>
        `;
    }).join("");
}

function paintTradeBuckets(trades) {
    const profitContainer = document.getElementById("profit-trades-list");
    const lossContainer = document.getElementById("loss-trades-list");
    const closedTrades = (trades || []).filter((trade) => trade.status === "CLOSED" && trade.profit !== null);
    const profitableTrades = closedTrades.filter((trade) => trade.profit >= 0);
    const losingTrades = closedTrades.filter((trade) => trade.profit < 0);

    profitContainer.innerHTML = profitableTrades.length
        ? profitableTrades.map((trade) => buildTradeBucketItem(trade, true)).join("")
        : `<div class="empty-state">Brak sprzedanych coinow z zyskiem.</div>`;

    lossContainer.innerHTML = losingTrades.length
        ? losingTrades.map((trade) => buildTradeBucketItem(trade, false)).join("")
        : `<div class="empty-state">Brak sprzedanych coinow ze strata.</div>`;
}

function paintMarket(rows) {
    const table = document.getElementById("market-table");
    const visibleRows = filterRowsBySector(rows);
    if (!visibleRows.length) {
        table.innerHTML = `<tr><td colspan="12">Brak danych rynkowych dla wybranego sektora.</td></tr>`;
        return;
    }

    table.innerHTML = visibleRows.map((row) => `
        <tr class="market-row ${row.symbol === selectedSymbol ? "active" : ""}" data-symbol="${row.symbol}">
            <td>${row.symbol}</td>
            <td>${formatQuote(row.price)}</td>
            <td class="${toneClass(row.change_24h)}">${formatSignedPercent(row.change_24h)}</td>
            <td>${percentFormatter.format(row.rsi)}</td>
            <td>${percentFormatter.format(row.macd)}</td>
            <td>${row.trend}</td>
            <td>${percentFormatter.format(row.volume_change)}%</td>
            <td>${percentFormatter.format(row.up_probability)}%</td>
            <td>${percentFormatter.format(row.bottom_probability)}%</td>
            <td>${percentFormatter.format(row.top_probability)}%</td>
            <td><span class="badge ${signalBadgeClass(row.reversal_signal)}">${row.reversal_signal}</span></td>
            <td><span class="badge ${row.decision.toLowerCase()}">${row.decision}</span></td>
        </tr>
    `).join("");

    table.querySelectorAll(".market-row").forEach((row) => {
        row.addEventListener("click", async () => {
            await setSelectedSymbol(row.dataset.symbol);
        });
    });
}

function filterRowsBySector(rows) {
    if (selectedSector === "ALL") {
        return rows;
    }
    const sectorSymbols = dashboardState?.config?.symbol_groups?.[selectedSector] || [];
    return rows.filter((row) => sectorSymbols.includes(row.symbol));
}

function paintSectorFilters(config) {
    const container = document.getElementById("market-sector-filter");
    const groups = config?.symbol_groups || {};
    const options = [{ id: "ALL", label: "Wszystkie" }, ...Object.keys(groups).map((group) => ({ id: group, label: group }))];
    container.innerHTML = options.map((option) => `
        <button class="switcher-button ${option.id === selectedSector ? "active" : ""}" data-sector="${option.id}">${option.label}</button>
    `).join("");

    container.querySelectorAll(".switcher-button").forEach((button) => {
        button.addEventListener("click", () => {
            selectedSector = button.dataset.sector;
            paintSectorFilters(config);
            paintMarket(dashboardState.market);
        });
    });
}

function paintPositions(positions) {
    const container = document.getElementById("positions-list");
    if (!positions.length) {
        container.innerHTML = `<div class="stack-item"><div class="stack-item-meta">Brak otwartych pozycji.</div></div>`;
        return;
    }

    container.innerHTML = positions.map((position) => {
        const pnlClass = position.pnl_value >= 0 ? "positive" : "negative";
        return `
            <div class="stack-item">
                <div class="stack-item-title">
                    <span>${position.symbol}</span>
                    <span class="${pnlClass}">${percentFormatter.format(position.pnl_pct)}%</span>
                </div>
                <div class="stack-item-meta">
                    Ilosc: ${position.quantity}<br>
                    Buy: ${formatQuote(position.buy_price)}<br>
                    Aktualnie: ${formatQuote(position.current_price)}<br>
                    Wycena: ${formatQuote(position.value)}<br>
                    PnL: <span class="${pnlClass}">${formatQuote(position.pnl_value)}</span>
                </div>
            </div>
        `;
    }).join("");
}

function paintDecisions(decisions) {
    const container = document.getElementById("decision-list");
    if (!decisions.length) {
        container.innerHTML = `<div class="stack-item"><div class="stack-item-meta">Brak decyzji.</div></div>`;
        return;
    }

    container.innerHTML = decisions.map((decision) => `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>${decision.symbol}</span>
                <span class="badge ${decision.decision.toLowerCase()}">${decision.decision}</span>
            </div>
            <div class="stack-item-meta">
                Pewnosc: ${percentFormatter.format(decision.confidence)}%<br>
                ${decision.reason}<br>
                ${new Date(decision.timestamp).toLocaleString("pl-PL")}
            </div>
        </div>
    `).join("");
}

function paintTrades(trades) {
    const container = document.getElementById("trade-list");
    if (!trades.length) {
        container.innerHTML = `<div class="stack-item"><div class="stack-item-meta">Brak transakcji.</div></div>`;
        return;
    }

    container.innerHTML = trades.map((trade) => {
        const profitClass = (trade.profit || 0) >= 0 ? "positive" : "negative";
        const tradeBadge = trade.status === "OPEN" ? "buy" : (trade.profit || 0) >= 0 ? "buy" : "sell";
        const tradeLabel = trade.status === "OPEN" ? "KUPIONE" : "SPRZEDANE";
        const profitValue = trade.profit === null ? "W toku" : `<span class="${profitClass}">${formatQuote(trade.profit)}</span>`;
        return `
            <div class="stack-item">
                <div class="stack-item-title">
                    <span>${trade.symbol}</span>
                    <span class="badge ${tradeBadge}">${tradeLabel}</span>
                </div>
                <div class="stack-item-meta">
                    Ilosc: ${numberFormatter.format(trade.quantity)}<br>
                    Kupno: ${formatQuote(trade.buy_price)} | wartosc ${formatQuote(trade.buy_value)} | fee ${formatQuote(trade.buy_fee)}<br>
                    Sprzedaz: ${trade.sell_price === null ? "-" : `${formatQuote(trade.sell_price)} | wartosc ${formatQuote(trade.sell_value)} | fee ${formatQuote(trade.sell_fee)}`}<br>
                    Wynik: ${profitValue}<br>
                    Otwarcie: ${new Date(trade.opened_at).toLocaleString("pl-PL")}<br>
                    Zamkniecie: ${trade.closed_at ? new Date(trade.closed_at).toLocaleString("pl-PL") : "pozycja nadal otwarta"}
                </div>
            </div>
        `;
    }).join("");
}

function setStatus(message) {
    document.getElementById("status-line").textContent = message;
}

function paintLiveOrders(orders) {
    const container = document.getElementById("live-order-list");
    if (!container) return;
    if (!orders.length) {
        container.innerHTML = `<div class="stack-item"><div class="stack-item-meta">Brak prób LIVE.</div></div>`;
        return;
    }
    const statusLabels = { ok: "OK", error: "BŁĄD", skip: "POMINIĘTO", exception: "WYJĄTEK" };
    const statusClasses = { ok: "buy", error: "sell", skip: "hold", exception: "sell" };
    container.innerHTML = orders.map((o) => {
        const badge = statusClasses[o.status] || "hold";
        const label = statusLabels[o.status] || o.status.toUpperCase();
        const detail = o.detail ? `<br>${o.detail}` : "";
        const alloc = o.allocation ? ` | alokacja: ${numberFormatter.format(o.allocation)}` : "";
        const oid = o.order_id ? ` | orderId: ${o.order_id}` : "";
        return `
            <div class="stack-item">
                <div class="stack-item-title">
                    <span>${o.symbol || "—"}</span>
                    <span class="badge ${o.action ? o.action.toLowerCase() : "hold"}">${o.action || "?"}</span>
                    <span class="badge ${badge}">${label}</span>
                </div>
                <div class="stack-item-meta">
                    ${new Date(o.created_at).toLocaleString("pl-PL")}${alloc}${oid}${detail}
                </div>
            </div>`;
    }).join("");
}

async function setSelectedSymbol(symbol) {
    selectedSymbol = symbol;
    if (!dashboardState) {
        return;
    }
    paintMarket(dashboardState.market);
    paintChartSelector();
    updateAgentPulseStrip();
    await renderSelectedChart();
}

function paintChartSelector() {
    const container = document.getElementById("chart-switcher");
    const symbols = (dashboardState?.market || []).map((row) => row.symbol);
    if (!symbols.length) {
        container.innerHTML = `<div class="empty-state">Brak wykresow.</div>`;
        return;
    }

    container.innerHTML = symbols.map((symbol) => `
        <button class="switcher-button ${symbol === selectedSymbol ? "active" : ""}" data-symbol="${symbol}">${symbol}</button>
    `).join("");

    container.querySelectorAll(".switcher-button").forEach((button) => {
        button.addEventListener("click", async () => {
            await setSelectedSymbol(button.dataset.symbol);
        });
    });
}

function paintChartTabs() {
    const container = document.getElementById("chart-tabs");
    container.innerHTML = chartTabs.map((tab) => `
        <button class="switcher-button ${tab.id === selectedChartTab ? "active" : ""}" data-tab="${tab.id}">${tab.label}</button>
    `).join("");

    container.querySelectorAll(".switcher-button").forEach((button) => {
        button.addEventListener("click", async () => {
            selectedChartTab = button.dataset.tab;
            paintChartTabs();
            await renderSelectedChart();
        });
    });
}

function paintChartRangeSwitcher() {
    const container = document.getElementById("chart-range-switcher");
    container.innerHTML = historyModes.map((mode) => `
        <button class="switcher-button ${mode.id === selectedHistoryMode ? "active" : ""}" data-range="${mode.id}">${mode.label}</button>
    `).join("");

    container.querySelectorAll(".switcher-button").forEach((button) => {
        button.addEventListener("click", async () => {
            selectedHistoryMode = button.dataset.range;
            paintChartRangeSwitcher();
            paintLifecycleIntervalSwitcher();
            await renderSelectedChart();
        });
    });
}

function paintLifecycleIntervalSwitcher() {
    const container = document.getElementById("chart-interval-switcher");
    if (selectedHistoryMode !== "max") {
        container.innerHTML = "";
        return;
    }

    container.innerHTML = lifecycleIntervals.map((interval) => `
        <button class="switcher-button ${interval.id === selectedLifecycleInterval ? "active" : ""}" data-interval="${interval.id}">${interval.label}</button>
    `).join("");

    container.querySelectorAll(".switcher-button").forEach((button) => {
        button.addEventListener("click", async () => {
            selectedLifecycleInterval = button.dataset.interval;
            paintLifecycleIntervalSwitcher();
            await renderSelectedChart();
        });
    });
}

async function renderSelectedChart() {
    if (!selectedSymbol) {
        paintChart(null, null);
        return;
    }
    const chartPackage = await fetchChartPackage(selectedSymbol);
    if (selectedHistoryMode === "max" && selectedSymbol) {
        const lifecycleHistory = await fetchLongHistory(selectedSymbol);
        paintChart(chartPackage, lifecycleHistory);
        return;
    }
    paintChart(chartPackage, null);
}

async function fetchChartPackage(symbol) {
    if (chartPackageCache[symbol]) {
        return chartPackageCache[symbol];
    }
    const response = await fetch(`/api/chart-package?symbol=${encodeURIComponent(symbol)}`);
    if (!response.ok) {
        throw new Error(`Nie udalo sie pobrac wykresu ${symbol}.`);
    }
    const payload = await response.json();
    chartPackageCache[symbol] = payload;
    return payload;
}

async function fetchLongHistory(symbol) {
    if (chartHistoryCache[symbol]) {
        return chartHistoryCache[symbol];
    }
    const response = await fetch(`/api/chart-history?symbol=${encodeURIComponent(symbol)}`);
    if (!response.ok) {
        throw new Error(`Nie udalo sie pobrac historii ${symbol}.`);
    }
    const payload = await response.json();
    chartHistoryCache[symbol] = payload;
    return payload;
}

function paintChart(chartPackage, lifecycleHistory) {
    const chart = document.getElementById("price-chart");
    const summary = document.getElementById("chart-summary");
    const insights = document.getElementById("chart-insights");

    if (selectedHistoryMode === "max") {
        paintLifecycleChart(chart, summary, insights, lifecycleHistory, chartPackage);
        return;
    }

    if (!chartPackage || !chartPackage.points?.length) {
        chart.innerHTML = "";
        summary.innerHTML = `<div class="empty-state">Brak danych do analizy wykresu.</div>`;
        insights.innerHTML = "";
        setChartHoverState(null);
        return;
    }

    if (selectedChartTab === "price") {
        paintPriceTab(chart, summary, insights, chartPackage);
        return;
    }
    if (selectedChartTab === "volume") {
        paintVolumeTab(chart, summary, insights, chartPackage);
        return;
    }
    if (selectedChartTab === "rsi") {
        paintRsiTab(chart, summary, insights, chartPackage);
        return;
    }
    if (selectedChartTab === "macd") {
        paintMacdTab(chart, summary, insights, chartPackage);
        return;
    }

    const width = 920;
    const height = 560;
    const paddingX = 44;
    const series = chartPackage.points.slice(-60);
    const panels = {
        price: { top: 38, height: 250 },
        volume: { top: 314, height: 76 },
        rsi: { top: 420, height: 58 },
        macd: { top: 500, height: 48 },
    };
    const priceValues = series.flatMap((point) => [point.low, point.high, point.ema20, point.ema50]);
    const priceMin = Math.min(...priceValues, chartPackage.summary.support);
    const priceMax = Math.max(...priceValues, chartPackage.summary.resistance);
    const volumeMax = Math.max(...series.map((point) => point.volume), 1);
    const rsiMin = 0;
    const rsiMax = 100;
    const macdValues = series.flatMap((point) => [point.macd, point.macd_signal, point.macd_hist, 0]);
    const macdMin = Math.min(...macdValues);
    const macdMax = Math.max(...macdValues);
    const ema20Path = buildPanelLinePath(series, (point) => point.ema20, priceMin, priceMax, width, panels.price, paddingX);
    const ema50Path = buildPanelLinePath(series, (point) => point.ema50, priceMin, priceMax, width, panels.price, paddingX);
    const rsiPath = buildPanelLinePath(series, (point) => point.rsi, rsiMin, rsiMax, width, panels.rsi, paddingX);
    const macdPath = buildPanelLinePath(series, (point) => point.macd, macdMin, macdMax, width, panels.macd, paddingX);
    const macdSignalPath = buildPanelLinePath(series, (point) => point.macd_signal, macdMin, macdMax, width, panels.macd, paddingX);
    const latest = series[series.length - 1];
    const firstDate = series[0].date;
    const lastDate = latest.date;

    chart.innerHTML = `
        ${buildMultiPanelGrid(width, panels, paddingX)}
        ${buildPriceReferenceLine(chartPackage.summary.support, "SUPPORT", "#26a69a", priceMin, priceMax, width, panels.price, paddingX)}
        ${buildPriceReferenceLine(chartPackage.summary.resistance, "RESIST", "#ef5350", priceMin, priceMax, width, panels.price, paddingX)}
        ${buildCandles(series, priceMin, priceMax, width, panels.price, paddingX)}
        <path d="${ema20Path}" fill="none" stroke="#2962ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="${ema50Path}" fill="none" stroke="#ff6d00" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        ${buildVolumeBars(series, volumeMax, width, panels.volume, paddingX)}
        ${buildRsiGuides(width, panels.rsi, paddingX)}
        <path d="${rsiPath}" fill="none" stroke="#f0b44a" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"></path>
        ${buildMacdHistogram(series, macdMin, macdMax, width, panels.macd, paddingX)}
        ${buildMacdZeroLine(macdMin, macdMax, width, panels.macd, paddingX)}
        <path d="${macdPath}" fill="none" stroke="#2962ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="${macdSignalPath}" fill="none" stroke="#ff6d00" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        ${buildPanelLabels(width, panels, paddingX, chartPackage, latest, volumeMax)}
        ${buildChartLegend(width, paddingX)}
        <text x="${paddingX}" y="24" fill="#787b86" font-size="11" font-family="-apple-system,BlinkMacSystemFont,'Trebuchet MS',sans-serif">${chartPackage.symbol} · ${firstDate} – ${lastDate} · ${chartPackage.summary.source}</text>
        <text x="${width - paddingX}" y="24" fill="#d1d4dc" font-size="12" font-weight="600" text-anchor="end">${formatQuote(latest.close)}</text>
    `;
    setChartHoverState(buildIndexChartHoverState({
        points: series,
        width,
        paddingX,
        pricePanel: panels.price,
        priceMin,
        priceMax,
        overlayTop: panels.price.top,
        overlayBottom: panels.macd.top + panels.macd.height,
        symbol: chartPackage.symbol,
        source: chartPackage.summary.source,
    }));

    summary.innerHTML = `
        ${buildSummaryCard("7 dni", `${formatSignedPercent(chartPackage.summary.change_7d)}`, toneClass(chartPackage.summary.change_7d))}
        ${buildSummaryCard("30 dni", `${formatSignedPercent(chartPackage.summary.change_30d)}`, toneClass(chartPackage.summary.change_30d))}
        ${buildSummaryCard("24h", `${formatSignedPercent(chartPackage.summary.change_24h)}`, toneClass(chartPackage.summary.change_24h))}
        ${buildSummaryCard("Zmiennosc 14d", `${percentFormatter.format(chartPackage.summary.volatility_14d)}%`, "")}
        ${buildSummaryCard("Wsparcie", formatQuote(chartPackage.summary.support), "")}
        ${buildSummaryCard("Opor", formatQuote(chartPackage.summary.resistance), "")}
        ${buildSummaryCard("EMA20", formatQuote(chartPackage.summary.ema20), "")}
        ${buildSummaryCard("EMA50", formatQuote(chartPackage.summary.ema50), "")}
        ${buildSummaryCard("RSI", `${percentFormatter.format(chartPackage.summary.rsi)}`, toneClass(50 - chartPackage.summary.rsi))}
        ${buildSummaryCard("MACD", `${percentFormatter.format(chartPackage.summary.macd)}`, toneClass(chartPackage.summary.macd - chartPackage.summary.macd_signal))}
        ${buildSummaryCard("P up", `${percentFormatter.format(chartPackage.summary.up_probability)}%`, toneClass(chartPackage.summary.up_probability - 50))}
        ${buildSummaryCard("P dolek", `${percentFormatter.format(chartPackage.summary.bottom_probability)}%`, toneClass(chartPackage.summary.bottom_probability - 50))}
        ${buildSummaryCard("P szczyt", `${percentFormatter.format(chartPackage.summary.top_probability)}%`, toneClass(50 - chartPackage.summary.top_probability))}
        ${buildSummaryCard("Sygnał", chartPackage.summary.signal_alignment.toUpperCase(), chartPackage.summary.signal_alignment === "bullish" ? "positive" : chartPackage.summary.signal_alignment === "bearish" ? "negative" : "")}
    `;

    const allInsights = [...chartPackage.insights, ...(chartPackage.summary.probability_explanation || [])];
    insights.innerHTML = allInsights.map((item) => `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>${chartPackage.symbol}</span>
                <span class="badge hold">WYKRES</span>
            </div>
            <div class="stack-item-meta">${item}</div>
        </div>
    `).join("");
}

function paintPriceTab(chart, summary, insights, chartPackage) {
    const width = 920;
    const height = 560;
    const paddingX = 44;
    const panel = { top: 56, height: 430 };
    const series = chartPackage.points.slice(-120);
    const minValue = Math.min(...series.map((point) => point.low), chartPackage.summary.support);
    const maxValue = Math.max(...series.map((point) => point.high), chartPackage.summary.resistance);
    const ema20Path = buildPanelLinePath(series, (point) => point.ema20, minValue, maxValue, width, panel, paddingX);
    const ema50Path = buildPanelLinePath(series, (point) => point.ema50, minValue, maxValue, width, panel, paddingX);
    const latest = series[series.length - 1];
    chart.innerHTML = `
        ${buildSinglePanelGrid(width, panel, paddingX)}
        ${buildPriceReferenceLine(chartPackage.summary.support, "SUPPORT", "#26a69a", minValue, maxValue, width, panel, paddingX)}
        ${buildPriceReferenceLine(chartPackage.summary.resistance, "RESIST", "#ef5350", minValue, maxValue, width, panel, paddingX)}
        ${buildCandles(series, minValue, maxValue, width, panel, paddingX)}
        <path d="${ema20Path}" fill="none" stroke="#2962ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="${ema50Path}" fill="none" stroke="#ff6d00" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <text x="${paddingX}" y="28" fill="#787b86" font-size="11">${chartPackage.symbol} · cena · ${series.length} świec</text>
        <text x="${width - paddingX}" y="28" fill="#d1d4dc" font-size="12" font-weight="600" text-anchor="end">${formatQuote(latest.close)}</text>
        ${buildChartLegend(width, paddingX)}
    `;
    setChartHoverState(buildIndexChartHoverState({
        points: series,
        width,
        paddingX,
        pricePanel: panel,
        priceMin: minValue,
        priceMax: maxValue,
        overlayTop: panel.top,
        overlayBottom: panel.top + panel.height,
        symbol: chartPackage.symbol,
        source: chartPackage.summary.source,
    }));
    summary.innerHTML = `
        ${buildSummaryCard("Cena", formatQuote(chartPackage.summary.current_price), "")}
        ${buildSummaryCard("Wsparcie", formatQuote(chartPackage.summary.support), "")}
        ${buildSummaryCard("Opor", formatQuote(chartPackage.summary.resistance), "")}
        ${buildSummaryCard("EMA20", formatQuote(chartPackage.summary.ema20), "")}
        ${buildSummaryCard("EMA50", formatQuote(chartPackage.summary.ema50), "")}
    `;
    insights.innerHTML = `
        <div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">CENA</span></div><div class="stack-item-meta">Tu agent widzi swiece, srednie EMA oraz reakcje na wsparciu i oporze. To jest glowny widok do nauki price action.</div></div>
    `;
}

function paintVolumeTab(chart, summary, insights, chartPackage) {
    const width = 920;
    const height = 560;
    const paddingX = 44;
    const panel = { top: 56, height: 430 };
    const series = chartPackage.points.slice(-120);
    const volumeMax = Math.max(...series.map((point) => point.volume), 1);
    chart.innerHTML = `
        ${buildSinglePanelGrid(width, panel, paddingX)}
        ${buildVolumeBars(series, volumeMax, width, panel, paddingX)}
        <text x="${paddingX}" y="28" fill="#787b86" font-size="11">${chartPackage.symbol} · wolumen</text>
        <text x="${width - paddingX}" y="28" fill="#d1d4dc" font-size="12" font-weight="600" text-anchor="end">max ${compactNumber(volumeMax)}</text>
    `;
    setChartHoverState(null);
    summary.innerHTML = `
        ${buildSummaryCard("Zmiana wolumenu", `${formatSignedPercent(chartPackage.summary.volume_change)}`, toneClass(chartPackage.summary.volume_change))}
        ${buildSummaryCard("Trend", chartPackage.summary.trend, chartPackage.summary.trend === "UP" ? "positive" : chartPackage.summary.trend === "DOWN" ? "negative" : "")}
    `;
    insights.innerHTML = `
        <div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">WOLUMEN</span></div><div class="stack-item-meta">Ten widok pokazuje, czy ruch ceny ma uczestnictwo rynku. Agent powinien uczyc sie odrozniania wybicia z kapitalem od pustego szarpniecia.</div></div>
    `;
}

function paintRsiTab(chart, summary, insights, chartPackage) {
    const width = 920;
    const height = 560;
    const paddingX = 44;
    const panel = { top: 56, height: 430 };
    const series = chartPackage.points.slice(-120);
    const rsiPath = buildPanelLinePath(series, (point) => point.rsi, 0, 100, width, panel, paddingX);
    chart.innerHTML = `
        ${buildSinglePanelGrid(width, panel, paddingX)}
        ${buildRsiGuides(width, panel, paddingX)}
        <path d="${rsiPath}" fill="none" stroke="#f0b44a" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"></path>
        <text x="${paddingX}" y="28" fill="#787b86" font-size="11">${chartPackage.symbol} · RSI</text>
        <text x="${width - paddingX}" y="28" fill="#d1d4dc" font-size="12" font-weight="600" text-anchor="end">RSI ${percentFormatter.format(chartPackage.summary.rsi)}</text>
    `;
    setChartHoverState(null);
    summary.innerHTML = `
        ${buildSummaryCard("RSI", `${percentFormatter.format(chartPackage.summary.rsi)}`, toneClass(50 - chartPackage.summary.rsi))}
        ${buildSummaryCard("Strefa", chartPackage.summary.rsi_zone.toUpperCase(), chartPackage.summary.rsi_zone === "oversold" ? "positive" : chartPackage.summary.rsi_zone === "overbought" ? "negative" : "")}
        ${buildSummaryCard("P dolek", `${percentFormatter.format(chartPackage.summary.bottom_probability)}%`, toneClass(chartPackage.summary.bottom_probability - 50))}
        ${buildSummaryCard("P szczyt", `${percentFormatter.format(chartPackage.summary.top_probability)}%`, toneClass(50 - chartPackage.summary.top_probability))}
    `;
    insights.innerHTML = `
        <div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">RSI</span></div><div class="stack-item-meta">RSI ma byc czytane w kontekscie trendu. Oversold nie oznacza automatycznie BUY, a overbought nie oznacza automatycznie SELL.</div></div>
    `;
}

function paintMacdTab(chart, summary, insights, chartPackage) {
    const width = 920;
    const height = 560;
    const paddingX = 44;
    const panel = { top: 56, height: 430 };
    const series = chartPackage.points.slice(-120);
    const macdValues = series.flatMap((point) => [point.macd, point.macd_signal, point.macd_hist, 0]);
    const minValue = Math.min(...macdValues);
    const maxValue = Math.max(...macdValues);
    const macdPath = buildPanelLinePath(series, (point) => point.macd, minValue, maxValue, width, panel, paddingX);
    const macdSignalPath = buildPanelLinePath(series, (point) => point.macd_signal, minValue, maxValue, width, panel, paddingX);
    chart.innerHTML = `
        ${buildSinglePanelGrid(width, panel, paddingX)}
        ${buildMacdZeroLine(minValue, maxValue, width, panel, paddingX)}
        ${buildMacdHistogram(series, minValue, maxValue, width, panel, paddingX)}
        <path d="${macdPath}" fill="none" stroke="#2962ff" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <path d="${macdSignalPath}" fill="none" stroke="#ff6d00" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"></path>
        <text x="${paddingX}" y="28" fill="#787b86" font-size="11">${chartPackage.symbol} · MACD</text>
        <text x="${width - paddingX}" y="28" fill="#d1d4dc" font-size="12" font-weight="600" text-anchor="end">MACD ${percentFormatter.format(chartPackage.summary.macd)}</text>
        ${buildChartLegend(width, paddingX)}
    `;
    setChartHoverState(null);
    summary.innerHTML = `
        ${buildSummaryCard("MACD", `${percentFormatter.format(chartPackage.summary.macd)}`, toneClass(chartPackage.summary.macd - chartPackage.summary.macd_signal))}
        ${buildSummaryCard("Signal", `${percentFormatter.format(chartPackage.summary.macd_signal)}`, "")}
        ${buildSummaryCard("Stan", chartPackage.summary.macd_state.toUpperCase(), chartPackage.summary.macd_state === "bullish" ? "positive" : "negative")}
        ${buildSummaryCard("P up", `${percentFormatter.format(chartPackage.summary.up_probability)}%`, toneClass(chartPackage.summary.up_probability - 50))}
    `;
    insights.innerHTML = `
        <div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">MACD</span></div><div class="stack-item-meta">MACD pokazuje momentum i zmiane reżimu. Agent powinien laczyc crossover z trendem i wolumenem, zamiast handlowac sam sygnal.</div></div>
    `;
}

function paintLifecycleChart(chart, summary, insights, lifecycleHistory, chartPackage) {
    if (!lifecycleHistory?.points?.length) {
        chart.innerHTML = "";
        summary.innerHTML = `<div class="empty-state">Brak historii od startu coina.</div>`;
        insights.innerHTML = "";
        setChartHoverState(null);
        return;
    }

    const width = 920;
    const paddingX = 44;
    const panels = {
        price: { top: 56, height: 322 },
        volume: { top: 410, height: 76 },
    };
    const lifecycleSeries = buildLifecycleCandles(lifecycleHistory.points, 220, selectedLifecycleInterval);
    const candles = lifecycleSeries.candles;
    const minValue = Math.min(...candles.map((point) => Math.max(point.low, 0.00000001)), lifecycleHistory.summary.atl_price || Number.MAX_VALUE);
    const maxValue = Math.max(...candles.map((point) => point.high), lifecycleHistory.summary.ath_price || 0);
    const volumeMax = Math.max(...candles.map((point) => point.volume || 0), 1);
    const minTimestamp = Math.min(...candles.map((point) => point.timestampValue));
    const maxTimestamp = Math.max(...candles.map((point) => point.timestampValue));
    const athY = projectPanelY(lifecycleHistory.summary.ath_price, minValue, maxValue, panels.price.top, panels.price.height);
    const currentY = projectPanelY(lifecycleHistory.summary.current_price, minValue, maxValue, panels.price.top, panels.price.height);
    chart.innerHTML = `
        ${buildMultiPanelGrid(width, panels, paddingX)}
        ${buildPriceReferenceLine(lifecycleHistory.summary.ath_price, "ATH", "#ef5350", minValue, maxValue, width, panels.price, paddingX)}
        ${buildLifecycleCandlesSvg(candles, minValue, maxValue, width, panels.price, paddingX, minTimestamp, maxTimestamp)}
        ${buildLifecycleVolumeBars(candles, volumeMax, width, panels.volume, paddingX, minTimestamp, maxTimestamp)}
        <line x1="${paddingX}" y1="${athY}" x2="${width - paddingX}" y2="${athY}" stroke="rgba(239,83,80,0.45)" stroke-dasharray="6 4" stroke-width="1"></line>
        <line x1="${paddingX}" y1="${currentY}" x2="${width - paddingX}" y2="${currentY}" stroke="rgba(38,166,154,0.45)" stroke-dasharray="6 4" stroke-width="1"></line>
        ${buildLifecycleYearMarkers(candles, width, panels, paddingX, minTimestamp, maxTimestamp)}
        <text x="${paddingX}" y="28" fill="#787b86" font-size="11">${lifecycleHistory.symbol} · historia · ${lifecycleHistory.summary.start_date} – ${lifecycleHistory.summary.end_date} · ${String(lifecycleHistory.summary.history_source).toUpperCase()} · ${lifecycleSeries.intervalLabel}</text>
        <text x="${width - paddingX}" y="28" fill="#d1d4dc" font-size="12" font-weight="600" text-anchor="end">${formatQuote(lifecycleHistory.summary.current_price)}</text>
        <text x="${paddingX}" y="${athY - 8}" fill="#ef5350" font-size="10">ATH ${formatQuote(lifecycleHistory.summary.ath_price)} · ${lifecycleHistory.summary.ath_date}</text>
        <text x="${paddingX}" y="${currentY - 8}" fill="#26a69a" font-size="10">NOW ${formatQuote(lifecycleHistory.summary.current_price)}</text>
        <text x="${width - paddingX}" y="${panels.volume.top - 10}" fill="#787b86" font-size="11" text-anchor="end">vol max ${compactNumber(volumeMax)}</text>
        ${buildChartLegend(width, paddingX)}
    `;
    setChartHoverState(buildTimeChartHoverState({
        points: candles,
        width,
        paddingX,
        pricePanel: panels.price,
        priceMin: minValue,
        priceMax: maxValue,
        overlayTop: panels.price.top,
        overlayBottom: panels.volume.top + panels.volume.height,
        minTimestamp,
        maxTimestamp,
        symbol: lifecycleHistory.symbol,
        source: lifecycleHistory.summary.history_source,
    }));
    summary.innerHTML = `
        ${buildSummaryCard("Start", formatQuote(lifecycleHistory.summary.inception_price), "")}
        ${buildSummaryCard("Teraz", formatQuote(lifecycleHistory.summary.current_price), "")}
        ${buildSummaryCard("ATH", formatQuote(lifecycleHistory.summary.ath_price), "")}
        ${buildSummaryCard("ATL", formatQuote(lifecycleHistory.summary.atl_price), "")}
        ${buildSummaryCard("Zmiana od startu", `${formatSignedPercent(lifecycleHistory.summary.change_since_inception)}`, toneClass(lifecycleHistory.summary.change_since_inception))}
        ${buildSummaryCard("Lata na rynku", `${numberFormatter.format(lifecycleHistory.summary.years_listed)}`, "")}
        ${buildSummaryCard("Swiece", lifecycleSeries.intervalLabel, "")}
        ${buildSummaryCard("Punkty historii", compactNumber(lifecycleHistory.summary.points_count || lifecycleHistory.points.length), "")}
        ${buildSummaryCard("Zrodlo", String(lifecycleHistory.summary.history_source).toUpperCase(), "")}
    `;
    insights.innerHTML = `
        <div class="stack-item"><div class="stack-item-title"><span>${lifecycleHistory.symbol}</span><span class="badge neutral">OD STARTU</span></div><div class="stack-item-meta">To jest pelna historia oparta przede wszystkim o dzienne OHLC z Binance, a na ekran trafia adaptacyjnie zagregowana wersja ${lifecycleSeries.intervalLabel}, zeby wykres wygladal i czytal sie bardziej jak na Binance.</div></div>
        ${chartPackage ? `<div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge hold">TRYB</span></div><div class="stack-item-meta">Widok "Od startu" pokazuje caly cykl zycia aktywa wraz z wolumenem. Zakladki RSI, MACD i wolumenu nadal sluza do nauki krotszego horyzontu.</div></div>` : ""}
    `;
}

function buildLifecycleCandles(points, maxCandles, forcedInterval = "auto") {
    const normalized = (points || []).map((point) => ({
        date: point.date,
        timestamp: point.timestamp || point.date,
        timestampValue: Date.parse(point.timestamp || point.date),
        open: Number(point.open ?? point.close),
        high: Number(point.high ?? Math.max(point.open ?? point.close, point.close)),
        low: Number(point.low ?? Math.min(point.open ?? point.close, point.close)),
        close: Number(point.close),
        volume: Number(point.volume || 0),
    })).sort((left, right) => left.timestampValue - right.timestampValue);

    if (!normalized.length) {
        return { candles: [], intervalLabel: "-" };
    }

    const bucketDays = forcedInterval === "auto" ? resolveLifecycleBucketDays(normalized, maxCandles) : resolveForcedLifecycleBucketDays(forcedInterval);
    const bucketMs = bucketDays * 24 * 60 * 60 * 1000;
    const startTimestamp = normalized[0].timestampValue;
    const grouped = [];

    normalized.forEach((point) => {
        const bucketIndex = Math.floor((point.timestampValue - startTimestamp) / bucketMs);
        const existing = grouped[grouped.length - 1];
        if (!existing || existing.bucketIndex !== bucketIndex) {
            grouped.push({
                bucketIndex,
                date: point.date,
                timestamp: point.timestamp,
                timestampValue: point.timestampValue,
                open: point.open,
                high: point.high,
                low: point.low,
                close: point.close,
                volume: point.volume,
            });
            return;
        }
        existing.high = Math.max(existing.high, point.high, point.close);
        existing.low = Math.min(existing.low, point.low, point.close);
        existing.close = point.close;
        existing.volume += point.volume;
    });

    const candles = forcedInterval === "auto" && grouped.length > maxCandles ? compressLifecycleCandles(grouped, maxCandles) : grouped;
    return {
        candles,
        intervalLabel: formatLifecycleIntervalLabel(bucketDays),
    };
}

function buildLifecycleCandlesSvg(candles, minValue, maxValue, width, panel, paddingX, minTimestamp, maxTimestamp) {
    return candles.map((point, index) => {
        const x = projectTimeX(point.timestampValue, minTimestamp, maxTimestamp, width, paddingX);
        const nextPoint = candles[Math.min(index + 1, candles.length - 1)];
        const nextX = projectTimeX(nextPoint.timestampValue, minTimestamp, maxTimestamp, width, paddingX);
        const bodyWidth = Math.max(0.8, Math.min(8, Math.abs(nextX - x) * 0.72 || 4));
        const openY = projectPanelY(point.open, minValue, maxValue, panel.top, panel.height);
        const closeY = projectPanelY(point.close, minValue, maxValue, panel.top, panel.height);
        const highY = projectPanelY(point.high, minValue, maxValue, panel.top, panel.height);
        const lowY = projectPanelY(point.low, minValue, maxValue, panel.top, panel.height);
        const isUp = point.close >= point.open;
        const color = isUp ? "#26a69a" : "#ef5350";
        const bodyY = Math.min(openY, closeY);
        const bodyHeight = Math.max(1.2, Math.abs(closeY - openY));
        return `
            <line x1="${x}" y1="${highY}" x2="${x}" y2="${lowY}" stroke="${color}" stroke-width="1.1"></line>
            <rect x="${x - bodyWidth / 2}" y="${bodyY}" width="${bodyWidth}" height="${bodyHeight}" fill="${color}" opacity="0.88" rx="1"></rect>
        `;
    }).join("");
}

function buildLifecycleVolumeBars(points, volumeMax, width, panel, paddingX, minTimestamp, maxTimestamp) {
    return points.map((point, index) => {
        const x = projectTimeX(point.timestampValue, minTimestamp, maxTimestamp, width, paddingX);
        const nextPoint = points[Math.min(index + 1, points.length - 1)];
        const nextX = projectTimeX(nextPoint.timestampValue, minTimestamp, maxTimestamp, width, paddingX);
        const barWidth = Math.max(0.8, Math.min(8, Math.abs(nextX - x) * 0.72 || 4));
        const y = projectPanelY(point.volume || 0, 0, volumeMax, panel.top, panel.height);
        const height = Math.max(1.5, panel.top + panel.height - y);
        const color = point.close >= point.open ? "rgba(38,166,154,0.55)" : "rgba(239,83,80,0.55)";
        return `<rect x="${x - barWidth / 2}" y="${y}" width="${barWidth}" height="${height}" fill="${color}" rx="1"></rect>`;
    }).join("");
}

function buildLifecycleYearMarkers(points, width, panels, paddingX, minTimestamp, maxTimestamp) {
    const markers = [];
    const seenYears = new Set();
    points.forEach((point, index) => {
        const year = point.date.slice(0, 4);
        if (seenYears.has(year)) {
            return;
        }
        if (!point.date.endsWith("-01-01") && index !== 0) {
            return;
        }
        seenYears.add(year);
        const x = projectTimeX(point.timestampValue, minTimestamp, maxTimestamp, width, paddingX);
        markers.push(`
            <line x1="${x}" y1="${panels.price.top}" x2="${x}" y2="${panels.volume.top + panels.volume.height}" stroke="rgba(42,46,57,0.8)" stroke-dasharray="3 6" stroke-width="1"></line>
            <text x="${x}" y="${panels.volume.top + panels.volume.height + 18}" fill="#787b86" font-size="10" text-anchor="middle">${year}</text>
        `);
    });
    return markers.join("");
}

function resolveLifecycleBucketDays(points, maxCandles) {
    if (points.length <= maxCandles) {
        return 1;
    }
    const firstTimestamp = points[0].timestampValue;
    const lastTimestamp = points[points.length - 1].timestampValue;
    const totalDays = Math.max(1, Math.round((lastTimestamp - firstTimestamp) / 86400000) + 1);
    const targetBucketDays = Math.ceil(totalDays / maxCandles);
    const supportedBuckets = [1, 3, 7, 14, 30, 60, 90, 180];
    return supportedBuckets.find((value) => targetBucketDays <= value) || supportedBuckets[supportedBuckets.length - 1];
}

function resolveForcedLifecycleBucketDays(intervalId) {
    const mapping = {
        "1d": 1,
        "1w": 7,
        "1m": 30,
    };
    return mapping[intervalId] || 1;
}

function formatLifecycleIntervalLabel(bucketDays) {
    if (bucketDays === 1) {
        return "1D";
    }
    if (bucketDays === 7) {
        return "1W";
    }
    if (bucketDays === 14) {
        return "2W";
    }
    if (bucketDays === 30) {
        return "1M";
    }
    if (bucketDays === 60) {
        return "2M";
    }
    if (bucketDays === 90) {
        return "3M";
    }
    if (bucketDays === 180) {
        return "6M";
    }
    return `${bucketDays}D`;
}

function compressLifecycleCandles(points, maxCandles) {
    const bucketSize = Math.ceil(points.length / maxCandles);
    const compressed = [];
    for (let index = 0; index < points.length; index += bucketSize) {
        const slice = points.slice(index, index + bucketSize);
        compressed.push({
            bucketIndex: slice[0].bucketIndex,
            date: slice[0].date,
            timestamp: slice[0].timestamp,
            timestampValue: slice[0].timestampValue,
            open: slice[0].open,
            high: Math.max(...slice.map((item) => item.high)),
            low: Math.min(...slice.map((item) => item.low)),
            close: slice[slice.length - 1].close,
            volume: slice.reduce((sum, item) => sum + item.volume, 0),
        });
    }
    return compressed;
}

function buildIndexChartHoverState({ points, width, paddingX, pricePanel, priceMin, priceMax, overlayTop, overlayBottom, symbol, source }) {
    return {
        width,
        paddingX,
        overlayTop,
        overlayBottom,
        symbol,
        source,
        points: points.map((point, index) => ({
            ...point,
            x: projectX(index, points.length, width, paddingX),
            closeY: projectPanelY(point.close, priceMin, priceMax, pricePanel.top, pricePanel.height),
        })),
    };
}

function buildTimeChartHoverState({ points, width, paddingX, pricePanel, priceMin, priceMax, overlayTop, overlayBottom, minTimestamp, maxTimestamp, symbol, source }) {
    return {
        width,
        paddingX,
        overlayTop,
        overlayBottom,
        symbol,
        source,
        points: points.map((point) => ({
            ...point,
            x: projectTimeX(point.timestampValue, minTimestamp, maxTimestamp, width, paddingX),
            closeY: projectPanelY(point.close, priceMin, priceMax, pricePanel.top, pricePanel.height),
        })),
    };
}

function setChartHoverState(state) {
    chartHoverState = state;
    initChartHoverInteractions();
    clearChartHover();
}

function initChartHoverInteractions() {
    if (chartHoverHandlersBound) {
        return;
    }
    const chart = document.getElementById("price-chart");
    if (!chart) {
        return;
    }
    chart.addEventListener("mousemove", handleChartHoverMove);
    chart.addEventListener("mouseleave", clearChartHover);
    chartHoverHandlersBound = true;
}

function handleChartHoverMove(event) {
    if (!chartHoverState?.points?.length) {
        clearChartHover();
        return;
    }

    const chart = document.getElementById("price-chart");
    const rect = chart.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * chartHoverState.width;
    const point = findNearestHoverPoint(x, chartHoverState.points);
    if (!point) {
        clearChartHover();
        return;
    }
    renderChartHover(point);
}

function findNearestHoverPoint(targetX, points) {
    let bestPoint = null;
    let bestDistance = Number.POSITIVE_INFINITY;
    points.forEach((point) => {
        const distance = Math.abs(point.x - targetX);
        if (distance < bestDistance) {
            bestDistance = distance;
            bestPoint = point;
        }
    });
    return bestPoint;
}

function renderChartHover(point) {
    const overlay = document.getElementById("chart-overlay");
    const panel = document.getElementById("chart-hover-panel");
    if (!overlay || !panel || !chartHoverState) {
        return;
    }

    panel.className = point.x > chartHoverState.width * 0.58 ? "chart-hover-panel visible right" : "chart-hover-panel visible";
    panel.innerHTML = `
        <div class="chart-hover-head">
            <span>${chartHoverState.symbol}</span>
            <span class="badge neutral">${String(chartHoverState.source || "-").toUpperCase()}</span>
        </div>
        <div class="chart-hover-date">${formatHoverDate(point.timestamp || point.date)}</div>
        <div class="chart-hover-grid">
            <div class="chart-hover-item"><span>Open</span><strong>${formatQuote(point.open)}</strong></div>
            <div class="chart-hover-item"><span>High</span><strong>${formatQuote(point.high)}</strong></div>
            <div class="chart-hover-item"><span>Low</span><strong>${formatQuote(point.low)}</strong></div>
            <div class="chart-hover-item"><span>Close</span><strong>${formatQuote(point.close)}</strong></div>
            <div class="chart-hover-item"><span>Wolumen</span><strong>${compactNumber(point.volume || 0)}</strong></div>
            <div class="chart-hover-item"><span>Zmiana</span><strong class="${toneClass(point.close - point.open)}">${formatSignedPercent(((point.close - point.open) / (point.open || 1)) * 100)}</strong></div>
        </div>
    `;

    overlay.innerHTML = `
        <line x1="${point.x}" y1="${chartHoverState.overlayTop}" x2="${point.x}" y2="${chartHoverState.overlayBottom}" stroke="rgba(120,123,134,0.4)" stroke-dasharray="4 4" stroke-width="1"></line>
        <line x1="${chartHoverState.paddingX}" y1="${point.closeY}" x2="${chartHoverState.width - chartHoverState.paddingX}" y2="${point.closeY}" stroke="rgba(120,123,134,0.3)" stroke-dasharray="4 4" stroke-width="1"></line>
        <circle cx="${point.x}" cy="${point.closeY}" r="4" fill="#131722" stroke="#2962ff" stroke-width="2"></circle>
    `;
}

function clearChartHover() {
    const overlay = document.getElementById("chart-overlay");
    const panel = document.getElementById("chart-hover-panel");
    if (overlay) {
        overlay.innerHTML = "";
    }
    if (panel) {
        panel.className = "chart-hover-panel";
        panel.innerHTML = "";
    }
}

function formatHoverDate(value) {
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) {
        return String(value || "-");
    }
    return parsed.toLocaleDateString("pl-PL", { year: "numeric", month: "short", day: "2-digit" });
}

function projectTimeX(timestampValue, minTimestamp, maxTimestamp, width, padding) {
    if (maxTimestamp <= minTimestamp) {
        return width / 2;
    }
    return padding + ((width - padding * 2) * (timestampValue - minTimestamp)) / (maxTimestamp - minTimestamp);
}

function buildSinglePanelGrid(width, panel, paddingX) {
    const rows = 5;
    const columns = 6;
    const horizontal = Array.from({ length: rows + 1 }, (_, index) => {
        const y = panel.top + (panel.height / rows) * index;
        return `<line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="rgba(42,46,57,0.6)" stroke-width="1"></line>`;
    }).join("");
    const vertical = Array.from({ length: columns + 1 }, (_, index) => {
        const x = paddingX + ((width - paddingX * 2) / columns) * index;
        return `<line x1="${x}" y1="${panel.top}" x2="${x}" y2="${panel.top + panel.height}" stroke="rgba(42,46,57,0.4)" stroke-width="1"></line>`;
    }).join("");
    return horizontal + vertical;
}

function buildMultiPanelGrid(width, panels, paddingX) {
    const columnCount = 6;
    const panelEntries = Object.values(panels);
    const verticalLines = Array.from({ length: columnCount + 1 }, (_, index) => {
        const x = paddingX + ((width - paddingX * 2) / columnCount) * index;
        return `<line x1="${x}" y1="${panelEntries[0].top}" x2="${x}" y2="${panelEntries[panelEntries.length - 1].top + panelEntries[panelEntries.length - 1].height}" stroke="rgba(42,46,57,0.4)" stroke-width="1"></line>`;
    }).join("");
    const horizontalLines = panelEntries.map((panel) => {
        const rows = panel === panels.price ? 4 : 2;
        return Array.from({ length: rows + 1 }, (_, index) => {
            const y = panel.top + (panel.height / rows) * index;
            return `<line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="rgba(42,46,57,0.6)" stroke-width="1"></line>`;
        }).join("");
    }).join("");
    return `${verticalLines}${horizontalLines}`;
}

function buildPanelLinePath(points, accessor, minValue, maxValue, width, panel, paddingX) {
    return points.map((point, index) => {
        const x = projectX(index, points.length, width, paddingX);
        const y = projectPanelY(accessor(point), minValue, maxValue, panel.top, panel.height);
        return `${index === 0 ? "M" : "L"} ${x.toFixed(2)} ${y.toFixed(2)}`;
    }).join(" ");
}

function projectX(index, total, width, padding) {
    if (total <= 1) {
        return width / 2;
    }
    return padding + ((width - padding * 2) * index) / (total - 1);
}

function projectPanelY(value, minValue, maxValue, panelTop, panelHeight) {
    if (maxValue === minValue) {
        return panelTop + panelHeight / 2;
    }
    const normalized = (value - minValue) / (maxValue - minValue);
    return panelTop + panelHeight - normalized * panelHeight;
}

function buildCandles(points, minValue, maxValue, width, panel, paddingX) {
    const step = (width - paddingX * 2) / Math.max(points.length, 1);
    const candleWidth = Math.max(3, Math.min(10, step * 0.62));
    return points.map((point, index) => {
        const x = projectX(index, points.length, width, paddingX);
        const openY = projectPanelY(point.open, minValue, maxValue, panel.top, panel.height);
        const closeY = projectPanelY(point.close, minValue, maxValue, panel.top, panel.height);
        const highY = projectPanelY(point.high, minValue, maxValue, panel.top, panel.height);
        const lowY = projectPanelY(point.low, minValue, maxValue, panel.top, panel.height);
        const isUp = point.close >= point.open;
        const color = isUp ? "#26a69a" : "#ef5350";
        const bodyY = Math.min(openY, closeY);
        const bodyHeight = Math.max(1.5, Math.abs(closeY - openY));
        return `
            <line x1="${x}" y1="${highY}" x2="${x}" y2="${lowY}" stroke="${color}" stroke-width="1.4"></line>
            <rect x="${x - candleWidth / 2}" y="${bodyY}" width="${candleWidth}" height="${bodyHeight}" fill="${color}" opacity="0.9" rx="1"></rect>
        `;
    }).join("");
}

function buildVolumeBars(points, maxVolume, width, panel, paddingX) {
    const step = (width - paddingX * 2) / Math.max(points.length, 1);
    const barWidth = Math.max(3, Math.min(10, step * 0.62));
    return points.map((point, index) => {
        const x = projectX(index, points.length, width, paddingX);
        const barHeight = (point.volume / maxVolume) * panel.height;
        const y = panel.top + panel.height - barHeight;
        const color = point.close >= point.open ? "rgba(38,166,154,0.55)" : "rgba(239,83,80,0.55)";
        return `<rect x="${x - barWidth / 2}" y="${y}" width="${barWidth}" height="${Math.max(1.5, barHeight)}" fill="${color}" rx="1"></rect>`;
    }).join("");
}

function buildRsiGuides(width, panel, paddingX) {
    const levels = [30, 50, 70];
    return levels.map((level) => {
        const y = projectPanelY(level, 0, 100, panel.top, panel.height);
        return `
            <line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="rgba(42,46,57,0.8)" stroke-dasharray="4 4" stroke-width="1"></line>
            <text x="${width - paddingX + 4}" y="${y + 4}" fill="#787b86" font-size="10">${level}</text>
        `;
    }).join("");
}

function buildMacdHistogram(points, minValue, maxValue, width, panel, paddingX) {
    const step = (width - paddingX * 2) / Math.max(points.length, 1);
    const barWidth = Math.max(2, Math.min(8, step * 0.52));
    const zeroY = projectPanelY(0, minValue, maxValue, panel.top, panel.height);
    return points.map((point, index) => {
        const x = projectX(index, points.length, width, paddingX);
        const valueY = projectPanelY(point.macd_hist, minValue, maxValue, panel.top, panel.height);
        const y = Math.min(zeroY, valueY);
        const height = Math.max(1.2, Math.abs(valueY - zeroY));
        const color = point.macd_hist >= 0 ? "rgba(38,166,154,0.7)" : "rgba(239,83,80,0.7)";
        return `<rect x="${x - barWidth / 2}" y="${y}" width="${barWidth}" height="${height}" fill="${color}" rx="1"></rect>`;
    }).join("");
}

function buildMacdZeroLine(minValue, maxValue, width, panel, paddingX) {
    const y = projectPanelY(0, minValue, maxValue, panel.top, panel.height);
    return `<line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="rgba(42,46,57,0.8)" stroke-dasharray="4 4" stroke-width="1"></line>`;
}

function buildPriceReferenceLine(value, label, color, minValue, maxValue, width, panel, paddingX) {
    const y = projectPanelY(value, minValue, maxValue, panel.top, panel.height);
    return `
        <line x1="${paddingX}" y1="${y}" x2="${width - paddingX}" y2="${y}" stroke="${color}" stroke-dasharray="6 4" stroke-width="1"></line>
        <text x="${paddingX}" y="${y - 6}" fill="${color}" font-size="10">${label} ${formatQuote(value)}</text>
    `;
}

function buildPanelLabels(width, panels, paddingX, chartPackage, latest, volumeMax) {
    const volumeLabel = compactNumber(volumeMax);
    return `
        <text x="${paddingX}" y="${panels.price.top - 10}" fill="#d1d4dc" font-size="11" font-weight="600">Price + EMA</text>
        <text x="${paddingX}" y="${panels.volume.top - 10}" fill="#d1d4dc" font-size="11" font-weight="600">Volume</text>
        <text x="${width - paddingX}" y="${panels.volume.top - 10}" fill="#787b86" font-size="10" text-anchor="end">max ${volumeLabel}</text>
        <text x="${paddingX}" y="${panels.rsi.top - 10}" fill="#d1d4dc" font-size="11" font-weight="600">RSI ${percentFormatter.format(chartPackage.summary.rsi)}</text>
        <text x="${paddingX}" y="${panels.macd.top - 10}" fill="#d1d4dc" font-size="11" font-weight="600">MACD ${percentFormatter.format(chartPackage.summary.macd)}</text>
        <text x="${width - paddingX}" y="${panels.macd.top - 10}" fill="#787b86" font-size="10" text-anchor="end">sig ${percentFormatter.format(chartPackage.summary.macd_signal)}</text>
        <text x="${width - paddingX}" y="${panels.price.top - 10}" fill="#787b86" font-size="10" text-anchor="end">${formatQuote(latest.close)}</text>
    `;
}

function buildChartLegend(width, paddingX) {
    const items = [
        { label: "EMA20", color: "#2962ff" },
        { label: "EMA50", color: "#ff6d00" },
        { label: "RSI", color: "#f0b44a" },
        { label: "MACD", color: "#2962ff" },
        { label: "Signal", color: "#ff6d00" },
    ];
    return items.map((item, index) => {
        const x = paddingX + index * 86;
        return `
            <line x1="${x}" y1="548" x2="${x + 16}" y2="548" stroke="${item.color}" stroke-width="2"></line>
            <text x="${x + 22}" y="552" fill="#787b86" font-size="10">${item.label}</text>
        `;
    }).join("");
}

function compactNumber(value) {
    if (value >= 1_000_000_000) {
        return `${numberFormatter.format(value / 1_000_000_000)}B`;
    }
    if (value >= 1_000_000) {
        return `${numberFormatter.format(value / 1_000_000)}M`;
    }
    if (value >= 1_000) {
        return `${numberFormatter.format(value / 1_000)}K`;
    }
    return numberFormatter.format(value);
}

function buildSummaryCard(label, value, extraClass) {
    return `
        <div class="summary-card ${extraClass}">
            <span>${label}</span>
            <strong class="${extraClass}">${value}</strong>
        </div>
    `;
}

function buildQuickCard(label, value, description) {
    return `
        <div class="quick-card">
            <span>${label}</span>
            <strong>${value}</strong>
            <small>${description}</small>
        </div>
    `;
}

function buildTradeBucketItem(trade, isProfit) {
    return `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>${trade.symbol}</span>
                <span class="badge ${isProfit ? "buy" : "sell"}">${isProfit ? "PLUS" : "MINUS"}</span>
            </div>
            <div class="stack-item-meta">
                Kupno: ${formatQuote(trade.buy_price)}<br>
                Sprzedaz: ${trade.sell_price === null ? "-" : formatQuote(trade.sell_price)}<br>
                Wynik: <span class="${isProfit ? "positive" : "negative"}">${formatQuote(trade.profit)}</span><br>
                Zamkniecie: ${trade.closed_at ? new Date(trade.closed_at).toLocaleString("pl-PL") : "-"}
            </div>
        </div>
    `;
}

function paintLearning(learning) {
    const findings = document.getElementById("learning-findings");
    const curriculum = document.getElementById("learning-curriculum");
    const nextSteps = document.getElementById("learning-next-steps");
    const knowledgeBase = document.getElementById("learning-knowledge-base");
    const requirements = document.getElementById("learning-requirements");

    findings.innerHTML = (learning.findings || []).map((item) => `
        <div class="stack-item">
            <div class="stack-item-title"><span>${item.title}</span></div>
            <div class="stack-item-meta">${item.description}</div>
        </div>
    `).join("");

    curriculum.innerHTML = (learning.curriculum || []).map((item) => `
        <div class="stack-item">
            <div class="stack-item-title"><span>${item.title}</span></div>
            <div class="stack-item-meta">${item.description}</div>
        </div>
    `).join("");

    nextSteps.innerHTML = (learning.next_steps || []).map((item) => `
        <div class="stack-item">
            <div class="stack-item-title"><span>Nastepny eksperyment</span></div>
            <div class="stack-item-meta">${item}</div>
        </div>
    `).join("");

    knowledgeBase.innerHTML = (learning.knowledge_base || []).map((item) => `
        <div class="stack-item">
            <div class="stack-item-title"><span>${item.title}</span></div>
            <div class="stack-item-meta">${item.description}</div>
        </div>
    `).join("");

    requirements.innerHTML = (learning.requirements || []).map((item) => `
        <div class="stack-item">
            <div class="stack-item-title"><span>${item.title}</span></div>
            <div class="stack-item-meta">${item.description}</div>
        </div>
    `).join("");
}

function paintArticles(articles) {
    const container = document.getElementById("article-list");
    if (!articles?.length) {
        container.innerHTML = `<div class="empty-state">Brak materialow edukacyjnych.</div>`;
        return;
    }

    container.innerHTML = articles.map((article) => `
        <article class="article-card">
            <div class="article-meta">${article.source}</div>
            <h3>${article.title}</h3>
            <p>${article.summary}</p>
            <a class="article-link" href="${article.url}" target="_blank" rel="noreferrer">Otworz artykul</a>
        </article>
    `).join("");
}

function paintSystemStatus(systemStatus) {
    const container = document.getElementById("system-status");
    if (!systemStatus) {
        container.innerHTML = `<div class="empty-state">Brak statusu systemu.</div>`;
        return;
    }

    const scheduler = systemStatus.scheduler || {};
    const schedulerActive = Boolean(scheduler.active);
    const schedulerHealth = scheduler.health || (schedulerActive ? "active" : scheduler.enabled ? "stale" : "stopped");
    document.getElementById("scheduler-button").textContent = schedulerActive ? "Zatrzymaj scheduler" : scheduler.enabled ? "Napraw scheduler" : "Start scheduler";

    container.innerHTML = `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Scheduler</span>
                <span class="badge ${schedulerHealth === "active" ? "buy" : schedulerHealth === "stale" ? "sell" : "hold"}">${schedulerHealth === "active" ? "AKTYWNY" : schedulerHealth === "stale" ? "UTKNAL" : "STOP"}</span>
            </div>
            <div class="stack-item-meta">
                Interwal: ${scheduler.interval_seconds || "-"} s<br>
                Ostatni start: ${scheduler.last_run_started_at || "-"}<br>
                Ostatnie zakonczenie: ${scheduler.last_run_completed_at || "-"}<br>
                Worker zyje: ${scheduler.thread_alive ? "tak" : "nie"}<br>
                Watchdog zyje: ${scheduler.watchdog_alive ? "tak" : "nie"}<br>
                Liczba automatycznych cykli: ${scheduler.total_runs || 0}${scheduler.last_error ? `<br>Info: ${scheduler.last_error}` : ""}
            </div>
        </div>
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Tryb pracy</span>
                <span class="badge ${systemStatus.trading_mode === "PAPER" ? "hold" : "sell"}">${systemStatus.trading_mode}</span>
            </div>
            <div class="stack-item-meta">
                Learning mode: ${systemStatus.learning_mode ? "aktywny" : "wylaczony"}<br>
                Exploration rate: ${percentFormatter.format((systemStatus.exploration_rate || 0) * 100)}%<br>
                Interwal rynku: ${systemStatus.market_interval}<br>
                Quote: ${systemStatus.quote_currency}<br>
                Coiny w watchliscie: ${systemStatus.tracked_symbols_count}<br>
                Max trade/day: ${systemStatus.max_trades_per_day}<br>
                Max open positions: ${systemStatus.max_open_positions}
            </div>
        </div>
        <div class="stack-item">
            <div class="stack-item-title">
                <span>Zrodla danych</span>
                <span class="badge neutral">LIVE</span>
            </div>
            <div class="stack-item-meta">
                ${(systemStatus.data_sources || []).join(", ")}<br>
                Binance private API: ${systemStatus.binance_private_ready ? "gotowe" : "brak kluczy, tylko publiczne dane/paper trading"}<br>
                PLN FX: ${dashboardState?.config?.display_rate_source || "-"}<br>
                Ostatnie ceny moga minimalnie roznic sie od Bing lub CoinGecko, bo panel bierze kurs z gield crypto i przelicza go do PLN oddzielnym live FX.
            </div>
        </div>
    `;
}

function syncAllocUI(systemStatus) {
    if (!systemStatus) return;
    const mode = systemStatus.live_alloc_mode || 'percent';
    const value = systemStatus.live_alloc_value || 10;
    const radio = document.querySelector(`input[name="alloc-mode"][value="${mode}"]`);
    if (radio) radio.checked = true;
    const input = document.getElementById('alloc-value-input');
    if (input) input.value = value;
    const allocValueRow = document.getElementById('alloc-value-row');
    const allocValueLabel = document.getElementById('alloc-value-label');
    if (allocValueRow) {
        allocValueRow.style.display = mode === 'max' ? 'none' : '';
    }
    if (allocValueLabel) {
        allocValueLabel.textContent = mode === 'percent' ? 'Procent (%)' : 'Kwota (PLN)';
    }
}

function paintBacktest(backtest) {
    const container = document.getElementById("backtest-ranking");
    if (!backtest?.rankings?.length) {
        container.innerHTML = `<div class="empty-state">Brak wynikow backtestu.</div>`;
        return;
    }

    container.innerHTML = backtest.rankings.map((row, index) => `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>${index + 1}. ${row.label}</span>
                <span class="badge ${index === 0 ? "buy" : "neutral"}">ROI ${formatSignedPercent(row.roi)}</span>
            </div>
            <div class="stack-item-meta">
                Profit: ${formatQuote(row.profit)}<br>
                Win rate: ${percentFormatter.format(row.win_rate)}%<br>
                Trades: ${row.trades}<br>
                Max drawdown: ${percentFormatter.format(row.max_drawdown)}%<br>
                Testowane symbole: ${row.symbols_tested}
            </div>
        </div>
    `).join("");
}

function toneClass(value) {
    if (value > 0) {
        return "positive";
    }
    if (value < 0) {
        return "negative";
    }
    return "";
}

function formatSignedPercent(value) {
    const prefix = value > 0 ? "+" : "";
    return `${prefix}${percentFormatter.format(value)}%`;
}

function formatQuote(value, sourceCurrency = null) {
    const quoteCurrency = sourceCurrency || dashboardState?.config?.quote_currency || "USD";
    const displayCurrency = dashboardState?.config?.display_currency || quoteCurrency;
    const convertedValue = convertCurrency(value, quoteCurrency, displayCurrency);
    if (["USD", "PLN", "EUR", "GBP"].includes(displayCurrency)) {
        return new Intl.NumberFormat("pl-PL", {
            style: "currency",
            currency: displayCurrency,
            maximumFractionDigits: Math.abs(convertedValue) < 1 ? 4 : 2,
        }).format(convertedValue);
    }
    return `${numberFormatter.format(convertedValue)} ${displayCurrency}`;
}

function convertCurrency(value, sourceCurrency, targetCurrency) {
    if (value === null || value === undefined) {
        return value;
    }
    if (sourceCurrency === targetCurrency) {
        return value;
    }
    const rates = dashboardState?.config?.display_fx_rates || {};
    const key = `${String(sourceCurrency).toUpperCase()}_${String(targetCurrency).toUpperCase()}`;
    const rate = rates[key] || 1;
    return Number(value) * rate;
}

function signalBadgeClass(signal) {
    if (signal === "BOTTOM_WATCH" || signal === "UP_BIAS") {
        return "buy";
    }
    if (signal === "TOP_WATCH" || signal === "DOWN_BIAS") {
        return "sell";
    }
    return "neutral";
}

async function runCycle() {
    setStatus("Uruchamianie cyklu agenta...");
    const response = await fetch("/api/run-cycle", { method: "POST" });
    if (!response.ok) {
        throw new Error("Nie udalo sie uruchomic cyklu.");
    }
    const payload = await response.json();
    await applyDashboardPayload(payload.dashboard, true);
    setStatus(`Cykl zakonczony: ${new Date().toLocaleTimeString("pl-PL")}`);
}

async function loadAiInsight() {
    setStatus("Generowanie komentarza AI...");
    const symbolQuery = selectedSymbol ? `?symbol=${encodeURIComponent(selectedSymbol)}` : "";
    const response = await fetch(`/api/ai-insight${symbolQuery}`);
    if (!response.ok) {
        throw new Error("Nie udalo sie pobrac komentarza AI.");
    }
    const payload = await response.json();
    document.getElementById("ai-message").textContent = payload.message;
    if (payload.enabled) {
        await renderDashboard();
        document.getElementById("ai-message").textContent = payload.message;
    }
    setStatus(payload.enabled ? "Komentarz AI gotowy." : "AI nieaktywne bez klucza API.");
}

async function switchAgentMode(mode) {
    setStatus(`Zmiana trybu agenta na ${mode}...`);
    const response = await fetch(`/api/agent-mode/${encodeURIComponent(mode)}`, { method: "POST" });
    if (!response.ok) {
        throw new Error("Nie udalo sie zmienic trybu agenta.");
    }
    const payload = await response.json();
    if (currentUser) {
        currentUser.agent_mode = payload.mode;
    }
    await applyDashboardPayload(payload.dashboard, true);
    setStatus(`Tryb agenta aktywny: ${payload.mode}`);
}

async function resetPaperPortfolio() {
    const confirmed = window.confirm("To wyczysci paper trade i przywroci kapital startowy. Scheduler zostanie zatrzymany, zeby agent od razu znowu nie otworzyl pozycji. Kontynuowac?");
    if (!confirmed) {
        return;
    }
    setStatus("Resetowanie paper portfela do stanu startowego...");
    const response = await fetch("/api/paper/reset", { method: "POST" });
    if (!response.ok) {
        throw new Error("Nie udalo sie zresetowac paper portfela.");
    }
    const payload = await response.json();
    chartHistoryCache = {};
    await applyDashboardPayload(payload.dashboard, true);
    setStatus(payload.scheduler_stopped ? "Paper portfel zresetowany. Scheduler zostal zatrzymany, zeby zostalo czyste 1000 PLN." : payload.message);
}

async function toggleScheduler() {
    const scheduler = dashboardState?.system_status?.scheduler || {};
    const shouldStop = Boolean(scheduler.active);
    const endpoint = shouldStop ? "/api/scheduler/stop" : "/api/scheduler/start";
    setStatus(shouldStop ? "Zatrzymywanie schedulera..." : scheduler.enabled ? "Naprawianie schedulera..." : "Uruchamianie schedulera...");
    const response = await fetch(endpoint, { method: "POST" });
    if (!response.ok) {
        throw new Error("Nie udalo sie zmienic stanu schedulera.");
    }
    await renderDashboard();
}

function openPageMenu() {
    document.body.classList.add("menu-open");
}

function closePageMenu() {
    document.body.classList.remove("menu-open");
}

function initPageMenu() {
    const menuToggle = document.getElementById("menu-toggle-button");
    const menuClose = document.getElementById("menu-close-button");
    const menu = document.getElementById("page-menu");
    if (!menuToggle || !menuClose || !menu) {
        return;
    }
    menuToggle.addEventListener("click", openPageMenu);
    menuClose.addEventListener("click", closePageMenu);
    menu.querySelectorAll("a").forEach((link) => {
        link.addEventListener("click", () => {
            closePageMenu();
        });
    });
}

// ==================== APP VIEW SWITCHING ====================

const viewTitles = {
    dashboard: "Dashboard",
    market: "Rynek",
    charts: "Wykresy",
    portfolio: "Portfel",
    activity: "Aktywnosc",
    ai: "AI Advisor",
    settings: "Status",
    help: "Pomoc"
};

let currentView = "dashboard";

function switchView(viewName) {
    if (viewName === currentView) return;
    
    // Update sidebar nav
    document.querySelectorAll(".nav-item").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.view === viewName);
    });
    
    // Update mobile nav
    document.querySelectorAll(".mobile-nav-item").forEach(btn => {
        btn.classList.toggle("active", btn.dataset.view === viewName);
    });
    
    // Update views
    document.querySelectorAll(".app-view").forEach(view => {
        view.classList.toggle("active", view.dataset.view === viewName);
    });
    
    // Update title
    const titleEl = document.getElementById("view-title");
    if (titleEl) {
        titleEl.textContent = viewTitles[viewName] || viewName;
    }
    
    currentView = viewName;
    
    // Sync duplicate elements between views if needed
    if (viewName === "portfolio") {
        syncPortfolioView();
    }
}

function syncPortfolioView() {
    // Copy bought coins menu to portfolio view
    const source = document.getElementById("bought-coins-menu");
    const target = document.getElementById("bought-coins-menu-2");
    if (source && target) {
        target.innerHTML = source.innerHTML;
    }
}

function initViewSwitching() {
    // Desktop sidebar nav
    document.querySelectorAll(".nav-item[data-view]").forEach(btn => {
        btn.addEventListener("click", () => {
            switchView(btn.dataset.view);
        });
    });
    
    // Mobile bottom nav
    document.querySelectorAll(".mobile-nav-item[data-view]").forEach(btn => {
        btn.addEventListener("click", () => {
            switchView(btn.dataset.view);
        });
    });
    
    // Initialize collapsible headers
    document.querySelectorAll(".card-header.collapsible").forEach(header => {
        header.addEventListener("click", () => {
            header.classList.toggle("collapsed");
            const body = header.nextElementSibling;
            if (body) {
                body.style.display = header.classList.contains("collapsed") ? "none" : "";
            }
        });
    });
    
    // Mobile accordion for dashboard cards
    initMobileAccordion();
    window.addEventListener("resize", initMobileAccordion);
}

function initMobileAccordion() {
    const isMobile = window.innerWidth <= 768;
    const dashCards = document.querySelectorAll(".dashboard-grid > .card");
    
    dashCards.forEach(card => {
        const header = card.querySelector(":scope > .card-header");
        const body = card.querySelector(":scope > .card-body");
        if (!header || !body) return;
        
        if (isMobile) {
            if (!header._mobileReady) {
                header._mobileReady = true;
                
                // Agent card starts OPEN, rest collapsed
                const isAgentCard = card.classList.contains("agent-card");
                if (!isAgentCard) {
                    header.classList.add("m-collapsed");
                    body.classList.add("m-hidden");
                }
                
                header.addEventListener("click", function mobileTap(e) {
                    if (window.innerWidth > 768) return;
                    e.stopPropagation();
                    const isCollapsed = header.classList.toggle("m-collapsed");
                    body.classList.toggle("m-hidden", isCollapsed);
                });
            }
        } else {
            // Desktop: ensure everything visible
            header.classList.remove("m-collapsed");
            body.classList.remove("m-hidden");
        }
    });
}

// ==================== BUTTON EVENT HANDLERS ====================

document.getElementById("refresh-button").addEventListener("click", async () => {
    try {
        await renderDashboard();
    } catch (error) {
        setStatus(error.message);
    }
});

document.getElementById("run-cycle-button").addEventListener("click", async () => {
    try {
        await runCycle();
    } catch (error) {
        setStatus(error.message);
    }
});

document.getElementById("ai-button").addEventListener("click", async () => {
    try {
        await loadAiInsight();
    } catch (error) {
        setStatus(error.message);
    }
});

document.getElementById("scheduler-button").addEventListener("click", async () => {
    try {
        await toggleScheduler();
    } catch (error) {
        setStatus(error.message);
    }
});

// Mobile action buttons (cycle + scheduler duplicates for mobile)
const mobileCycleBtn = document.getElementById("mobile-cycle-btn");
if (mobileCycleBtn) {
    mobileCycleBtn.addEventListener("click", async () => {
        try { await runCycle(); } catch(e) { setStatus(e.message); }
    });
}
const mobileSchedBtn = document.getElementById("mobile-scheduler-btn");
if (mobileSchedBtn) {
    mobileSchedBtn.addEventListener("click", async () => {
        try { await toggleScheduler(); } catch(e) { setStatus(e.message); }
    });
}

document.getElementById("reset-paper-button").addEventListener("click", async () => {
    try {
        await resetPaperPortfolio();
    } catch (error) {
        setStatus(error.message);
    }
});

// AI refresh button in AI view
const aiRefreshBtn = document.getElementById("ai-refresh-button");
if (aiRefreshBtn) {
    aiRefreshBtn.addEventListener("click", async () => {
        try {
            await loadAiInsight();
        } catch (error) {
            setStatus(error.message);
        }
    });
}

initPageMenu();
initViewSwitching();
initAuthUI();
checkAuthStatus();
renderDashboardWithRetry().catch((error) => setStatus(error.message));
window.setInterval(() => {
    updateAgentPulseStrip();
}, 1000);

// ==================== PWA Install Prompt ====================

let deferredPrompt = null;

window.addEventListener('beforeinstallprompt', (e) => {
    e.preventDefault();
    deferredPrompt = e;
    showInstallPrompt();
});

function showInstallPrompt() {
    // Check if already installed or dismissed
    if (window.matchMedia('(display-mode: standalone)').matches) {
        return;
    }
    
    const dismissed = localStorage.getItem('pwa-install-dismissed');
    if (dismissed && Date.now() - parseInt(dismissed) < 7 * 24 * 60 * 60 * 1000) {
        return; // Don't show for 7 days after dismissal
    }
    
    // Create prompt if doesn't exist
    let prompt = document.querySelector('.install-prompt');
    if (!prompt) {
        prompt = document.createElement('div');
        prompt.className = 'install-prompt visible';
        prompt.innerHTML = `
            <div class="install-prompt-text">
                <strong>Zainstaluj Agent Krypto</strong><br>
                Dodaj aplikacje do ekranu glownego dla szybkiego dostepu.
            </div>
            <div class="install-prompt-actions">
                <button class="ghost-button" id="install-dismiss">Pozniej</button>
                <button class="primary-button" id="install-accept">Instaluj</button>
            </div>
        `;
        document.body.appendChild(prompt);
        
        document.getElementById('install-dismiss').addEventListener('click', () => {
            prompt.classList.remove('visible');
            localStorage.setItem('pwa-install-dismissed', Date.now().toString());
        });
        
        document.getElementById('install-accept').addEventListener('click', async () => {
            prompt.classList.remove('visible');
            if (deferredPrompt) {
                deferredPrompt.prompt();
                const { outcome } = await deferredPrompt.userChoice;
                console.log('PWA install:', outcome);
                deferredPrompt = null;
            }
        });
    } else {
        prompt.classList.add('visible');
    }
}

// Handle app installed event
window.addEventListener('appinstalled', () => {
    console.log('PWA installed successfully');
    const prompt = document.querySelector('.install-prompt');
    if (prompt) {
        prompt.classList.remove('visible');
    }
    deferredPrompt = null;
});

// ==================== Mobile Touch Enhancements ====================

// Prevent double-tap zoom on buttons
document.addEventListener('touchend', (e) => {
    if (e.target.tagName === 'BUTTON' || e.target.closest('button')) {
        e.preventDefault();
        e.target.click();
    }
}, { passive: false });

// Pull to refresh (simple implementation)
let touchStartY = 0;
let isPulling = false;

document.addEventListener('touchstart', (e) => {
    if (window.scrollY === 0) {
        touchStartY = e.touches[0].clientY;
    }
}, { passive: true });

document.addEventListener('touchmove', (e) => {
    if (window.scrollY === 0 && e.touches[0].clientY > touchStartY + 60) {
        isPulling = true;
    }
}, { passive: true });

document.addEventListener('touchend', async () => {
    if (isPulling && window.scrollY === 0) {
        isPulling = false;
        // Trigger refresh
        try {
            await renderDashboardWithRetry(1, 0);
            setStatus('Odswiezono');
        } catch (error) {
            setStatus('Blad odswiezania');
        }
    }
}, { passive: true });

// Vibration feedback on important actions (if supported)
function vibrate(pattern = 10) {
    if ('vibrate' in navigator) {
        navigator.vibrate(pattern);
    }
}

// Add vibration to action buttons
['run-cycle-button', 'ai-button', 'reset-paper-button'].forEach(id => {
    const btn = document.getElementById(id);
    if (btn) {
        btn.addEventListener('click', () => vibrate(15));
    }
});

// Online/offline indicator
window.addEventListener('online', () => {
    setStatus('Polaczony z siecia');
    renderDashboardWithRetry(1, 0).catch(() => {});
});

window.addEventListener('offline', () => {
    setStatus('Brak polaczenia - tryb offline');
});