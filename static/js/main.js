// ===========================
// AuctionHub - Main JavaScript
// ===========================

// === Configuration ===
const CONFIG = {
    API_URL: 'http://localhost:8000',
    WS_URL: 'ws://localhost:8000'
};

// === Utility Functions ===
const Utils = {
    // Format money
    formatMoney(amount) {
        return new Intl.NumberFormat('en-US', {
            style: 'currency',
            currency: 'USD'
        }).format(amount);
    },

    // Format time remaining
    formatTimeRemaining(seconds) {
        if (seconds <= 0) return 'Завершён';
        
        const days = Math.floor(seconds / 86400);
        const hours = Math.floor((seconds % 86400) / 3600);
        const minutes = Math.floor((seconds % 3600) / 60);
        const secs = seconds % 60;
        
        if (days > 0) return `${days}д ${hours}ч`;
        if (hours > 0) return `${hours}ч ${minutes}м`;
        if (minutes > 0) return `${minutes}м ${secs}с`;
        return `${secs}с`;
    },

    // Format relative time (для уведомлений)
    formatRelativeTime(timestamp) {
        const date = new Date(timestamp);
        const now = new Date();
        const diff = Math.floor((now - date) / 1000);
        
        if (diff < 60) return 'Только что';
        if (diff < 3600) return `${Math.floor(diff / 60)} мин. назад`;
        if (diff < 86400) return `${Math.floor(diff / 3600)} ч. назад`;
        if (diff < 604800) return `${Math.floor(diff / 86400)} дн. назад`;
        
        return date.toLocaleDateString('ru-RU', { day: 'numeric', month: 'short' });
    },

    // Debounce function
    debounce(func, wait) {
        let timeout;
        return function executedFunction(...args) {
            const later = () => {
                clearTimeout(timeout);
                func(...args);
            };
            clearTimeout(timeout);
            timeout = setTimeout(later, wait);
        };
    },

    // Show error
    showError(elementId, message) {
        const errorEl = document.getElementById(elementId);
        if (errorEl) {
            errorEl.textContent = message;
            errorEl.classList.add('show');
            setTimeout(() => errorEl.classList.remove('show'), 5000);
        }
    },

    // Hide error
    hideError(elementId) {
        const errorEl = document.getElementById(elementId);
        if (errorEl) {
            errorEl.classList.remove('show');
        }
    }
};

// === Authentication ===
const Auth = {
    // Get token from localStorage
    getToken() {
        return localStorage.getItem('token');
    },

    // Set token
    setToken(token) {
        localStorage.setItem('token', token);
    },

    // Remove token
    removeToken() {
        localStorage.removeItem('token');
    },

    // Check if user is authenticated
    isAuthenticated() {
        return !!this.getToken();
    },

    // Get current user ID from token
    getUserId() {
        const token = this.getToken();
        if (!token) return null;
        
        try {
            const payload = JSON.parse(atob(token.split('.')[1]));
            return payload.user_id;
        } catch (e) {
            console.error('Error parsing token:', e);
            return null;
        }
    },

    // Get user data
    async getUser() {
        const token = this.getToken();
        if (!token) return null;

        try {
            const response = await fetch(`${CONFIG.API_URL}/api/me`, {
                headers: {
                    'Authorization': `Bearer ${token}`
                }
            });

            if (response.ok) {
                return await response.json();
            }
            return null;
        } catch (error) {
            console.error('Error fetching user:', error);
            return null;
        }
    },

    // Login
    async login(username, password) {
        try {
            const response = await fetch(`${CONFIG.API_URL}/api/login`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, password })
            });

            if (response.ok) {
                const data = await response.json();
                this.setToken(data.token);
                return { success: true, user: data.user };
            } else {
                const error = await response.json();
                return { success: false, error: error.detail };
            }
        } catch (error) {
            console.error('Login error:', error);
            return { success: false, error: 'Network error' };
        }
    },

    // Register
    async register(username, email, password) {
        try {
            const response = await fetch(`${CONFIG.API_URL}/api/register`, {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json'
                },
                body: JSON.stringify({ username, email, password })
            });

            if (response.ok) {
                const data = await response.json();
                this.setToken(data.token);
                return { success: true, user: data.user };
            } else {
                const error = await response.json();
                return { success: false, error: error.detail };
            }
        } catch (error) {
            console.error('Register error:', error);
            return { success: false, error: 'Network error' };
        }
    },

    // Logout
    logout() {
        this.removeToken();
        window.location.href = '/index.html';
    }
};

