/**
 * 🔄 Ειδοποίηση νέας έκδοσης: ανίχνευση ?v=N, μπάρα, καθαρό URL.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
const V = require('../services/version_check.js');

const page = (v) => `<!DOCTYPE html><body><script src="js/api.js?v=${v}"></script><script src="js/app.js?v=${v}"></script></body>`;

test('parseVersion/loadedVersion/isStale', () => {
    assert.equal(V.parseVersion(page(74)), 74);
    assert.equal(V.parseVersion('<html></html>'), null);
    const dom = new JSDOM(page(73));
    assert.equal(V.loadedVersion(dom.window.document), 73);
    assert.equal(V.isStale(73, 74), true);
    assert.equal(V.isStale(74, 74), false);
    assert.equal(V.isStale(null, 74), false);     // χωρίς πληροφορία → σιωπή
    assert.equal(V.isStale(73, null), false);
});

test('το πραγματικό index.html: ένα app.js με την ίδια έκδοση με όλα τα άλλα', () => {
    const html = fs.readFileSync(path.join(__dirname, '..', '..', 'index.html'), 'utf8');
    const all = [...html.matchAll(/\?v=(\d+)/g)].map(m => Number(m[1]));
    assert.equal(new Set(all).size, 1);
    assert.equal(V.parseVersion(html), all[0]);
});

test('reloadUrl κρατά hash/params, cleanUrl αφαιρεί μόνο το _v', () => {
    assert.equal(V.reloadUrl({ pathname: '/', search: '?a=1', hash: '#today' }, 5), '/?a=1&_v=5#today');
    const dom = new JSDOM('<!DOCTYPE html><body></body>', { url: 'http://x/?a=1&_v=5#today' });
    V.cleanUrl(dom.window);
    assert.equal(dom.window.location.href, 'http://x/?a=1#today');
});

test('check: νέα έκδοση → μία μπάρα· ίδια έκδοση ή σφάλμα δικτύου → τίποτα', async () => {
    const make = (served, fail = false) => {
        const dom = new JSDOM(page(73), { url: 'http://x/' });
        dom.window.fetch = async () => { if (fail) throw new Error('offline'); return { ok: true, text: async () => page(served) }; };
        return dom.window;
    };
    V._shown = false;
    const same = make(73);
    await V.check(same);
    assert.equal(same.document.getElementById('version-banner'), null);
    const offline = make(74, true);
    await V.check(offline);
    assert.equal(offline.document.getElementById('version-banner'), null);
    const stale = make(74);
    await V.check(stale);
    await V.check(stale);
    assert.equal(stale.document.querySelectorAll('#version-banner').length, 1);
    stale.document.getElementById('version-later').click();
    assert.equal(stale.document.getElementById('version-banner'), null);
    V._shown = false;
});
