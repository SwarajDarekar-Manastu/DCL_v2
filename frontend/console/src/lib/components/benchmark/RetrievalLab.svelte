<script lang="ts">
	import { ApiError, retrievalSearch, type RetrievalLabRequest, type SearchResult } from '$lib/api_endpoint';
	import { score, splitList, viewerHref } from './links';

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

<form class="lab" onsubmit={search} aria-label="Retrieval lab">
	<label class="query"
		>Query <textarea rows="2" bind:value={queryText} placeholder="e.g. C-103 thermal margin ECSS"></textarea></label
	>
	<div class="row">
		<label
			>Scope
			<select bind:value={scope}>
				<option value="child">child chunks</option>
				<option value="parent">parents</option>
				<option value="tables_only">tables only</option>
				<option value="figures_only">figures only</option>
			</select>
		</label>
		<label>k <input type="number" min="1" max="50" bind:value={k} /></label>
		<label class="check"><input type="checkbox" bind:checked={rerank} /> rerank</label>
		<label>Answer language <input class="short" bind:value={userLanguage} /></label>
	</div>
	<details>
		<summary>Filters</summary>
		<div class="row">
			<label>Doc kinds <input bind:value={docKinds} placeholder="test_report, datasheet" /></label>
			<label>Test plans <input bind:value={testPlans} placeholder="TP30, TP37" /></label>
			<label>Languages <input bind:value={languages} placeholder="en, de" /></label>
			<label>Max trust tier <input type="number" min="1" max="6" bind:value={trustTierMax} /></label>
		</div>
		<div class="row">
			<label class="check"><input type="checkbox" bind:group={origins} value="internal" /> internal</label>
			<label class="check"><input type="checkbox" bind:group={origins} value="external_kept" /> external library</label>
			<label class="check"><input type="checkbox" bind:checked={includeSuperseded} /> include superseded</label>
			<label class="check"><input type="checkbox" bind:checked={includeNeedsReview} /> include unverified</label>
		</div>
	</details>
	<button type="submit" disabled={busy || !queryText.trim()}>{busy ? 'Searching…' : 'Search'}</button>
</form>

{#if error}<p class="error" role="alert">{error}</p>{/if}

{#if result}
	<p class="summary" aria-label="Search summary">
		{result.hits.length} hits · dense path {result.dense_path ?? '—'}
		{#each Object.entries(result.leg_counts ?? {}) as [leg, n] (leg)}· {leg} {n} {/each}
		· rerank margin (1–5) {score(result.rerank_margin_1_5)}
	</p>
	{#each result.warnings ?? [] as warning (warning)}<p class="warning" role="status">⚠ {warning}</p>{/each}
	<table class="hits">
		<thead><tr><th>#</th><th>Rerank</th><th>RRF</th><th>Passage</th><th>Kind</th><th>Origin</th></tr></thead>
		<tbody>
			{#each result.hits as hit, i (hit.doc_id + hit.anchor)}
				<tr>
					<td>{i + 1}</td>
					<td>{score(hit.rerank_score)}</td>
					<td>{score(hit.rrf_score, 4)}</td>
					<td>
						<a href={viewerHref(hit.doc_id, hit.anchor)}>{hit.title ?? hit.doc_id}{hit.page_no ? `, p. ${hit.page_no}` : ''}</a>
						{#if hit.needs_review}<span class="flag" title="unverified extraction">⚠</span>{/if}
						<div class="crumb">{hit.breadcrumb}</div>
						<button type="button" class="link" aria-expanded={!!open[i]} onclick={() => (open[i] = !open[i])}>
							{open[i] ? 'Hide text' : 'Show text'}
						</button>
						{#if open[i]}
							<pre>{hit.passage}</pre>
							<details><summary>Parent</summary><pre>{hit.parent_text}</pre></details>
						{/if}
						{#if hit.also_in?.length}<div class="crumb">also in {hit.also_in.length} other document(s)</div>{/if}
					</td>
					<td>{hit.node_type}{hit.doc_kind ? ` · ${hit.doc_kind}` : ''}</td>
					<td>{hit.source_origin ?? ''}{hit.trust_tier ? ` · tier ${hit.trust_tier}` : ''}{hit.language ? ` · ${hit.language}` : ''}</td>
				</tr>
			{/each}
		</tbody>
	</table>
{/if}

<style>
	.lab {
		display: grid;
		gap: 0.6rem;
		font-size: 0.84rem;
		margin-bottom: 1rem;
	}
	.row {
		display: flex;
		flex-wrap: wrap;
		gap: 0.6rem 1rem;
		align-items: end;
		margin-top: 0.4rem;
	}
	label {
		display: grid;
		gap: 0.15rem;
	}
	.check {
		display: flex;
		align-items: center;
		gap: 0.3rem;
	}
	textarea,
	input:not([type='checkbox']),
	select {
		font: inherit;
		padding: 0.3rem;
		background: var(--surface);
		color: inherit;
		border: 1px solid var(--border);
		border-radius: 0.25rem;
	}
	.short {
		width: 4rem;
	}
	button[type='submit'] {
		justify-self: start;
		font: inherit;
		padding: 0.35rem 1rem;
		cursor: pointer;
	}
	.summary,
	.crumb {
		font-size: 0.8rem;
		opacity: 0.8;
	}
	.warning {
		color: var(--warn);
		margin: 0.2rem 0;
	}
	.error {
		color: var(--hard);
	}
	.hits {
		border-collapse: collapse;
		width: 100%;
		font-size: 0.82rem;
	}
	.hits th,
	.hits td {
		border-bottom: 1px solid var(--border);
		padding: 0.35rem 0.4rem;
		text-align: left;
		vertical-align: top;
	}
	.hits td:nth-child(2),
	.hits td:nth-child(3) {
		font-variant-numeric: tabular-nums;
	}
	.flag {
		color: var(--warn);
		margin-left: 0.3rem;
	}
	.link {
		background: none;
		border: 0;
		padding: 0;
		color: var(--accent);
		cursor: pointer;
		font: inherit;
		font-size: 0.78rem;
	}
	pre {
		white-space: pre-wrap;
		font-size: 0.78rem;
		margin: 0.3rem 0;
	}
</style>
