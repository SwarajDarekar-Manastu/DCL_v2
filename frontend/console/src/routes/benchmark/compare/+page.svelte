<script lang="ts">
	import { page } from '$app/state';
	import { ApiError, compareRuns, type RunComparison } from '$lib/api_endpoint';
	import { session } from '$lib/auth/session.svelte';
	import { caseHref, runHref } from '$lib/components/benchmark/links';
	import { ribbon } from '$lib/components/benchmark/run_view';
	import ArrowRightIcon from '@lucide/svelte/icons/arrow-right';
	import Notice from '$lib/components/shell/Notice.svelte';
	import Page from '$lib/components/shell/Page.svelte';
	import RoleGate from '$lib/components/shell/RoleGate.svelte';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';
	import { cn } from '$lib/utils';

	let base = $derived(page.url.searchParams.get('base') ?? '');
	let head = $derived(page.url.searchParams.get('head') ?? '');
	let data = $state<RunComparison | null>(null);
	let error = $state('');

	$effect(() => {
		const [b, h] = [base, head];
		if (!b || !h) {
			error = 'Choose two runs on the Benchmark page.';
			return;
		}
		compareRuns(b, h)
			.then((c) => {
				data = c;
				error = '';
			})
			.catch((e) => (error = e instanceof ApiError ? e.detail : String(e)));
	});

	let items = $derived(data ? ribbon(data.head.aggregate, data.base.aggregate) : []);
	const display = (v: unknown) => (v === null || v === undefined ? '—' : typeof v === 'object' ? JSON.stringify(v) : String(v));
</script>

{#snippet outcome(passed: boolean | null, failureClass: string | null | undefined, missing: string)}
	{#if passed === null}<span class="text-muted-foreground">{missing}</span>{:else if passed}<ToneBadge tone="ok">pass</ToneBadge>{:else}<span
			class="inline-flex items-center gap-1.5"><ToneBadge tone="hard">fail</ToneBadge><span class="font-mono text-xs">{failureClass ?? ''}</span></span
		>{/if}
{/snippet}

<RoleGate roles={session.user?.roles ?? []} role="viewer">
	<Page title="Compare runs" width="full">
		{#snippet below()}
			{#if data}
				<p class="m-0 flex flex-wrap items-center gap-2 text-sm">
					<span class="text-muted-foreground">Base</span>
					<a class="font-mono" href={runHref(data.base.run_id)}>{data.base.run_id.slice(0, 8)}</a>
					<ArrowRightIcon class="text-muted-foreground size-3.5" aria-label="to" />
					<span class="text-muted-foreground">Head</span>
					<a class="font-mono" href={runHref(data.head.run_id)}>{data.head.run_id.slice(0, 8)}</a>
					<ToneBadge tone="outline">{data.head.suite}</ToneBadge>
				</p>
			{/if}
		{/snippet}

		{#if error}<Notice tone="error" class="mb-4">{error}</Notice>{/if}
		{#if data}
			{#if items.length}
				<ul class="m-0 mb-5 grid list-none grid-cols-2 gap-px overflow-hidden rounded-lg border bg-border p-0 md:grid-cols-4" aria-label="Summary">
					{#each items as item (item.key)}
						<li class="bg-card grid gap-0.5 px-4 py-3">
							<span class="text-muted-foreground text-xs">{item.label}</span><span class="num font-mono text-lg font-semibold">{item.value}</span>
							{#if item.delta}<span
									class={cn('num font-mono text-xs', item.better === true && 'text-ok', item.better === false && 'text-hard', item.better === null && 'text-muted-foreground')}
									>{item.delta}</span
								>{/if}
						</li>
					{/each}
				</ul>
			{/if}

			<div class="grid gap-5">
				{#each [{ title: 'Newly failing', rows: data.newly_failing, cls: 'text-hard' }, { title: 'Newly passing', rows: data.newly_passing, cls: 'text-ok' }, { title: 'Still failing', rows: data.still_failing, cls: '' }] as group (group.title)}
					<section class="panel">
						<div class="panel-header">
							<h2 class={cn('panel-title', group.cls)}>{group.title} <span class="num font-mono">({group.rows.length})</span></h2>
						</div>
						{#if group.rows.length}
							<table class="data-table">
								<thead><tr><th>Case</th><th class="w-[35%]">Before</th><th class="w-[35%]">After</th></tr></thead>
								<tbody>
									{#each group.rows as d (d.case_id)}
										<tr>
											<td><a class="font-mono text-xs" href={caseHref(d.case_id)}>{d.case_id}</a></td>
											<td>{@render outcome(d.base_passed, d.base_failure_class, 'not run')}</td>
											<td>{@render outcome(d.head_passed, d.head_failure_class, '—')}</td>
										</tr>
									{/each}
								</tbody>
							</table>
						{:else}
							<p class="text-muted-foreground m-0 px-4 py-3 text-sm">None.</p>
						{/if}
					</section>
				{/each}

				<section class="panel">
					<div class="panel-header"><h2 class="panel-title">Configuration changes</h2></div>
					{#if Object.keys(data.config_diff).length === 0}
						<p class="text-muted-foreground m-0 px-4 py-3 text-sm">Same configuration.</p>
					{:else}
						<table class="data-table">
							<thead><tr><th>Setting</th><th class="w-[35%]">Before</th><th class="w-[35%]">After</th></tr></thead>
							<tbody>
								{#each Object.entries(data.config_diff) as [key, change] (key)}
									<tr>
										<td><code>{key}</code></td>
										<td class="font-mono text-xs break-all">{display(change.base)}</td>
										<td class="font-mono text-xs break-all">{display(change.head)}</td>
									</tr>
								{/each}
							</tbody>
						</table>
					{/if}
				</section>
			</div>
		{/if}
	</Page>
</RoleGate>
