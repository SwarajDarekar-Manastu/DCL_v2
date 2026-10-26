<script lang="ts">
	import { ApiError, getOpsSummary, listFailedTasks, listRoots, type FailedTask, type OpsSummary, type RootStatus } from '$lib/api_endpoint';
	import SyncStatus from '$lib/components/ops/SyncStatus.svelte';
	import OpsOverview from '$lib/components/ops/OpsOverview.svelte';
	import LlmUsage from '$lib/components/ops/LlmUsage.svelte';
	import { live } from '$lib/live.svelte';
	import { hasRole } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import RefreshCwIcon from '@lucide/svelte/icons/refresh-cw';
	import { Button } from '$lib/components/ui/button';
	import FailedTasks from '$lib/components/ops/FailedTasks.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';

	let isAdmin = $derived(hasRole(session.user?.roles ?? [], 'admin'));
	let isReviewer = $derived(hasRole(session.user?.roles ?? [], 'reviewer'));
	let roots = $state<RootStatus[] | null>(null);
	let failed = $state<FailedTask[] | null>(null);
	let error = $state('');
	let reload = $state(0);
	let summary = $state<OpsSummary | null>(null);
	let summaryError = $state('');
	let tick = $state(0);

	// Counters refresh every 30 s and on live review/run events.
	$effect(() => {
		void tick;
		void reload;
		void live.reviewCounts;
		void live.lastRunEvent;
		if (isReviewer)
			listRoots()
				.then((r) => (roots = r))
				.catch((e) => (summaryError = e instanceof ApiError ? e.detail : String(e)));
		getOpsSummary()
			.then((s) => {
				summary = s;
				summaryError = '';
			})
			.catch((e) => (summaryError = e instanceof ApiError ? e.detail : String(e)));
	});
	$effect(() => {
		const timer = setInterval(() => (tick += 1), 30_000);
		return () => clearInterval(timer);
	});

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
	<Page title="Ops" description="Sync status, queue depths, Gemini use and cost, failed tasks (file 08 §4.2).">
		<div class="grid gap-5">
			{#if summaryError}<Notice tone="error">{summaryError}</Notice>{/if}
			{#if roots}<SyncStatus {roots} />{/if}
			{#if summary}<OpsOverview {summary} />{/if}
			<LlmUsage />
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
		</div>
	</Page>
</RoleGate>
