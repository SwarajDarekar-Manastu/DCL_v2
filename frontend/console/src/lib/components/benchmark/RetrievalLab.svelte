<script lang="ts">
	import { ApiError, retrievalSearch, type RetrievalLabRequest, type SearchResult } from '$lib/api_endpoint';
	import { score, splitList, viewerHref } from './links';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import SearchIcon from '@lucide/svelte/icons/search';
	import { Button } from '$lib/components/ui/button';
	import EmptyState from '$lib/components/shell/EmptyState.svelte';
	import Notice from '$lib/components/shell/Notice.svelte';

	let queryText = $state('');
	let scope = $state<RetrievalLabRequest['scope']>('child');
	let k = $state(30);
	let rerank = $state(true);
	let userLanguage = $state('en');
	let docKinds = $state('');
	let testPlans = $state('');
	let languages = $state('');
	let origins = $state<string[]>([]);
	let trustTierMax = $state<number | null>(null);
	let includeSuperseded = $state(false);
	let includeNeedsReview = $state(true);

	let result = $state<SearchResult | null>(null);
	let error = $state('');
	let busy = $state(false);
	let open = $state<Record<number, boolean>>({});

	function buildRequest(): RetrievalLabRequest {
		return {
			query: queryText.trim(),
			scope,
			k,
			rerank,
			user_language: userLanguage || 'en',
			filters: {
				doc_ids: [],
				doc_kinds: splitList(docKinds),
				test_plan_ids: splitList(testPlans),
				source_origins: origins,
				trust_tier_max: trustTierMax || null,
				node_types: [],
				languages: splitList(languages),
				include_superseded: includeSuperseded,
				include_needs_review: includeNeedsReview
			}
		};
	}

	async function search(event: SubmitEvent) {
		event.preventDefault();
		if (!queryText.trim()) return;
		busy = true;
		error = '';
		try {
			result = await retrievalSearch(buildRequest());
			open = {};
		} catch (e) {
			result = null;
			error = e instanceof ApiError ? e.detail : String(e);
		} finally {
			busy = false;
		}
	}
</script>

<form class="panel mb-5 grid gap-3 p-4" onsubmit={search} aria-label="Retrieval lab">
	<label class="grid gap-1"
		><span class="field-label">Query</span>
		<textarea class="field text-sm" rows="2" bind:value={queryText} placeholder="e.g. C-103 thermal margin ECSS"></textarea></label
	>
	<div class="flex flex-wrap items-end gap-3">
		<label class="grid gap-1"
			><span class="field-label">Scope</span>
			<select class="field w-40" bind:value={scope}>
				<option value="child">child chunks</option>
				<option value="parent">parents</option>
				<option value="tables_only">tables only</option>
				<option value="figures_only">figures only</option>
			</select>
		</label>
		<label class="grid gap-1"><span class="field-label">k</span> <input class="field num w-20 font-mono" type="number" min="1" max="50" bind:value={k} /></label>
		<label class="flex h-8 items-center gap-2"><input type="checkbox" bind:checked={rerank} /> rerank</label>
		<label class="grid gap-1"><span class="field-label">Answer language</span> <input class="field w-20" bind:value={userLanguage} /></label>
		<Button type="submit" class="ml-auto" disabled={busy || !queryText.trim()}><SearchIcon />{busy ? 'Searching…' : 'Search'}</Button>
	</div>
	<details class="group border-t pt-3">
		<summary class="text-muted-foreground hover:text-foreground text-sm font-medium">Filters</summary>
		<div class="mt-3 grid grid-cols-2 gap-3 lg:grid-cols-4">
			<label class="grid gap-1"><span class="field-label">Doc kinds</span> <input class="field" bind:value={docKinds} placeholder="test_report, datasheet" /></label>
			<label class="grid gap-1"><span class="field-label">Test plans</span> <input class="field" bind:value={testPlans} placeholder="TP30, TP37" /></label>
			<label class="grid gap-1"><span class="field-label">Languages</span> <input class="field" bind:value={languages} placeholder="en, de" /></label>
			<label class="grid gap-1"
				><span class="field-label">Max trust tier</span> <input class="field num font-mono" type="number" min="1" max="6" bind:value={trustTierMax} /></label
			>
		</div>
		<div class="mt-3 flex flex-wrap gap-x-5 gap-y-2">
			<label class="flex items-center gap-2"><input type="checkbox" bind:group={origins} value="internal" /> internal</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:group={origins} value="external_kept" /> external library</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:checked={includeSuperseded} /> include superseded</label>
			<label class="flex items-center gap-2"><input type="checkbox" bind:checked={includeNeedsReview} /> include unverified</label>
		</div>
	</details>
