/**
 * Tests for services/timetable_interactions.js (pollSolve), using Node's
 * built-in mock timers so the 3s poll interval doesn't make the test slow.
 * Only setTimeout is mocked; Date stays real, so the deadline (≥60s out) never
 * trips during these fast tests.
 */
const { test } = require('node:test');
const assert = require('node:assert/strict');

const TimetableInteractions = require('../services/timetable_interactions.js');

// Flush pending microtasks (lets pollSolve's awaited continuation run + register
// its next setTimeout) between synchronous timer ticks.
const flush = () => new Promise((r) => setImmediate(r));

test('pollSolve: returns the status once the run leaves generating', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    global.API = { solver: { status: async () => ({ status: 'optimal', solution_id: 1 }) } };
    const p = TimetableInteractions.pollSolve(1, 120);
    t.mock.timers.tick(3000);   // fire the first poll interval
    assert.deepEqual(await p, { status: 'optimal', solution_id: 1 });
});

test('pollSolve: keeps polling past a transient status error', async (t) => {
    t.mock.timers.enable({ apis: ['setTimeout'] });
    let n = 0;
    global.API = {
        solver: {
            status: async () => {
                n += 1;
                if (n === 1) throw new Error('transient');
                return { status: 'feasible' };
            },
        },
    };
    const p = TimetableInteractions.pollSolve(1, 120);
    t.mock.timers.tick(3000);   // poll #1 → throws, swallowed
    await flush();              // let the catch run + the next setTimeout register
    t.mock.timers.tick(3000);   // poll #2 → feasible, returns
    assert.deepEqual(await p, { status: 'feasible' });
    assert.equal(n, 2);
});
