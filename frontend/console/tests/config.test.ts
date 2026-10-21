import { describe, expect, it } from 'vitest';
import { buildConfig, ConfigError } from '../src/lib/config';

const MSAL = {
	VITE_ENTRA_TENANT_ID: 'tenant-1',
	VITE_ENTRA_CLIENT_ID: 'client-1',
	VITE_ENTRA_API_SCOPE: 'api://dcl-console-api/access_as_user'
};

describe('buildConfig', () => {
	it('defaults the API to the page origin and derives the websocket URL', () => {
		const config = buildConfig(MSAL, 'https://console.dcl.local');
		expect(config.apiBaseUrl).toBe('https://console.dcl.local');
		expect(config.wsUrl).toBe('wss://console.dcl.local/ws');
		expect(config.auth.authority).toBe('https://login.microsoftonline.com/tenant-1');
		expect(config.auth.redirectUri).toBe('https://console.dcl.local/');
	});

	it('uses VITE_API_BASE_URL without a trailing slash', () => {
		const config = buildConfig({ ...MSAL, VITE_API_BASE_URL: 'http://localhost:8200/' }, 'http://localhost:5173');
		expect(config.apiBaseUrl).toBe('http://localhost:8200');
		expect(config.wsUrl).toBe('ws://localhost:8200/ws');
	});

	it('refuses msal mode with missing Entra settings', () => {
		expect(() => buildConfig({ VITE_ENTRA_TENANT_ID: 't' }, 'http://x')).toThrow(
			new ConfigError('missing VITE_ENTRA_CLIENT_ID, VITE_ENTRA_API_SCOPE')
		);
	});

	it('allows dev auth only under the Vite dev server', () => {
		expect(() => buildConfig({ VITE_AUTH_MODE: 'dev', DEV: false }, 'http://x')).toThrow(ConfigError);
		const config = buildConfig({ VITE_AUTH_MODE: 'dev', DEV: true, VITE_DEV_ROLES: 'viewer' }, 'http://x');
		expect(config.auth.mode).toBe('dev');
		expect(config.auth.devRoles).toEqual(['viewer']);
	});

	it('refuses an unknown auth mode', () => {
		expect(() => buildConfig({ VITE_AUTH_MODE: 'none' }, 'http://x')).toThrow(ConfigError);
	});
});
