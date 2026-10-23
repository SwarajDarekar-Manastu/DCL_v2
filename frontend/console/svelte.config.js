import adapter from '@sveltejs/adapter-static';
import { vitePreprocess } from '@sveltejs/vite-plugin-svelte';

/** @type {import('@sveltejs/kit').Config} */
const config = {
	preprocess: vitePreprocess(),
	kit: {
		adapter: adapter({ fallback: 'index.html' }),
		// The repository's asset/ folder holds the screenshots the in-app guides show (docker: `asset` build context).
		alias: { $asset: '../../asset' }
	}
};

export default config;
