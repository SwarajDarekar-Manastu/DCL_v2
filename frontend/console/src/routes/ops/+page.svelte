<script lang="ts">
	import { ApiError, listFailedTasks, type FailedTask } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import FailedTasks from '$lib/components/ops/FailedTasks.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let isAdmin = $derived(hasRole(session.user?.roles ?? [], 'admin'));
	let failed = $state<FailedTask[] | null>(null);
	let error = $state('');
	let reload = $state(0);

	$effect(() => {
		void reload;
		if (!isAdmin) return;
		listFailedTasks()
			.then((page) => {
				failed = page.items;
				error = '';
			})
			.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)));
	});
</script>

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<h1>Ops</h1>
	<p>Sync status, queue depths, failed tasks and cost today (file 08 §4.2).</p>

	{#if isAdmin}
		<section>
			<h2>Failed tasks <button type="button" onclick={() => (reload += 1)}>Refresh</button></h2>
			<p class="muted">Tasks that failed after their last retry, newest first (the latest 100). Retry is not available yet.</p>
			{#if error}<p class="error" role="alert">{error}</p>{/if}
			{#if failed}<FailedTasks items={failed} />{/if}
		</section>
	{/if}
</RoleGate>

<style>
	h2 {
		font-size: 0.95rem;
		margin: 1rem 0 0.4rem;
		display: flex;
		gap: 0.6rem;
		align-items: center;
	}
	button {
		font: inherit;
		font-size: 0.8rem;
		padding: 0.1rem 0.5rem;
		cursor: pointer;
	}
	.muted {
		opacity: 0.7;
		font-size: 0.84rem;
	}
	.error {
		color: var(--hard);
	}
</style>
