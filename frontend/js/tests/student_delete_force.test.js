/**
 * Μαθητές: ο server απαντά 409 (requires_force) όταν ο μαθητής έχει τμήματα/
 * εξαιρέσεις/κωλύματα· η επιβεβαίωση του DataTable ξαναστέλνει
 * `api.delete(id, true)` — άρα το API.students.delete πρέπει να στέλνει
 * ?force=true (πριν το αγνοούσε και ο μαθητής δεν σβηνόταν ποτέ από το UI).
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, baseRoutes } = require('./app_harness.js');

test('API.students.delete: force μόνο όταν ζητηθεί', async () => {
    const routes = baseRoutes({
        'DELETE /api/students/*': ({ search }) => (/force=true/.test(search)
            ? { __status: 204 }
            : { __status: 409, data: { detail: { code: 'student_in_use', requires_force: true,
                message: 'Ο μαθητής «Π Νίκος» έχει 1 τμήματα, 0 εξαιρέσεις καρτών, 2 κωλύματα.' } } }),
    });
    const app = await start(routes);
    try {
        await assert.rejects(() => app.G.API.students.delete(7), (err) => err.status === 409 && err.detail.requires_force);
        assert.equal(await app.G.API.students.delete(7, true), null);
        const dels = app.calls.filter(c => c.method === 'DELETE').map(c => c.path + c.search);
        assert.deepEqual(dels, ['/api/students/7', '/api/students/7?force=true']);
    } finally { app.close(); }
});
