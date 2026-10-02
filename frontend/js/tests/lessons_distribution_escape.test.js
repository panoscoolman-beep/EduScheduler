/**
 * Μαθήματα-Κάρτες: το «distribution» (Blocks) ως κείμενο στη λίστα και ακέραιο
 * (και με ") στη φόρμα επεξεργασίας.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const { start, go, sleep, waitFor, baseRoutes } = require('./app_harness.js');

test('distribution: escaped στη λίστα, ακέραιο στο πεδίο της φόρμας', async () => {
    const lesson = { id: 5, subject_id: 1, subject_name: 'Φυσική', teacher_id: 21, teacher_name: 'Νικολάου',
                     class_id: 11, class_name: 'Β2', classroom_id: null, classroom_name: null,
                     periods_per_week: 4, distribution: '2,"<b>2</b>' };
    const routes = baseRoutes({
        'GET /api/lessons/': () => [lesson],
        'GET /api/subjects/': () => [{ id: 1, name: 'Φυσική', short_name: 'ΦΥΣ' }],
        'GET /api/teachers/': () => [{ id: 21, name: 'Νικολάου', short_name: 'ΝΙΚ' }],
        'GET /api/classes/': () => [{ id: 11, name: 'Β2', short_name: 'Β2', student_ids: [] }],
        'GET /api/lessons/distribution-suggestions': () => ({ options: [] }),
    });
    const app = await start(routes);
    try {
        await go(app, 'lessons', 'tr[data-id="5"]');
        const row = app.doc.querySelector('tr[data-id="5"]');
        assert.equal(row.querySelector('b'), null);
        assert.match(row.textContent, /2,"<b>2<\/b>/);
        // Χωρίς distribution: το «όλα 1ωρα» όπως πριν
        lesson.distribution = null;
        await go(app, 'lessons', 'tr[data-id="5"]');
        assert.match(app.doc.querySelector('tr[data-id="5"]').innerHTML, /<span class="text-muted">όλα 1ωρα<\/span>/);

        lesson.distribution = '2,"<b>2</b>';
        await go(app, 'lessons', '.dt-edit[data-id="5"]');
        app.doc.querySelector('.dt-edit[data-id="5"]').click();
        await waitFor(app.w, () => app.doc.getElementById('f-dist'));
        assert.equal(app.doc.getElementById('f-dist').value, '2,"<b>2</b>');
        await sleep(app.w, 30);
    } finally { app.close(); }
});
