<script lang="ts">
	import { ApiError, listFailedTasks, type FailedTask } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
	import { Button } from '$lib/components/ui/button';
	import FailedTasks from '$lib/components/ops/FailedTasks.svelte';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
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
	<Page title="Ops" description="Sync status, queue depths, failed tasks and cost today (file 08 §4.2).">
		<div class="grid gap-5">
			{#if isAdmin}
				<section class="panel" aria-labelledby="failed-title">
					<div class="panel-header">
						<div>
							<h2 id="failed-title" class="panel-title">Failed tasks</h2>
							<p class="text-muted-foreground m-0 text-xs">
								Tasks that failed after their last retry, newest first (the latest 100). Retry is not available yet.
							</p>
						</div>
						<Button variant="outline" size="sm" onclick={() => (reload += 1)}><RefreshCwIcon />Refresh</Button>
					</div>
					{#if error}<div class="px-4 py-3"><Notice tone="error">{error}</Notice></div>{/if}
					{#if failed}<FailedTasks items={failed} />{/if}
				</section>
			{/if}
			<EmptyState
				title="More operations data to come"
				description="Sync freshness per root, Celery queue depths and today's model cost against the budget will appear here once their APIs are connected."
			/>
		</div>
	</Page>
</RoleGate>
