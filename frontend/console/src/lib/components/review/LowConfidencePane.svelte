<script lang="ts">
	// LOW_CONFIDENCE_EXTRACTION evidence: the cropped regions with the model's reading (click to zoom), or two
	// readings of one table side by side with the differing cells marked.
	import type { Evidence } from '$lib/api_endpoint';
	import AssetImage from './AssetImage.svelte';
	import ImageZoom from './ImageZoom.svelte';
	import { cellDiff, tableCells } from './evidence';

	type LowConfidence = Extract<Evidence, { kind: 'low_confidence' }>;

	interface Props {
		evidence: LowConfidence;
	}

	let { evidence }: Props = $props();
	let zoomed = $state<string | null>(null);
	// The zoom gives focus back to the crop that opened it.
	let opener: HTMLElement | null = null;
	function openZoom(uri: string, event: MouseEvent) {
		opener = event.currentTarget as HTMLElement;
		zoomed = uri;
	}
	function closeZoom() {
		zoomed = null;
		opener?.focus();
	}
	let showOcr = $state(false);
	let a = $derived(tableCells(evidence.table_a_html));
	let b = $derived(tableCells(evidence.table_b_html));
	let diff = $derived(cellDiff(a, b));
	const pct = (v: number | null | undefined) => (v === null || v === undefined ? '—' : `${Math.round(v * 100)}%`);
</script>

{#if evidence.crops.length}
	<ul class="m-0 grid list-none gap-3 p-0 sm:grid-cols-2" aria-label="Uncertain readings">
		{#each evidence.crops as crop, i (crop.crop_uri + i)}
			<li class="grid content-start gap-1.5 rounded-md border p-2.5">
				<button
					type="button"
					class="cursor-zoom-in rounded border-0 bg-transparent p-0"
					aria-label="Zoom crop {i + 1}{crop.printed_label ? `: ${crop.printed_label}` : ''}"
					onclick={(e) => openZoom(crop.crop_uri, e)}
				>
					<AssetImage uri={crop.crop_uri} alt="Crop {i + 1}" class="max-h-40 w-full object-contain" />
				</button>
				{#if crop.printed_label}<span class="text-muted-foreground text-xs">{crop.printed_label}</span>{/if}
				<p class="m-0">
					<span class="font-mono text-base font-semibold">{crop.model_value ?? 'no reading'}</span>
					<span class="text-muted-foreground text-xs">{` · confidence ${pct(crop.confidence)}`}</span>
				</p>
				{#if crop.alternatives.length}<p class="text-muted-foreground m-0 text-xs">Also possible: {crop.alternatives.join(', ')}</p>{/if}
				{#if crop.ocr_text}<p class="text-muted-foreground m-0 text-xs">OCR read: <span class="text-foreground font-mono">{crop.ocr_text}</span></p>{/if}
			</li>
		{/each}
	</ul>
{/if}

{#if a.length || b.length}
	<div class="grid gap-2 lg:grid-cols-2">
		{#each [['A', a], ['B', b]] as const as [name, rows] (name)}
			<div class="overflow-x-auto rounded-md border">
				<table class="w-full text-xs" aria-label="Table reading {name}">
					<caption class="text-muted-foreground px-2.5 py-1 text-left">Reading {name}</caption>
					<tbody>
						{#each rows as row, r (r)}
							<tr class="border-t">
								{#each row as cell, c (c)}
									<td class="px-2 py-0.5 font-mono {diff.has(`${r}:${c}`) ? 'bg-warn-bg text-warn' : ''}" data-diff={diff.has(`${r}:${c}`) ? 'true' : undefined}>{cell}</td>
								{/each}
							</tr>
						{/each}
					</tbody>
				</table>
			</div>
		{/each}
	</div>
	<p class="text-muted-foreground m-0 text-xs">{diff.size} {diff.size === 1 ? 'cell differs' : 'cells differ'} between the two readings.</p>
{/if}

{#if evidence.page_ocr_text}
	<div class="grid gap-1.5">
		<button type="button" class="text-link w-fit cursor-pointer border-0 bg-transparent p-0 text-xs" aria-expanded={showOcr} onclick={() => (showOcr = !showOcr)}
			>{showOcr ? 'Hide page OCR text' : 'Show page OCR text'}</button
		>
		{#if showOcr}<pre class="code-block m-0 max-h-72 overflow-auto text-xs whitespace-pre-wrap" aria-label="Page OCR text">{evidence.page_ocr_text}</pre>{/if}
	</div>
{/if}

<ImageZoom uri={zoomed} onClose={closeZoom} />
