/**
 * API Client — Centralized HTTP communication with the backend.
 */
const API = {
    BASE_URL: '/api',

    async request(endpoint, options = {}) {
        const url = `${this.BASE_URL}${endpoint}`;
        const config = {
            headers: { 'Content-Type': 'application/json', ...options.headers },
            ...options,
        };
        if (config.body && typeof config.body === 'object') {
            config.body = JSON.stringify(config.body);
        }

        const response = await fetch(url, config);

        if (response.status === 204) return null;

        const data = await response.json().catch(() => null);

        if (!response.ok) {
            let message = `Σφάλμα ${response.status}`;
            if (data && data.detail) {
                if (Array.isArray(data.detail)) {
                    message = data.detail.map(err => `${err.loc.slice(-1)}: ${err.msg}`).join(', ');
                } else {
                    message = data.detail;
                }
            }
            throw new Error(message);
        }

        return data;
    },

    get(endpoint) { return this.request(endpoint); },
    post(endpoint, body) { return this.request(endpoint, { method: 'POST', body }); },
    put(endpoint, body) { return this.request(endpoint, { method: 'PUT', body }); },
    delete(endpoint) { return this.request(endpoint, { method: 'DELETE' }); },

    // ─── Entity-specific helpers ───────────────────────
    teachers: {
        list: () => API.get('/teachers/'),
        get: (id) => API.get(`/teachers/${id}`),
        create: (data) => API.post('/teachers/', data),
        update: (id, data) => API.put(`/teachers/${id}`, data),
        delete: (id) => API.delete(`/teachers/${id}`),
        getAvailability: (id) => API.get(`/teachers/${id}/availability`),
        updateAvailability: (id, data) => API.put(`/teachers/${id}/availability`, data),
    },
    subjects: {
        list: () => API.get('/subjects/'),
        get: (id) => API.get(`/subjects/${id}`),
        create: (data) => API.post('/subjects/', data),
        update: (id, data) => API.put(`/subjects/${id}`, data),
        delete: (id) => API.delete(`/subjects/${id}`),
    },
    students: {
        list: () => API.get('/students/'),
        get: (id) => API.get(`/students/${id}`),
        create: (data) => API.post('/students/', data),
        update: (id, data) => API.put(`/students/${id}`, data),
        delete: (id) => API.delete(`/students/${id}`),
        getAvailability: (id) => API.get(`/students/${id}/availability`),
        updateAvailability: (id, data) => API.put(`/students/${id}/availability`, data),
    },
    classrooms: {
        list: () => API.get('/classrooms/'),
        get: (id) => API.get(`/classrooms/${id}`),
        create: (data) => API.post('/classrooms/', data),
        update: (id, data) => API.put(`/classrooms/${id}`, data),
        delete: (id) => API.delete(`/classrooms/${id}`),
    },
    classes: {
        list: () => API.get('/classes/'),
        get: (id) => API.get(`/classes/${id}`),
        create: (data) => API.post('/classes/', data),
        update: (id, data) => API.put(`/classes/${id}`, data),
        delete: (id) => API.delete(`/classes/${id}`),
    },
    periods: {
        list: () => API.get('/periods/'),
        get: (id) => API.get(`/periods/${id}`),
        create: (data) => API.post('/periods/', data),
        update: (id, data) => API.put(`/periods/${id}`, data),
        delete: (id) => API.delete(`/periods/${id}`),
        seedDefaults: () => API.post('/periods/seed-defaults', {}),
    },
    lessonsBulkImport: {
        preview: (csv) => API.post('/lessons/bulk-import/preview', { csv }),
        commit: (csv) => API.post('/lessons/bulk-import/commit', { csv }),
    },
    lessonsDistributionSuggestions: (ppw) =>
        API.get(`/lessons/distribution-suggestions?ppw=${ppw}`),
    lessons: {
        list: () => API.get('/lessons/'),
        get: (id) => API.get(`/lessons/${id}`),
        create: (data) => API.post('/lessons/', data),
        update: (id, data) => API.put(`/lessons/${id}`, data),
        delete: (id) => API.delete(`/lessons/${id}`),
    },
    constraints: {
        list: () => API.get('/constraints/'),
        get: (id) => API.get(`/constraints/${id}`),
        create: (data) => API.post('/constraints/', data),
        update: (id, data) => API.put(`/constraints/${id}`, data),
        delete: (id) => API.delete(`/constraints/${id}`),
        seedDefaults: () => API.post('/constraints/seed-defaults', {}),
    },
    solver: {
        generate: (data) => API.post('/solver/generate', data),
        regenerateWithLocks: (sourceId, data) => API.post(`/solver/regenerate/${sourceId}`, data),
        listSolutions: () => API.get('/solver/solutions'),
        getSolution: (id) => API.get(`/solver/solutions/${id}`),
        deleteSolution: (id) => API.delete(`/solver/solutions/${id}`),
        updateSlot: (solutionId, slotId, data) => API.put(`/solver/solutions/${solutionId}/slots/${slotId}`, data),
        compare: (ids) => API.get(`/solver/compare?ids=${ids.join(',')}`),
    },
    settings: {
        get: () => API.get('/settings/'),
        update: (data) => API.put('/settings/', data),
        listTemplates: () => API.get('/settings/templates'),
        previewTemplate: (key) => API.post(`/settings/templates/${key}/preview`, {}),
        applyTemplate: (key) => API.post(`/settings/templates/${key}/apply`, {}),
    },
};
