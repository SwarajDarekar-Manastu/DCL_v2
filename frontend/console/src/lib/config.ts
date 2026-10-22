// The one place that reads VITE_* variables and shapes the Console's backend access and auth (file 08 §7).

export type AuthMode = 'msal' | 'dev';

export interface ConsoleConfig {
	apiBaseUrl: string;
	wsUrl: string;
	auth: {
		mode: AuthMode;
		tenantId: string;
		clientId: string;
		apiScope: string;
		authority: string;
		redirectUri: string;
		/** Dev-only sign-in token, set by vite.config.ts under the dev server only */
		devToken: string;
	};
}

export class ConfigError extends Error {}

type Env = Record<string, string | boolean | undefined>;

function str(env: Env, name: string): string {
	const value = env[name];
	return typeof value === 'string' ? value.trim() : '';
}

export function buildConfig(env: Env, origin: string): ConsoleConfig {
	const apiBaseUrl = (str(env, 'VITE_API_BASE_URL') || origin).replace(/\/+$/, '');
	const wsUrl = apiBaseUrl.replace(/^http/, 'ws') + '/ws';
	const mode = (str(env, 'VITE_AUTH_MODE') || 'msal') as AuthMode;
	if (mode !== 'msal' && mode !== 'dev') {
		throw new ConfigError(`VITE_AUTH_MODE must be "msal" or "dev", got "${mode}"`);
	}
	if (mode === 'dev' && env.DEV !== true) {
		throw new ConfigError('VITE_AUTH_MODE=dev is only allowed under the Vite dev server');
	}
	const devToken = str(env, 'VITE_DEV_TOKEN');
	if (mode === 'dev' && !devToken) {
		throw new ConfigError('VITE_AUTH_MODE=dev needs DCL_CONSOLE_DEV_TOKEN in the repository .env (dev sign-in)');
	}
	const tenantId = str(env, 'VITE_ENTRA_TENANT_ID');
	const clientId = str(env, 'VITE_ENTRA_CLIENT_ID');
	const apiScope = str(env, 'VITE_ENTRA_API_SCOPE');
	if (mode === 'msal') {
		const missing = [
			['VITE_ENTRA_TENANT_ID', tenantId],
			['VITE_ENTRA_CLIENT_ID', clientId],
			['VITE_ENTRA_API_SCOPE', apiScope]
		]
			.filter(([, value]) => !value)
			.map(([name]) => name);
		if (missing.length) throw new ConfigError(`missing ${missing.join(', ')}`);
	}
	return {
		apiBaseUrl,
		wsUrl,
		auth: {
			mode,
			tenantId,
			clientId,
			apiScope,
			authority: `https://login.microsoftonline.com/${tenantId}`,
			redirectUri: origin + '/',
			devToken
		}
	};
}

let cached: ConsoleConfig | undefined;

export function getConfig(): ConsoleConfig {
	cached ??= buildConfig(import.meta.env, globalThis.location.origin);
	return cached;
}
