import { sveltekit } from '@sveltejs/kit/vite';
import tailwindcss from '@tailwindcss/vite';
import { svelteTesting } from '@testing-library/svelte/vite';
import { defineConfig } from 'vitest/config';

// The dev server is only a dev server: sign-in is the same local password sign-in as the build
// (VITE_AUTH_MODE=local by default, src/lib/config.ts); no token is defined here.
export default defineConfig({
	plugins: [tailwindcss(), sveltekit(), svelteTesting()],
	server: { fs: { allow: ['../../asset'] } },
	test: {
		environment: 'jsdom',
		include: ['tests/**/*.test.ts']
	}
});
