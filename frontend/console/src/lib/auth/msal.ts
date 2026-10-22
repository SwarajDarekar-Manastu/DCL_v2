// Entra ID sign-in for the Console: MSAL browser, redirect flow with PKCE (file 08 §2.3).
// Talks to Entra only; every backend call goes through src/lib/api_endpoint.ts.

import {
	InteractionRequiredAuthError,
	PublicClientApplication,
	type AccountInfo,
	type Configuration,
	type IPublicClientApplication
} from '@azure/msal-browser';
import type { ConsoleConfig } from '$lib/config';

export interface AuthClient {
	/** Completes a pending redirect and returns the signed-in account name, or null. */
	init(): Promise<string | null>;
	login(): Promise<void>;
	logout(): Promise<void>;
	/** An access token for the Console API; redirects to sign-in when interaction is required. */
	getToken(): Promise<string>;
}

type PcaFactory = (configuration: Configuration) => IPublicClientApplication;

const defaultFactory: PcaFactory = (configuration) => new PublicClientApplication(configuration);

export function createMsalAuth(auth: ConsoleConfig['auth'], factory: PcaFactory = defaultFactory): AuthClient {
	const pca = factory({
		auth: {
			clientId: auth.clientId,
			authority: auth.authority,
			redirectUri: auth.redirectUri,
			postLogoutRedirectUri: auth.redirectUri,
			// After sign-in, return to the page that asked for it (e.g. a citation deep link from chat).
			navigateToLoginRequestUrl: true
		},
		cache: { cacheLocation: 'sessionStorage' }
	});
	const scopes = [auth.apiScope];
	let account: AccountInfo | null = null;

	return {
		async init() {
			await pca.initialize();
			const result = await pca.handleRedirectPromise();
			account = result?.account ?? pca.getActiveAccount() ?? pca.getAllAccounts()[0] ?? null;
			if (account) pca.setActiveAccount(account);
			return account ? account.name || account.username : null;
		},
		async login() {
			await pca.loginRedirect({ scopes, redirectStartPage: globalThis.location?.href });
		},
		async logout() {
			await pca.logoutRedirect({ account: account ?? undefined });
		},
		async getToken() {
			if (!account) throw new Error('not signed in');
			try {
				return (await pca.acquireTokenSilent({ scopes, account })).accessToken;
			} catch (error) {
				if (error instanceof InteractionRequiredAuthError) {
					await pca.acquireTokenRedirect({ scopes, account });
				}
				throw error;
			}
		}
	};
}
