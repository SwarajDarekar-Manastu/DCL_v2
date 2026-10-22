import { describe, expect, it, vi } from 'vitest';
import { buildConfig } from '../src/lib/config';
import { session, startSession } from '../src/lib/auth/session.svelte';
import type { AuthClient } from '../src/lib/auth/msal';
import { getMe } from '../src/lib/api_endpoint';

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

describe('local sign-in', () => {
	const local = buildConfig({ VITE_API_BASE_URL: 'http://api' }, 'http://console');
	const user = { oid: 'u1', name: 'Asha', email: 'asha@manastuspace.com', roles: ['viewer', 'admin'] };
	const later = new Date(Date.now() + 3600_000).toISOString();

	it('signs in with email and password, then reads the roles from /auth/me', async () => {
		sessionStorage.clear();
		const fetchMock = vi.fn(async (url: string) =>
			url.endsWith('/auth/login')
				? new Response(JSON.stringify({ access_token: 'jwt-1', token_type: 'bearer', expires_at: later, user }))
				: new Response(JSON.stringify(user))
		);
		vi.stubGlobal('fetch', fetchMock);
		await startSession(local);
		expect(session.status).toBe('signed_out');
		await session.signInWithPassword('asha@manastuspace.com', 'pw');
		expect(session.status).toBe('signed_in');
		expect(session.user).toEqual(user);
		const [loginUrl, loginInit] = fetchMock.mock.calls[0] as unknown as [string, RequestInit];
		expect(loginUrl).toBe('http://api/auth/login');
		expect(loginInit.headers).toEqual({ 'Content-Type': 'application/json' });
		const [, meInit] = fetchMock.mock.calls[1] as unknown as [string, RequestInit];
		expect(meInit.headers).toMatchObject({ Authorization: 'Bearer jwt-1' });
		vi.unstubAllGlobals();
	});

	it('goes back to the sign-in form when the API answers 401 mid-session', async () => {
		sessionStorage.setItem('dcl-session', JSON.stringify({ token: 'jwt-1', expiresAt: Date.now() + 3600_000 }));
		const fetchMock = vi.fn(async () => new Response(JSON.stringify(user)));
		vi.stubGlobal('fetch', fetchMock);
		await startSession(local);
		expect(session.status).toBe('signed_in');
		fetchMock.mockImplementation(async () => new Response(JSON.stringify({ detail: 'account disabled' }), { status: 401 }));
		await expect(getMe()).rejects.toThrow('account disabled');
		expect(session.status).toBe('signed_out');
		expect(session.notice).toBe('Your session has ended. Sign in again.');
		expect(sessionStorage.getItem('dcl-session')).toBeNull();
		vi.unstubAllGlobals();
	});

	it('restores the session after a reload and signs out on request', async () => {
		sessionStorage.setItem('dcl-session', JSON.stringify({ token: 'jwt-2', expiresAt: Date.now() + 3600_000 }));
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify(user))));
		await startSession(local);
		expect(session.status).toBe('signed_in');
		await session.signOut();
		expect(session.status).toBe('signed_out');
		expect(sessionStorage.getItem('dcl-session')).toBeNull();
		vi.unstubAllGlobals();
	});

	it('shows a wrong password on the form and stays signed out', async () => {
		sessionStorage.clear();
		vi.stubGlobal('fetch', vi.fn(async () => new Response(JSON.stringify({ detail: 'wrong email or password' }), { status: 401 })));
		await startSession(local);
		await expect(session.signInWithPassword('a@b.c', 'bad')).rejects.toThrow('wrong email or password');
		expect(session.status).toBe('signed_out');
		vi.unstubAllGlobals();
	});
});
