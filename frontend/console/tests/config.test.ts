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
		expect(() => buildConfig({ VITE_AUTH_MODE: 'msal', VITE_ENTRA_TENANT_ID: 't' }, 'http://x')).toThrow(
			new ConfigError('missing VITE_ENTRA_CLIENT_ID, VITE_ENTRA_API_SCOPE')
		);
	});

	it('has no dev sign-in mode any more', () => {
		expect(() => buildConfig({ VITE_AUTH_MODE: 'dev', DEV: true, VITE_DEV_TOKEN: 't'.repeat(40) }, 'http://x')).toThrow(
			new ConfigError('VITE_AUTH_MODE must be "local" or "msal", got "dev"')
		);
	});

	it('uses local password sign-in unless another mode is asked for', () => {
		expect(buildConfig({}, 'http://x').auth.mode).toBe('local');
		expect(buildConfig({ ...MSAL, VITE_AUTH_MODE: 'msal' }, 'http://x').auth.mode).toBe('msal');
	});

	it('refuses an unknown auth mode', () => {
		expect(() => buildConfig({ VITE_AUTH_MODE: 'none' }, 'http://x')).toThrow(ConfigError);
	});
});
