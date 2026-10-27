/**
 * Toast Notification Component
 *
 * action (προαιρετικό): { label, onClick } → κουμπί μέσα στο μήνυμα,
 * π.χ. «↩ Αναίρεση» μετά από μετακίνηση.
 */
const Toast = {
    show(message, type = 'info', duration = 4000, action = null) {
        const container = document.getElementById('toast-container');
        const icons = { success: '✅', error: '❌', warning: '⚠️', info: 'ℹ️' };

        const toast = document.createElement('div');
        toast.className = `toast ${type}`;
        toast.setAttribute('role', type === 'error' ? 'alert' : 'status');
        toast.innerHTML = `
            <span class="toast-icon" aria-hidden="true">${icons[type] || icons.info}</span>
            <span class="toast-message">${message}</span>
            <button class="toast-close" aria-label="Κλείσιμο">&times;</button>
        `;

        const dismiss = () => {
            toast.style.opacity = '0';
            toast.style.transform = 'translateX(100%)';
            setTimeout(() => toast.remove(), 300);
        };

        if (action && action.label && typeof action.onClick === 'function') {
            const btn = document.createElement('button');
            btn.type = 'button';
            btn.className = 'btn btn-secondary btn-sm toast-action';
            btn.textContent = action.label;
            btn.addEventListener('click', () => {
                dismiss();
                action.onClick();
            });
            toast.insertBefore(btn, toast.querySelector('.toast-close'));
        }

        toast.querySelector('.toast-close').addEventListener('click', dismiss);

        container.appendChild(toast);

        setTimeout(() => {
            if (toast.parentNode) dismiss();
        }, duration);
    },

    success(message) { this.show(message, 'success'); },
    error(message, duration = 6000) { this.show(message, 'error', duration); },
    warning(message) { this.show(message, 'warning'); },
    info(message) { this.show(message, 'info'); },
};
