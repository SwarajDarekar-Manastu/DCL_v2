<script lang="ts">
	import type { ViewerPayload } from '$lib/api_endpoint';

	interface Props {
		payload: ViewerPayload;
		translating: boolean;
		onToggleTranslate: () => void;
	}

	let { payload, translating, onToggleTranslate }: Props = $props();
	let doc = $derived(payload.document);
	let links = $derived(payload.links);
	const ORIGIN_LABEL = { internal: 'Internal', external_kept: 'External library' } as const;
	const TIER_LABEL = ['', 'measured telemetry', 'internal report', 'standard', 'vendor datasheet', 'paper / article', 'live web'];
	let foreign = $derived(!!payload.translation.source_language && payload.translation.source_language !== 'en');
</script>

<aside>
	<h2>{doc.title}</h2>
	<dl>
		<dt>Kind</dt>
		<dd>{doc.doc_kind}</dd>
		<dt>Origin</dt>
		<dd>{ORIGIN_LABEL[doc.source_origin]} · tier {doc.trust_tier} ({TIER_LABEL[doc.trust_tier]})</dd>
		{#if doc.language}<dt>Language</dt>
			<dd>{doc.language}</dd>{/if}
		{#if doc.test_ids.length}<dt>Tests</dt>
			<dd>{doc.test_ids.join(', ')}</dd>{/if}
		{#if doc.doc_date}<dt>Date</dt>
			<dd>{doc.doc_date}</dd>{/if}
		<dt>Status</dt>
		<dd>{doc.status}{doc.open_flags ? ` · ${doc.open_flags} open flag${doc.open_flags === 1 ? '' : 's'}` : ''}</dd>
	</dl>

	<ul class="links">
		{#each links.onedrive as location (location.web_url)}
			<li><a href={location.web_url} target="_blank" rel="noopener noreferrer">Open in OneDrive</a> <small>{location.path}</small></li>
		{/each}
		{#if links.download_url}
			<li><a href={links.download_url} rel="noopener noreferrer">Download original</a></li>
		{/if}
		{#if links.review_case_key}
			<li><a href="/review?case={encodeURIComponent(links.review_case_key)}">Open review case</a></li>
		{/if}
	</ul>

	{#if foreign}
		<button type="button" aria-pressed={translating} disabled={!payload.translation.available} onclick={onToggleTranslate}>
			{translating ? 'Show original' : 'Translate'}
		</button>
		{#if !payload.translation.available}<small>Translation is not enabled for this document.</small>{/if}
	{/if}
</aside>

<style>
	aside {
		background: var(--surface);
		border: 1px solid var(--border);
		border-radius: 0.5rem;
		padding: 1rem;
		font-size: 0.875rem;
	}
	h2 {
		font-size: 1rem;
		margin: 0 0 0.75rem;
	}
	dl {
		display: grid;
		grid-template-columns: auto 1fr;
		gap: 0.3rem 0.75rem;
		margin: 0 0 1rem;
	}
	dt {
		opacity: 0.65;
	}
	dd {
		margin: 0;
	}
	.links {
		padding: 0;
		list-style: none;
		display: grid;
		gap: 0.4rem;
	}
	small {
		display: block;
		opacity: 0.65;
		word-break: break-all;
	}
	button {
		margin-top: 0.5rem;
		padding: 0.35rem 0.8rem;
		border-radius: 0.3rem;
		border: 1px solid var(--accent);
		background: transparent;
		color: var(--accent);
		cursor: pointer;
	}
	button[aria-pressed='true'] {
		background: var(--accent);
		color: white;
	}
	button:disabled {
		opacity: 0.5;
		cursor: not-allowed;
	}
</style>
