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

describe('startSession with a broken build configuration', () => {
	it('shows the configuration error instead of throwing', async () => {
		vi.stubEnv('VITE_ENTRA_TENANT_ID', '');
		await startSession();
		expect(session.status).toBe('error');
		expect(session.error).toContain('missing VITE_ENTRA_TENANT_ID');
		vi.unstubAllEnvs();
	});
});
