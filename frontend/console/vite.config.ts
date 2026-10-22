import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { loadEnv } from 'vite';
import { defineConfig } from 'vitest/config';

export default defineConfig(({ command, mode }) => {
	// Dev-only sign-in (user-approved, DECISIONS 2026-10-22): the Vite dev server sends the token from the
	// repository .env. It is defined only when serving in development, so no build ever contains it.
	const serving = command === 'serve' && mode === 'development';
	// Vite runs from frontend/console; the stack's .env sits at the repository root.
	const local = loadEnv(mode, '.', 'VITE_');
	const stack = loadEnv(mode, '../..', 'DCL_CONSOLE_DEV_');
	const devToken = serving ? local.VITE_DEV_TOKEN || stack.DCL_CONSOLE_DEV_TOKEN || '' : '';
	return {
		plugins: [tailwindcss(), sveltekit(), svelteTesting()],
		define: { 'import.meta.env.VITE_DEV_TOKEN': JSON.stringify(devToken) },
		test: {
			environment: 'jsdom',
			include: ['tests/**/*.test.ts']
		}
	};
});
