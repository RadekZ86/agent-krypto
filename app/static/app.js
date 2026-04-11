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
let dashboardRefreshTimerId = null;

// ==================== LIGHTWEIGHT CHARTS STATE ====================
let lwChart = null;
let lwCandleSeries = null;
let lwVolumeSeries = null;
let lwEma20Series = null;
let lwEma50Series = null;

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
    if (selector) {
        const binanceKeys = userApiKeys.filter(k => k.exchange === 'binance');
        selector.innerHTML = '<option value="">Wybierz klucz API</option>' + 
            binanceKeys.map(key => `
                <option value="${key.id}">${key.label || 'BINANCE'} - ${key.api_key} ${key.is_testnet ? '(Testnet)' : ''}</option>
            `).join('');
    }
    const bybitSelector = document.getElementById('bybit-key-selector');
    if (bybitSelector) {
        const bybitKeys = userApiKeys.filter(k => k.exchange === 'bybit');
        bybitSelector.innerHTML = '<option value="">Wybierz klucz API</option>' + 
            bybitKeys.map(key => `
                <option value="${key.id}">${key.label || 'BYBIT'} - ${key.api_key} ${key.is_testnet ? '(Testnet)' : ''}</option>
            `).join('');
    }
}

async function addApiKey(exchange, apiKey, apiSecret, isTestnet, permissions) {
    try {
        const response = await fetch('/api/keys', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                exchange: exchange,
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
    const key = userApiKeys.find(k => k.id === keyId);
    const exchange = key ? key.exchange : 'binance';
    const exchangeLabel = exchange === 'bybit' ? 'Bybit' : 'Binance';
    const testUrl = exchange === 'bybit' ? `/api/bybit/test?key_id=${keyId}` : `/api/binance/test?key_id=${keyId}`;
    try {
        setStatus(`Testowanie połączenia z ${exchangeLabel}...`);
        const response = await fetch(testUrl);
        const text = await response.text();
        let data;
        try { data = JSON.parse(text); } catch { data = { detail: text || `Błąd serwera (${response.status})` }; }
        
        if (data.success) {
            alert(`✅ Połączenie z ${exchangeLabel} działa poprawnie!\n` + (data.message || 'OK'));
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

        // Show dust conversion button if Binance key is active
        const dustBtn = document.getElementById('dust-convert-btn');
        if (dustBtn) dustBtn.classList.remove('hidden');
    } catch (error) {
        if (balancesContainer) balancesContainer.innerHTML = `<p class="empty-state">Błąd: ${error.message}</p>`;
    }
}

async function convertDustToBNB() {
    const btn = document.getElementById('dust-convert-btn');
    const resultDiv = document.getElementById('dust-convert-result');
    if (btn) btn.disabled = true;
    if (btn) btn.textContent = '⏳ Konwertuję...';
    try {
        const res = await fetch('/api/binance/dust/convert', {method: 'POST'});
        const data = await res.json();
        if (resultDiv) {
            resultDiv.classList.remove('hidden');
            if (data.ok) {
                resultDiv.innerHTML = `<span class="positive">✅ Zamieniono ${data.converted_count} aktywów → ${data.total_bnb.toFixed(6)} BNB</span>`;
            } else {
                resultDiv.innerHTML = `<span class="negative">❌ ${data.error || 'Błąd konwersji'}</span>`;
            }
        }
    } catch (e) {
        if (resultDiv) { resultDiv.classList.remove('hidden'); resultDiv.innerHTML = `<span class="negative">❌ ${e.message}</span>`; }
    }
    if (btn) { btn.disabled = false; btn.textContent = '🧹 Zamień resztki na BNB'; }
}

async function loadBybitData(keyId) {
    const balancesContainer = document.getElementById('bybit-balances');
    const portfolioDisplay = document.getElementById('bybit-portfolio-value');
    const positionsContainer = document.getElementById('bybit-positions');
    const positionsList = document.getElementById('bybit-positions-list');

    if (!keyId) {
        if (balancesContainer) balancesContainer.innerHTML = '<p class="empty-state">Wybierz klucz API aby zobaczyć balans Bybit</p>';
        if (portfolioDisplay) portfolioDisplay.classList.add('hidden');
        if (positionsContainer) positionsContainer.classList.add('hidden');
        return;
    }

    try {
        if (balancesContainer) balancesContainer.innerHTML = '<p class="empty-state">Ładowanie...</p>';

        const [portRes, posRes] = await Promise.all([
            fetch(`/api/bybit/portfolio?key_id=${keyId}`),
            fetch('/api/bybit/positions')
        ]);

        const portText = await portRes.text();
        const posText = await posRes.text();
        let portData, posData;
        try { portData = JSON.parse(portText); } catch { portData = { detail: portText || `Błąd (${portRes.status})` }; }
        try { posData = JSON.parse(posText); } catch { posData = { positions: [] }; }

        if (!portRes.ok) {
            throw new Error(portData.detail || 'Nie udało się pobrać danych Bybit');
        }

        // Show holdings
        if (balancesContainer && portData.holdings) {
            if (portData.holdings.length === 0) {
                balancesContainer.innerHTML = '<p class="empty-state">Brak środków na koncie Bybit</p>';
            } else {
                balancesContainer.innerHTML = portData.holdings.map(h => `
                    <div class="balance-item">
                        <span class="balance-asset">${h.asset}</span>
                        <span class="balance-amount">${parseFloat(h.total).toFixed(4)} ${h.unrealized_pnl ? `<small style="color:${h.unrealized_pnl >= 0 ? 'var(--positive)' : 'var(--negative)'}">(${h.unrealized_pnl >= 0 ? '+' : ''}${h.unrealized_pnl.toFixed(2)})</small>` : ''}</span>
                    </div>
                `).join('');
            }
        }

        // Show portfolio value
        if (portfolioDisplay && portData.total_value !== undefined) {
            portfolioDisplay.classList.remove('hidden');
            portfolioDisplay.querySelector('.value').textContent =
                `$${parseFloat(portData.total_value).toFixed(2)} USDT`;
        }

        // Show open perpetual positions
        const positions = posData.positions || [];
        if (positionsContainer && positionsList) {
            if (positions.length > 0) {
                positionsContainer.classList.remove('hidden');
                positionsList.innerHTML = positions.map(p => {
                    const pnlColor = p.unrealized_pnl >= 0 ? 'var(--positive)' : 'var(--negative)';
                    return `
                    <div class="bybit-position-item" style="padding:6px 0;border-bottom:1px solid var(--border)">
                        <div style="display:flex;justify-content:space-between;align-items:center">
                            <strong>${p.symbol}</strong>
                            <span class="badge-leverage">${p.leverage}x ${p.margin_mode}</span>
                        </div>
                        <div style="display:flex;justify-content:space-between;font-size:0.85em;margin-top:4px">
                            <span>${p.side} ${p.size}</span>
                            <span>Wejście: $${p.entry_price.toFixed(2)}</span>
                            <span style="color:${pnlColor}">P&L: $${p.unrealized_pnl.toFixed(2)}</span>
                        </div>
                        ${p.liq_price > 0 ? `<div style="font-size:0.8em;color:var(--negative)">Liq: $${p.liq_price.toFixed(2)}</div>` : ''}
                    </div>`;
                }).join('');
            } else {
                positionsContainer.classList.add('hidden');
            }
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
            const exchange = document.getElementById('api-exchange').value;
            const apiKey = document.getElementById('api-key-input').value;
            const apiSecret = document.getElementById('api-secret-input').value;
            const isTestnet = document.getElementById('api-testnet').checked;
            const permissions = document.getElementById('api-permissions').value;
            
            const result = await addApiKey(exchange, apiKey, apiSecret, isTestnet, permissions);
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

    // Bybit key selector
    const bybitKeySelector = document.getElementById('bybit-key-selector');
    if (bybitKeySelector) {
        bybitKeySelector.addEventListener('change', (e) => {
            loadBybitData(e.target.value);
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
    const sysStatus = payload.system_status || {};
    const isLive = (payload.config?.trading_mode || sysStatus.trading_mode) === "LIVE";
    const hasExchangeKeys = sysStatus.binance_private_ready || sysStatus.bybit_private_ready;
    const bw = isLive && payload.binance_wallet ? payload.binance_wallet : null;
    const ls = isLive && payload.live_stats ? payload.live_stats : null;
    const bybitW = isLive && payload.bybit_wallet ? payload.bybit_wallet : null;
    const bybitP = isLive && payload.bybit_positions ? payload.bybit_positions : null;
    // In LIVE mode with exchange keys: hide paper data, show real or loading
    const hidePaper = isLive && hasExchangeKeys;
    paintWallet(payload.wallet, bw, ls, bybitW, hidePaper);
    paintModeStrip(payload.system_status, payload.config, payload.wallet);
    paintAgentMode(payload.system_status, payload.config);
    paintCapitalSummary(payload.wallet, bw, ls, bybitW, bybitP, hidePaper);
    paintApiUsage(payload.api_usage);
    paintBoughtCoins(bw ? (bw.holdings || []).filter(h => h.value > 1).map(h => ({symbol: h.asset, buy_value: h.value, quantity: h.total, buy_price: h.value / (h.total || 1)})) : (hidePaper ? [] : payload.wallet.positions));
    paintWatchlist(payload.market);
    paintPrivateLearning(payload.private_learning);
    paintTradeRanking(payload.trade_ranking);
    paintTradeBuckets(payload.recent_trades);
    paintSectorFilters(payload.config);
    paintMarket(payload.market);
    paintPositions(hidePaper && !bw ? [] : (bw ? [] : payload.wallet.positions));
    paintDecisions(payload.recent_decisions);
    paintTrades(hidePaper ? [] : payload.recent_trades);
    paintLiveOrders(payload.live_orders || []);
    if (payload.live_portfolio && payload.live_portfolio.length) {
        const quoteCur = payload.binance_wallet ? payload.binance_wallet.quote_currency : "PLN";
        paintLivePortfolio(payload.live_portfolio, quoteCur);
    }
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
    paintLeveragePaper(payload.leverage_paper);
    syncAllocUI(payload.system_status);
}

function paintChartError(message) {
    destroyLwChart();
    const container = document.getElementById("lw-chart-container");
    if (container) container.innerHTML = "";
    document.getElementById("chart-summary").innerHTML = `<div class="empty-state">${message}</div>`;
    document.getElementById("chart-insights").innerHTML = "";
}

function paintWallet(wallet, binanceWallet, liveStats, bybitWallet, hidePaper) {
    // Update metric labels based on mode
    const isExchange = binanceWallet || hidePaper;
    const metricLabels = {
        "cash-balance": isExchange ? `Wolne ${binanceWallet ? (binanceWallet.quote_currency || "USDT") : "..."}` : "Gotowka",
        "gross-profit": isExchange ? "Zysk (niezreal.)" : "Zysk",
        "gross-loss": isExchange ? "Strata (niezreal.)" : "Strata",
        "realized-profit": isExchange ? "Bilans P&L" : "Bilans",
        "buy-count": "Kupione",
        "sell-count": "Sprzedane",
        "win-rate": "Win rate",
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
        const holdingsCount = (binanceWallet.holdings || []).filter(h => h.value > 1 && !stableAssets.includes(h.asset)).length;
        document.getElementById("cash-balance").textContent = formatQuote(cashValue, walletQuote);
        document.getElementById("equity").textContent = formatQuote(totalValue, walletQuote);
        document.getElementById("open-positions-count").textContent = String(holdingsCount);

        // Use real live stats from Binance data
        if (liveStats) {
            document.getElementById("buy-count").textContent = String(liveStats.buy_count);
            document.getElementById("sell-count").textContent = String(liveStats.sell_count);
            document.getElementById("win-rate").textContent = `${percentFormatter.format(liveStats.win_rate)}%`;
            const profitEl = document.getElementById("gross-profit");
            profitEl.textContent = formatQuote(liveStats.gross_profit, walletQuote);
            profitEl.style.color = liveStats.gross_profit > 0 ? "var(--positive)" : "";
            const lossEl = document.getElementById("gross-loss");
            lossEl.textContent = formatQuote(liveStats.gross_loss, walletQuote);
            lossEl.style.color = liveStats.gross_loss > 0 ? "var(--negative)" : "";
            const balanceEl = document.getElementById("realized-profit");
            balanceEl.textContent = formatQuote(liveStats.realized_pnl, walletQuote);
            balanceEl.style.color = liveStats.realized_pnl >= 0 ? "var(--positive)" : "var(--negative)";
        } else {
            document.getElementById("buy-count").textContent = "–";
            document.getElementById("sell-count").textContent = "–";
            document.getElementById("win-rate").textContent = "–";
            document.getElementById("gross-profit").textContent = "–";
            document.getElementById("gross-loss").textContent = "–";
            document.getElementById("realized-profit").textContent = formatQuote(totalValue, walletQuote);
        }
    } else if (hidePaper) {
        // LIVE mode but exchange data not loaded yet — show loading
        document.getElementById("cash-balance").textContent = "Ładuję...";
        document.getElementById("equity").textContent = "Ładuję...";
        document.getElementById("buy-count").textContent = "–";
        document.getElementById("sell-count").textContent = "–";
        document.getElementById("open-positions-count").textContent = "–";
        document.getElementById("gross-profit").textContent = "–";
        document.getElementById("gross-loss").textContent = "–";
        document.getElementById("realized-profit").textContent = "–";
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
    paintQuickSummary(wallet, binanceWallet, liveStats, hidePaper);
    
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
        const pnl = liveStats ? (liveStats.realized_pnl || 0) : 0;

        if (heroBalance) {
            heroBalance.textContent = formatQuote(binanceWallet.total_value || 0, walletQuote);
            heroBalance.style.color = "var(--positive)";
        }

        // Relabel mobile hero stats for LIVE
        const heroBalanceLabel = document.querySelector(".mobile-hero-top .mobile-hero-top-label");
        if (heroBalanceLabel) heroBalanceLabel.textContent = "Portfel Binance";

        const heroStatDivs = document.querySelectorAll(".mobile-hero-stat");
        if (heroStatDivs[0]) heroStatDivs[0].querySelector("span").textContent = "Zysk";
        if (heroStatDivs[1]) heroStatDivs[1].querySelector("span").textContent = "Strata";
        if (heroStatDivs[2]) heroStatDivs[2].querySelector("span").textContent = "Win rate";

        if (heroProfit) {
            const gp = liveStats ? (liveStats.gross_profit || 0) : 0;
            heroProfit.textContent = formatQuote(gp, walletQuote);
            heroProfit.style.color = gp > 0 ? "var(--positive)" : "";
        }
        if (heroLoss) {
            const gl = liveStats ? (liveStats.gross_loss || 0) : 0;
            heroLoss.textContent = formatQuote(gl, walletQuote);
            heroLoss.style.color = gl > 0 ? "var(--negative)" : "";
            heroLoss.closest(".mobile-hero-stat")?.classList.remove("positive");
            heroLoss.closest(".mobile-hero-stat")?.classList.add(gl > 0 ? "negative" : "positive");
        }
        if (heroWinrate) heroWinrate.textContent = liveStats ? `${percentFormatter.format(liveStats.win_rate || 0)}%` : "–";
    } else if (hidePaper) {
        // LIVE mode but exchange data loading
        const heroBalanceLabel = document.querySelector(".mobile-hero-top .mobile-hero-top-label");
        if (heroBalanceLabel) heroBalanceLabel.textContent = "Portfel LIVE";
        if (heroBalance) { heroBalance.textContent = "Ładuję..."; heroBalance.style.color = ""; }
        if (heroProfit) heroProfit.textContent = "–";
        if (heroLoss) heroLoss.textContent = "–";
        if (heroWinrate) heroWinrate.textContent = "–";
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
    const dataStale = systemStatus?.data_stale || false;
    const staleSymbols = systemStatus?.stale_symbols || [];
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
            ${dataStale ? `<span class="status-pill sell" title="${staleSymbols.join(', ')}">⚠ STALE DATA (${staleSymbols.length} sym)</span>` : ""}
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

function paintCapitalSummary(wallet, binanceWallet, liveStats, bybitWallet, bybitPositions, hidePaper) {
    const container = document.getElementById("capital-summary");
    const lp = dashboardState?.leverage_paper;

    if (binanceWallet) {
        const totalValue = binanceWallet.total_value || 0;
        const walletQuote = binanceWallet.quote_currency || "USDT";
        const stableAssets = ["USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"];
        const cashHolding = (binanceWallet.holdings || []).find(h => h.asset === walletQuote) || (binanceWallet.holdings || []).find(h => stableAssets.includes(h.asset));
        const cashValue = cashHolding ? cashHolding.free || 0 : 0;
        const lockedValue = totalValue - cashValue;
        const cryptoHoldings = (binanceWallet.holdings || []).filter(h => h.total > 0 && !stableAssets.includes(h.asset));
        const cashLabel = `Wolne ${walletQuote}`;
        const ls = liveStats || {};
        let holdingsHtml = cryptoHoldings.map(h =>
            buildQuickCard(h.asset, formatQuote(h.value, walletQuote), `${h.total.toFixed(6)} szt.`)
        ).join("");

        // Combined total
        const bybitTotal = bybitWallet ? (bybitWallet.total_value || 0) : 0;
        const combinedTotal = totalValue + bybitTotal;
        let combinedHtml = "";
        if (bybitWallet) {
            combinedHtml = `<div class="portfolio-section-header combined">💰 Łącznie wszystkie giełdy: ${formatQuote(combinedTotal, walletQuote)}</div>`;
        }

        // Binance section
        let commissionHtml = "";
        if (ls.total_commission) {
            const commParts = Object.entries(ls.commission_by_asset || {}).map(([a, v]) => `${v.toFixed(4)} ${a}`).join(", ");
            commissionHtml = buildQuickCard("Prowizje LIVE", commParts || `${ls.total_commission.toFixed(6)}`, "Realne opłaty giełdowe Binance");
        }
        let binanceHtml = `<div class="portfolio-section-header binance">🟡 Binance</div>
            ${buildQuickCard("Portfel Binance", formatQuote(totalValue, walletQuote), "Łącznie aktywa na Binance")}
            ${buildQuickCard(cashLabel, formatQuote(cashValue, walletQuote), "Gotówka do handlu")}
            ${buildQuickCard("W pozycjach", formatQuote(lockedValue, walletQuote), `${cryptoHoldings.length} aktywów`)}
            ${buildQuickCard("Kupione", `${ls.buy_count || 0}`, "Zlecenia BUY")}
            ${buildQuickCard("Sprzedane", `${ls.sell_count || 0}`, "Zlecenia SELL")}
            ${buildQuickCard("Bilans P&L", formatQuote(ls.realized_pnl || 0, walletQuote), `Win rate: ${percentFormatter.format(ls.win_rate || 0)}%`)}
            ${commissionHtml}
            ${holdingsHtml}`;

        // Bybit section
        let bybitHtml = "";
        if (bybitWallet) {
            const bybitAvail = bybitWallet.available_balance || 0;
            const bybitPnl = bybitWallet.total_unrealized_pnl || 0;
            bybitHtml = `<div class="portfolio-section-header bybit">🟠 Bybit</div>
                ${buildQuickCard("Portfel Bybit", formatQuote(bybitTotal, "USDT"), "Konto Unified")}
                ${buildQuickCard("Bybit wolne", formatQuote(bybitAvail, "USDT"), "Dostępne do handlu")}`;
            if (bybitPnl !== 0) {
                bybitHtml += buildQuickCard("P&L (niezreal.)", formatQuote(bybitPnl, "USDT"), "Otwarte pozycje");
            }
            if (bybitPositions && bybitPositions.length > 0) {
                bybitHtml += bybitPositions.map(p =>
                    buildQuickCard(`${p.symbol} ${p.side}`, `${p.leverage}x | $${p.unrealized_pnl.toFixed(2)}`, `Wejście: $${p.entry_price.toFixed(2)} | ${p.size}`)
                ).join("");
            }
        }

        // Leverage paper section
        let leverageHtml = "";
        if (lp) {
            const lpPnlClass = (lp.total_realized_pnl || 0) >= 0 ? "positive" : "negative";
            leverageHtml = `<div class="portfolio-section-header leverage">⚡ Nauka dźwigni (Paper)</div>
                ${buildQuickCard("Margin", `$${numberFormatter.format(lp.available_margin)}`, `z $${numberFormatter.format(lp.paper_balance)}`)}
                ${buildQuickCard("Dźwignia", `${lp.current_leverage_level}x`, `${lp.total_trades} transakcji`)}
                ${buildQuickCard("P&L", `<span class="${lpPnlClass}">$${numberFormatter.format(lp.total_realized_pnl || 0)}</span>`, `Win: ${percentFormatter.format(lp.win_rate || 0)}% | Liq: ${lp.liquidations}`)}`;
        }

        container.innerHTML = `${combinedHtml}${binanceHtml}${bybitHtml}${leverageHtml}`;
    } else if (hidePaper) {
        // LIVE mode, exchange data still loading
        container.innerHTML = `
            <div class="portfolio-section-header binance">🟡 Portfel giełdowy</div>
            ${buildQuickCard("Status", "Ładowanie danych...", "Łączenie z giełdą Binance/Bybit")}
        `;
    } else {
        const displayStartPln = dashboardState?.config?.start_balance_display_pln || 1000;

        // Paper leverage section
        let leverageHtml = "";
        if (lp) {
            const lpPnlClass = (lp.total_realized_pnl || 0) >= 0 ? "positive" : "negative";
            leverageHtml = `<div class="portfolio-section-header leverage">⚡ Nauka dźwigni (Paper)</div>
                ${buildQuickCard("Margin", `$${numberFormatter.format(lp.available_margin)}`, `z $${numberFormatter.format(lp.paper_balance)}`)}
                ${buildQuickCard("Dźwignia", `${lp.current_leverage_level}x`, `${lp.total_trades} transakcji`)}
                ${buildQuickCard("P&L", `<span class="${lpPnlClass}">$${numberFormatter.format(lp.total_realized_pnl || 0)}</span>`, `Win: ${percentFormatter.format(lp.win_rate || 0)}% | Liq: ${lp.liquidations}`)}`;
        }

        container.innerHTML = `
            <div class="portfolio-section-header paper">📄 Paper trading (Spot)</div>
            ${buildQuickCard("Start", formatQuote(wallet.starting_balance), `Reset przywraca ${percentFormatter.format(displayStartPln)} PLN`)}
            ${buildQuickCard("Wydał na zakupy", formatQuote(wallet.spent_on_buys), "Łączna wartość wejść BUY")}
            ${buildQuickCard("Wróciło ze sprzedaży", formatQuote(wallet.capital_returned), "Kapitał po SELL")}
            ${buildQuickCard("Fee łącznie", formatQuote(wallet.fees_paid), "Prowizje")}
            ${buildQuickCard("Zostało gotówki", formatQuote(wallet.cash_balance), "Możliwe do wydania")}
            ${buildQuickCard("Zablokowane", formatQuote(wallet.capital_locked_cost), "W otwartych pozycjach")}
            ${leverageHtml}
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

function paintQuickSummary(wallet, binanceWallet, liveStats, hidePaper) {
    const container = document.getElementById("quick-summary");
    if (!container) {
        return;
    }
    if (hidePaper && !binanceWallet) {
        container.innerHTML = buildQuickCard("Portfel LIVE", "Ładowanie...", "Łączenie z giełdą");
        return;
    }
    if (binanceWallet) {
        const walletQuote = binanceWallet.quote_currency || "USDT";
        const totalValue = binanceWallet.total_value || 0;
        const stableAssets = ["USDT", "BUSD", "FDUSD", "PLN", "EUR", "USD", "USDC"];
        const cryptoHoldings = (binanceWallet.holdings || []).filter(h => h.total > 0 && !stableAssets.includes(h.asset));
        const cashHolding = (binanceWallet.holdings || []).find(h => h.asset === walletQuote);
        const cashValue = cashHolding ? cashHolding.free || 0 : 0;
        const ls = liveStats || {};
        let commCard = "";
        if (ls.total_commission) {
            const commParts = Object.entries(ls.commission_by_asset || {}).map(([a, v]) => `${v.toFixed(4)} ${a}`).join(", ");
            commCard = buildQuickCard("Prowizje LIVE", commParts || `${ls.total_commission.toFixed(6)}`, "Realne opłaty giełdowe Binance");
        }
        container.innerHTML = `
            ${buildQuickCard("Portfel Binance", formatQuote(totalValue, walletQuote), "Wartosc wszystkich aktywow na koncie")}
            ${buildQuickCard(`Wolne ${walletQuote}`, formatQuote(cashValue, walletQuote), "Gotowka dostepna do handlu")}
            ${buildQuickCard("Kupione (LIVE)", `${ls.buy_count || 0} zleceń`, "Zlecenia BUY wykonane przez agenta na Binance")}
            ${buildQuickCard("Sprzedane (LIVE)", `${ls.sell_count || 0} zleceń`, "Zlecenia SELL wykonane przez agenta na Binance")}
            ${buildQuickCard("Zysk niezreal.", formatQuote(ls.gross_profit || 0, walletQuote), `${ls.winning_count || 0} zyskownych pozycji`)}
            ${buildQuickCard("Strata niezreal.", formatQuote(ls.gross_loss || 0, walletQuote), `${ls.losing_count || 0} stratnych pozycji`)}
            ${buildQuickCard("Bilans P&L", formatQuote(ls.realized_pnl || 0, walletQuote), `Win rate: ${percentFormatter.format(ls.win_rate || 0)}%`)}
            ${commCard}
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
    const isLive = (dashboardState?.config?.trading_mode || dashboardState?.system_status?.trading_mode) === "LIVE";
    const closedTrades = (trades || []).filter((trade) => trade.status === "CLOSED" && trade.profit !== null);
    const profitableTrades = closedTrades.filter((trade) => trade.profit >= 0);
    const losingTrades = closedTrades.filter((trade) => trade.profit < 0);

    const sourceLabel = isLive ? "" : " (paper)";
    profitContainer.innerHTML = profitableTrades.length
        ? profitableTrades.map((trade) => buildTradeBucketItem(trade, true)).join("")
        : `<div class="empty-state">Brak sprzedanych coinów z zyskiem${sourceLabel}.</div>`;

    lossContainer.innerHTML = losingTrades.length
        ? losingTrades.map((trade) => buildTradeBucketItem(trade, false)).join("")
        : `<div class="empty-state">Brak sprzedanych coinów ze stratą${sourceLabel}.</div>`;
}

function paintMarket(rows) {
    const table = document.getElementById("market-table");
    const visibleRows = filterRowsBySector(rows);
    if (!visibleRows.length) {
        table.innerHTML = `<tr><td colspan="15">Brak danych rynkowych dla wybranego sektora.</td></tr>`;
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
            <td>${whaleIndicator(row)}</td>
            <td class="${fundingToneClass(row.funding_rate)}">${row.funding_rate != null ? row.funding_rate.toFixed(3) + '%' : '-'}</td>
            <td class="${oiTrendClass(row.oi_trend)}">${row.oi_trend || '-'}</td>
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
    const container = document.getElementById("lw-chart-container");
    const summary = document.getElementById("chart-summary");
    const insights = document.getElementById("chart-insights");

    if (!container) return;

    // Lifecycle (max) mode: use the long history
    if (selectedHistoryMode === "max" && lifecycleHistory?.points?.length) {
        paintLwChart(container, summary, insights, lifecycleHistory, chartPackage, true);
        return;
    }

    if (!chartPackage || !chartPackage.points?.length) {
        destroyLwChart();
        summary.innerHTML = `<div class="empty-state">Brak danych do analizy wykresu.</div>`;
        insights.innerHTML = "";
        return;
    }

    paintLwChart(container, summary, insights, chartPackage, chartPackage, false);
}

function destroyLwChart() {
    if (lwChart) {
        lwChart.remove();
        lwChart = null;
        lwCandleSeries = null;
        lwVolumeSeries = null;
        lwEma20Series = null;
        lwEma50Series = null;
    }
}

function paintLwChart(container, summary, insights, dataSource, chartPackage, isLifecycle) {
    destroyLwChart();
    container.innerHTML = "";

    const points = isLifecycle ? dataSource.points : dataSource.points;
    if (!points || !points.length) {
        summary.innerHTML = `<div class="empty-state">Brak danych.</div>`;
        return;
    }

    // Determine which tab to show
    const showOverview = selectedChartTab === "overview" || isLifecycle;
    const showPrice = selectedChartTab === "price" && !isLifecycle;
    const showVolume = selectedChartTab === "volume" && !isLifecycle;
    const showRsi = selectedChartTab === "rsi" && !isLifecycle;
    const showMacd = selectedChartTab === "macd" && !isLifecycle;

    const chartHeight = window.innerWidth <= 768 ? 320 : 520;
    const chartWidth = container.clientWidth || container.parentElement?.clientWidth || window.innerWidth - 40;

    lwChart = LightweightCharts.createChart(container, {
        width: chartWidth,
        height: chartHeight,
        layout: {
            background: { type: 'solid', color: '#131722' },
            textColor: '#787b86',
            fontSize: 11,
            fontFamily: "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', sans-serif",
        },
        grid: {
            vertLines: { color: 'rgba(42, 46, 57, 0.5)' },
            horzLines: { color: 'rgba(42, 46, 57, 0.5)' },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: 'rgba(41, 98, 255, 0.4)', width: 1, style: 2, labelBackgroundColor: '#2962ff' },
            horzLine: { color: 'rgba(41, 98, 255, 0.4)', width: 1, style: 2, labelBackgroundColor: '#2962ff' },
        },
        rightPriceScale: {
            borderColor: 'rgba(42, 46, 57, 0.8)',
            scaleMargins: { top: 0.05, bottom: showOverview ? 0.25 : 0.05 },
        },
        timeScale: {
            borderColor: 'rgba(42, 46, 57, 0.8)',
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 3,
        },
        handleScroll: { vertTouchDrag: false },
        handleScale: { axisPressedMouseMove: { time: true, price: false } },
    });

    // Prepare OHLC data
    const series = (showOverview || showPrice ? points : points).map(p => {
        const t = p.timestamp || p.date;
        const time = Math.floor(new Date(t).getTime() / 1000);
        return {
            time,
            open: Number(p.open ?? p.close),
            high: Number(p.high ?? Math.max(p.open ?? p.close, p.close)),
            low: Number(p.low ?? Math.min(p.open ?? p.close, p.close)),
            close: Number(p.close),
            volume: Number(p.volume || 0),
            ema20: p.ema20 != null ? Number(p.ema20) : null,
            ema50: p.ema50 != null ? Number(p.ema50) : null,
            rsi: p.rsi != null ? Number(p.rsi) : null,
            macd: p.macd != null ? Number(p.macd) : null,
            macd_signal: p.macd_signal != null ? Number(p.macd_signal) : null,
            macd_hist: p.macd_hist != null ? Number(p.macd_hist) : null,
            bb_upper: p.bb_upper != null ? Number(p.bb_upper) : null,
            bb_lower: p.bb_lower != null ? Number(p.bb_lower) : null,
            sma20: p.sma20 != null ? Number(p.sma20) : null,
            vwap: p.vwap != null ? Number(p.vwap) : null,
        };
    }).sort((a, b) => a.time - b.time);

    // Deduplicate by time
    const uniqueSeries = [];
    const seenTimes = new Set();
    for (const p of series) {
        if (!seenTimes.has(p.time)) {
            seenTimes.add(p.time);
            uniqueSeries.push(p);
        }
    }

    if (showRsi) {
        // RSI as line chart
        const rsiSeries = lwChart.addLineSeries({
            color: '#f0b44a',
            lineWidth: 2,
            priceScaleId: 'right',
        });
        rsiSeries.setData(uniqueSeries.filter(p => p.rsi != null).map(p => ({ time: p.time, value: p.rsi })));

        // RSI reference lines
        rsiSeries.createPriceLine({ price: 70, color: 'rgba(239,83,80,0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Overbought' });
        rsiSeries.createPriceLine({ price: 30, color: 'rgba(38,166,154,0.5)', lineWidth: 1, lineStyle: 2, axisLabelVisible: true, title: 'Oversold' });
        rsiSeries.createPriceLine({ price: 50, color: 'rgba(120,123,134,0.3)', lineWidth: 1, lineStyle: 2, axisLabelVisible: false });

    } else if (showMacd) {
        // MACD histogram
        const histSeries = lwChart.addHistogramSeries({
            priceScaleId: 'right',
            priceFormat: { type: 'price', precision: 6, minMove: 0.000001 },
        });
        histSeries.setData(uniqueSeries.filter(p => p.macd_hist != null).map(p => ({
            time: p.time,
            value: p.macd_hist,
            color: p.macd_hist >= 0 ? 'rgba(38,166,154,0.6)' : 'rgba(239,83,80,0.6)',
        })));

        // MACD line
        const macdLine = lwChart.addLineSeries({ color: '#2962ff', lineWidth: 2, priceScaleId: 'right' });
        macdLine.setData(uniqueSeries.filter(p => p.macd != null).map(p => ({ time: p.time, value: p.macd })));

        // Signal line
        const signalLine = lwChart.addLineSeries({ color: '#ff6d00', lineWidth: 2, priceScaleId: 'right' });
        signalLine.setData(uniqueSeries.filter(p => p.macd_signal != null).map(p => ({ time: p.time, value: p.macd_signal })));

    } else if (showVolume) {
        // Volume bars as main
        const volSeries = lwChart.addHistogramSeries({
            priceScaleId: 'right',
            priceFormat: { type: 'volume' },
        });
        volSeries.setData(uniqueSeries.map(p => ({
            time: p.time,
            value: p.volume,
            color: p.close >= p.open ? 'rgba(38,166,154,0.7)' : 'rgba(239,83,80,0.7)',
        })));

    } else {
        // Overview or Price: candlestick chart
        lwCandleSeries = lwChart.addCandlestickSeries({
            upColor: '#26a69a',
            downColor: '#ef5350',
            borderDownColor: '#ef5350',
            borderUpColor: '#26a69a',
            wickDownColor: '#ef5350',
            wickUpColor: '#26a69a',
        });
        lwCandleSeries.setData(uniqueSeries.map(p => ({
            time: p.time, open: p.open, high: p.high, low: p.low, close: p.close,
        })));

        // Volume overlay (bottom histogram)
        if (showOverview) {
            lwVolumeSeries = lwChart.addHistogramSeries({
                priceFormat: { type: 'volume' },
                priceScaleId: 'volume',
            });
            lwChart.priceScale('volume').applyOptions({
                scaleMargins: { top: 0.82, bottom: 0 },
            });
            lwVolumeSeries.setData(uniqueSeries.map(p => ({
                time: p.time,
                value: p.volume,
                color: p.close >= p.open ? 'rgba(38,166,154,0.25)' : 'rgba(239,83,80,0.25)',
            })));
        }

        // EMA lines
        if (!isLifecycle) {
            const ema20Data = uniqueSeries.filter(p => p.ema20 != null).map(p => ({ time: p.time, value: p.ema20 }));
            const ema50Data = uniqueSeries.filter(p => p.ema50 != null).map(p => ({ time: p.time, value: p.ema50 }));

            if (ema20Data.length > 0) {
                lwEma20Series = lwChart.addLineSeries({
                    color: '#2962ff',
                    lineWidth: 1,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                lwEma20Series.setData(ema20Data);
            }

            if (ema50Data.length > 0) {
                lwEma50Series = lwChart.addLineSeries({
                    color: '#ff6d00',
                    lineWidth: 1,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false,
                });
                lwEma50Series.setData(ema50Data);
            }

            // ── Bollinger Bands (shaded area) ──
            const bbUpperData = uniqueSeries.filter(p => p.bb_upper != null).map(p => ({ time: p.time, value: p.bb_upper }));
            const bbLowerData = uniqueSeries.filter(p => p.bb_lower != null).map(p => ({ time: p.time, value: p.bb_lower }));

            if (bbUpperData.length > 0) {
                const bbUpperLine = lwChart.addLineSeries({
                    color: 'rgba(156,39,176,0.5)',
                    lineWidth: 1,
                    lineStyle: 2,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    title: 'BB↑',
                });
                bbUpperLine.setData(bbUpperData);
            }
            if (bbLowerData.length > 0) {
                const bbLowerLine = lwChart.addLineSeries({
                    color: 'rgba(156,39,176,0.5)',
                    lineWidth: 1,
                    lineStyle: 2,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    title: 'BB↓',
                });
                bbLowerLine.setData(bbLowerData);
            }

            // ── VWAP line ──
            const vwapData = uniqueSeries.filter(p => p.vwap != null).map(p => ({ time: p.time, value: p.vwap }));
            if (vwapData.length > 0) {
                const vwapLine = lwChart.addLineSeries({
                    color: '#ffeb3b',
                    lineWidth: 2,
                    lineStyle: 0,
                    crosshairMarkerVisible: false,
                    priceLineVisible: false,
                    lastValueVisible: false,
                    title: 'VWAP',
                });
                vwapLine.setData(vwapData);
            }
        }

        // ── Fibonacci retracement levels ──
        if (chartPackage?.summary?.fibonacci && lwCandleSeries) {
            const fib = chartPackage.summary.fibonacci;
            const fibLevels = [
                { price: fib.fib_236, label: 'Fib 23.6%', color: 'rgba(0,188,212,0.4)' },
                { price: fib.fib_382, label: 'Fib 38.2%', color: 'rgba(0,188,212,0.5)' },
                { price: fib.fib_500, label: 'Fib 50%', color: 'rgba(0,188,212,0.6)' },
                { price: fib.fib_618, label: 'Fib 61.8%', color: 'rgba(0,188,212,0.7)' },
                { price: fib.fib_786, label: 'Fib 78.6%', color: 'rgba(0,188,212,0.5)' },
            ];
            for (const fl of fibLevels) {
                if (fl.price) {
                    lwCandleSeries.createPriceLine({
                        price: fl.price, color: fl.color, lineWidth: 1, lineStyle: 1,
                        axisLabelVisible: false, title: fl.label,
                    });
                }
            }
        }

        // Support/resistance price lines
        if (chartPackage?.summary) {
            const s = chartPackage.summary;
            if (s.support) {
                lwCandleSeries.createPriceLine({
                    price: s.support, color: 'rgba(38,166,154,0.6)', lineWidth: 1, lineStyle: 2,
                    axisLabelVisible: true, title: 'WSPARCIE',
                });
            }
            if (s.resistance) {
                lwCandleSeries.createPriceLine({
                    price: s.resistance, color: 'rgba(239,83,80,0.6)', lineWidth: 1, lineStyle: 2,
                    axisLabelVisible: true, title: 'OPÓR',
                });
            }
        }

        // Buy/sell markers from decisions
        if (chartPackage?.markers?.length && lwCandleSeries) {
            const timeSet = new Set(uniqueSeries.map(p => p.time));
            const markers = chartPackage.markers
                .map(m => {
                    const t = Math.floor(new Date(m.time).getTime() / 1000);
                    if (!timeSet.has(t)) return null;
                    const isBuy = m.action === "BUY";
                    return {
                        time: t,
                        position: isBuy ? 'belowBar' : 'aboveBar',
                        color: isBuy ? '#26a69a' : '#ef5350',
                        shape: isBuy ? 'arrowUp' : 'arrowDown',
                        text: isBuy ? 'KUP' : 'SPRZEDAJ',
                    };
                })
                .filter(Boolean)
                .sort((a, b) => a.time - b.time);
            // Deduplicate markers by time
            const uniqueMarkers = [];
            const seenMarkerTimes = new Set();
            for (const m of markers) {
                if (!seenMarkerTimes.has(m.time)) {
                    seenMarkerTimes.add(m.time);
                    uniqueMarkers.push(m);
                }
            }
            if (uniqueMarkers.length) {
                lwCandleSeries.setMarkers(uniqueMarkers);
            }
        }

        // ATH/ATL lines for lifecycle
        if (isLifecycle && dataSource?.summary) {
            const ls = dataSource.summary;
            if (ls.ath_price) {
                lwCandleSeries.createPriceLine({
                    price: ls.ath_price, color: 'rgba(239,83,80,0.6)', lineWidth: 1, lineStyle: 2,
                    axisLabelVisible: true, title: `ATH ${ls.ath_date || ''}`,
                });
            }
            if (ls.atl_price && ls.atl_price > 0) {
                lwCandleSeries.createPriceLine({
                    price: ls.atl_price, color: 'rgba(38,166,154,0.4)', lineWidth: 1, lineStyle: 2,
                    axisLabelVisible: true, title: `ATL`,
                });
            }
        }
    }

    lwChart.timeScale().fitContent();

    // ── Chart legend overlay ──
    if (showOverview || showPrice) {
        const legend = document.createElement('div');
        legend.style.cssText = 'position:absolute;top:8px;left:8px;z-index:10;display:flex;flex-wrap:wrap;gap:6px 12px;font-size:11px;pointer-events:none;';
        const items = [
            { color: '#2962ff', label: 'EMA20' },
            { color: '#ff6d00', label: 'EMA50' },
            { color: '#9c27b0', label: 'Bollinger' },
            { color: '#ffeb3b', label: 'VWAP' },
            { color: '#00bcd4', label: 'Fibonacci' },
        ];
        legend.innerHTML = items.map(i =>
            `<span style="display:flex;align-items:center;gap:3px;"><span style="width:12px;height:2px;background:${i.color};display:inline-block;"></span><span style="color:#787b86;">${i.label}</span></span>`
        ).join('');
        container.style.position = 'relative';
        container.appendChild(legend);
    }
    
    // Responsive resize
    const resizeObserver = new ResizeObserver(entries => {
        if (lwChart) {
            const { width } = entries[0].contentRect;
            lwChart.applyOptions({ width });
        }
    });
    resizeObserver.observe(container);

    // Build summary and insights
    paintChartSummaryAndInsights(summary, insights, chartPackage, isLifecycle ? dataSource : null);
}

function paintChartSummaryAndInsights(summary, insights, chartPackage, lifecycleHistory) {
    if (lifecycleHistory?.summary) {
        const ls = lifecycleHistory.summary;
        summary.innerHTML = `
            ${buildSummaryCard("Start", formatQuote(ls.inception_price), "")}
            ${buildSummaryCard("Teraz", formatQuote(ls.current_price), "")}
            ${buildSummaryCard("ATH", formatQuote(ls.ath_price), "")}
            ${buildSummaryCard("ATL", formatQuote(ls.atl_price), "")}
            ${buildSummaryCard("Od startu", `${formatSignedPercent(ls.change_since_inception)}`, toneClass(ls.change_since_inception))}
            ${buildSummaryCard("Lata na rynku", `${numberFormatter.format(ls.years_listed)}`, "")}
            ${buildSummaryCard("Punkty", compactNumber(ls.points_count || 0), "")}
            ${buildSummaryCard("Zrodlo", String(ls.history_source || "").toUpperCase(), "")}
        `;
        insights.innerHTML = `
            <div class="stack-item"><div class="stack-item-title"><span>${lifecycleHistory.symbol || ""}</span><span class="badge neutral">OD STARTU</span></div><div class="stack-item-meta">Pelna historia cenowa z interaktywnym wykresem. Mozesz przybliżać, przesuwać i najeżdżać na świece.</div></div>
        `;
        return;
    }

    if (!chartPackage?.summary) {
        summary.innerHTML = "";
        insights.innerHTML = "";
        return;
    }

    const s = chartPackage.summary;

    if (selectedChartTab === "rsi") {
        summary.innerHTML = `
            ${buildSummaryCard("RSI", `${percentFormatter.format(s.rsi)}`, toneClass(50 - s.rsi))}
            ${buildSummaryCard("Strefa", s.rsi_zone?.toUpperCase() || "-", s.rsi_zone === "oversold" ? "positive" : s.rsi_zone === "overbought" ? "negative" : "")}
            ${buildSummaryCard("P up", `${percentFormatter.format(s.up_probability)}%`, toneClass(s.up_probability - 50))}
        `;
        insights.innerHTML = `<div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">RSI</span></div><div class="stack-item-meta">RSI mierzy przegrzanie lub wykupienie rynku. Agent interpretuje go razem z trendem cenowym i wolumenem.</div></div>`;
        return;
    }
    if (selectedChartTab === "macd") {
        summary.innerHTML = `
            ${buildSummaryCard("MACD", `${percentFormatter.format(s.macd)}`, toneClass(s.macd - s.macd_signal))}
            ${buildSummaryCard("Signal", `${percentFormatter.format(s.macd_signal)}`, "")}
            ${buildSummaryCard("Stan", s.macd_state?.toUpperCase() || "-", s.macd_state === "bullish" ? "positive" : "negative")}
            ${buildSummaryCard("P up", `${percentFormatter.format(s.up_probability)}%`, toneClass(s.up_probability - 50))}
        `;
        insights.innerHTML = `<div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">MACD</span></div><div class="stack-item-meta">MACD pokazuje momentum i zmiane trendu. Agent łączy crossover z trendem i wolumenem.</div></div>`;
        return;
    }
    if (selectedChartTab === "volume") {
        summary.innerHTML = `
            ${buildSummaryCard("Zmiana vol.", `${percentFormatter.format(s.volume_change)}%`, toneClass(s.volume_change))}
            ${buildSummaryCard("Trend", s.trend?.toUpperCase() || "-", s.trend === "UP" ? "positive" : s.trend === "DOWN" ? "negative" : "")}
            ${buildSummaryCard("P up", `${percentFormatter.format(s.up_probability)}%`, toneClass(s.up_probability - 50))}
        `;
        insights.innerHTML = `<div class="stack-item"><div class="stack-item-title"><span>${chartPackage.symbol}</span><span class="badge neutral">WOLUMEN</span></div><div class="stack-item-meta">Wolumen potwierdza sile ruchow cenowych. Agent bada czy trend jest wspierany aktywnością rynku.</div></div>`;
        return;
    }

    // Overview / Price tab
    summary.innerHTML = `
        ${buildSummaryCard("7 dni", `${formatSignedPercent(s.change_7d)}`, toneClass(s.change_7d))}
        ${buildSummaryCard("30 dni", `${formatSignedPercent(s.change_30d)}`, toneClass(s.change_30d))}
        ${buildSummaryCard("24h", `${formatSignedPercent(s.change_24h)}`, toneClass(s.change_24h))}
        ${buildSummaryCard("Zmiennosc 14d", `${percentFormatter.format(s.volatility_14d)}%`, "")}
        ${buildSummaryCard("Wsparcie", formatQuote(s.support), "")}
        ${buildSummaryCard("Opor", formatQuote(s.resistance), "")}
        ${buildSummaryCard("EMA20", formatQuote(s.ema20), "")}
        ${buildSummaryCard("EMA50", formatQuote(s.ema50), "")}
        ${buildSummaryCard("RSI", `${percentFormatter.format(s.rsi)}`, toneClass(50 - s.rsi))}
        ${buildSummaryCard("MACD", `${percentFormatter.format(s.macd)}`, toneClass(s.macd - s.macd_signal))}
        ${buildSummaryCard("P up", `${percentFormatter.format(s.up_probability)}%`, toneClass(s.up_probability - 50))}
        ${buildSummaryCard("P dolek", `${percentFormatter.format(s.bottom_probability)}%`, toneClass(s.bottom_probability - 50))}
        ${buildSummaryCard("P szczyt", `${percentFormatter.format(s.top_probability)}%`, toneClass(50 - s.top_probability))}
        ${buildSummaryCard("Sygnał", s.signal_alignment?.toUpperCase() || "-", s.signal_alignment === "bullish" ? "positive" : s.signal_alignment === "bearish" ? "negative" : "")}
    `;

    const allInsights = [...(chartPackage.insights || []), ...(s.probability_explanation || [])];
    insights.innerHTML = allInsights.map((item) => `
        <div class="stack-item">
            <div class="stack-item-title">
                <span>${chartPackage.symbol}</span>
                <span class="badge hold">ANALIZA</span>
            </div>
            <div class="stack-item-meta">${item}</div>
        </div>
    `).join("");
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

function paintLeveragePaper(data) {
    const statsContainer = document.getElementById("leverage-stats");
    const openContainer = document.getElementById("leverage-open-positions");
    const closedContainer = document.getElementById("leverage-closed-trades");
    if (!statsContainer) return;

    if (!data) {
        statsContainer.innerHTML = `<div class="empty-state">Agent jeszcze nie rozpoczął nauki dźwigni.</div>`;
        if (openContainer) openContainer.innerHTML = "";
        if (closedContainer) closedContainer.innerHTML = "";
        return;
    }

    const pnlClass = (data.total_realized_pnl || 0) >= 0 ? "positive" : "negative";
    statsContainer.innerHTML = `
        ${buildQuickCard("Balans Paper", `$${numberFormatter.format(data.paper_balance)}`, "Startowy kapitał wirtualny")}
        ${buildQuickCard("Dostępny margin", `$${numberFormatter.format(data.available_margin)}`, "Wolne środki na nowe pozycje")}
        ${buildQuickCard("Equity", `$${numberFormatter.format(data.current_equity)}`, "Margin + otwarte pozycje")}
        ${buildQuickCard("P&L łączny", `<span class="${pnlClass}">$${numberFormatter.format(data.total_realized_pnl || 0)}</span>`, `${data.total_trades || 0} transakcji zamkniętych`)}
        ${buildQuickCard("Win rate", `${percentFormatter.format(data.win_rate || 0)}%`, `${data.wins || 0}W / ${data.losses || 0}L`)}
        ${buildQuickCard("Dźwignia", `${data.current_leverage_level || 2}x`, `Likwidacje: ${data.liquidations || 0}`)}
    `;

    if (openContainer) {
        const open = data.open_positions || [];
        if (!open.length) {
            openContainer.innerHTML = `<div class="empty-state">Brak otwartych pozycji lewarowanych.</div>`;
        } else {
            openContainer.innerHTML = open.map(p => {
                const sideClass = p.side === "LONG" ? "buy" : "sell";
                return `<div class="stack-item">
                    <div class="stack-item-title">
                        <span>${p.symbol}</span>
                        <span class="badge ${sideClass}">${p.side} ${p.leverage}x</span>
                    </div>
                    <div class="stack-item-meta">
                        Wejście: $${numberFormatter.format(p.entry_price)} | Margin: $${numberFormatter.format(p.margin_used)}<br>
                        Likwidacja: $${numberFormatter.format(p.liquidation_price)}${p.take_profit ? ` | TP: $${numberFormatter.format(p.take_profit)}` : ""}${p.stop_loss ? ` | SL: $${numberFormatter.format(p.stop_loss)}` : ""}<br>
                        Funding: $${p.funding_fees.toFixed(4)} | ${new Date(p.opened_at).toLocaleString("pl-PL")}
                    </div>
                </div>`;
            }).join("");
        }
    }

    if (closedContainer) {
        const closed = data.recent_closed || [];
        if (!closed.length) {
            closedContainer.innerHTML = `<div class="empty-state">Brak zamkniętych transakcji lewarowanych.</div>`;
        } else {
            closedContainer.innerHTML = closed.map(t => {
                const pnl = t.pnl || 0;
                const tone = pnl >= 0 ? "positive" : "negative";
                const sideClass = t.side === "LONG" ? "buy" : "sell";
                const statusBadge = t.status === "LIQUIDATED" ? `<span class="badge sell">LIKWIDACJA</span>` : "";
                return `<div class="stack-item">
                    <div class="stack-item-title">
                        <span>${t.symbol} ${t.side} ${t.leverage}x</span>
                        <span class="badge ${sideClass}">${t.close_reason || ""}${statusBadge}</span>
                    </div>
                    <div class="stack-item-meta">
                        Wejście: $${numberFormatter.format(t.entry_price)} → Wyjście: $${numberFormatter.format(t.exit_price)}<br>
                        P&L: <span class="${tone}">$${numberFormatter.format(pnl)} (${t.pnl_pct > 0 ? "+" : ""}${percentFormatter.format(t.pnl_pct)}%)</span><br>
                        Funding: $${t.funding_fees.toFixed(4)} | ${t.closed_at ? new Date(t.closed_at).toLocaleString("pl-PL") : "-"}
                    </div>
                </div>`;
            }).join("");
        }
    }

    // Initialize leverage chart (once controls exist)
    paintLeverageChartControls();
    fetchAndPaintLeverageChart();
}

// ═══════════════════════════════════════════════════════════
// LEVERAGE PERPETUAL CHART (Bybit klines + agent markers)
// ═══════════════════════════════════════════════════════════

let levChart = null;
let levSelectedSymbol = "BTC";
let levSelectedInterval = "60";
const levIntervals = [
    { id: "15", label: "15m" },
    { id: "60", label: "1H" },
    { id: "240", label: "4H" },
    { id: "D", label: "1D" },
];

function paintLeverageChartControls() {
    const symContainer = document.getElementById("lev-chart-symbols");
    const intContainer = document.getElementById("lev-chart-intervals");
    if (!symContainer || !intContainer) return;

    // Symbol buttons — use tracked symbols that have leverage positions, or top 8
    const topSymbols = ["BTC", "ETH", "SOL", "XRP", "DOGE", "ADA", "AVAX", "LINK"];
    symContainer.innerHTML = topSymbols.map(s =>
        `<button class="switcher-button${s === levSelectedSymbol ? " active" : ""}" data-lev-sym="${s}">${s}</button>`
    ).join("");
    symContainer.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", () => {
            levSelectedSymbol = btn.dataset.levSym;
            symContainer.querySelectorAll("button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            fetchAndPaintLeverageChart();
        });
    });

    // Interval buttons
    intContainer.innerHTML = levIntervals.map(i =>
        `<button class="switcher-button${i.id === levSelectedInterval ? " active" : ""}" data-lev-int="${i.id}">${i.label}</button>`
    ).join("");
    intContainer.querySelectorAll("button").forEach(btn => {
        btn.addEventListener("click", () => {
            levSelectedInterval = btn.dataset.levInt;
            intContainer.querySelectorAll("button").forEach(b => b.classList.remove("active"));
            btn.classList.add("active");
            fetchAndPaintLeverageChart();
        });
    });
}

let _levChartCache = {};

async function fetchAndPaintLeverageChart() {
    const container = document.getElementById("lev-chart-container");
    const infoBox = document.getElementById("lev-chart-info");
    if (!container) return;

    const cacheKey = `${levSelectedSymbol}_${levSelectedInterval}`;
    const cached = _levChartCache[cacheKey];
    if (cached && Date.now() - cached.ts < 120000) {
        paintLeverageChart(cached.data);
        return;
    }

    container.innerHTML = `<div class="empty-state">Ładowanie wykresu ${levSelectedSymbol}USDT...</div>`;

    try {
        const resp = await fetch(`/api/leverage/chart/${levSelectedSymbol}?interval=${levSelectedInterval}&limit=200`);
        if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
        const data = await resp.json();
        _levChartCache[cacheKey] = { data, ts: Date.now() };
        paintLeverageChart(data);
    } catch (err) {
        container.innerHTML = `<div class="empty-state">Błąd ładowania wykresu: ${err.message}</div>`;
    }
}

function destroyLevChart() {
    if (levChart) {
        levChart.remove();
        levChart = null;
    }
}

function paintLeverageChart(data) {
    const container = document.getElementById("lev-chart-container");
    const infoBox = document.getElementById("lev-chart-info");
    if (!container) return;

    destroyLevChart();
    container.innerHTML = "";

    const klines = data.klines || [];
    if (!klines.length) {
        container.innerHTML = `<div class="empty-state">Brak danych klines dla ${data.symbol}.</div>`;
        return;
    }

    const chartHeight = window.innerWidth <= 768 ? 300 : 440;
    const chartWidth = container.clientWidth || container.parentElement?.clientWidth || window.innerWidth - 60;

    levChart = LightweightCharts.createChart(container, {
        width: chartWidth,
        height: chartHeight,
        layout: {
            background: { type: "solid", color: "#0d1117" },
            textColor: "#8b949e",
            fontSize: 11,
            fontFamily: "-apple-system, BlinkMacSystemFont, 'Trebuchet MS', sans-serif",
        },
        grid: {
            vertLines: { color: "rgba(48,54,61,0.6)" },
            horzLines: { color: "rgba(48,54,61,0.6)" },
        },
        crosshair: {
            mode: LightweightCharts.CrosshairMode.Normal,
            vertLine: { color: "rgba(88,166,255,0.3)", width: 1, style: 2, labelBackgroundColor: "#58a6ff" },
            horzLine: { color: "rgba(88,166,255,0.3)", width: 1, style: 2, labelBackgroundColor: "#58a6ff" },
        },
        rightPriceScale: {
            borderColor: "rgba(48,54,61,0.8)",
            scaleMargins: { top: 0.05, bottom: 0.22 },
        },
        timeScale: {
            borderColor: "rgba(48,54,61,0.8)",
            timeVisible: true,
            secondsVisible: false,
            rightOffset: 3,
        },
        handleScroll: { vertTouchDrag: false },
        handleScale: { axisPressedMouseMove: { time: true, price: false } },
    });

    // Deduplicate klines by time
    const seenTimes = new Set();
    const uniqueKlines = [];
    for (const k of klines) {
        if (!seenTimes.has(k.time)) {
            seenTimes.add(k.time);
            uniqueKlines.push(k);
        }
    }

    // Candlestick series
    const candleSeries = levChart.addCandlestickSeries({
        upColor: "#3fb950",
        downColor: "#f85149",
        borderDownColor: "#f85149",
        borderUpColor: "#3fb950",
        wickDownColor: "#f85149",
        wickUpColor: "#3fb950",
    });
    candleSeries.setData(uniqueKlines.map(k => ({
        time: k.time, open: k.open, high: k.high, low: k.low, close: k.close,
    })));

    // Volume overlay
    const volSeries = levChart.addHistogramSeries({
        priceFormat: { type: "volume" },
        priceScaleId: "lev-volume",
    });
    levChart.priceScale("lev-volume").applyOptions({
        scaleMargins: { top: 0.84, bottom: 0 },
    });
    volSeries.setData(uniqueKlines.map(k => ({
        time: k.time,
        value: k.volume,
        color: k.close >= k.open ? "rgba(63,185,80,0.2)" : "rgba(248,81,73,0.2)",
    })));

    // ── Agent leverage trade markers ──
    const markers = data.markers || [];
    if (markers.length && candleSeries) {
        const timeSet = new Set(uniqueKlines.map(k => k.time));
        const chartMarkers = [];

        for (const m of markers) {
            // Snap marker time to the nearest kline time
            let bestTime = m.time;
            if (!timeSet.has(bestTime)) {
                let closest = null;
                let minDiff = Infinity;
                for (const kt of timeSet) {
                    const diff = Math.abs(kt - bestTime);
                    if (diff < minDiff) { minDiff = diff; closest = kt; }
                }
                if (closest !== null && minDiff < 86400 * 7) bestTime = closest;
                else continue;
            }

            if (m.type === "entry") {
                const isLong = m.side === "LONG";
                chartMarkers.push({
                    time: bestTime,
                    position: isLong ? "belowBar" : "aboveBar",
                    color: isLong ? "#3fb950" : "#f85149",
                    shape: isLong ? "arrowUp" : "arrowDown",
                    text: `${isLong ? "LONG" : "SHORT"} ${m.leverage}x`,
                });
            } else if (m.type === "exit") {
                const pnl = m.pnl || 0;
                const isWin = pnl >= 0;
                const label = m.status === "LIQUIDATED" ? "LIQ" :
                    (m.reason === "take_profit" ? "TP" :
                    (m.reason === "stop_loss" ? "SL" : "EXIT"));
                chartMarkers.push({
                    time: bestTime,
                    position: m.side === "LONG" ? "aboveBar" : "belowBar",
                    color: isWin ? "#58a6ff" : "#d29922",
                    shape: "circle",
                    text: `${label} ${pnl >= 0 ? "+" : ""}${pnl.toFixed(1)}$`,
                });
            }
        }

        // Sort and deduplicate
        chartMarkers.sort((a, b) => a.time - b.time);
        const uniqueMarkers = [];
        const seenMTimes = new Set();
        for (const m of chartMarkers) {
            const key = `${m.time}_${m.text}`;
            if (!seenMTimes.has(key)) {
                seenMTimes.add(key);
                uniqueMarkers.push(m);
            }
        }
        if (uniqueMarkers.length) candleSeries.setMarkers(uniqueMarkers);
    }

    // ── Open position lines (entry, TP, SL, liquidation) ──
    const positions = data.positions || [];
    for (const pos of positions) {
        const isLong = pos.side === "LONG";
        // Entry price line
        candleSeries.createPriceLine({
            price: pos.entry_price,
            color: isLong ? "#3fb950" : "#f85149",
            lineWidth: 2,
            lineStyle: 0,
            axisLabelVisible: true,
            title: `${pos.side} ${pos.leverage}x WEJŚCIE`,
        });
        // Take profit
        if (pos.take_profit) {
            candleSeries.createPriceLine({
                price: pos.take_profit,
                color: "#58a6ff",
                lineWidth: 1,
                lineStyle: 2,
                axisLabelVisible: true,
                title: "TP",
            });
        }
        // Stop loss
        if (pos.stop_loss) {
            candleSeries.createPriceLine({
                price: pos.stop_loss,
                color: "#d29922",
                lineWidth: 1,
                lineStyle: 2,
                axisLabelVisible: true,
                title: "SL",
            });
        }
        // Liquidation
        if (pos.liquidation_price) {
            candleSeries.createPriceLine({
                price: pos.liquidation_price,
                color: "#f85149",
                lineWidth: 1,
                lineStyle: 1,
                axisLabelVisible: true,
                title: "⚠ LIKWIDACJA",
            });
        }
    }

    // ── Funding rate info bar ──
    if (infoBox) {
        const fr = data.funding_rate_pct || 0;
        const frClass = fr > 0.01 ? "negative" : (fr < -0.01 ? "positive" : "");
        const mp = data.mark_price ? numberFormatter.format(data.mark_price) : "-";
        const ip = data.index_price ? numberFormatter.format(data.index_price) : "-";
        const fh = (data.funding_history || []).slice(0, 5);
        const fhHtml = fh.length ? fh.map(f => {
            const fc = f.rate > 0.0001 ? "negative" : (f.rate < -0.0001 ? "positive" : "");
            return `<span class="${fc}">${f.rate_pct}%</span>`;
        }).join(" → ") : "";

        infoBox.innerHTML = `
            <div class="lev-info-row">
                <span>Funding: <strong class="${frClass}">${fr.toFixed(4)}%</strong></span>
                <span>Mark: <strong>$${mp}</strong></span>
                <span>Index: <strong>$${ip}</strong></span>
                ${fhHtml ? `<span class="lev-funding-history">Historia: ${fhHtml}</span>` : ""}
            </div>
        `;
    }

    // Resize handler
    const resizeObserver = new ResizeObserver(() => {
        if (levChart && container.clientWidth > 0) {
            levChart.applyOptions({ width: container.clientWidth });
        }
    });
    resizeObserver.observe(container);

    levChart.timeScale().fitContent();
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

function whaleIndicator(row) {
    const sig = row.whale_signal || "NONE";
    const score = row.whale_score || 0;
    const count = row.whale_alerts_24h || 0;
    if (sig === "NONE" && count === 0) return '<span class="whale-none">—</span>';
    let icon = "🐋";
    let cls = "whale-mild";
    if (sig.startsWith("WHALE_")) { cls = "whale-strong"; }
    else if (sig.startsWith("SPIKE_")) { cls = sig === "SPIKE_UP" ? "whale-up" : "whale-down"; icon = "⚡"; }
    else if (sig === "VOL_ANOMALY" || sig === "HIGH_VOLUME") { cls = "whale-vol"; icon = "📊"; }
    else if (sig === "PRICE_ANOMALY") { cls = "whale-down"; icon = "⚠️"; }
    const countBadge = count > 1 ? `<sup class="whale-count">${count}</sup>` : "";
    return `<span class="${cls}" title="${sig} (score ${score})">${icon}${countBadge}</span>`;
}

function fundingToneClass(rate) {
    if (rate == null) return "";
    if (rate > 0.03) return "negative";
    if (rate < -0.01) return "positive";
    return "";
}

function oiTrendClass(trend) {
    if (trend === "RISING") return "positive";
    if (trend === "FALLING") return "negative";
    return "";
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
    ai: "Czat z Agentem",
    calendar: "Kalendarz",
    settings: "Status",
    help: "Pomoc"
};

let currentView = "dashboard";

function switchView(viewName) {
    if (viewName === currentView) return;

    // Deactivate old view directly
    const oldView = document.querySelector(`.app-view[data-view="${currentView}"]`);
    if (oldView) oldView.classList.remove("active");
    
    // Activate new view directly
    const newView = document.querySelector(`.app-view[data-view="${viewName}"]`);
    if (newView) newView.classList.add("active");

    // Update sidebar nav
    const oldNavDesktop = document.querySelector(`.nav-item[data-view="${currentView}"]`);
    const newNavDesktop = document.querySelector(`.nav-item[data-view="${viewName}"]`);
    if (oldNavDesktop) oldNavDesktop.classList.remove("active");
    if (newNavDesktop) newNavDesktop.classList.add("active");

    // Update mobile nav
    const oldNavMobile = document.querySelector(`.mobile-nav-item[data-view="${currentView}"]`);
    const newNavMobile = document.querySelector(`.mobile-nav-item[data-view="${viewName}"]`);
    if (oldNavMobile) oldNavMobile.classList.remove("active");
    if (newNavMobile) newNavMobile.classList.add("active");
    
    // Update title
    const titleEl = document.getElementById("view-title");
    if (titleEl) {
        titleEl.textContent = viewTitles[viewName] || viewName;
    }
    
    currentView = viewName;

    // Scroll to top on mobile
    if (newView) newView.scrollTop = 0;
    
    // Sync duplicate elements between views if needed
    if (viewName === "portfolio") {
        syncPortfolioView();
    }
    if (viewName === "calendar" && !window._calendarLoaded) {
        window._calendarLoaded = true;
        initCalendar();
    }
    if (viewName === "charts") {
        // On mobile, charts view was display:none during initial render,
        // so the chart may have width 0 or not exist. Re-render it.
        if (lwChart) {
            const c = document.getElementById("lw-chart-container");
            if (c && c.clientWidth > 0) {
                lwChart.applyOptions({ width: c.clientWidth });
                lwChart.timeScale().fitContent();
            } else {
                // Container still has no width — re-render after layout
                requestAnimationFrame(() => renderSelectedChart().catch(() => {}));
            }
        } else if (selectedSymbol) {
            renderSelectedChart().catch(() => {});
        }
    }
}

function syncPortfolioView() {
    // If live portfolio data exists, paintLivePortfolio handles it.
    // Fallback: copy bought coins menu to portfolio view for PAPER mode.
    const liveEl = document.getElementById("live-portfolio-list");
    const paperEl = document.getElementById("bought-coins-menu-2");
    if (liveEl && liveEl.children.length > 0) {
        liveEl.style.display = "";
        if (paperEl) paperEl.style.display = "none";
        return;
    }
    if (paperEl) {
        paperEl.style.display = "";
        const source = document.getElementById("bought-coins-menu");
        if (source) paperEl.innerHTML = source.innerHTML;
    }
    if (liveEl) liveEl.style.display = "none";
}

function paintLivePortfolio(holdings, quoteCurrency) {
    const container = document.getElementById("live-portfolio-list");
    const label = document.getElementById("portfolio-total-label");
    if (!container) return;
    if (!holdings || !holdings.length) {
        container.innerHTML = `<div class="empty-state">Brak danych portfela.</div>`;
        if (label) label.textContent = "";
        return;
    }
    const qc = quoteCurrency || "PLN";
    const totalValue = holdings.reduce((s, h) => s + (h.value || 0), 0);
    const totalPnl = holdings.filter(h => !h.is_stable).reduce((s, h) => s + (h.pnl_value || 0), 0);
    const pnlClass = totalPnl >= 0 ? "positive" : "negative";
    const pnlSign = totalPnl >= 0 ? "+" : "";
    if (label) label.innerHTML = `Razem: <strong>${formatQuote(totalValue, qc)}</strong> &nbsp; <span class="${pnlClass}">${pnlSign}${formatQuote(totalPnl, qc)}</span>`;

    container.innerHTML = holdings.map(h => {
        if (h.is_stable) {
            return `<div class="pf-row pf-stable">
                <div class="pf-symbol">${h.asset}</div>
                <div class="pf-value">${formatQuote(h.value, qc)}</div>
                <div class="pf-pnl stable">stablecoin</div>
            </div>`;
        }
        const cls = h.pnl_value >= 0 ? "positive" : "negative";
        const sign = h.pnl_value >= 0 ? "+" : "";
        const pctSign = h.pnl_pct >= 0 ? "+" : "";
        const arrow = h.pnl_value >= 0 ? "▲" : "▼";
        const avgBuy = h.avg_buy_price ? formatQuote(h.avg_buy_price, qc) : "—";
        const curPrice = h.current_price ? formatQuote(h.current_price, qc) : "—";
        return `<div class="pf-row">
            <div class="pf-main">
                <div class="pf-symbol">${h.asset}</div>
                <div class="pf-qty">${numberFormatter.format(h.total)}</div>
            </div>
            <div class="pf-prices">
                <span class="pf-label">Kupno:</span> <span>${avgBuy}</span>
                <span class="pf-label">Teraz:</span> <span>${curPrice}</span>
            </div>
            <div class="pf-right">
                <div class="pf-value">${formatQuote(h.value, qc)}</div>
                <div class="pf-pnl ${cls}">
                    <span class="pf-arrow">${arrow}</span>
                    ${sign}${formatQuote(h.pnl_value, qc)}
                    <span class="pf-pct">(${pctSign}${h.pnl_pct.toFixed(1)}%)</span>
                </div>
            </div>
        </div>`;
    }).join("");
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
    document.querySelectorAll(".card-header.collapsible").forEach((header, idx) => {
        const body = header.nextElementSibling;
        // Help cards: collapse all except first
        if (header.closest('.help-page') && idx > 0 && body) {
            header.classList.add("collapsed");
            body.style.display = "none";
        }
        header.addEventListener("click", () => {
            header.classList.toggle("collapsed");
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
    switchView("ai");
    const input = document.getElementById("chat-input");
    if (input) input.focus();
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

// Mobile more menu (bottom sheet)
const mobileMoreMenu = document.getElementById("mobile-more-menu");
const mobileMoreBtn = document.getElementById("mobile-more-btn");
if (mobileMoreMenu && mobileMoreBtn) {
    mobileMoreBtn.addEventListener("click", () => {
        mobileMoreMenu.classList.remove("hidden");
    });
    const backdrop = mobileMoreMenu.querySelector(".mobile-more-backdrop");
    if (backdrop) {
        backdrop.addEventListener("click", () => {
            mobileMoreMenu.classList.add("hidden");
        });
    }
    mobileMoreMenu.querySelectorAll(".mobile-more-item[data-view]").forEach(item => {
        item.addEventListener("click", () => {
            mobileMoreMenu.classList.add("hidden");
            switchView(item.dataset.view);
        });
    });
}

// Mobile AI brief button
const mobileAiBriefBtn = document.getElementById("mobile-ai-brief-btn");
if (mobileAiBriefBtn) {
    mobileAiBriefBtn.addEventListener("click", async () => {
        switchView("ai");
        try { await loadAiInsightToChat(); } catch(e) { setStatus(e.message); }
    });
}

document.getElementById("reset-paper-button").addEventListener("click", async () => {
    try {
        await resetPaperPortfolio();
    } catch (error) {
        setStatus(error.message);
    }
});

// AI refresh button in AI view — puts analysis into chat
const aiRefreshBtn = document.getElementById("ai-refresh-button");
if (aiRefreshBtn) {
    aiRefreshBtn.addEventListener("click", async () => {
        try {
            await loadAiInsightToChat();
        } catch (error) {
            setStatus(error.message);
        }
    });
}

// ==================== AGENT CHAT ====================
let chatHistory = [];

function addChatMessage(role, text, isHtml) {
    const container = document.getElementById("chat-messages");
    if (!container) return;
    const msgDiv = document.createElement("div");
    msgDiv.className = `chat-msg ${role}`;

    const avatar = document.createElement("div");
    avatar.className = "chat-avatar";
    avatar.textContent = role === "agent" ? "🤖" : "👤";

    const bubble = document.createElement("div");
    bubble.className = "chat-bubble";
    if (isHtml) {
        bubble.innerHTML = text;
    } else {
        bubble.textContent = text;
    }

    msgDiv.appendChild(avatar);
    msgDiv.appendChild(bubble);
    container.appendChild(msgDiv);
    container.scrollTop = container.scrollHeight;
}

function showChatTyping(show) {
    const el = document.getElementById("chat-typing");
    if (el) el.classList.toggle("hidden", !show);
    if (show) {
        const container = document.getElementById("chat-messages");
        if (container) container.scrollTop = container.scrollHeight;
    }
}

async function sendChatMessage(userMsg) {
    if (!userMsg || !userMsg.trim()) return;
    userMsg = userMsg.trim();

    addChatMessage("user", userMsg);
    chatHistory.push({ role: "user", content: userMsg });

    const input = document.getElementById("chat-input");
    if (input) { input.value = ""; input.focus(); }

    showChatTyping(true);
    setStatus("Agent myśli...");

    try {
        const resp = await fetch("/api/agent-chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message: userMsg, history: chatHistory.slice(-10) }),
        });
        const data = await resp.json();
        showChatTyping(false);

        if (!data.enabled) {
            addChatMessage("agent", data.reply || "Błąd: AI niedostępne.");
            setStatus("AI niedostępne");
            return;
        }

        const reply = data.reply || "Nie uzyskano odpowiedzi.";
        chatHistory.push({ role: "assistant", content: reply });

        // Check if there's an actionable command
        if (data.command && data.command.action && data.command.symbol) {
            const cmd = data.command;
            const confirmHtml = `<p>${escapeHtml(reply)}</p>
                <div class="chat-command-confirm">
                    <p class="chat-cmd-label">⚡ Wykryto polecenie: <strong>${cmd.action} ${cmd.symbol}</strong></p>
                    <button class="chat-exec-btn" data-action="${escapeHtml(cmd.action)}" data-symbol="${escapeHtml(cmd.symbol)}">
                        Wykonaj ${cmd.action} ${cmd.symbol}
                    </button>
                    <button class="chat-cancel-btn">Anuluj</button>
                </div>`;
            addChatMessage("agent", confirmHtml, true);
        } else {
            addChatMessage("agent", reply);
        }

        // Show self-modification results if any
        if (data.selfmod_results && data.selfmod_results.length > 0) {
            const modParts = data.selfmod_results.map(r =>
                r.ok ? `✅ ${r.message || "OK"}` : `❌ ${r.error || "Błąd"}`
            );
            addChatMessage("agent", `<div class="chat-selfmod-notice">🔧 <strong>Modyfikacja agenta:</strong><br>${modParts.join("<br>")}</div>`, true);
        }

        setStatus(`Czat: odpowiedź (${data.input_tokens || 0}+${data.output_tokens || 0} tokenów)`);
    } catch (err) {
        showChatTyping(false);
        addChatMessage("agent", "Błąd połączenia z serwerem. Spróbuj ponownie.");
        setStatus("Błąd czatu");
    }
}

async function executeChatCommand(action, symbol) {
    addChatMessage("agent", `⏳ Wykonuję ${action} ${symbol}...`);
    setStatus(`Wykonuję ${action} ${symbol}...`);

    try {
        const resp = await fetch("/api/agent-chat/execute", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action, symbol }),
        });
        const data = await resp.json();

        if (data.ok) {
            addChatMessage("agent", `✅ ${data.detail}`);
            setStatus(`Zlecenie wykonane: ${data.detail}`);
            // Refresh dashboard to show updated balances
            try { await renderDashboardWithRetry(1, 0); } catch(e) {}
        } else {
            addChatMessage("agent", `❌ Nie udało się: ${data.error || "Nieznany błąd"}`);
            setStatus(`Błąd zlecenia: ${data.error || ""}`);
        }
    } catch (err) {
        addChatMessage("agent", "❌ Błąd połączenia z serwerem.");
        setStatus("Błąd wykonania zlecenia");
    }
}

async function loadAiInsightToChat() {
    addChatMessage("user", "Daj mi analizę rynku");
    showChatTyping(true);
    setStatus("Generowanie analizy AI...");

    try {
        const symbolQuery = selectedSymbol ? `?symbol=${encodeURIComponent(selectedSymbol)}` : "";
        const resp = await fetch(`/api/ai-insight${symbolQuery}`);
        const data = await resp.json();
        showChatTyping(false);

        if (data.enabled && data.message) {
            addChatMessage("agent", data.message);
            chatHistory.push({ role: "assistant", content: data.message });
            setStatus("Analiza AI gotowa");
        } else {
            addChatMessage("agent", data.message || "AI niedostępne.");
            setStatus("AI nieaktywne");
        }
    } catch (err) {
        showChatTyping(false);
        addChatMessage("agent", "Błąd pobierania analizy AI.");
        setStatus("Błąd AI");
    }
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

// Chat form submit
const chatForm = document.getElementById("chat-form");
if (chatForm) {
    chatForm.addEventListener("submit", (e) => {
        e.preventDefault();
        const input = document.getElementById("chat-input");
        if (input && input.value.trim()) {
            sendChatMessage(input.value);
        }
    });
}

// Quick action buttons
document.querySelectorAll(".chat-quick-btn").forEach(btn => {
    btn.addEventListener("click", () => {
        const msg = btn.getAttribute("data-msg");
        if (msg) sendChatMessage(msg);
    });
});

// Clear chat button
const chatClearBtn = document.getElementById("chat-clear-btn");
if (chatClearBtn) {
    chatClearBtn.addEventListener("click", () => {
        chatHistory = [];
        const container = document.getElementById("chat-messages");
        if (container) {
            container.innerHTML = `<div class="chat-msg agent">
                <div class="chat-avatar">🤖</div>
                <div class="chat-bubble">
                    <p>Czat wyczyszczony. Jak mogę pomóc?</p>
                </div>
            </div>`;
        }
    });
}

// Delegate click for execute/cancel buttons in chat, and suggestion clicks
document.addEventListener("click", (e) => {
    const execBtn = e.target.closest(".chat-exec-btn");
    if (execBtn) {
        const action = execBtn.getAttribute("data-action");
        const symbol = execBtn.getAttribute("data-symbol");
        if (action && symbol) {
            execBtn.disabled = true;
            execBtn.textContent = "Wysyłam...";
            executeChatCommand(action, symbol);
        }
        return;
    }
    const cancelBtn = e.target.closest(".chat-cancel-btn");
    if (cancelBtn) {
        const confirmBox = cancelBtn.closest(".chat-command-confirm");
        if (confirmBox) {
            confirmBox.innerHTML = "<em>Anulowano.</em>";
        }
        return;
    }
    // Clickable suggestion items
    const suggestionLi = e.target.closest(".chat-suggestions-list li");
    if (suggestionLi) {
        sendChatMessage(suggestionLi.textContent.trim());
    }
});

// ==================== CALENDAR ====================
let _calYear, _calMonth, _calData = null;

const PL_MONTHS = ["Styczeń","Luty","Marzec","Kwiecień","Maj","Czerwiec",
    "Lipiec","Sierpień","Wrzesień","Październik","Listopad","Grudzień"];
const PL_DAYS_SHORT = ["Pon","Wt","Śr","Czw","Pt","Sob","Nd"];

function initCalendar() {
    const now = new Date();
    _calYear = now.getFullYear();
    _calMonth = now.getMonth() + 1;
    document.getElementById("cal-prev").addEventListener("click", () => {
        _calMonth--;
        if (_calMonth < 1) { _calMonth = 12; _calYear--; }
        loadCalendar();
    });
    document.getElementById("cal-next").addEventListener("click", () => {
        _calMonth++;
        if (_calMonth > 12) { _calMonth = 1; _calYear++; }
        loadCalendar();
    });
    document.getElementById("cal-today").addEventListener("click", () => {
        const n = new Date();
        _calYear = n.getFullYear();
        _calMonth = n.getMonth() + 1;
        loadCalendar();
    });
    loadCalendar();
}

async function loadCalendar() {
    const titleEl = document.getElementById("cal-month-title");
    titleEl.textContent = PL_MONTHS[_calMonth - 1] + " " + _calYear;
    try {
        const res = await fetch(`/api/calendar?year=${_calYear}&month=${_calMonth}`);
        if (!res.ok) throw new Error("Błąd API");
        _calData = await res.json();
        renderCalendarGrid(_calData);
        renderCalMonthSummary(_calData.month_summary);
        renderCalYearSummary(_calData.year_summary);
        // Clear day/week until user clicks
        document.getElementById("cal-day-summary").innerHTML = '<p class="empty-state">Kliknij dzień w kalendarzu</p>';
        document.getElementById("cal-week-summary").innerHTML = '<p class="empty-state">—</p>';
    } catch (e) {
        console.error("Calendar load error:", e);
    }
}

function renderCalendarGrid(data) {
    const container = document.getElementById("cal-days");
    container.innerHTML = "";
    const today = new Date();
    const todayStr = today.getFullYear() + "-" + String(today.getMonth()+1).padStart(2,"0") + "-" + String(today.getDate()).padStart(2,"0");

    // API returns full grid with padding days (in_month=false)
    (data.days || []).forEach(dd => {
        const cell = document.createElement("div");
        const dayNum = parseInt(dd.date.split("-")[2], 10);
        cell.className = "cal-day";
        if (!dd.in_month) cell.classList.add("other-month");
        if (dd.date === todayStr) cell.classList.add("today");

        const hasData = (dd.buys && dd.buys.length) || (dd.sells && dd.sells.length) ||
                        (dd.live_buys && dd.live_buys.length) || (dd.live_sells && dd.live_sells.length);
        if (hasData) cell.classList.add("has-data");

        let content = `<span class="cal-day-num">${dayNum}</span>`;

        if (dd.buys && dd.buys.length) {
            dd.buys.slice(0, 2).forEach(b => {
                content += `<div class="cal-entry cal-buy">▲ ${b.symbol}</div>`;
            });
            if (dd.buys.length > 2) content += `<div class="cal-entry cal-buy-more">+${dd.buys.length - 2} kupno</div>`;
        }
        if (dd.sells && dd.sells.length) {
            dd.sells.slice(0, 2).forEach(s => {
                content += `<div class="cal-entry cal-sell">▼ ${s.symbol}</div>`;
            });
            if (dd.sells.length > 2) content += `<div class="cal-entry cal-sell-more">+${dd.sells.length - 2} sprzedaż</div>`;
        }
        if (dd.live_buys && dd.live_buys.length) {
            dd.live_buys.slice(0, 2).forEach(b => {
                content += `<div class="cal-entry cal-live-buy">⚡ ${b.symbol}</div>`;
            });
            if (dd.live_buys.length > 2) content += `<div class="cal-entry cal-buy-more">+${dd.live_buys.length - 2} live</div>`;
        }
        if (dd.live_sells && dd.live_sells.length) {
            dd.live_sells.slice(0, 2).forEach(s => {
                content += `<div class="cal-entry cal-live-sell">⚡ ${s.symbol}</div>`;
            });
            if (dd.live_sells.length > 2) content += `<div class="cal-entry cal-sell-more">+${dd.live_sells.length - 2} live</div>`;
        }

        cell.innerHTML = content;
        if (dd.in_month) {
            cell.addEventListener("click", () => onCalDayClick(dd));
        }
        container.appendChild(cell);
    });
}

function onCalDayClick(dd) {
    // Highlight selected day
    document.querySelectorAll("#cal-days .cal-day").forEach(c => c.classList.remove("selected"));
    const allDays = document.querySelectorAll("#cal-days .cal-day:not(.other-month)");
    const dayNum = parseInt(dd.date.split("-")[2], 10);
    allDays.forEach(c => {
        const num = parseInt(c.querySelector(".cal-day-num")?.textContent);
        if (num === dayNum) c.classList.add("selected");
    });

    const daySumEl = document.getElementById("cal-day-summary");
    const hasAny = dd.buys.length + dd.sells.length + dd.live_buys.length + dd.live_sells.length;
    if (!hasAny) {
        daySumEl.innerHTML = '<p class="empty-state">Brak aktywności w tym dniu</p>';
    } else {
        let h = '<div class="cal-summary-detail">';
        if (dd.buys.length) {
            const list = dd.buys.map(b => `${b.symbol} (${b.value} USD)`).join(", ");
            h += `<div class="cal-stat"><span class="cal-label">Kupno (paper):</span> <span class="cal-value positive">${list}</span></div>`;
        }
        if (dd.sells.length) {
            const list = dd.sells.map(s => `${s.symbol} (${s.profit >= 0 ? '+' : ''}${s.profit} USD)`).join(", ");
            h += `<div class="cal-stat"><span class="cal-label">Sprzedaż (paper):</span> <span class="cal-value negative">${list}</span></div>`;
        }
        if (dd.live_buys.length) {
            const list = dd.live_buys.map(b => `${b.symbol} ${b.time}`).join(", ");
            h += `<div class="cal-stat"><span class="cal-label">Kupno (LIVE):</span> <span class="cal-value positive">${list}</span></div>`;
        }
        if (dd.live_sells.length) {
            const list = dd.live_sells.map(s => `${s.symbol} ${s.time}`).join(", ");
            h += `<div class="cal-stat"><span class="cal-label">Sprzedaż (LIVE):</span> <span class="cal-value negative">${list}</span></div>`;
        }
        if (dd.live_errors) h += `<div class="cal-stat"><span class="cal-label">Błędy LIVE:</span> <span class="cal-value">${dd.live_errors}</span></div>`;
        if (dd.paper_profit !== 0) h += `<div class="cal-stat"><span class="cal-label">Paper profit:</span> <span class="cal-value ${dd.paper_profit >= 0 ? 'positive' : 'negative'}">${dd.paper_profit >= 0 ? '+' : ''}${dd.paper_profit.toFixed(2)} USD</span></div>`;
        if (dd.live_volume > 0) h += `<div class="cal-stat"><span class="cal-label">Wolumen LIVE:</span> <span class="cal-value">${dd.live_volume.toFixed(2)}</span></div>`;
        h += '</div>';
        daySumEl.innerHTML = h;
    }

    // Find week for this day
    const dt = new Date(dd.date);
    const weekStart = new Date(dt);
    weekStart.setDate(dt.getDate() - ((dt.getDay() + 6) % 7)); // Monday
    const weekKey = weekStart.toISOString().split("T")[0];
    renderCalWeekSummary(_calData.weeks ? _calData.weeks[weekKey] : null, weekKey);
}

function renderCalWeekSummary(week, label) {
    const el = document.getElementById("cal-week-summary");
    if (!week) { el.innerHTML = '<p class="empty-state">Brak danych dla tego tygodnia</p>'; return; }
    el.innerHTML = `<div class="cal-summary-detail">
        <h4>${label}</h4>
        <div class="cal-stat"><span class="cal-label">Kupno:</span> <span class="cal-value">${week.buys}</span></div>
        <div class="cal-stat"><span class="cal-label">Sprzedaż:</span> <span class="cal-value">${week.sells}</span></div>
        <div class="cal-stat"><span class="cal-label">Paper profit:</span> <span class="cal-value ${week.profit >= 0 ? 'positive' : 'negative'}">${week.profit >= 0 ? '+' : ''}${week.profit.toFixed(2)} USD</span></div>
        <div class="cal-stat"><span class="cal-label">Wolumen LIVE:</span> <span class="cal-value">${week.volume.toFixed(2)}</span></div>
        <div class="cal-stat"><span class="cal-label">Błędy:</span> <span class="cal-value">${week.errors}</span></div>
    </div>`;
}

function renderCalMonthSummary(ms) {
    const el = document.getElementById("cal-month-summary");
    if (!ms) { el.innerHTML = '<p class="empty-state">—</p>'; return; }
    el.innerHTML = `<div class="cal-summary-detail">
        <div class="cal-stat"><span class="cal-label">Aktywne dni:</span> <span class="cal-value">${ms.active_days}</span></div>
        <div class="cal-stat"><span class="cal-label">Kupno:</span> <span class="cal-value">${ms.buys}</span></div>
        <div class="cal-stat"><span class="cal-label">Sprzedaż:</span> <span class="cal-value">${ms.sells}</span></div>
        <div class="cal-stat"><span class="cal-label">Paper profit:</span> <span class="cal-value ${ms.profit >= 0 ? 'positive' : 'negative'}">${ms.profit >= 0 ? '+' : ''}${ms.profit.toFixed(2)} USD</span></div>
        <div class="cal-stat"><span class="cal-label">Wolumen LIVE:</span> <span class="cal-value">${ms.volume.toFixed(2)}</span></div>
        <div class="cal-stat"><span class="cal-label">Błędy:</span> <span class="cal-value">${ms.errors}</span></div>
    </div>`;
}

function renderCalYearSummary(ys) {
    const el = document.getElementById("cal-year-summary");
    if (!ys) { el.innerHTML = '<p class="empty-state">—</p>'; return; }
    el.innerHTML = `<div class="cal-summary-detail">
        <div class="cal-stat"><span class="cal-label">Rok:</span> <span class="cal-value">${_calYear}</span></div>
        <div class="cal-stat"><span class="cal-label">Transakcje LIVE:</span> <span class="cal-value">${ys.live_trades}</span></div>
        <div class="cal-stat"><span class="cal-label">Wolumen LIVE:</span> <span class="cal-value">${ys.live_volume.toFixed(2)}</span></div>
        <div class="cal-stat"><span class="cal-label">Paper zamknięte:</span> <span class="cal-value">${ys.paper_closed}</span></div>
        <div class="cal-stat"><span class="cal-label">Paper profit:</span> <span class="cal-value ${ys.paper_profit >= 0 ? 'positive' : 'negative'}">${ys.paper_profit >= 0 ? '+' : ''}${ys.paper_profit.toFixed(2)} USD</span></div>
    </div>`;
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