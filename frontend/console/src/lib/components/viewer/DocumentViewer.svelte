<script lang="ts">
	import ChevronLeftIcon from '@lucide/svelte/icons/chevron-left';
	import ChevronRightIcon from '@lucide/svelte/icons/chevron-right';
	import FileTextIcon from '@lucide/svelte/icons/file-text';
	import ImageIcon from '@lucide/svelte/icons/image';
	import LanguagesIcon from '@lucide/svelte/icons/languages';
	import TriangleAlertIcon from '@lucide/svelte/icons/triangle-alert';
	import type { ViewerPayload } from '$lib/api_endpoint';
	import { Button } from '$lib/components/ui/button';
	import { cn } from '$lib/utils';
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
	/** Display width of page and image renders; "fit" fills the column. Client-side only. */
	let zoom = $state<'fit' | '75' | '100' | '150' | '200'>('fit');
	const ZOOM_WIDTH = { fit: '100%', '75': '45rem', '100': '60rem', '150': '90rem', '200': '120rem' } as const;
	const seconds = (ms: number) => (ms / 1000).toFixed(3);
	const KIND_LABEL = { page: 'Page', image: 'Image', table: 'Table', code: 'Code', text: 'Text', video: 'Video' } as const;
	let hasImage = $derived((view.kind === 'page' && !showText) || view.kind === 'image');
	let regionCount = $derived(view.kind === 'page' || view.kind === 'image' ? view.regions.length : 0);
	const pagerLink =
		'text-muted-foreground hover:bg-muted hover:text-foreground inline-flex h-7 items-center gap-1 rounded-md px-2 text-[0.8rem] font-medium no-underline transition-colors hover:no-underline';
</script>