// === API Client ===
const API = {
    // Generic fetch with auth
    async fetch(endpoint, options = {}) {
        const token = Auth.getToken();
        const headers = {
            'Content-Type': 'application/json',
            ...options.headers
        };

        if (token) {
            headers['Authorization'] = `Bearer ${token}`;
        }

        try {
            const response = await fetch(`${CONFIG.API_URL}${endpoint}`, {
                ...options,
                headers
            });

            return response;
        } catch (error) {
            console.error('API Error:', error);
            throw error;
        }
    },

    // Get auctions
    async getAuctions(page = 1, status = 'active', pageSize = 12) {
        const response = await this.fetch(
            `/api/auctions?page=${page}&page_size=${pageSize}&status=${status}`
        );
        if (response.ok) {
            return await response.json();
        }
        throw new Error('Failed to fetch auctions');
    },

    // Get single auction
    async getAuction(id) {
        const response = await this.fetch(`/api/auctions/${id}`);
        if (response.ok) {
            return await response.json();
        }
        throw new Error('Failed to fetch auction');
    },

    // Create auction
    async createAuction(data) {
        const response = await this.fetch('/api/auctions', {
            method: 'POST',
            body: JSON.stringify(data)
        });
        
        if (response.ok) {
            return await response.json();
        }
        
        const error = await response.json();
        throw new Error(error.detail || 'Failed to create auction');
    },

    // Place bid
    async placeBid(auctionId, amount) {
        const response = await this.fetch('/api/bids', {
            method: 'POST',
            body: JSON.stringify({
                auction_id: auctionId,
                amount: amount
            })
        });
        
        if (response.ok) {
            return await response.json();
        }
        
        const error = await response.json();
        throw new Error(error.detail || 'Failed to place bid');
    },

    // Get auction bids
    async getAuctionBids(auctionId, page = 1, pageSize = 10) {
        const response = await this.fetch(
            `/api/auctions/${auctionId}/bids?page=${page}&page_size=${pageSize}`
        );
        if (response.ok) {
            return await response.json();
        }
        throw new Error('Failed to fetch bids');
    },

    // Upload image
    async uploadImage(file) {
        const token = Auth.getToken();
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${CONFIG.API_URL}/api/upload-image`, {
            method: 'POST',
            headers: {
                'Authorization': `Bearer ${token}`
            },
            body: formData
        });

        if (response.ok) {
            return await response.json();
        }
        
        const error = await response.json();
        throw new Error(error.detail || 'Failed to upload image');
    },

    // Get participation
    async getMyParticipation() {
        const response = await this.fetch('/api/my/participation');
        if (response.ok) {
            return await response.json();
        }
        throw new Error('Failed to fetch participation');
    }
};

// === UI Components ===
const UI = {
    // Show/hide loading
    showLoading(elementId) {
        const el = document.getElementById(elementId);
        if (el) {
            el.innerHTML = '<div class="loading"></div>';
        }
    },

    hideLoading(elementId) {
        const el = document.getElementById(elementId);
        if (el) {
            el.innerHTML = '';
        }
    },

    // Show modal
    showModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.add('show');
            document.body.style.overflow = 'hidden';
        }
    },

    // Hide modal
    hideModal(modalId) {
        const modal = document.getElementById(modalId);
        if (modal) {
            modal.classList.remove('show');
            document.body.style.overflow = '';
        }
    },

    // Toggle sidebar (mobile)
    toggleSidebar() {
        const sidebar = document.getElementById('sidebar');
        const overlay = document.getElementById('overlay');
        
        if (sidebar && overlay) {
            sidebar.classList.toggle('show');
            overlay.classList.toggle('show');
        }
    },

    // Update user info in sidebar
    async updateUserInfo() {
        const user = await Auth.getUser();
        if (!user) {
            // Redirect to login or show guest UI
            this.showGuestUI();
            return;
        }

        // Update avatar
        const avatarEl = document.querySelector('.avatar');
        if (avatarEl) {
            avatarEl.textContent = user.username.charAt(0).toUpperCase();
        }

        // Update username
        const usernameEls = document.querySelectorAll('.user-name, [id="userName"]');
        usernameEls.forEach(el => {
            el.textContent = user.username;
        });

        // Update balance
        const balanceEls = document.querySelectorAll('.user-balance, [id="userBalance"]');
        balanceEls.forEach(el => {
            el.textContent = Utils.formatMoney(user.balance);
        });
    },

    // Show guest UI
    showGuestUI() {
        const createBtn = document.getElementById('createBtn');
        if (createBtn) {
            createBtn.style.display = 'none';
        }

        // Hide user card
        const userCard = document.querySelector('.user-card');
        if (userCard) {
            userCard.style.display = 'none';
        }
    }
};

// === Page Initialization ===
document.addEventListener('DOMContentLoaded', async () => {
    // Update user info if authenticated
    if (Auth.isAuthenticated()) {
        await UI.updateUserInfo();
    } else {
        UI.showGuestUI();
    }

    // Setup sidebar toggle
    const menuBtns = document.querySelectorAll('.menu-btn');
    menuBtns.forEach(btn => {
        btn.addEventListener('click', () => UI.toggleSidebar());
    });

    // Setup overlay click
    const overlay = document.getElementById('overlay');
    if (overlay) {
        overlay.addEventListener('click', () => UI.toggleSidebar());
    }

    // Setup logout button
    const logoutBtn = document.getElementById('logoutBtn');
    if (logoutBtn) {
        logoutBtn.addEventListener('click', () => Auth.logout());
    }

    // Close modals on escape
    document.addEventListener('keydown', (e) => {
        if (e.key === 'Escape') {
            document.querySelectorAll('.modal.show').forEach(modal => {
                modal.classList.remove('show');
            });
            document.body.style.overflow = '';
        }
    });
});

// === Export for use in other files ===
window.AuctionHub = {
    CONFIG,
    Utils,
    Auth,
    API,
    UI
};
