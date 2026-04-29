// ===========================
// Notifications System
// ===========================

const NotificationSystem = {
    notifications: [],
    unreadCount: 0,
    ws: null,
    reconnectAttempts: 0,
    maxReconnectAttempts: 5,

    // Initialize
    async init() {
        const userId = window.AuctionHub.Auth.getUserId();
        if (!userId) return;

        // Load notifications
        await this.loadNotifications();

        // Connect WebSocket
        this.connectWebSocket(userId);

        // Setup UI
        this.setupUI();
    },

    // Setup UI elements
    setupUI() {
        // Bell click handler
        const bell = document.getElementById('notificationBell');
        if (bell) {
            bell.addEventListener('click', (e) => {
                e.stopPropagation();
                this.toggleDropdown();
            });
        }

        // Close dropdown when clicking outside
        document.addEventListener('click', (e) => {
            const wrapper = document.querySelector('.notifications-wrapper');
            const dropdown = document.getElementById('notificationDropdown');
            
            if (wrapper && !wrapper.contains(e.target)) {
                if (dropdown && dropdown.classList.contains('show')) {
                    dropdown.classList.remove('show');
                }
            }
        });

        // Mark all as read
        const markAllBtn = document.querySelector('.mark-all-read');
        if (markAllBtn) {
            markAllBtn.addEventListener('click', () => this.markAllAsRead());
        }
    },

    // Connect WebSocket
    connectWebSocket(userId) {
        const token = window.AuctionHub.Auth.getToken();
        if (!token) return;
        const wsUrl = `${window.AuctionHub.CONFIG.WS_URL}/ws/notifications/${userId}?token=${encodeURIComponent(token)}`;
        
        try {
            this.ws = new WebSocket(wsUrl);
            
            this.ws.onopen = () => {
                console.log('вњ… WebSocket notifications connected');
                this.reconnectAttempts = 0;
                
                // Send ping every 25 seconds
                this.pingInterval = setInterval(() => {
                    if (this.ws.readyState === WebSocket.OPEN) {
                        this.ws.send('ping');
                    }
                }, 25000);
            };
            
            this.ws.onmessage = (event) => {
                try {
                    const data = JSON.parse(event.data);
                    
                    if (data.type === 'notification') {
                        this.handleNewNotification(data.notification);
                    }
                } catch (e) {
                    console.error('Error parsing WebSocket message:', e);
                }
            };
            
            this.ws.onerror = (error) => {
                console.error('WebSocket error:', error);
            };
            
            this.ws.onclose = () => {
                console.log('WebSocket closed');
                if (this.pingInterval) {
                    clearInterval(this.pingInterval);
                }
                
                // Reconnect with exponential backoff
                if (this.reconnectAttempts < this.maxReconnectAttempts) {
                    const delay = Math.min(1000 * Math.pow(2, this.reconnectAttempts), 30000);
                    console.log(`Reconnecting in ${delay}ms...`);
                    
                    setTimeout(() => {
                        this.reconnectAttempts++;
                        this.connectWebSocket(userId);
                    }, delay);
                }
            };
        } catch (error) {
            console.error('Error connecting WebSocket:', error);
        }
    },

    // Handle new notification
    handleNewNotification(notification) {
        // Add to list
        this.notifications.unshift(notification);
        
        // Update badge
        if (!notification.is_read) {
            this.unreadCount++;
            this.updateBadge();
        }
        
        // Render list
        this.renderNotifications();
        
        // Show toast
        this.showToast(notification);
        
        // Browser notification (if permitted)
        this.showBrowserNotification(notification);
    },

    // Load notifications from API
    async loadNotifications() {
        try {
            const response = await window.AuctionHub.API.fetch('/api/notifications?limit=20');
            
            if (response.ok) {
                this.notifications = await response.json();
                this.unreadCount = this.notifications.filter(n => !n.is_read).length;
                this.updateBadge();
                this.renderNotifications();
            }
        } catch (error) {
            console.error('Error loading notifications:', error);
        }
    },

    // Toggle dropdown
    toggleDropdown() {
        const dropdown = document.getElementById('notificationDropdown');
        if (dropdown) {
            const isShowing = dropdown.classList.contains('show');
            dropdown.classList.toggle('show');
            
            if (!isShowing) {
                // Refresh when opening
                this.loadNotifications();
            }
        }
    },
    // Render notifications list
    renderNotifications() {
        const list = document.getElementById('notificationList');
        if (!list) return;
        
        if (this.notifications.length === 0) {
            list.innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">📭</div>
                    <div>Нет уведомлений</div>
                </div>
            `;
            return;
        }
        
        list.innerHTML = this.notifications.map(n => {
            const safeTitle = this.escapeHtml(n.title);
            const safeMessage = this.escapeHtml(n.message);
            const safeAuctionTitle = this.escapeHtml(n.auction_title);
            const notificationId = Number.isFinite(Number(n.id)) ? Number(n.id) : 0;
            const auctionIdValue = Number.isFinite(Number(n.auction_id)) ? Number(n.auction_id) : 'null';
            return `
            <div class="notification-item ${!n.is_read ? 'unread' : ''}" 
                 onclick="NotificationSystem.handleNotificationClick(${notificationId}, ${auctionIdValue})">
                <div style="display: flex; align-items: flex-start; gap: 12px;">
                    <span class="notification-icon">${this.getIcon(n.type)}</span>
                    <div class="notification-content">
                        <div class="notification-text">
                            <strong>${safeTitle}</strong><br>
                            ${safeMessage}
                            ${n.auction_title ? `<br><small style="color: var(--accent-primary);">${safeAuctionTitle}</small>` : ''}
                        </div>
                        <div class="notification-meta">
                            <span class="notification-time">${window.AuctionHub.Utils.formatRelativeTime(n.created_at)}</span>
                            <div class="notification-actions">
                                ${!n.is_read ? `<span class="notification-action" onclick="event.stopPropagation(); NotificationSystem.markAsRead(${notificationId})">Прочитать</span>` : ''}
                                <span class="notification-action" onclick="event.stopPropagation(); NotificationSystem.deleteNotification(${notificationId})">Удалить</span>
                            </div>
                        </div>
                    </div>
                </div>
            </div>
        `;
        }).join('');
    },
    // Update badge count
    updateBadge() {
        const badge = document.getElementById('notificationBadge');
        if (badge) {
            if (this.unreadCount > 0) {
                badge.textContent = this.unreadCount > 99 ? '99+' : this.unreadCount;
                badge.style.display = 'block';
                badge.classList.add('pulse');
            } else {
                badge.style.display = 'none';
                badge.classList.remove('pulse');
            }
        }
    },

    // Get icon for notification type
    getIcon(type) {
        const icons = {
            'bid_outbid': 'рџ”',
            'bid_placed': 'рџЋЇ',
            'auction_ending': 'вЏ°',
            'auction_won': 'рџЋ‰',
            'auction_lost': 'рџў',
            'auction_sold': 'рџ’°'
        };
        return icons[type] || 'рџ””';
    },

    // Get toast type
    getToastType(notificationType) {
        const types = {
            'bid_outbid': 'warning',
            'auction_won': 'success',
            'auction_lost': 'error',
            'auction_ending': 'info',
            'bid_placed': 'info',
            'auction_sold': 'success'
        };
        return types[notificationType] || 'info';
    },

    // Escape user-provided text before injecting it into HTML templates.
    escapeHtml(value) {
        return String(value ?? '')
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;')
            .replace(/"/g, '&quot;')
            .replace(/'/g, '&#39;');
    },

    // Show toast notification
    showToast(notification) {
        const container = document.getElementById('toastContainer');
        if (!container) {
            // Create container if it doesn't exist
            const newContainer = document.createElement('div');
            newContainer.id = 'toastContainer';
            newContainer.className = 'toast-container';
            document.body.appendChild(newContainer);
        }
        
        const toast = document.createElement('div');
        toast.className = `toast ${this.getToastType(notification.type)}`;
        const safeTitle = this.escapeHtml(notification.title);
        const safeMessage = this.escapeHtml(notification.message);
        
        toast.innerHTML = `
            <div class="toast-icon">${this.getIcon(notification.type)}</div>
            <div class="toast-content">
                <div class="toast-title">${safeTitle}</div>
                <div class="toast-message">${safeMessage}</div>
            </div>
            <div class="toast-close" onclick="this.parentElement.remove()">вњ•</div>
        `;
        
        const toastContainer = document.getElementById('toastContainer');
        toastContainer.appendChild(toast);
        
        // Auto remove after 5 seconds
        setTimeout(() => {
            toast.remove();
        }, 5000);
    },

    // Show browser notification
    showBrowserNotification(notification) {
        if (!('Notification' in window)) return;
        
        if (Notification.permission === 'granted') {
            new Notification(notification.title, {
                body: notification.message,
                icon: '/static/images/logo.png',
                badge: '/static/images/badge.png',
                tag: `auction-${notification.id}`,
                requireInteraction: false
            });
        } else if (Notification.permission !== 'denied') {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    this.showBrowserNotification(notification);
                }
            });
        }
    },

    // Handle notification click
    async handleNotificationClick(notificationId, auctionId) {
        await this.markAsRead(notificationId);
        
        if (auctionId) {
            window.location.href = `/auction.html?id=${auctionId}`;
        }
    },

    // Mark as read
    async markAsRead(notificationId) {
        try {
            const response = await window.AuctionHub.API.fetch(
                `/api/notifications/${notificationId}/read`,
                { method: 'POST' }
            );
            
            if (response.ok) {
                const notification = this.notifications.find(n => n.id === notificationId);
                if (notification && !notification.is_read) {
                    notification.is_read = true;
                    this.unreadCount = Math.max(0, this.unreadCount - 1);
                    this.updateBadge();
                    this.renderNotifications();
                }
            }
        } catch (error) {
            console.error('Error marking notification as read:', error);
        }
    },

    // Mark all as read
    async markAllAsRead() {
        try {
            const response = await window.AuctionHub.API.fetch(
                '/api/notifications/mark-all-read',
                { method: 'POST' }
            );
            
            if (response.ok) {
                this.notifications.forEach(n => n.is_read = true);
                this.unreadCount = 0;
                this.updateBadge();
                this.renderNotifications();
            }
        } catch (error) {
            console.error('Error marking all as read:', error);
        }
    },

    // Delete notification
    async deleteNotification(notificationId) {
        try {
            const response = await window.AuctionHub.API.fetch(
                `/api/notifications/${notificationId}`,
                { method: 'DELETE' }
            );
            
            if (response.ok) {
                const notification = this.notifications.find(n => n.id === notificationId);
                if (notification && !notification.is_read) {
                    this.unreadCount = Math.max(0, this.unreadCount - 1);
                }
                
                this.notifications = this.notifications.filter(n => n.id !== notificationId);
                this.updateBadge();
                this.renderNotifications();
            }
        } catch (error) {
            console.error('Error deleting notification:', error);
        }
    },

    // Get notification settings
    async getSettings() {
        try {
            const user = await window.AuctionHub.Auth.getUser();
            if (!user) return null;
            
            return {
                email_notifications: user.email_notifications,
                notify_outbid: user.notify_outbid,
                notify_winning: user.notify_winning,
                notify_ending: user.notify_ending,
                notify_sold: user.notify_sold
            };
        } catch (error) {
            console.error('Error getting settings:', error);
            return null;
        }
    },

    // Update notification settings
    async updateSettings(settings) {
        try {
            const response = await window.AuctionHub.API.fetch(
                '/api/notification-settings',
                {
                    method: 'PUT',
                    body: JSON.stringify(settings)
                }
            );
            
            if (response.ok) {
                this.showToast({
                    type: 'auction_won',
                    title: 'РќР°СЃС‚СЂРѕР№РєРё СЃРѕС…СЂР°РЅРµРЅС‹',
                    message: 'Р’Р°С€Рё РїСЂРµРґРїРѕС‡С‚РµРЅРёСЏ РѕР±РЅРѕРІР»РµРЅС‹'
                });
                return true;
            }
            return false;
        } catch (error) {
            console.error('Error updating settings:', error);
            return false;
        }
    }
};

// Initialize when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    if (window.AuctionHub && window.AuctionHub.Auth.isAuthenticated()) {
        NotificationSystem.init();
    }
});

// Export
window.NotificationSystem = NotificationSystem;

