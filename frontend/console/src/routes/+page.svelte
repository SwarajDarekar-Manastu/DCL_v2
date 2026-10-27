<script lang="ts">
	import ArrowUpRightIcon from '@lucide/svelte/icons/arrow-up-right';
	import { visibleNav } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import { listCases } from '$lib/api_endpoint';
	import { hasRole } from '$lib/auth/roles';
	import PageHeader from '$lib/components/shell/PageHeader.svelte';

	let items = $derived(visibleNav(session.user?.roles ?? []));
	const BLURB: Record<string, string> = {
		'/review': 'Questions the pipeline could not answer on its own: units, readings, disagreements. Decide, undo.',
		'/benchmark': 'Golden suites, runs, regressions and the retrieval lab.',
		'/entities': 'Canonical entities and alias merges.',
		'/settings': 'Pipeline configuration: sources, gate, routes, models, prompts.',
		'/ops': 'Sync status, queue depths, failed tasks and cost today.',
		'/audit': 'Who changed what, when, with before and after.'
	};
	// How much is waiting, asked of the server (the live review counts are never published).
	let waiting = $state<{ hard: number; soft: number } | null>(null);
	$effect(() => {
		if (!hasRole(session.user?.roles ?? [], 'reviewer')) return;
		listCases({ limit: 1 })
			.then((list) => (waiting = { hard: list.open_hard, soft: list.open_soft }))
			.catch(() => (waiting = null));
	});
</script>

<div class="mx-auto w-full max-w-[1400px] px-6 pt-5 pb-10">
	<PageHeader title="Welcome, {session.user?.name}" description="Pick an area to work in." />
	<ul class="m-0 grid list-none grid-cols-2 gap-3 p-0 xl:grid-cols-3">
		{#each items as item (item.href)}
			<li>
				<a
					href={item.href}
					class="group bg-card hover:border-border-strong flex h-full flex-col gap-1 rounded-xl border p-4 no-underline transition-colors hover:no-underline"
				>
					<span class="text-foreground flex items-center justify-between font-medium">
						{item.label}
						<ArrowUpRightIcon class="text-muted-foreground size-4 opacity-0 transition-opacity group-hover:opacity-100" aria-hidden="true" />
					</span>
					<span class="text-muted-foreground">{BLURB[item.href]}</span>
					{#if item.href === '/review' && waiting}
						<span class="num text-muted-foreground mt-2 text-xs">
							{#if waiting.hard + waiting.soft === 0}Nothing waiting.{:else}<span class="text-foreground font-medium"
									>{waiting.hard + waiting.soft} question{waiting.hard + waiting.soft === 1 ? '' : 's'} waiting</span
								>{#if waiting.hard}<span class="text-hard"> · {waiting.hard} keep files out of search</span>{/if}{/if}
						</span>
					{/if}
				</a>
			</li>
		{/each}
	</ul>
</div>
