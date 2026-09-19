import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { runInNewContext } from 'node:vm';
import { describe, expect, it, vi } from 'vitest';

const listeners: Record<string, (event: unknown) => void> = {};
runInNewContext(readFileSync(resolve(process.cwd(), 'public/sw.js'), 'utf8'), {
  self: { location: { origin: 'https://ely.test' }, addEventListener: (name: string, handler: (event: unknown) => void) => { listeners[name] = handler; } },
  URL,
});

describe('fresh admin and authenticated state', () => {
  it.each([
    ['/admin/learning/candidates?status=candidate', false],
    ['/api/conversations', false],
    ['/some-authenticated-data', true],
  ])('never serves a cached response for %s', (path, authenticated) => {
    const respondWith = vi.fn();
    listeners.fetch({ request: { method: 'GET', url: `https://ely.test${path}`, mode: 'cors', headers: { has: () => authenticated } }, respondWith });
    expect(respondWith).not.toHaveBeenCalled();
  });
});