<div class="grid items-start gap-5 xl:grid-cols-[minmax(0,1fr)_20rem]">
	<section class="min-w-0 space-y-3" aria-label="Document content">
		{#if payload.resolution.status !== 'exact'}
			<p
				class="bg-warn-bg border-warn-border text-foreground m-0 flex gap-2.5 rounded-lg border px-3.5 py-2.5"
				role="status"
				data-status={payload.resolution.status}
			>
				<TriangleAlertIcon class="text-warn mt-0.5 size-4 shrink-0" aria-hidden="true" />
				<span>
					<span class="font-medium">
						{payload.resolution.status === 'page_fallback'
							? 'The cited passage changed since it was cited; showing the page it was on.'
							: 'The cited location no longer exists in this document; showing the document.'}
					</span>
					{#if payload.resolution.message}<span class="text-muted-foreground mt-0.5 block font-mono text-xs"
							>{payload.resolution.message}</span
						>{/if}
				</span>
			</p>
		{/if}

		<div class="panel overflow-hidden">
			<div class="bg-background flex min-h-11 flex-wrap items-center gap-x-3 gap-y-1.5 border-b px-3 py-1.5" role="toolbar" aria-label="Viewer">
				<span class="text-muted-foreground flex items-center gap-1.5 text-xs font-medium">
					{#if view.kind === 'page' || view.kind === 'image'}<ImageIcon class="size-3.5" aria-hidden="true" />{:else}<FileTextIcon
							class="size-3.5"
							aria-hidden="true"
						/>{/if}
					{KIND_LABEL[view.kind]}
				</span>
				{#if view.kind === 'page'}
					<nav class="flex items-center gap-1" aria-label="Pages">
						{#if view.page_no > 1}<a class={pagerLink} href={pageHref(view.page_no - 1)}
								><ChevronLeftIcon class="size-3.5" aria-hidden="true" /><span class="sr-only">←</span> Page {view.page_no - 1}</a
							>{/if}
						<span class="num px-1 text-sm font-medium">Page {view.page_no} of {view.page_count}</span>
						{#if view.page_no < view.page_count}<a class={pagerLink} href={pageHref(view.page_no + 1)}
								>Page {view.page_no + 1} <span class="sr-only">→</span><ChevronRightIcon class="size-3.5" aria-hidden="true" /></a
							>{/if}
					</nav>
				{/if}
				{#if regionCount}
					<span class="text-muted-foreground flex items-center gap-3 text-xs">
						<span class="flex items-center gap-1.5"><span class="border-info bg-info-bg size-2.5 rounded-[2px] border-2" aria-hidden="true"></span>cited</span>
						<span class="flex items-center gap-1.5"><span class="border-hard bg-hard-bg size-2.5 rounded-[2px] border-2" aria-hidden="true"></span>flag</span>
					</span>
				{/if}
				<span class="ml-auto flex items-center gap-2">
					{#if hasImage}
						<label class="text-muted-foreground flex items-center gap-1.5 text-xs">
							Zoom
							<select class="field text-foreground h-7 w-auto text-xs" bind:value={zoom}>
								<option value="fit">Fit</option>
								<option value="75">75%</option>
								<option value="100">100%</option>
								<option value="150">150%</option>
								<option value="200">200%</option>
							</select>
						</label>
					{/if}
					{#if view.kind === 'page' && view.text}
						<Button variant="outline" size="sm" aria-pressed={showText} onclick={() => (showText = !showText)}>
							{showText ? 'Show image' : 'Show text'}
						</Button>
					{/if}
					{#if translating}
						<span class="text-info flex items-center gap-1 text-xs font-medium"><LanguagesIcon class="size-3.5" aria-hidden="true" />Translation on</span>
					{/if}
				</span>
			</div>

			<div class={cn('bg-muted/40 p-4', hasImage && 'overflow-auto')}>
				{#if view.kind === 'page'}
					{#if showText}
						<pre class="code-block bg-background m-0 text-[13px] leading-6">{view.text}</pre>
					{:else}
						<div class="mx-auto" style="width: {ZOOM_WIDTH[zoom]}; max-width: {zoom === 'fit' ? '60rem' : 'none'}">
							<ImageWithRegions
								src={view.image_url}
								alt="Page {view.page_no} of {payload.document.title}"
								width={view.width}
								height={view.height}
								regions={view.regions}
							/>
						</div>
					{/if}
				{:else if view.kind === 'image'}
					<figure class="m-0">
						<div class="mx-auto" style="width: {ZOOM_WIDTH[zoom]}; max-width: {zoom === 'fit' ? '60rem' : 'none'}">
							<ImageWithRegions
								src={view.image_url}
								alt={view.caption || `${view.image_kind} from ${payload.document.title}`}
								width={view.width}
								height={view.height}
								regions={view.regions}
							/>
						</div>
						{#if view.caption}<figcaption class="text-muted-foreground mt-2 text-center text-xs">{view.caption}</figcaption>{/if}
					</figure>
				{:else if view.kind === 'table'}
					<TableView rows={view.rows} headerRows={view.header_rows} highlight={view.highlight ?? null} sheetName={view.sheet_name ?? null} />
				{:else if view.kind === 'code'}
					<CodeView language={view.language} firstLine={view.first_line} lines={view.lines} highlight={view.highlight ?? null} />
				{:else if view.kind === 'text'}
					{#if view.breadcrumb}<p class="text-muted-foreground m-0 mb-2 text-xs">{view.breadcrumb}</p>{/if}
					<pre class="code-block bg-background m-0 text-[13px] leading-6">{view.text}</pre>
				{:else if view.kind === 'video'}
					<!-- svelte-ignore a11y_media_has_caption (test-cell footage has no captions) -->
					<video
						class="mx-auto block w-full max-w-[60rem] rounded-md bg-black"
						controls
						preload="metadata"
						src="{view.video_url}#t={seconds(view.t_ms)}"
						poster={view.poster_url ?? undefined}
					></video>
					<p class="text-muted-foreground num m-0 mt-2 text-center text-xs">Starts at {seconds(view.t_ms)} s</p>
				{/if}
			</div>
		</div>

		{#if translating}
			<section class="panel" aria-label="Translation">
				<div class="panel-header">
					<h2 class="panel-title flex items-center gap-1.5"><LanguagesIcon class="size-4" aria-hidden="true" />Translation</h2>
				</div>
				<div class="panel-body space-y-2">
					{#if payload.translation.translated_text}
						<p class="text-muted-foreground m-0 text-xs">Translated from {payload.translation.source_language}; the original stays the cited source.</p>
						<pre class="code-block m-0 font-sans text-sm leading-6">{payload.translation.translated_text}</pre>
					{:else if payload.translation.pending}
						<p class="text-muted-foreground m-0 text-xs">Translation requested; it appears here when ready.</p>
					{/if}
				</div>
			</section>
		{/if}
	</section>

	<MetaPanel {payload} {translating} {onToggleTranslate} />
</div>
