<script lang="ts">
	import type { Snippet } from 'svelte';
	import LockIcon from '@lucide/svelte/icons/lock';
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
	<section class="mx-auto mt-16 max-w-md px-6 text-center" role="alert">
		<span class="bg-muted text-muted-foreground mx-auto mb-4 flex size-10 items-center justify-center rounded-full" aria-hidden="true">
			<LockIcon class="size-5" />
		</span>
		<h2 class="m-0 text-base">Not available</h2>
		<p class="text-muted-foreground mt-1">
			This page needs the <strong class="text-foreground font-medium">{role}</strong> role. Ask a DCL admin to add you to the matching Entra ID group.
		</p>
	</section>
{/if}
