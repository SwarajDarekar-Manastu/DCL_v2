<script lang="ts">
	import type { ViewerRegion } from '$lib/api_endpoint';
	import { cn } from '$lib/utils';

	interface Props {
		src: string;
		alt: string;
		/** Pixels when the pipeline recorded them; without them the box takes the image's own size. */
		width?: number | null;
		height?: number | null;
		regions: ViewerRegion[];
	}

	let { src, alt, width, height, regions }: Props = $props();
	const pct = (value: number) => `${(value * 100).toFixed(3)}%`;
	const label = (region: ViewerRegion) => region.label + (region.confidence == null ? '' : ` (confidence ${region.confidence.toFixed(2)})`);
	// Status colors: cited passage = info (blue), flagged region = hard (red).
	const KIND = {
		cited: 'border-info bg-info/10',
		flag: 'border-hard bg-hard/10'
	} as const;
</script>

<!-- Regions use normalized coordinates, so percentages keep them on target at any rendered size. -->
<div class="bg-background relative w-full overflow-visible rounded-md border shadow-sm" style={width && height ? `aspect-ratio: ${width} / ${height}` : undefined}>
	<img class={width && height ? "block h-full w-full" : "block h-auto w-full"} {src} {alt} width={width ?? undefined} height={height ?? undefined} />
	{#each regions as region, i (i)}
		<!-- A button so keyboard users can Tab through the regions; focus scrolls it into view and shows its label. -->
		<button
			type="button"
			class={cn(
				'group absolute cursor-default rounded-[2px] border-2 p-0 shadow-[0_0_0_1px_var(--background)] outline-none',
				'focus-visible:ring-ring focus-visible:ring-2 focus-visible:ring-offset-1',
				KIND[region.kind]
			)}
			data-testid="region"
			data-region-index={i}
			data-kind={region.kind}
			style="left: {pct(region.bbox[0])}; top: {pct(region.bbox[1])}; width: {pct(region.bbox[2] - region.bbox[0])}; height: {pct(region.bbox[3] - region.bbox[1])}"
			title={label(region)}
			aria-label="{region.kind} region: {label(region)}"
			onfocus={(e) => e.currentTarget.scrollIntoView?.({ block: 'center', inline: 'nearest' })}
		>
			<span
				class="bg-popover text-popover-foreground pointer-events-none absolute bottom-full left-0 mb-1 hidden rounded-sm border px-1.5 py-0.5 text-[11px] whitespace-nowrap shadow-sm group-focus-visible:block"
				aria-hidden="true">{label(region)}</span
			>
		</button>
	{/each}
</div>
