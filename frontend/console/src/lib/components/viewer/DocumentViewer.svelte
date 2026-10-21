<script lang="ts">
	import type { ViewerPayload } from '$lib/api_endpoint';
	import CodeView from './CodeView.svelte';
	import ImageWithRegions from './ImageWithRegions.svelte';
	import MetaPanel from './MetaPanel.svelte';
	import TableView from './TableView.svelte';

	interface Props {
		payload: ViewerPayload;
		translating: boolean;
		onToggleTranslate: () => void;
		/** Link to another page of the same document (anchor without hash). */
		pageHref: (pageNo: number) => string;
	}

	let { payload, translating, onToggleTranslate, pageHref }: Props = $props();
	let view = $derived(payload.view);
	let showText = $state(false);
	const seconds = (ms: number) => (ms / 1000).toFixed(3);
</script>

<div class="viewer">
	<section class="main">
		{#if payload.resolution.status !== 'exact'}
			<p class="fallback" role="status" data-status={payload.resolution.status}>
				{payload.resolution.status === 'page_fallback'
					? 'The cited passage changed since it was cited; showing the page it was on.'
					: 'The cited location no longer exists in this document; showing the document.'}
				{#if payload.resolution.message}<span class="detail">{payload.resolution.message}</span>{/if}
			</p>
		{/if}

		{#if view.kind === 'page'}
			<nav class="pager" aria-label="Pages">
				{#if view.page_no > 1}<a href={pageHref(view.page_no - 1)}>← Page {view.page_no - 1}</a>{/if}
				<span>Page {view.page_no} of {view.page_count}</span>
				{#if view.page_no < view.page_count}<a href={pageHref(view.page_no + 1)}>Page {view.page_no + 1} →</a>{/if}
				{#if view.text}
					<button type="button" aria-pressed={showText} onclick={() => (showText = !showText)}>
						{showText ? 'Show image' : 'Show text'}
					</button>
				{/if}
			</nav>
			{#if showText}
				<pre class="text">{view.text}</pre>
			{:else}
				<ImageWithRegions
					src={view.image_url}
					alt="Page {view.page_no} of {payload.document.title}"
					width={view.width}
					height={view.height}
					regions={view.regions}
				/>
			{/if}
		{:else if view.kind === 'image'}
			<ImageWithRegions
				src={view.image_url}
				alt={view.caption || `${view.image_kind} from ${payload.document.title}`}
				width={view.width}
				height={view.height}
				regions={view.regions}
			/>
			{#if view.caption}<p class="caption">{view.caption}</p>{/if}
		{:else if view.kind === 'table'}
			<TableView rows={view.rows} headerRows={view.header_rows} highlight={view.highlight} sheetName={view.sheet_name} />
		{:else if view.kind === 'code'}
			<CodeView language={view.language} firstLine={view.first_line} lines={view.lines} highlight={view.highlight} />
		{:else if view.kind === 'text'}
			{#if view.breadcrumb}<p class="caption">{view.breadcrumb}</p>{/if}
			<pre class="text">{view.text}</pre>
		{:else if view.kind === 'video'}
			<!-- svelte-ignore a11y_media_has_caption (test-cell footage has no captions) -->
			<video controls preload="metadata" src="{view.video_url}#t={seconds(view.t_ms)}" poster={view.poster_url ?? undefined}></video>
			<p class="caption">Starts at {seconds(view.t_ms)} s</p>
		{/if}

		{#if translating}
			<section class="translation" aria-label="Translation">
				{#if payload.translation.translated_text}
					<p class="marker">Translated from {payload.translation.source_language}; the original stays the cited source.</p>
					<pre class="text">{payload.translation.translated_text}</pre>
				{:else if payload.translation.pending}
					<p class="marker">Translation requested; it appears here when ready.</p>
				{/if}
			</section>
		{/if}
	</section>

	<MetaPanel {payload} {translating} {onToggleTranslate} />
</div>

<style>
	.viewer {
		display: grid;
		grid-template-columns: minmax(0, 1fr) 20rem;
		gap: 1rem;
		align-items: start;
	}
	@media (max-width: 900px) {
		.viewer {
			grid-template-columns: 1fr;
		}
	}
	.fallback {
		margin: 0 0 0.75rem;
		padding: 0.6rem 0.8rem;
		border-left: 4px solid var(--warn);
		background: rgb(245 158 11 / 0.12);
	}
	.detail {
		display: block;
		font-size: 0.85rem;
		opacity: 0.8;
	}
	.pager {
		display: flex;
		gap: 1rem;
		align-items: center;
		margin-bottom: 0.5rem;
		font-size: 0.9rem;
	}
	.pager button {
		margin-left: auto;
	}
	.text {
		white-space: pre-wrap;
		background: var(--surface);
		border: 1px solid var(--border);
		padding: 0.75rem;
		font-size: 0.875rem;
	}
	.caption,
	.marker {
		font-size: 0.85rem;
		opacity: 0.8;
	}
	video {
		width: 100%;
		max-width: 60rem;
		background: black;
	}
</style>
