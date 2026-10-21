<script lang="ts">
	import { SETTINGS_SECTIONS } from './sections';

	interface Props {
		current: string;
	}

	let { current }: Props = $props();
</script>

<nav aria-label="Settings sections">
	<ul>
		{#each SETTINGS_SECTIONS as section (section.id)}
			<li>
				<a href="/settings/{section.id}" aria-current={section.id === current ? 'page' : undefined}>{section.title}</a>
			</li>
		{/each}
	</ul>
</nav>

<style>
	ul {
		list-style: none;
		margin: 0;
		padding: 0;
		display: grid;
		gap: 0.15rem;
	}
	a {
		display: block;
		padding: 0.4rem 0.7rem;
		border-radius: 0.3rem;
		text-decoration: none;
		color: inherit;
	}
	a[aria-current='page'] {
		background: var(--surface);
		border: 1px solid var(--border);
		font-weight: 600;
	}
	a:hover {
		background: var(--surface);
	}
</style>
