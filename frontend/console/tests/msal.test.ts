import { InteractionRequiredAuthError, type IPublicClientApplication } from '@azure/msal-browser';
import { describe, expect, it, vi } from 'vitest';
import { createMsalAuth } from '../src/lib/auth/msal';

const AUTH = {
	mode: 'msal' as const,
	tenantId: 'tenant-1',
	clientId: 'client-1',
	apiScope: 'api://dcl-console-api/access_as_user',
	authority: 'https://login.microsoftonline.com/tenant-1',
	redirectUri: 'https://console/',
	devRoles: []
};
const ACCOUNT = { name: 'Asha Rao', username: 'asha@manastuspace.com', homeAccountId: 'h' };

function fakePca(overrides: Record<string, unknown> = {}) {
	const pca = {
		initialize: vi.fn(async () => {}),
		handleRedirectPromise: vi.fn(async () => null),
		getActiveAccount: vi.fn(() => null),
		getAllAccounts: vi.fn(() => []),
		setActiveAccount: vi.fn(),
		loginRedirect: vi.fn(async () => {}),
		logoutRedirect: vi.fn(async () => {}),
		acquireTokenSilent: vi.fn(async () => ({ accessToken: 'access-1' })),
		acquireTokenRedirect: vi.fn(async () => {}),
		...overrides
	};
	return pca;
}

function client(pca: ReturnType<typeof fakePca>) {
	let seen: unknown;
	const auth = createMsalAuth(AUTH, (configuration) => {
		seen = configuration;
		return pca as unknown as IPublicClientApplication;
	});
	return { auth, seen: () => seen };
}

describe('createMsalAuth', () => {
	it('configures MSAL for the Console app registration', () => {
		const { seen } = client(fakePca());
		expect(seen()).toMatchObject({
			auth: {
				clientId: 'client-1',
				authority: 'https://login.microsoftonline.com/tenant-1',
				redirectUri: 'https://console/',
				navigateToLoginRequestUrl: true
			},
			cache: { cacheLocation: 'sessionStorage' }
		});
	});

	it('returns null when nobody is signed in, and login redirects with the API scope', async () => {
		const pca = fakePca();
		const { auth } = client(pca);
		expect(await auth.init()).toBeNull();
		await auth.login();
		expect(pca.loginRedirect).toHaveBeenCalledWith({
			scopes: ['api://dcl-console-api/access_as_user'],
			redirectStartPage: globalThis.location.href
		});
	});

	it('completes the redirect, activates the account and gets tokens silently', async () => {
		const pca = fakePca({ handleRedirectPromise: vi.fn(async () => ({ account: ACCOUNT })) });
		const { auth } = client(pca);
		expect(await auth.init()).toBe('Asha Rao');
		expect(pca.setActiveAccount).toHaveBeenCalledWith(ACCOUNT);
		expect(await auth.getToken()).toBe('access-1');
		expect(pca.acquireTokenSilent).toHaveBeenCalledWith({ scopes: ['api://dcl-console-api/access_as_user'], account: ACCOUNT });
	});

	it('falls back to an interactive redirect when the silent call needs interaction', async () => {
		const pca = fakePca({
			getAllAccounts: vi.fn(() => [ACCOUNT]),
			acquireTokenSilent: vi.fn(async () => {
				throw new InteractionRequiredAuthError('interaction_required');
			})
		});
		const { auth } = client(pca);
		await auth.init();
		await expect(auth.getToken()).rejects.toBeInstanceOf(InteractionRequiredAuthError);
		expect(pca.acquireTokenRedirect).toHaveBeenCalledWith({ scopes: ['api://dcl-console-api/access_as_user'], account: ACCOUNT });
	});
});
