<script lang="ts">
	import ArrowUpRightIcon from '@lucide/svelte/icons/arrow-up-right';
	import { visibleNav } from '$lib/auth/roles';
	import { session } from '$lib/auth/session.svelte';
	import { live } from '$lib/live.svelte';
	import PageHeader from '$lib/components/shell/PageHeader.svelte';

	let items = $derived(visibleNav(session.user?.roles ?? []));
	const BLURB: Record<string, string> = {
		'/review': 'Flags and halted documents, sorted by impact. Resolve, reject, undo.',
		'/benchmark': 'Golden suites, runs, regressions and the retrieval lab.',
		'/entities': 'Canonical entities and alias merges.',
		'/settings': 'Pipeline configuration: sources, gate, routes, models, prompts.',
		'/ops': 'Sync status, queue depths, failed tasks and cost today.',
		'/audit': 'Who changed what, when, with before and after.'
	};
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
					{#if item.href === '/review' && live.reviewCounts}
						<span class="num text-muted-foreground mt-2 text-xs">
							<span class="text-hard font-medium">{live.reviewCounts.hard} HARD</span> · {live.reviewCounts.soft} SOFT open
						</span>
					{/if}
				</a>
			</li>
		{/each}
	</ul>
</div>
