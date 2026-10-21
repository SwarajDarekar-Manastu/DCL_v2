<script lang="ts">
	import { visibleNav } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';

	let items = $derived(visibleNav(session.user?.roles ?? []));
</script>

<h1>Welcome, {session.user?.name}</h1>
<ul class="areas">
	{#each items as item (item.href)}
		<li><a href={item.href}>{item.label}</a></li>
	{/each}
</ul>

<style>
	.areas {
		display: grid;
		grid-template-columns: repeat(auto-fill, minmax(10rem, 1fr));
		gap: 0.75rem;
		padding: 0;
		list-style: none;
	}
	.areas a {
		display: block;
		padding: 1rem;
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 0.5rem;
		text-decoration: none;
	}
</style>
