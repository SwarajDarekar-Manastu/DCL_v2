import { describe, expect, it, vi } from 'vitest';
import { buildConfig } from '../src/lib/config';
import { session, startSession } from '../src/lib/auth/session.svelte';
import type { AuthClient } from '../src/lib/auth/msal';

const config = buildConfig(
	{ VITE_ENTRA_TENANT_ID: 't', VITE_ENTRA_CLIENT_ID: 'c', VITE_ENTRA_API_SCOPE: 's', VITE_API_BASE_URL: 'http://api' },
	'http://console'
);

function fakeAuth(account: string | null): AuthClient {
	return { init: async () => account, login: vi.fn(), logout: vi.fn(), getToken: async () => 'tok' };
}

describe('startSession', () => {
	it('is signed out when MSAL has no account', async () => {
		await startSession(config, fakeAuth(null));
		expect(session.status).toBe('signed_out');
	});

	it('takes roles from the server, not from the token', async () => {
		const user = { oid: 'o', name: 'Asha', email: 'a@x', roles: ['viewer', 'reviewer'] };
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(user))));
		await startSession(config, fakeAuth('Asha'));
		expect(session.status).toBe('signed_in');
		expect(session.user).toEqual(user);
		vi.unstubAllGlobals();
	});

	it('shows the server refusal on error', async () => {
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'group overage: configure' }), { status: 403 })));
		await startSession(config, fakeAuth('Asha'));
		expect(session.status).toBe('error');
		expect(session.error).toBe('group overage: configure');
		vi.unstubAllGlobals();
	});
});

describe('dev sign-in', () => {
	it('sends the dev token and takes the user from the server', async () => {
		const dev = buildConfig({ VITE_AUTH_MODE: 'dev', DEV: true, VITE_DEV_TOKEN: 'd'.repeat(40), VITE_API_BASE_URL: 'http://api' }, 'http://console');
		const user = { oid: 'dev-sign-in', name: 'Dev sign-in', email: 'dev@localhost', roles: ['viewer', 'reviewer'] };
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(user)));
		vi.stubGlobal('fetch', fetchMock);
		await startSession(dev);
		expect(session.status).toBe('signed_in');
		expect(session.user).toEqual(user);
		const [, init] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(init.headers).toMatchObject({ Authorization: `Bearer ${'d'.repeat(40)}` });
		vi.unstubAllGlobals();
	});
});

describe('startSession with a broken build configuration', () => {
	it('shows the configuration error instead of throwing', async () => {
		// Hermetic: every value config.ts reads is stubbed, whatever a local .env contains,
		// and fresh modules drop the cached config.
		for (const name of ['VITE_API_BASE_URL', 'VITE_ENTRA_TENANT_ID', 'VITE_ENTRA_CLIENT_ID', 'VITE_ENTRA_API_SCOPE', 'VITE_DEV_TOKEN']) {
			vi.stubEnv(name, '');
		}
		vi.stubEnv('VITE_AUTH_MODE', 'msal');
		vi.resetModules();
		const fresh = await import('../src/lib/auth/session.svelte');
		await fresh.startSession();
		expect(fresh.session.status).toBe('error');
		expect(fresh.session.error).toContain('missing VITE_ENTRA_TENANT_ID, VITE_ENTRA_CLIENT_ID, VITE_ENTRA_API_SCOPE');
		vi.unstubAllEnvs();
	});
});
