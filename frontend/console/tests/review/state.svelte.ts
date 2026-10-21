// Wraps test data in real Svelte $state, the way pages hold API results.
export function reactive<T extends object>(value: T): T {
	const state = $state(value);
	return state;
}
