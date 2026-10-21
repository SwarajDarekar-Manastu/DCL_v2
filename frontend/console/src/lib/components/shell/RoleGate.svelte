<script lang="ts">
	import type { Snippet } from 'svelte';
	import { hasRole, type ConsoleRole } from '$lib/auth/roles';

	interface Props {
		roles: readonly string[];
		role: ConsoleRole;
		children: Snippet;
	}

	let { roles, role, children }: Props = $props();
</script>

{#if hasRole(roles, role)}
	{@render children()}
{:else}
	<section class="denied" role="alert">
		<h2>Not available</h2>
		<p>This page needs the <strong>{role}</strong> role. Ask a DCL admin to add you to the matching Entra ID group.</p>
	</section>
{/if}

<style>
	.denied {
		max-width: 36rem;
		margin: 3rem auto;
		padding: 1.5rem;
		border: 1px solid var(--border);
		border-radius: 0.5rem;
	}
</style>
