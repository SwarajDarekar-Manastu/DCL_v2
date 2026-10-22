<script lang="ts">
	import ClipboardCheckIcon from '@lucide/svelte/icons/clipboard-check';
	import DownloadIcon from '@lucide/svelte/icons/download';
	import ExternalLinkIcon from '@lucide/svelte/icons/external-link';
	import LanguagesIcon from '@lucide/svelte/icons/languages';
	import type { ViewerPayload } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import ToneBadge from '$lib/components/shell/ToneBadge.svelte';

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
	const linkRow =
		'hover:bg-muted text-foreground flex items-center gap-2 rounded-md px-2 py-1.5 text-sm font-medium no-underline transition-colors hover:no-underline';
</script>

<aside class="panel xl:sticky xl:top-[calc(var(--sticky-top,0px)+1.25rem)]" aria-label="Document details">
	<div class="border-b px-4 py-3">
		<p class="eyebrow">Document</p>
		<h2 class="m-0 mt-1 text-sm leading-5 break-words">{doc.title}</h2>
	</div>
	<div class="panel-body space-y-4">
		<dl class="kv">
			<dt>Kind</dt>
			<dd>{doc.doc_kind}</dd>
			<dt>Origin</dt>
			<dd>{ORIGIN_LABEL[doc.source_origin]} · tier {doc.trust_tier} ({TIER_LABEL[doc.trust_tier]})</dd>
			{#if doc.language}<dt>Language</dt>
				<dd>{doc.language}</dd>{/if}
			{#if doc.test_ids.length}<dt>Tests</dt>
				<dd class="font-mono text-xs leading-5">{doc.test_ids.join(', ')}</dd>{/if}
			{#if doc.doc_date}<dt>Date</dt>
				<dd class="num">{doc.doc_date}</dd>{/if}
			<dt>Status</dt>
			<dd class="flex flex-wrap items-center gap-1.5">
				<span>{doc.status}</span>
				{#if doc.open_flags}<ToneBadge tone="warn">{doc.open_flags} open flag{doc.open_flags === 1 ? '' : 's'}</ToneBadge>{/if}
			</dd>
		</dl>

		<ul class="m-0 -mx-2 list-none space-y-0.5 border-t p-0 pt-3">
			{#each links.onedrive as location (location.web_url)}
				<li>
					<a class={linkRow} href={location.web_url} target="_blank" rel="noopener noreferrer"
						><ExternalLinkIcon class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />Open in OneDrive</a
					>
					<small class="text-muted-foreground block px-2 pb-1 pl-8 font-mono text-[11px] leading-4 break-all">{location.path}</small>
				</li>
			{/each}
			{#if links.download_url}
				<li>
					<a class={linkRow} href={links.download_url} rel="noopener noreferrer"
						><DownloadIcon class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />Download original</a
					>
				</li>
			{/if}
			{#if links.review_case_key}
				<li>
					<a class={linkRow} href="/review?case={encodeURIComponent(links.review_case_key)}"
						><ClipboardCheckIcon class="text-muted-foreground size-4 shrink-0" aria-hidden="true" />Open review case</a
					>
				</li>
			{/if}
		</ul>

		{#if foreign}
			<div class="space-y-1.5 border-t pt-3">
				<Button
					variant={translating ? 'default' : 'outline'}
					size="sm"
					class="w-full"
					aria-pressed={translating}
					disabled={!payload.translation.available}
					onclick={onToggleTranslate}
				>
					<LanguagesIcon aria-hidden="true" />{translating ? 'Show original' : 'Translate'}
				</Button>
				{#if !payload.translation.available}<small class="text-muted-foreground block text-xs">Translation is not enabled for this document.</small>{/if}
			</div>
		{/if}
	</div>
</aside>