</form>

{#if error}<Notice tone="error" class="mb-4">{error}</Notice>{/if}

{#if result}
	<section class="panel" aria-labelledby="hits-title">
		<div class="panel-header">
			<h2 id="hits-title" class="panel-title">Results</h2>
			<p class="num text-muted-foreground m-0 text-xs" aria-label="Search summary">
				{result.hits.length} hits · dense path {result.dense_path ?? '—'}
				{#each Object.entries(result.leg_counts ?? {}) as [leg, n] (leg)}· {leg} {n} {/each}
				· rerank margin (1–5) {score(result.rerank_margin_1_5)}
			</p>
		</div>
		{#each result.warnings ?? [] as warning (warning)}
			<p class="text-warn bg-warn-bg m-0 flex items-center gap-1.5 border-b px-4 py-2 text-sm" role="status">
				<TriangleAlertIcon class="size-3.5 shrink-0" aria-hidden="true" />{warning}
			</p>
		{/each}
		{#if result.hits.length === 0}
			<EmptyState class="m-4" title="No hits" description="Loosen the filters or try another wording." />
		{:else}
			<table class="data-table">
				<thead
					><tr><th class="num w-10">#</th><th class="num w-20">Rerank</th><th class="num w-20">RRF</th><th>Passage</th><th>Kind</th><th>Origin</th></tr></thead
				>
				<tbody>
					{#each result.hits as hit, i (hit.doc_id + hit.anchor)}
						<tr>
							<td class="num text-muted-foreground font-mono">{i + 1}</td>
							<td class="num font-mono">{score(hit.rerank_score)}</td>
							<td class="num text-muted-foreground font-mono">{score(hit.rrf_score, 4)}</td>
							<td class="min-w-0">
								<a class="font-medium" href={viewerHref(hit.doc_id, hit.anchor)}>{hit.title ?? hit.doc_id}{hit.page_no ? `, p. ${hit.page_no}` : ''}</a>
								{#if hit.needs_review}<span class="text-warn ml-1.5 inline-flex align-[-2px]" title="unverified extraction"
										><TriangleAlertIcon class="size-3.5" aria-label="unverified extraction" /></span
									>{/if}
								<div class="text-muted-foreground mt-0.5 text-xs">{hit.breadcrumb}</div>
								<Button variant="link" size="xs" class="h-auto px-0" aria-expanded={!!open[i]} onclick={() => (open[i] = !open[i])}>
									{open[i] ? 'Hide text' : 'Show text'}
								</Button>
								{#if open[i]}
									<pre class="code-block my-1.5">{hit.passage}</pre>
									<details>
										<summary class="text-muted-foreground text-xs">Parent</summary>
										<pre class="code-block mt-1.5">{hit.parent_text}</pre>
									</details>
								{/if}
								{#if hit.also_in?.length}<div class="text-muted-foreground mt-0.5 text-xs">also in {hit.also_in.length} other document(s)</div>{/if}
							</td>
							<td class="text-muted-foreground text-xs">{hit.node_type}{hit.doc_kind ? ` · ${hit.doc_kind}` : ''}</td>
							<td class="text-muted-foreground text-xs"
								>{hit.source_origin ?? ''}{hit.trust_tier ? ` · tier ${hit.trust_tier}` : ''}{hit.language ? ` · ${hit.language}` : ''}</td
							>
						</tr>
					{/each}
				</tbody>
			</table>
		{/if}
	</section>
{/if}
